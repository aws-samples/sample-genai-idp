# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Discovery operations for IDP SDK."""

import json
import logging
import os
from pathlib import Path
from typing import List, Optional

from idp_sdk.exceptions import IDPConfigurationError, IDPResourceNotFoundError
from idp_sdk.models.discovery import DiscoveryBatchResult, DiscoveryResult

logger = logging.getLogger(__name__)


class DiscoveryOperation:
    """Document class discovery operations.

    Provides programmatic access to IDP Discovery, which analyzes documents
    using Amazon Bedrock to automatically generate JSON Schema definitions
    for document classes.

    Two operating modes:

    **Stack-connected mode** (with ``stack_name``):
        Uses the stack's discovery configuration (model, prompts) from DynamoDB
        and saves the discovered schema to the stack's configuration.

    **Local mode** (without ``stack_name``):
        Uses system default discovery settings, calls Bedrock directly with
        local file bytes, and returns the schema without saving anywhere.
        The schema is printed to stdout and/or written to a file via CLI.

    Example:
        Stack-connected:
        >>> client = IDPClient(stack_name="my-idp-stack")
        >>> result = client.discovery.run("./samples/w2/w2-sample.pdf")

        Local (no stack needed):
        >>> client = IDPClient()
        >>> result = client.discovery.run("./invoice.pdf")
        >>> print(json.dumps(result.json_schema, indent=2))
    """

    def __init__(self, client):
        self._client = client

    def run(
        self,
        document_path: str,
        ground_truth_path: Optional[str] = None,
        config_version: Optional[str] = None,
        stack_name: Optional[str] = None,
        **kwargs,
    ) -> DiscoveryResult:
        """Run discovery on a single document to generate a document class schema.

        If a stack_name is available (via client or parameter), operates in
        stack-connected mode: uses the stack's discovery config and saves the
        schema to DynamoDB. If no stack_name, operates in local mode: uses
        system defaults and returns the schema without saving.

        Args:
            document_path: Local path to the document file (PDF, PNG, JPG, TIFF)
            ground_truth_path: Optional local path to a JSON ground truth file.
            config_version: Configuration version to save to (stack mode only).
            stack_name: Optional stack name override.
            **kwargs: Additional parameters.

        Returns:
            DiscoveryResult with the generated schema and status.

        Raises:
            FileNotFoundError: If the document or ground truth file doesn't exist.
        """
        doc_path = Path(document_path)
        if not doc_path.exists():
            raise FileNotFoundError(f"Document not found: {document_path}")

        gt_data = None
        if ground_truth_path:
            gt_path = Path(ground_truth_path)
            if not gt_path.exists():
                raise FileNotFoundError(
                    f"Ground truth file not found: {ground_truth_path}"
                )
            gt_data = json.loads(gt_path.read_text(encoding="utf-8"))

        # Read file bytes locally — never upload to S3
        file_bytes = doc_path.read_bytes()

        # Determine mode: stack-connected or local
        resolved_stack = stack_name or self._client._stack_name
        if resolved_stack:
            return self._run_with_stack(
                resolved_stack, doc_path, file_bytes, gt_data, config_version
            )
        else:
            return self._run_local(doc_path, file_bytes, gt_data)

    def _run_with_stack(
        self,
        stack_name: str,
        doc_path: Path,
        file_bytes: bytes,
        gt_data: Optional[dict],
        config_version: Optional[str],
    ) -> DiscoveryResult:
        """Stack-connected mode: uses stack config, saves schema to DynamoDB."""
        try:
            # Get config table from stack resources
            config_table = self._get_config_table(stack_name)
            os.environ["CONFIGURATION_TABLE_NAME"] = config_table

            from idp_common.discovery.classes_discovery import ClassesDiscovery

            # ClassesDiscovery reads config from DynamoDB but we pass file_bytes
            # so it never reads from S3. input_prefix is used only for extension.
            discovery = ClassesDiscovery(
                input_bucket="local",
                input_prefix=doc_path.name,
                region=self._client._region,
                version=config_version,
            )

            if gt_data:
                result = discovery.discovery_classes_with_document_and_ground_truth(
                    input_bucket="local",
                    input_prefix=doc_path.name,
                    file_bytes=file_bytes,
                    ground_truth_data=gt_data,
                    save_to_config=True,
                )
            else:
                result = discovery.discovery_classes_with_document(
                    input_bucket="local",
                    input_prefix=doc_path.name,
                    file_bytes=file_bytes,
                    save_to_config=True,
                )

            schema = result.get("schema")
            doc_class = None
            if schema:
                doc_class = schema.get("$id") or schema.get("x-aws-idp-document-type")

            return DiscoveryResult(
                status="SUCCESS",
                document_class=doc_class,
                json_schema=schema,
                config_version=config_version,
                document_path=str(doc_path),
            )

        except Exception as e:
            logger.error(f"Discovery failed for {doc_path}: {e}")
            return DiscoveryResult(
                status="FAILED",
                document_path=str(doc_path),
                error=str(e),
            )

    def _run_local(
        self,
        doc_path: Path,
        file_bytes: bytes,
        gt_data: Optional[dict],
    ) -> DiscoveryResult:
        """Local mode: uses system defaults, no stack needed, no config save."""
        try:
            from idp_common import bedrock, image
            from idp_common.config.merge_utils import load_system_defaults

            # Load system defaults to get discovery prompts and model settings
            defaults = load_system_defaults("pattern-2")
            discovery_cfg = defaults.get("discovery", {})
            mode_cfg = (
                discovery_cfg.get("with_ground_truth", {})
                if gt_data
                else discovery_cfg.get("without_ground_truth", {})
            )

            model_id = mode_cfg.get("model_id", "us.amazon.nova-pro-v1:0")
            system_prompt = mode_cfg.get(
                "system_prompt",
                "You are an expert in processing forms. Extracting data from images and documents",
            )
            temperature = mode_cfg.get("temperature", 0.0)
            top_p = mode_cfg.get("top_p", 0.0)
            max_tokens = mode_cfg.get("max_tokens", 10000)

            # Build prompt
            sample_format = _sample_output_format()
            if gt_data:
                user_prompt = mode_cfg.get("user_prompt") or _prompt_with_gt(gt_data)
                if "{ground_truth_json}" in user_prompt:
                    user_prompt = user_prompt.replace(
                        "{ground_truth_json}", json.dumps(gt_data, indent=2)
                    )
            else:
                user_prompt = mode_cfg.get("user_prompt") or _prompt_without_gt()

            full_prompt = f"{user_prompt}\nFormat the extracted data using the below JSON format:\n{sample_format}"

            # Create content with file bytes
            file_extension = doc_path.suffix.lower().lstrip(".")
            if file_extension == "pdf":
                content = [
                    {
                        "document": {
                            "format": "pdf",
                            "name": "document_messages",
                            "source": {"bytes": file_bytes},
                        }
                    },
                    {"text": full_prompt},
                ]
            else:
                image_content = image.prepare_bedrock_image_attachment(file_bytes)
                content = [image_content, {"text": full_prompt}]

            # Call Bedrock
            region = self._client._region or os.environ.get("AWS_REGION", "us-west-2")
            client = bedrock.BedrockClient(region=region)
            response = client.invoke_model(
                model_id=model_id,
                system_prompt=system_prompt,
                content=content,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                context="ClassesDiscoveryLocal",
            )

            content_text = bedrock.extract_text_from_response(response)
            schema = json.loads(content_text)

            doc_class = schema.get("$id") or schema.get("x-aws-idp-document-type")

            return DiscoveryResult(
                status="SUCCESS",
                document_class=doc_class,
                json_schema=schema,
                document_path=str(doc_path),
            )

        except Exception as e:
            logger.error(f"Local discovery failed for {doc_path}: {e}")
            return DiscoveryResult(
                status="FAILED",
                document_path=str(doc_path),
                error=str(e),
            )

    def run_batch(
        self,
        document_paths: List[str],
        ground_truth_paths: Optional[List[Optional[str]]] = None,
        config_version: Optional[str] = None,
        stack_name: Optional[str] = None,
        **kwargs,
    ) -> DiscoveryBatchResult:
        """Run discovery on multiple documents sequentially.

        Args:
            document_paths: List of local paths to document files.
            ground_truth_paths: Optional list of ground truth file paths.
            config_version: Configuration version to save to.
            stack_name: Optional stack name override.

        Returns:
            DiscoveryBatchResult with overall stats and per-document results.
        """
        if ground_truth_paths and len(ground_truth_paths) != len(document_paths):
            raise IDPConfigurationError(
                f"ground_truth_paths length ({len(ground_truth_paths)}) "
                f"must match document_paths length ({len(document_paths)})"
            )

        results: List[DiscoveryResult] = []
        for i, doc_path in enumerate(document_paths):
            gt_path = (
                ground_truth_paths[i]
                if ground_truth_paths and ground_truth_paths[i]
                else None
            )
            result = self.run(
                document_path=doc_path,
                ground_truth_path=gt_path,
                config_version=config_version,
                stack_name=stack_name,
            )
            results.append(result)

        succeeded = sum(1 for r in results if r.status == "SUCCESS")
        failed = sum(1 for r in results if r.status != "SUCCESS")

        return DiscoveryBatchResult(
            total=len(results),
            succeeded=succeeded,
            failed=failed,
            results=results,
        )

    def _get_config_table(self, stack_name: str) -> str:
        """Get ConfigurationTable from stack resources."""
        import boto3

        cfn = boto3.client("cloudformation", region_name=self._client._region)
        paginator = cfn.get_paginator("list_stack_resources")

        for page in paginator.paginate(StackName=stack_name):
            for resource in page.get("StackResourceSummaries", []):
                if resource.get("LogicalResourceId") == "ConfigurationTable":
                    return resource.get("PhysicalResourceId", "")

        raise IDPResourceNotFoundError("ConfigurationTable not found in stack.")


