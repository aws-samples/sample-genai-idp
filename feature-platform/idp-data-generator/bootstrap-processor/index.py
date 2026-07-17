# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Config-bootstrap SQS processor.

Consumes bootstrap jobs, authors/resolves a document-class schema (cheap, in
this Lambda), creates a config version, then — when document generation is
requested and available — stages the schema_dir to the working bucket and
invokes the Synthesis AgentCore Runtime to generate a labeled test set. Status
is posted to AppSync to drive the UI subscription.
"""

import json
import logging
import os
import shutil
import tempfile
import uuid

import boto3
from idp_common.synthesis import bootstrap as bootstrap_mod
from idp_common.synthesis import engine, schema_bridge
from idp_common.synthesis.appsync_status import post_synthesis_status

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

APPSYNC_API_URL = os.environ.get("APPSYNC_API_URL")
WORKING_BUCKET = os.environ.get("WORKING_BUCKET")
TEST_SET_BUCKET = os.environ.get("TEST_SET_BUCKET")
SYNTHESIS_RUNTIME_ARN = os.environ.get("SYNTHESIS_RUNTIME_ARN")
CONFIGURATION_TABLE_NAME = os.environ.get("CONFIGURATION_TABLE_NAME")


def _status(
    job_id, status, message=None, error=None, config_version=None, test_set_id=None
):
    post_synthesis_status(
        APPSYNC_API_URL,
        job_id,
        status,
        status_message=message,
        error_message=error,
        config_version=config_version,
        test_set_id=test_set_id,
    )


def handler(event, context):
    logger.info("Received event: %s", json.dumps(event))
    batch_item_failures = []

    for record in event.get("Records", []):
        job_id = None
        try:
            body = json.loads(record["body"])
            job_id = body.get("jobId")
            _process_job(job_id, body)
        except Exception as e:
            logger.error("Error processing bootstrap job: %s", e, exc_info=True)
            batch_item_failures.append({"itemIdentifier": record["messageId"]})
            if job_id:
                _status(job_id, "FAILED", error=str(e))

    return {"batchItemFailures": batch_item_failures}


def _process_job(job_id, body):
    # The processor reads/writes config versions in the HOST's Configuration
    # DynamoDB table (gzip-compressed Binary storage format). That storage
    # contract lives in idp_common.config.ConfigurationManager, which this image
    # installs via idp_common[synthesis] (see agent-source/requirements.txt) — so
    # the extension shares the host's exact read/write format rather than
    # vendoring or round-tripping through a host mutation.
    from idp_common.config.configuration_manager import ConfigurationManager

    _status(job_id, "IN_PROGRESS", message="Authoring schema")

    config_manager = ConfigurationManager()

    request = bootstrap_mod.BootstrapRequest(
        prompt=body["prompt"],
        class_name=body.get("className"),
        field_hints=body.get("fieldHints", []),
        config_version=body.get("configVersion"),
        target_version=body.get("targetVersion"),
        doc_count=int(body.get("docCount", 3)),
        quality_threshold=int(body.get("threshold", 7)),
        augment=bool(body.get("augment", False)),
        model_id=body.get("modelId"),
        example_doc_keys=body.get("exampleDocKeys", []),
    )

    preauthored = body.get("preauthoredSchema")
    if preauthored:
        schema, tier = preauthored, "preauthored"
    else:
        config_classes = []
        if request.config_version:
            raw = config_manager.get_raw_configuration("Config", request.config_version)
            if raw:
                config_classes = list(raw.get("classes", []))

        schema, tier, matched = bootstrap_mod.resolve_schema(
            request,
            config_classes=config_classes,
            status_cb=lambda pct, msg: _status(job_id, "IN_PROGRESS", message=msg),
        )
        if schema is None:
            _status(job_id, "FAILED", error=f"Schema resolution failed (tier={tier})")
            return

    target_version = request.target_version or bootstrap_mod._default_version_name(
        schema
    )
    bootstrap_mod.merge_class_into_version(
        schema, target_version, config_manager=config_manager
    )
    _status(
        job_id,
        "IN_PROGRESS",
        message=f"Config version '{target_version}' created (tier={tier})",
        config_version=target_version,
    )

    want_generation = request.doc_count > 0 and body.get("generateDocs", True)

    if not want_generation:
        _status(
            job_id,
            "COMPLETED",
            message="Config version created (no generation requested)",
            config_version=target_version,
        )
        return

    if not SYNTHESIS_RUNTIME_ARN:
        _status(
            job_id,
            "COMPLETED",
            message=(
                "Config version created. Document generation unavailable; "
                "upload example documents to build a test set. " + engine.INSTALL_HINT
            ),
            config_version=target_version,
        )
        return

    schema_prefix = f"bootstrap/{job_id}/schema/"
    _stage_schema_dir(schema, schema_prefix)
    _status(
        job_id,
        "IN_PROGRESS",
        message="Invoking generator",
        config_version=target_version,
    )

    payload = {
        "jobId": job_id,
        "testSetId": target_version,
        "workingBucket": WORKING_BUCKET,
        "schemaPrefix": schema_prefix,
        "testSetBucket": TEST_SET_BUCKET,
        "count": request.doc_count,
        "threshold": request.quality_threshold,
        "augment": request.augment,
        "extra": request.prompt,
        "modelId": request.model_id,
        "allowedFieldNames": schema_bridge.field_names(schema),
    }
    # AgentCore Runtime sessions must be 33-256 chars. The handler kicks off
    # generation on a background thread and returns immediately; terminal
    # status flows back through AppSync, so this call does not block on the run.
    session_id = f"bootstrap-{job_id}-{uuid.uuid4().hex}"
    boto3.client("bedrock-agentcore").invoke_agent_runtime(
        agentRuntimeArn=SYNTHESIS_RUNTIME_ARN,
        runtimeSessionId=session_id,
        contentType="application/json",
        payload=json.dumps(payload).encode("utf-8"),
    )


def _stage_schema_dir(schema, prefix):
    work_dir = tempfile.mkdtemp(prefix="bootstrap-schema-")
    try:
        bootstrap_mod._write_schema_dir(schema, work_dir)
        s3 = boto3.client("s3")
        for fname in os.listdir(work_dir):
            fpath = os.path.join(work_dir, fname)
            if os.path.isfile(fpath):
                s3.upload_file(fpath, WORKING_BUCKET, f"{prefix}{fname}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
