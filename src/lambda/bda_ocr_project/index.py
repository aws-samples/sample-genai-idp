# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""CloudFormation custom resource: stack-scoped BDA OCR project.

Provisions a per-stack Bedrock Data Automation *standard-output SYNC* project
used by the ``bda`` OCR backend, created on stack create and deleted on stack
delete. The project name is derived from the stack name so multiple stacks in
one account no longer share/interfere with a single account-global project.

The project configuration logic (standard-output config, jpeg/png->DOCUMENT
modality-routing override, routing-override repair, find/create/delete) is
inlined here to keep this deploy-time Lambda's ZIP small: importing it from
``idp_common.bda.bda_ocr`` would eagerly pull the heavy ``bda_service`` /
``bda_invocation`` chain via ``idp_common/bda/__init__.py``. The canonical
source of that logic is ``lib/idp_common_pkg/idp_common/bda/bda_ocr.py`` —
keep the two in sync.
"""

import logging
import os
import re
import time

import boto3
import cfnresponse

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Suffix appended to the (sanitized) stack name to form the OCR project name.
# BDA project names must match ``^[a-zA-Z0-9-_]+$`` (max 128 chars); underscores
# are allowed, so ``<stackname>_OCR_StdOutput`` is valid.
OCR_PROJECT_NAME_SUFFIX = "_OCR_StdOutput"
_MAX_PROJECT_NAME_LEN = 128


def sanitize_ocr_project_name(stack_name):
    """Build the stack-scoped OCR project name from a stack name.

    Mirrors ``idp_common.bda.bda_ocr.sanitize_ocr_project_name``.
    """
    sanitized = re.sub(r"[^a-zA-Z0-9-]", "-", stack_name or "")
    sanitized = re.sub(r"-+", "-", sanitized).strip("-")
    max_stack_len = _MAX_PROJECT_NAME_LEN - len(OCR_PROJECT_NAME_SUFFIX)
    sanitized = sanitized[:max_stack_len].strip("-")
    return f"{sanitized}{OCR_PROJECT_NAME_SUFFIX}"


def build_standard_output_config():
    """Standard-output-only configuration for a pure-OCR SYNC project."""
    return {
        "document": {
            "extraction": {
                "granularity": {"types": ["PAGE", "ELEMENT", "WORD", "LINE"]},
                "boundingBox": {"state": "ENABLED"},
            },
            "generativeField": {"state": "DISABLED"},
            "outputFormat": {
                "textFormat": {"types": ["MARKDOWN"]},
                "additionalFileFormat": {"state": "DISABLED"},
            },
        }
    }


def build_override_config():
    """Force jpeg/png inputs to DOCUMENT modality (rendered page images)."""
    return {"modalityRouting": {"jpeg": "DOCUMENT", "png": "DOCUMENT"}}


def _find_project_arn_by_name(client, project_name):
    try:
        paginator = client.get_paginator("list_data_automation_projects")
    except Exception:
        paginator = None

    if paginator is not None:
        for page in paginator.paginate():
            for proj in page.get("projects", []):
                if proj.get("projectName") == project_name:
                    return proj["projectArn"]
        return None

    for proj in client.list_data_automation_projects().get("projects", []):
        if proj.get("projectName") == project_name:
            return proj["projectArn"]
    return None


def _ensure_project_routing_override(client, project_arn):
    """Repair an existing project missing the jpeg/png->DOCUMENT routing."""
    try:
        project = client.get_data_automation_project(projectArn=project_arn)["project"]
    except Exception:
        logger.warning(
            "Could not fetch BDA OCR project %s to verify routing", project_arn
        )
        return

    routing = (project.get("overrideConfiguration") or {}).get("modalityRouting") or {}
    if routing.get("jpeg") == "DOCUMENT" and routing.get("png") == "DOCUMENT":
        return

    logger.info(
        "Updating BDA OCR project %s to add jpeg/png->DOCUMENT routing", project_arn
    )
    client.update_data_automation_project(
        projectArn=project_arn,
        standardOutputConfiguration=build_standard_output_config(),
        overrideConfiguration=build_override_config(),
    )


def find_or_create_ocr_project(client, project_name):
    """Find or create the stack-scoped OCR project; wait for COMPLETED."""
    existing_arn = _find_project_arn_by_name(client, project_name)
    if existing_arn:
        _ensure_project_routing_override(client, existing_arn)
        logger.info("Reusing BDA OCR project %s", existing_arn)
        return existing_arn

    logger.info("Creating BDA OCR project %s", project_name)
    try:
        resp = client.create_data_automation_project(
            projectName=project_name,
            projectDescription="GenAIIDP stack-scoped pure-OCR standard-output project",
            projectStage="LIVE",
            projectType="SYNC",
            standardOutputConfiguration=build_standard_output_config(),
            overrideConfiguration=build_override_config(),
        )
        project_arn = resp["projectArn"]
    except client.exceptions.ConflictException:
        logger.info("BDA OCR project already created concurrently; re-fetching")
        existing_arn = _find_project_arn_by_name(client, project_name)
        if existing_arn:
            _ensure_project_routing_override(client, existing_arn)
            return existing_arn
        raise

    # A freshly created project is IN_PROGRESS until provisioned (~seconds).
    status = None
    for _ in range(60):
        status = client.get_data_automation_project(projectArn=project_arn)["project"][
            "status"
        ]
        if status == "COMPLETED":
            break
        time.sleep(2)
    else:
        logger.warning(
            "BDA OCR project %s not COMPLETED after ~120s (last status: %s)",
            project_arn,
            status,
        )
    return project_arn


def delete_ocr_project_by_name(client, project_name):
    """Best-effort delete by name; never raise (stack deletion must not fail)."""
    arn = _find_project_arn_by_name(client, project_name)
    if not arn:
        logger.info("BDA OCR project %s not found; nothing to delete", project_name)
        return None
    try:
        client.delete_data_automation_project(projectArn=arn)
        logger.info("Deleted BDA OCR project %s", arn)
        return arn
    except Exception:
        logger.warning("Failed to delete BDA OCR project %s", arn, exc_info=True)
        return None


def handler(event, context):
    logger.info("Event received: %s", event)
    request_type = event.get("RequestType")
    props = event.get("ResourceProperties", {}) or {}
    stack_name = props.get("StackName") or os.environ.get("STACK_NAME", "")
    project_name = sanitize_ocr_project_name(stack_name)
    # Stable physical id keyed on the project name: a name change (stack rename)
    # is treated by CloudFormation as a replace + delete of the old resource.
    physical_id = f"bda-ocr-project/{project_name}"

    try:
        client = boto3.client("bedrock-data-automation")
    except Exception:
        # Bedrock Data Automation is unavailable in this region/partition (e.g.
        # some GovCloud regions). Degrade gracefully so Textract-only stacks
        # still deploy; the OCR service errors only if the 'bda' backend is
        # actually selected here.
        logger.warning(
            "bedrock-data-automation client unavailable; returning empty ProjectArn",
            exc_info=True,
        )
        cfnresponse.send(
            event,
            context,
            cfnresponse.SUCCESS,
            {"ProjectArn": ""},
            physicalResourceId=physical_id,
        )
        return

    try:
        if request_type == "Delete":
            delete_ocr_project_by_name(client, project_name)
            cfnresponse.send(
                event,
                context,
                cfnresponse.SUCCESS,
                {"ProjectArn": ""},
                physicalResourceId=physical_id,
            )
            return

        # Create / Update: find-or-create and return the ARN.
        arn = find_or_create_ocr_project(client, project_name)
        cfnresponse.send(
            event,
            context,
            cfnresponse.SUCCESS,
            {"ProjectArn": arn},
            physicalResourceId=physical_id,
        )
    except Exception as e:
        logger.error("Error managing BDA OCR project: %s", e, exc_info=True)
        # On a create/update failure, fail the stack op with a clear reason.
        # (Delete already returns SUCCESS above and never reaches here.)
        cfnresponse.send(
            event,
            context,
            cfnresponse.FAILED,
            {"Error": str(e)},
            physicalResourceId=physical_id,
            reason=str(e),
        )
        raise
