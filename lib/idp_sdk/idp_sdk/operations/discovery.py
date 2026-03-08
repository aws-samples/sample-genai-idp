# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Discovery operations for IDP SDK."""

import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from idp_sdk.exceptions import IDPConfigurationError, IDPResourceNotFoundError
from idp_sdk.models.discovery import DiscoveryBatchResult, DiscoveryResult

logger = logging.getLogger(__name__)


class DiscoveryOperation:
    """Document class discovery operations.

    Provides programmatic access to IDP Discovery, which analyzes documents
    using Amazon Bedrock to automatically generate JSON Schema definitions
    for document classes. These schemas are saved to the IDP configuration
    and can be used for classification and extraction.

    Discovery supports two modes:
    - **Without ground truth**: Analyzes a document and infers the schema structure
    - **With ground truth**: Uses a JSON ground truth file as reference to generate
      a more accurate schema matching expected field names and types

    Example:
        >>> client = IDPClient(stack_name="my-idp-stack")
        >>> result = client.discovery.run("./samples/w2/w2-sample.pdf")
        >>> print(f"Discovered class: {result.document_class}")
        >>> print(json.dumps(result.schema, indent=2))

        >>> # With ground truth
        >>> result = client.discovery.run(
        ...     "./samples/w2/w2-sample.pdf",
        ...     ground_truth_path="./samples/w2/w2-ground-truth.json"
        ... )
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

        Uploads the document to the stack's S3 input bucket, invokes the
        ClassesDiscovery engine to analyze the document with Amazon Bedrock,
        and saves the generated JSON Schema to the stack's configuration.

        Args:
            document_path: Local path to the document file (PDF, PNG, JPG, TIFF)
            ground_truth_path: Optional local path to a JSON ground truth file.
                If provided, the discovery engine uses it as reference to generate
                a more accurate schema.
            config_version: Configuration version to save the discovered schema to.
                If not specified, saves to the active version.
            stack_name: Optional stack name override.
            **kwargs: Additional parameters (reserved for future use).

        Returns:
            DiscoveryResult with the generated schema, document class name,
            and status.

        Raises:
            IDPConfigurationError: If stack_name is not available.
            IDPResourceNotFoundError: If required stack resources are not found.
            FileNotFoundError: If the document or ground truth file doesn't exist.

        Examples:
            Basic discovery:
            >>> result = client.discovery.run("./invoice.pdf")
            >>> print(result.document_class)  # e.g., "Invoice"
            >>> print(result.status)  # "SUCCESS"

            With ground truth:
            >>> result = client.discovery.run(
            ...     "./w2-form.pdf",
            ...     ground_truth_path="./w2-expected.json"
            ... )

            With specific config version:
            >>> result = client.discovery.run(
            ...     "./invoice.pdf",
            ...     config_version="v2"
            ... )
        """
        # Validate stack first (before file checks)
        name = self._client._require_stack(stack_name)

        doc_path = Path(document_path)
        if not doc_path.exists():
            raise FileNotFoundError(f"Document not found: {document_path}")

        gt_path = None
        if ground_truth_path:
            gt_path = Path(ground_truth_path)
            if not gt_path.exists():
                raise FileNotFoundError(
                    f"Ground truth file not found: {ground_truth_path}"
                )

        # Get stack resources
        resources = self._get_discovery_resources(name)

        input_bucket = resources["input_bucket"]
        config_table = resources["config_table"]

        # Upload document to S3
        s3_doc_key = self._upload_to_s3(input_bucket, doc_path)

        # Upload ground truth if provided
        s3_gt_key = None
        if gt_path:
            s3_gt_key = self._upload_to_s3(input_bucket, gt_path)

        try:
            # Set up environment for ClassesDiscovery
            os.environ["CONFIGURATION_TABLE_NAME"] = config_table

            from idp_common.discovery.classes_discovery import ClassesDiscovery

            discovery = ClassesDiscovery(
                input_bucket=input_bucket,
                input_prefix=s3_doc_key,
                region=self._client._region,
                version=config_version,
            )

            # Run discovery
            if s3_gt_key:
                result = discovery.discovery_classes_with_document_and_ground_truth(
                    input_bucket=input_bucket,
                    input_prefix=s3_doc_key,
                    ground_truth_key=s3_gt_key,
                )
            else:
                result = discovery.discovery_classes_with_document(
                    input_bucket=input_bucket,
                    input_prefix=s3_doc_key,
                )

            # Read back the saved config to get the schema
            schema = self._get_last_discovered_schema(config_table, config_version)

            doc_class = None
            if schema:
                doc_class = schema.get("$id") or schema.get("x-aws-idp-document-type")

            return DiscoveryResult(
                status=result.get("status", "SUCCESS"),
                document_class=doc_class,
                json_schema=schema,
                config_version=config_version,
                document_path=str(doc_path),
            )

        except Exception as e:
            logger.error(f"Discovery failed for {document_path}: {e}")
            return DiscoveryResult(
                status="FAILED",
                document_path=str(doc_path),
                error=str(e),
            )
        finally:
            # Clean up uploaded files
            self._cleanup_s3(input_bucket, s3_doc_key)
            if s3_gt_key:
                self._cleanup_s3(input_bucket, s3_gt_key)

    def run_batch(
        self,
        document_paths: List[str],
        ground_truth_paths: Optional[List[Optional[str]]] = None,
        config_version: Optional[str] = None,
        stack_name: Optional[str] = None,
        **kwargs,
    ) -> DiscoveryBatchResult:
        """Run discovery on multiple documents sequentially.

        Processes each document individually, collecting results. If a
        ground_truth_paths list is provided, each entry corresponds to
        the document at the same index (use None for documents without
        ground truth).

        Args:
            document_paths: List of local paths to document files.
            ground_truth_paths: Optional list of ground truth file paths,
                one per document. Use None entries for documents without
                ground truth.
            config_version: Configuration version to save discovered schemas to.
            stack_name: Optional stack name override.
            **kwargs: Additional parameters.

        Returns:
            DiscoveryBatchResult with overall stats and per-document results.

        Examples:
            >>> results = client.discovery.run_batch([
            ...     "./invoice.pdf",
            ...     "./w2-form.pdf",
            ...     "./paystub.png",
            ... ])
            >>> print(f"Succeeded: {results.succeeded}/{results.total}")

            With selective ground truth:
            >>> results = client.discovery.run_batch(
            ...     ["./invoice.pdf", "./w2-form.pdf"],
            ...     ground_truth_paths=[None, "./w2-expected.json"],
            ... )
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

    def _get_discovery_resources(self, stack_name: str) -> Dict[str, str]:
        """Get required stack resources for discovery.

        Args:
            stack_name: CloudFormation stack name.

        Returns:
            Dict with 'input_bucket' and 'config_table' keys.

        Raises:
            IDPResourceNotFoundError: If required resources not found.
        """
        import boto3

        cfn = boto3.client("cloudformation", region_name=self._client._region)
        paginator = cfn.get_paginator("list_stack_resources")

        input_bucket = None
        config_table = None

        for page in paginator.paginate(StackName=stack_name):
            for resource in page.get("StackResourceSummaries", []):
                logical_id = resource.get("LogicalResourceId", "")
                physical_id = resource.get("PhysicalResourceId", "")

                if logical_id == "ConfigurationTable":
                    config_table = physical_id
                elif logical_id in ("InputBucket", "DocumentInputBucket"):
                    input_bucket = physical_id

        if not input_bucket:
            raise IDPResourceNotFoundError(
                "Input S3 bucket not found in stack. "
                "Looked for 'InputBucket' or 'DocumentInputBucket'."
            )
        if not config_table:
            raise IDPResourceNotFoundError("ConfigurationTable not found in stack.")

        return {"input_bucket": input_bucket, "config_table": config_table}

    def _upload_to_s3(self, bucket: str, file_path: Path) -> str:
        """Upload a local file to S3 under a discovery prefix.

        Args:
            bucket: S3 bucket name.
            file_path: Local file path.

        Returns:
            S3 key where the file was uploaded.
        """
        import boto3

        s3 = boto3.client("s3", region_name=self._client._region)
        job_id = str(uuid.uuid4())[:8]
        s3_key = f"discovery-sdk/{job_id}/{file_path.name}"

        logger.info(f"Uploading {file_path} to s3://{bucket}/{s3_key}")
        s3.upload_file(str(file_path), bucket, s3_key)

        return s3_key

    def _cleanup_s3(self, bucket: str, key: str) -> None:
        """Remove a temporary file from S3.

        Args:
            bucket: S3 bucket name.
            key: S3 key to delete.
        """
        try:
            import boto3

            s3 = boto3.client("s3", region_name=self._client._region)
            s3.delete_object(Bucket=bucket, Key=key)
            logger.debug(f"Cleaned up s3://{bucket}/{key}")
        except Exception as e:
            logger.warning(f"Failed to clean up s3://{bucket}/{key}: {e}")

    def _get_last_discovered_schema(
        self, config_table: str, config_version: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Read the most recently added class schema from config.

        After ClassesDiscovery saves the schema, we read it back from
        the configuration to return it to the caller.

        Args:
            config_table: DynamoDB table name.
            config_version: Configuration version.

        Returns:
            The last class schema dict, or None if not found.
        """
        try:
            os.environ["CONFIGURATION_TABLE_NAME"] = config_table
            from idp_common.config import ConfigurationReader

            reader = ConfigurationReader(table_name=config_table)
            config = reader.get_merged_configuration(
                version=config_version, as_model=False
            )

            classes = config.get("classes", [])
            if classes:
                return classes[-1]

            return None
        except Exception as e:
            logger.warning(f"Could not read back discovered schema: {e}")
            return None