# --- Standalone prompt helpers for local mode ---


def _sample_output_format() -> str:
    return """{
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "Form-1040",
    "x-aws-idp-document-type": "Form-1040",
    "type": "object",
    "description": "Brief summary of the document",
    "properties": {
        "PersonalInformation": {
            "type": "object",
            "description": "Personal information of Tax payer",
            "properties": {
                "FirstName": {"type": "string", "description": "First Name of Taxpayer"},
                "Age": {"type": "number", "description": "Age of Taxpayer"}
            }
        },
        "Dependents": {
            "type": "array",
            "description": "Dependents of taxpayer",
            "items": {
                "type": "object",
                "properties": {
                    "FirstName": {"type": "string", "description": "Dependent first name"},
                    "Age": {"type": "number", "description": "Dependent Age"}
                }
            }
        }
    }
}"""


def _prompt_without_gt() -> str:
    return """This image contains forms data. Analyze the form line by line.
Image may contain multiple pages, process all the pages.
Form may contain multiple name value pair in one line.
Extract all the names in the form including the name value pair which doesn't have value.

Generate a JSON Schema that describes the document structure:
- Use "$schema": "https://json-schema.org/draft/2020-12/schema"
- Set "$id" to a short document class name (e.g., "W4", "I-9", "Paystub")
- Set "x-aws-idp-document-type" to the same document class name
- Set "type": "object"
- Add "description" with a brief summary of the document (less than 50 words)

For the "properties" object:
- Group related fields as objects (type: "object") with their own "properties"
- For repeating/table data, use type: "array" with "items" containing object schema
- Each field should have "type" (string, number, boolean, etc.) and "description"

Do not extract the actual values, only the schema structure."""


def _prompt_with_gt(ground_truth_data: dict) -> str:
    gt_json = json.dumps(ground_truth_data, indent=2)
    return f"""This image contains unstructured data. Analyze the data line by line using the provided ground truth as reference.
<GROUND_TRUTH_REFERENCE>
{gt_json}
</GROUND_TRUTH_REFERENCE>

Generate a JSON Schema that describes the document structure using the ground truth as reference:
- Use "$schema": "https://json-schema.org/draft/2020-12/schema"
- Set "$id" to a short document class name (e.g., "W4", "I-9", "Paystub")
- Set "x-aws-idp-document-type" to the same document class name
- Set "type": "object"
- Add "description" with a brief summary of the document (less than 50 words)

For the "properties" object:
- Preserve the exact field names and groupings from ground truth
- Use nested objects (type: "object") for grouped fields with their own "properties"
- For repeating/table data, use type: "array" with "items" containing object schema

Match field names, data types, and structure from the ground truth reference.
Do not extract the actual values, only the schema structure."""
