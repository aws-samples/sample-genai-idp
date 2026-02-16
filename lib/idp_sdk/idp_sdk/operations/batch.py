# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Batch operations for IDP SDK."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from idp_sdk.exceptions import (
    IDPConfigurationError,
    IDPProcessingError,
    IDPResourceNotFoundError,
)
from idp_sdk.models import (
    BatchDeletionResult,
    BatchDownloadResult,
    BatchInfo,
    BatchListResult,
    BatchRerunResult,
    BatchResult,
    BatchStatus,
    DocumentDeletionResult,
    DocumentStatus,
    RerunStep,
    StopWorkflowsResult,
)


class BatchOperation:
    """Batch document processing operations."""

    def __init__(self, client):
        self._client = client

    def run(
        self,
        source: Optional[str] = None,
        manifest: Optional[str] = None,
        directory: Optional[str] = None,
        s3_uri: Optional[str] = None,
        test_set: Optional[str] = None,
        stack_name: Optional[str] = None,
        batch_id: Optional[str] = None,
        batch_prefix: str = "sdk-batch",
        file_pattern: str = "*.pdf",
        recursive: bool = True,
        number_of_files: Optional[int] = None,
        config_path: Optional[str] = None,
        config_version: Optional[str] = None,
        context: Optional[str] = None,
        **kwargs,
    ) -> BatchResult:
        """Run inference on a batch of documents.

        Args:
            source: Source path (auto-detects type: directory, manifest, or S3 URI)
            manifest: Path to manifest CSV file
            directory: Local directory containing documents
            s3_uri: S3 URI (s3://bucket/prefix/)
            test_set: Test set identifier
            stack_name: Optional stack name override
            batch_id: Optional custom batch ID
            batch_prefix: Prefix for batch output
            file_pattern: File pattern for directory/S3 scanning
            recursive: Recursively scan directories
            number_of_files: Limit number of files to process
            config_path: Path to custom configuration file
            config_version: Configuration version to use for processing
            context: Context for test set processing
            **kwargs: Additional parameters

        Returns:
            BatchResult with batch processing information
        """
        from idp_sdk.core.batch_processor import BatchProcessor

        name = self._client._require_stack(stack_name)

        if source:
            import os

            if source.startswith("s3://"):
                s3_uri = source
            elif os.path.isdir(source):
                directory = source
            elif os.path.isfile(source):
                manifest = source
            else:
                raise IDPConfigurationError(
                    f"Source '{source}' not found or unrecognized format"
                )

        sources = [manifest, directory, s3_uri, test_set]
        if sum(1 for s in sources if s) != 1:
            raise IDPConfigurationError(
                "Specify exactly one source: manifest, directory, s3_uri, or test_set"
            )

        try:
            # processor = BatchProcessor(
            #     stack_name=name, config_path=config_path, region=self._client._region
            # )

            processor = BatchProcessor(
                stack_name=name,
                config_path=config_path,
                config_version=config_version,
                region=self._client._region,
            )

            if test_set:
                result = self._process_test_set(
                    processor, test_set, context, number_of_files
                )
            elif manifest:
                result = processor.process_batch(
                    manifest_path=manifest,
                    output_prefix=batch_prefix,
                    batch_id=batch_id,
                    number_of_files=number_of_files,
                )
            elif directory:
                result = processor.process_batch_from_directory(
                    dir_path=directory,
                    file_pattern=file_pattern,
                    recursive=recursive,
                    output_prefix=batch_prefix,
                    batch_id=batch_id,
                    number_of_files=number_of_files,
                )
            else:
                result = processor.process_batch_from_s3_uri(
                    s3_uri=s3_uri,
                    file_pattern=file_pattern,
                    recursive=recursive,
                    output_prefix=batch_prefix,
                    batch_id=batch_id,
                )

            return BatchResult(
                batch_id=result["batch_id"],
                document_ids=result["document_ids"],
                queued=result.get("queued", 0),
                uploaded=result.get("uploaded", 0),
                failed=result.get("failed", 0),
                baselines_uploaded=result.get("baselines_uploaded", 0),
                source=result.get("source", ""),
                output_prefix=result.get("output_prefix", batch_prefix),
                timestamp=datetime.fromisoformat(
                    result.get("timestamp", datetime.now(timezone.utc).isoformat())
                ),
            )
        except Exception as e:
            raise IDPProcessingError(f"Batch processing failed: {e}") from e

    def _process_test_set(
        self,
        processor,
        test_set: str,
        context: Optional[str],
        number_of_files: Optional[int],
    ) -> Dict[str, Any]:
        """Process a test set (internal helper)."""
        import json

        import boto3

        lambda_client = boto3.client("lambda", region_name=self._client._region)
        all_functions = []
        paginator = lambda_client.get_paginator("list_functions")
        for page in paginator.paginate():
            all_functions.extend(page["Functions"])

        stack_name = self._client._require_stack()
        test_runner_function = next(
            (
                f["FunctionName"]
                for f in all_functions
                if stack_name in f["FunctionName"]
                and "TestRunnerFunction" in f["FunctionName"]
            ),
            None,
        )

        if not test_runner_function:
            raise IDPResourceNotFoundError(
                f"TestRunnerFunction not found for stack {stack_name}"
            )

        payload = {"arguments": {"input": {"testSetId": test_set}}}
        if context:
            payload["arguments"]["input"]["context"] = context
        if number_of_files:
            payload["arguments"]["input"]["numberOfFiles"] = number_of_files

        response = lambda_client.invoke(
            FunctionName=test_runner_function, Payload=json.dumps(payload)
        )
        result = json.loads(response["Payload"].read())

        resources = processor.resources
        test_set_bucket = resources.get("TestSetBucket")
        s3_client = boto3.client("s3", region_name=self._client._region)

        document_ids = []
        response = s3_client.list_objects_v2(
            Bucket=test_set_bucket, Prefix=f"{test_set}/input/"
        )

        if "Contents" in response:
            batch_id = result["testRunId"]
            for obj in response["Contents"]:
                key = obj["Key"]
                if not key.endswith("/"):
                    filename = key.split("/")[-1]
                    document_ids.append(f"{batch_id}/{filename}")

        return {
            "batch_id": result["testRunId"],
            "document_ids": document_ids,
            "queued": result.get("filesCount", len(document_ids)),
            "uploaded": 0,
            "failed": 0,
            "source": f"test-set:{test_set}",
            "output_prefix": test_set,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def rerun(
        self,
        step: Union[str, RerunStep],
        document_ids: Optional[List[str]] = None,
        batch_id: Optional[str] = None,
        stack_name: Optional[str] = None,
        **kwargs,
    ) -> BatchRerunResult:
        """Rerun processing for existing documents from a specific step.

        Args:
            step: Pipeline step to rerun from
            document_ids: List of document IDs to rerun
            batch_id: Batch ID (will rerun all documents in batch)
            stack_name: Optional stack name override
            **kwargs: Additional parameters

        Returns:
            BatchRerunResult with rerun statistics
        """
        from idp_sdk.core.rerun_processor import RerunProcessor

        name = self._client._require_stack(stack_name)
        step_str = step.value if isinstance(step, RerunStep) else step

        if not document_ids and not batch_id:
            raise IDPConfigurationError("Must specify either document_ids or batch_id")

        try:
            processor = RerunProcessor(stack_name=name, region=self._client._region)

            if batch_id and not document_ids:
                document_ids = processor.get_batch_document_ids(batch_id)

            result = processor.rerun_documents(
                document_ids=document_ids, step=step_str, monitor=False
            )

            return BatchRerunResult(
                documents_queued=result.get("documents_queued", 0),
                documents_failed=result.get("documents_failed", 0),
                failed_documents=result.get("failed_documents", []),
                step=RerunStep(step_str),
            )
        except Exception as e:
            raise IDPProcessingError(f"Rerun failed: {e}") from e

    def get_status(
        self,
        batch_id: str,
        stack_name: Optional[str] = None,
        **kwargs,
    ) -> BatchStatus:
        """Get status of a batch.

        Args:
            batch_id: Batch identifier
            stack_name: Optional stack name override
            **kwargs: Additional parameters

        Returns:
            BatchStatus with batch processing information
        """
        from idp_sdk.core.batch_processor import BatchProcessor
        from idp_sdk.core.progress_monitor import ProgressMonitor

        name = self._client._require_stack(stack_name)
        processor = BatchProcessor(stack_name=name, region=self._client._region)

        batch_info = processor.get_batch_info(batch_id)
        if not batch_info:
            raise IDPResourceNotFoundError(f"Batch not found: {batch_id}")

        document_ids = batch_info["document_ids"]

        monitor = ProgressMonitor(
            stack_name=name, resources=processor.resources, region=self._client._region
        )
        status_data = monitor.get_batch_status(document_ids)
        stats = monitor.calculate_statistics(status_data)

        documents = []
        for category in ["completed", "running", "queued", "failed"]:
            for doc in status_data.get(category, []):
                start_time = doc.get("start_time") or None
                end_time = doc.get("end_time") or None
                # Convert empty strings to None for datetime fields
                if start_time == "":
                    start_time = None
                if end_time == "":
                    end_time = None
                documents.append(
                    DocumentStatus(
                        document_id=doc.get("document_id", ""),
                        status=doc.get("status", "UNKNOWN"),
                        start_time=start_time,
                        end_time=end_time,
                        duration_seconds=doc.get("duration"),
                        num_pages=doc.get("num_pages"),
                        num_sections=doc.get("num_sections"),
                        error=doc.get("error"),
                    )
                )

        return BatchStatus(
            batch_id=batch_id,
            documents=documents,
            total=stats.get("total", len(documents)),
            completed=stats.get("completed", 0),
            failed=stats.get("failed", 0),
            in_progress=stats.get("running", 0),
            queued=stats.get("queued", 0),
            success_rate=stats.get("success_rate", 0.0) / 100.0,
            all_complete=stats.get("all_complete", False),
        )

    def list(
        self,
        limit: int = 10,
        next_token: Optional[str] = None,
        stack_name: Optional[str] = None,
        **kwargs,
    ) -> BatchListResult:
        """List recent batch processing jobs.

        Args:
            limit: Maximum number of batches to return
            next_token: Pagination token from previous request
            stack_name: Optional stack name override
            **kwargs: Additional parameters

        Returns:
            BatchListResult with batches and optional next_token
        """
        from idp_sdk.core.batch_processor import BatchProcessor

        name = self._client._require_stack(stack_name)
        processor = BatchProcessor(stack_name=name, region=self._client._region)
        result = processor.list_batches(limit=limit, next_token=next_token)

        batches = [
            BatchInfo(
                batch_id=b["batch_id"],
                document_ids=b["document_ids"],
                queued=b.get("queued", 0),
                failed=b.get("failed", 0),
                timestamp=b.get("timestamp", ""),
            )
            for b in result["batches"]
        ]

        return BatchListResult(
            batches=batches,
            count=result["count"],
            next_token=result.get("next_token"),
        )

    def download_results(
        self,
        batch_id: str,
        output_dir: str,
        file_types: Optional[List[str]] = None,
        stack_name: Optional[str] = None,
        **kwargs,
    ) -> BatchDownloadResult:
        """Download processing results from OutputBucket.

        Args:
            batch_id: Batch identifier
            output_dir: Local directory to save results
            file_types: List of file types to download
            stack_name: Optional stack name override
            **kwargs: Additional parameters

        Returns:
            BatchDownloadResult with download statistics
        """
        from idp_sdk.core.batch_processor import BatchProcessor

        name = self._client._require_stack(stack_name)
        processor = BatchProcessor(stack_name=name, region=self._client._region)

        types_list = file_types or ["all"]
        if "all" in types_list:
            types_list = ["pages", "sections", "summary", "evaluation"]

        result = processor.download_batch_results(
            batch_id=batch_id, output_dir=output_dir, file_types=types_list
        )

        return BatchDownloadResult(
            files_downloaded=result.get("files_downloaded", 0),
            documents_downloaded=result.get("documents_downloaded", 0),
            output_dir=result.get("output_dir", output_dir),
        )

    def download_sources(
        self,
        batch_id: str,
        output_dir: str,
        stack_name: Optional[str] = None,
        **kwargs,
    ) -> BatchDownloadResult:
        """Download original source files from InputBucket for all documents in a batch.

        Args:
            batch_id: Batch identifier
            output_dir: Local directory to save source files
            stack_name: Optional stack name override
            **kwargs: Additional parameters

        Returns:
            BatchDownloadResult with download statistics
        """
        import os

        import boto3

        from idp_sdk.core.batch_processor import BatchProcessor

        name = self._client._require_stack(stack_name)
        resources = self._client._get_stack_resources(name)
        input_bucket = resources["InputBucket"]

        processor = BatchProcessor(stack_name=name, region=self._client._region)
        batch_info = processor.get_batch_info(batch_id)
        if not batch_info:
            raise IDPResourceNotFoundError(f"Batch not found: {batch_id}")

        document_ids = batch_info["document_ids"]
        s3_client = boto3.client("s3", region_name=self._client._region)

        os.makedirs(output_dir, exist_ok=True)
        files_downloaded = 0

        try:
            for doc_id in document_ids:
                local_path = os.path.join(output_dir, doc_id)
                local_dir = os.path.dirname(local_path)
                os.makedirs(local_dir, exist_ok=True)

                s3_client.download_file(
                    Bucket=input_bucket, Key=doc_id, Filename=local_path
                )
                files_downloaded += 1

            return BatchDownloadResult(
                files_downloaded=files_downloaded,
                documents_downloaded=files_downloaded,
                output_dir=output_dir,
            )
        except Exception as e:
            raise IDPProcessingError(f"Failed to download sources: {e}") from e

    def delete_documents(
        self,
        batch_id: str,
        status_filter: Optional[str] = None,
        stack_name: Optional[str] = None,
        dry_run: bool = False,
        continue_on_error: bool = True,
        **kwargs,
    ) -> BatchDeletionResult:
        """Permanently delete all documents in a batch and their associated data.

        Args:
            batch_id: Batch identifier
            status_filter: Optional status filter (e.g., 'FAILED', 'COMPLETED')
            stack_name: Optional stack name override
            dry_run: If True, only simulate deletion without actually deleting
            continue_on_error: If True, continue deleting other documents if one fails
            **kwargs: Additional parameters

        Returns:
            BatchDeletionResult with deletion statistics
        """
        import boto3
        from idp_common.delete_documents import delete_documents, get_documents_by_batch

        name = self._client._require_stack(stack_name)
        resources = self._client._get_stack_resources(name)

        input_bucket = resources.get("InputBucket")
        output_bucket = resources.get("OutputBucket")
        documents_table_name = resources.get("DocumentsTable")

        if not input_bucket or not output_bucket or not documents_table_name:
            raise IDPResourceNotFoundError(
                "Required resources not found: InputBucket, OutputBucket, or DocumentsTable"
            )

        dynamodb = boto3.resource("dynamodb", region_name=self._client._region)
        tracking_table = dynamodb.Table(documents_table_name)
        s3_client = boto3.client("s3", region_name=self._client._region)

        try:
            document_ids = get_documents_by_batch(
                tracking_table=tracking_table,
                batch_id=batch_id,
                status_filter=status_filter,
            )

            if not document_ids:
                return BatchDeletionResult(
                    success=True,
                    deleted_count=0,
                    failed_count=0,
                    total_count=0,
                    dry_run=dry_run,
                    results=[],
                )

            result = delete_documents(
                object_keys=document_ids,
                tracking_table=tracking_table,
                s3_client=s3_client,
                input_bucket=input_bucket,
                output_bucket=output_bucket,
                dry_run=dry_run,
                continue_on_error=continue_on_error,
            )

            single_results = [
                DocumentDeletionResult(
                    success=r.get("success", False),
                    object_key=r.get("object_key", ""),
                    deleted=r.get("deleted", {}),
                    errors=r.get("errors", []),
                )
                for r in result.get("results", [])
            ]

            return BatchDeletionResult(
                success=result.get("success", False),
                deleted_count=result.get("deleted_count", 0),
                failed_count=result.get("failed_count", 0),
                total_count=result.get("total_count", 0),
                dry_run=result.get("dry_run", dry_run),
                results=single_results,
            )
        except Exception as e:
            raise IDPProcessingError(f"Batch deletion failed: {e}") from e

    def stop_workflows(
        self,
        stack_name: Optional[str] = None,
        skip_purge: bool = False,
        skip_stop: bool = False,
        **kwargs,
    ) -> StopWorkflowsResult:
        """Stop all running workflows for a stack.

        Args:
            stack_name: Optional stack name override
            skip_purge: Skip purging the queue
            skip_stop: Skip stopping executions
            **kwargs: Additional parameters

        Returns:
            StopWorkflowsResult with stop statistics
        """
        from idp_sdk.core.stop_workflows import WorkflowStopper

        name = self._client._require_stack(stack_name)
        stopper = WorkflowStopper(stack_name=name, region=self._client._region)
        results = stopper.stop_all(skip_purge=skip_purge, skip_stop=skip_stop)

        return StopWorkflowsResult(
            executions_stopped=results.get("executions_stopped"),
            documents_aborted=results.get("documents_aborted"),
            queue_purged=not skip_purge,
        )
