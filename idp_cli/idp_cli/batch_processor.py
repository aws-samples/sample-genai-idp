# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Batch Processor Module

Handles batch document upload and processing through SQS queue.
"""

import glob as glob_module
import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

from .manifest_parser import parse_manifest
from .stack_info import StackInfo

logger = logging.getLogger(__name__)


class BatchProcessor:
    """Processes batches of documents for IDP pipeline"""

    def __init__(
        self,
        stack_name: str,
        config_path: Optional[str] = None,
        region: Optional[str] = None,
    ):
        """
        Initialize batch processor

        Args:
            stack_name: Name of the CloudFormation stack
            config_path: Optional path to configuration YAML
            region: AWS region (optional)
        """
        self.stack_name = stack_name
        self.config_path = config_path
        self.region = region

        # Initialize AWS clients
        self.s3 = boto3.client("s3", region_name=region)
        self.dynamodb = boto3.resource("dynamodb", region_name=region)

        # Get stack resources
        stack_info = StackInfo(stack_name, region)
        if not stack_info.validate_stack():
            raise ValueError(
                f"Stack '{stack_name}' is not in a valid state for operations"
            )

        self.resources = stack_info.get_resources()
        logger.info(f"Initialized batch processor for stack: {stack_name}")

    def process_batch(
        self,
        manifest_path: str,
        output_prefix: str = "cli-batch",
        batch_id: Optional[str] = None,
    ) -> Dict:
        """
        Process batch of documents from manifest

        Args:
            manifest_path: Path to manifest file (CSV or JSON)
            output_prefix: Prefix for output organization
            batch_id: Optional custom batch ID (auto-generated if not provided)

        Returns:
            Dictionary with batch processing results
        """
        logger.info(f"Processing batch from manifest: {manifest_path}")

        # Generate or use provided batch ID
        if not batch_id:
            batch_id = self._generate_batch_id(output_prefix)
        logger.info(f"Batch ID: {batch_id}")

        # Parse manifest
        documents = parse_manifest(manifest_path)
        logger.info(f"Found {len(documents)} documents in manifest")

        # Process documents
        return self._process_documents(
            documents, batch_id, output_prefix, manifest_path
        )

    def process_batch_from_directory(
        self,
        dir_path: str,
        file_pattern: str = "*.pdf",
        recursive: bool = True,
        output_prefix: str = "cli-batch",
        batch_id: Optional[str] = None,
    ) -> Dict:
        """
        Process batch of documents from local directory

        Args:
            dir_path: Path to local directory
            file_pattern: Glob pattern for files (default: *.pdf)
            recursive: Include subdirectories
            output_prefix: Prefix for output organization
            batch_id: Optional custom batch ID (auto-generated if not provided)

        Returns:
            Dictionary with batch processing results
        """
        logger.info(f"Scanning directory: {dir_path}")

        # Generate or use provided batch ID
        if not batch_id:
            batch_id = self._generate_batch_id(output_prefix)
        logger.info(f"Batch ID: {batch_id}")

        # Scan directory and create manifest
        documents = self._scan_local_directory(dir_path, file_pattern, recursive)
        logger.info(f"Found {len(documents)} documents in directory")

        if not documents:
            raise ValueError(
                f"No documents found matching pattern '{file_pattern}' in {dir_path}"
            )

        # Process documents
        return self._process_documents(
            documents, batch_id, output_prefix, dir_path, base_dir=dir_path
        )

    def process_batch_from_s3_uri(
        self,
        s3_uri: str,
        file_pattern: str = "*.pdf",
        recursive: bool = True,
        output_prefix: str = "cli-batch",
        batch_id: Optional[str] = None,
    ) -> Dict:
        """
        Process batch of documents from S3 URI

        Args:
            s3_uri: S3 URI (e.g., s3://bucket/prefix/) - can be any bucket
            file_pattern: Pattern for files (default: *.pdf)
            recursive: Include sub-prefixes
            output_prefix: Prefix for output organization
            batch_id: Optional custom batch ID (auto-generated if not provided)

        Returns:
            Dictionary with batch processing results
        """
        logger.info(f"Scanning S3 URI: {s3_uri}")

        # Generate or use provided batch ID
        if not batch_id:
            batch_id = self._generate_batch_id(output_prefix)
        logger.info(f"Batch ID: {batch_id}")

        # Parse S3 URI to get bucket and prefix
        if not s3_uri.startswith("s3://"):
            raise ValueError(f"Invalid S3 URI: {s3_uri}. Must start with s3://")

        uri_parts = s3_uri[5:].split("/", 1)
        source_bucket = uri_parts[0]
        source_prefix = uri_parts[1] if len(uri_parts) > 1 else ""

        # Scan S3 URI and create manifest
        documents = self._scan_s3_uri(
            source_bucket, source_prefix, file_pattern, recursive
        )
        logger.info(f"Found {len(documents)} documents in S3 URI")

        if not documents:
            raise ValueError(
                f"No documents found matching pattern '{file_pattern}' in {s3_uri}"
            )

        # Process documents
        return self._process_documents(
            documents,
            batch_id,
            output_prefix,
            s3_uri,
        )

    def _process_documents(
        self,
        documents: List[Dict],
        batch_id: str,
        output_prefix: str,
        source: str,
        base_dir: Optional[str] = None,
    ) -> Dict:
        """
        Process list of documents

        Args:
            documents: List of document specifications
            batch_id: Batch identifier
            steps: Steps to execute
            output_prefix: Output prefix
            source: Source path/manifest for metadata
            base_dir: Base directory for path preservation (optional)

        Returns:
            Dictionary with batch processing results
        """
        results = {
            "batch_id": batch_id,
            "document_ids": [],
            "uploaded": 0,
            "queued": 0,
            "failed": 0,
            "baselines_uploaded": 0,
            "source": source,
            "output_prefix": output_prefix,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        for doc in documents:
            try:
                # Upload baseline if specified
                if doc.get("baseline_source"):
                    try:
                        self._upload_baseline(doc, batch_id, base_dir)
                        results["baselines_uploaded"] += 1
                        logger.info(f"Uploaded baseline for {doc['filename']}")
                    except Exception as e:
                        logger.error(
                            f"Failed to upload baseline for {doc['filename']}: {e}"
                        )
                        # Continue processing document even if baseline fails

                # Handle document upload/reference
                # S3 upload automatically triggers EventBridge -> QueueSender -> SQS
                s3_key = self._process_document_with_base(doc, batch_id, base_dir)

                results["document_ids"].append(
                    s3_key
                )  # Use s3_key as document_id for tracking
                results["queued"] += 1

                if doc["type"] == "local":
                    results["uploaded"] += 1

            except Exception as e:
                filename = doc.get(
                    "filename", os.path.basename(doc.get("path", "unknown"))
                )
                logger.error(f"Failed to process document {filename}: {e}")
                results["failed"] += 1

        # Store batch metadata
        self._store_batch_metadata(batch_id, results)

        logger.info(
            f"Batch processing complete: {results['queued']} queued, "
            f"{results['failed']} failed, {results['baselines_uploaded']} baselines uploaded"
        )
        return results

    def _scan_local_directory(
        self, dir_path: str, pattern: str, recursive: bool
    ) -> List[Dict]:
        """
        Scan local directory for documents

        Args:
            dir_path: Path to directory
            pattern: Glob pattern for files
            recursive: Include subdirectories

        Returns:
            List of document specifications
        """
        documents = []
        dir_path = os.path.abspath(dir_path)

        # Build glob pattern
        if recursive:
            search_pattern = os.path.join(dir_path, "**", pattern)
        else:
            search_pattern = os.path.join(dir_path, pattern)

        # Find all matching files
        for file_path in glob_module.glob(search_pattern, recursive=recursive):
            if os.path.isfile(file_path):
                # Calculate relative path from base directory
                rel_path = os.path.relpath(file_path, dir_path)

                # Use relative path (without extension) as document ID
                doc_id = os.path.splitext(rel_path)[0]

                # Extract filename
                filename = os.path.basename(file_path)

                documents.append(
                    {
                        "document_id": doc_id,
                        "path": file_path,
                        "filename": filename,  # Add filename key
                        "relative_path": rel_path,  # Store for path preservation
                        "type": "local",
                    }
                )

        return documents

    def _scan_s3_uri(
        self, bucket: str, prefix: str, pattern: str, recursive: bool
    ) -> List[Dict]:
        """
        Scan S3 URI for documents

        Args:
            bucket: S3 bucket name
            prefix: S3 prefix
            pattern: File pattern (supports * wildcard)
            recursive: Include sub-prefixes

        Returns:
            List of document specifications
        """
        documents = []

        # Ensure prefix ends with / if not empty
        if prefix and not prefix.endswith("/"):
            prefix = prefix + "/"

        try:
            # List objects
            paginator = self.s3.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=bucket, Prefix=prefix)

            # Convert pattern to simple wildcard match
            import fnmatch

            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj["Key"]

                    # Skip if it's just a directory marker
                    if key.endswith("/"):
                        continue

                    # Check recursive constraint
                    if not recursive:
                        # Only include files directly under prefix (no additional slashes)
                        rel_key = key[len(prefix) :]
                        if "/" in rel_key:
                            continue

                    # Check pattern match
                    filename = os.path.basename(key)
                    if not fnmatch.fnmatch(filename, pattern):
                        continue

                    # Use filename (without extension) as document ID
                    doc_id = os.path.splitext(filename)[0]

                    # Return full S3 URI for copying
                    full_uri = f"s3://{bucket}/{key}"

                    documents.append(
                        {
                            "document_id": doc_id,
                            "path": full_uri,
                            "filename": filename,
                            "type": "s3",  # Will be copied to InputBucket
                        }
                    )

            return documents

        except Exception as e:
            logger.error(f"Error scanning S3 URI: {e}")
            raise

    def _process_document_with_base(
        self, doc: Dict, batch_id: str, base_dir: Optional[str] = None
    ) -> str:
        """
        Process document with optional base directory for path preservation

        Args:
            doc: Document specification
            batch_id: Batch identifier
            base_dir: Base directory for calculating relative paths

        Returns:
            S3 key for the document
        """
        if doc["type"] == "local":
            # Upload local file with path preservation
            s3_key = self._upload_local_file_with_path(doc, batch_id, base_dir)
            logger.info(f"Uploaded {doc['filename']} to {s3_key}")
            return s3_key
        elif doc["type"] == "s3":
            # Copy from external S3 location to InputBucket
            s3_key = self._copy_s3_file(doc, batch_id)
            logger.info(f"Copied {doc['filename']} from {doc['path']} to {s3_key}")
            return s3_key
        elif doc["type"] == "s3-key":
            # Document already in InputBucket
            s3_key = doc["path"]
            self._validate_s3_key(s3_key)
            logger.info(f"Referenced existing {doc['filename']} at {s3_key}")
            return s3_key
        else:
            raise ValueError(f"Unknown document type: {doc['type']}")

    def _upload_local_file_with_path(
        self, doc: Dict, batch_id: str, base_dir: Optional[str] = None
    ) -> str:
        """
        Upload local file to S3 InputBucket with path preservation

        Args:
            doc: Document specification with 'path' and optional 'relative_path'
            batch_id: Batch identifier
            base_dir: Base directory for path preservation

        Returns:
            S3 key for uploaded file
        """
        local_path = doc["path"]
        filename = os.path.basename(local_path)

        # Use relative_path if provided (from directory scan), otherwise use filename
        if "relative_path" in doc and doc["relative_path"]:
            # Preserve directory structure: batch_id/relative_path
            relative_path = doc["relative_path"]
            s3_key = f"{batch_id}/{relative_path}"
        else:
            # Standardized: batch_id/filename
            s3_key = f"{batch_id}/{filename}"

        # Upload file
        input_bucket = self.resources["InputBucket"]
        self.s3.upload_file(Filename=local_path, Bucket=input_bucket, Key=s3_key)

        return s3_key

    def _generate_batch_id(self, prefix: str) -> str:
        """
        Generate batch ID from prefix and timestamp

        Args:
            prefix: Batch prefix (e.g., 'cli-batch', 'experiment-v1')

        Returns:
            Batch ID in format: {prefix}-{YYYYMMDD-HHMMSS}
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"{prefix}-{timestamp}"

    def _process_document(self, doc: Dict, batch_id: str) -> str:
        """
        Process a single document (upload, copy, or reference)

        Args:
            doc: Document specification from manifest
            batch_id: Batch identifier

        Returns:
            S3 key for the document in InputBucket
        """
        if doc["type"] == "local":
            # Upload local file to InputBucket
            s3_key = self._upload_local_file(doc, batch_id)
            logger.info(f"Uploaded {doc['filename']} to {s3_key}")
            return s3_key
        elif doc["type"] == "s3":
            # Copy from external S3 location to InputBucket
            s3_key = self._copy_s3_file(doc, batch_id)
            logger.info(f"Copied {doc['filename']} from {doc['path']} to {s3_key}")
            return s3_key
        elif doc["type"] == "s3-key":
            # Document already in InputBucket, validate it exists
            s3_key = doc["path"]
            self._validate_s3_key(s3_key)
            logger.info(f"Referenced existing {doc['filename']} at {s3_key}")
            return s3_key
        else:
            raise ValueError(f"Unknown document type: {doc['type']}")

    def _upload_local_file(self, doc: Dict, batch_id: str) -> str:
        """Upload local file to S3 InputBucket"""
        local_path = doc["path"]
        filename = doc["filename"]

        # Construct S3 key: batch_id/filename
        s3_key = f"{batch_id}/{filename}"

        # Upload file
        input_bucket = self.resources["InputBucket"]
        self.s3.upload_file(Filename=local_path, Bucket=input_bucket, Key=s3_key)

        return s3_key

    def _copy_s3_file(self, doc: Dict, batch_id: str) -> str:
        """
        Copy file from any S3 location to InputBucket

        Args:
            doc: Document specification with S3 URI
            batch_id: Batch identifier

        Returns:
            S3 key in InputBucket
        """
        s3_uri = doc["path"]
        filename = doc["filename"]

        # Parse S3 URI
        # Format: s3://bucket/key/path/file.pdf
        uri_parts = s3_uri[5:].split("/", 1)  # Remove 's3://' and split
        source_bucket = uri_parts[0]
        source_key = uri_parts[1] if len(uri_parts) > 1 else ""

        if not source_key:
            raise ValueError(f"Invalid S3 URI (no key): {s3_uri}")

        # Construct destination key: batch_id/filename
        dest_key = f"{batch_id}/{filename}"

        # Copy object
        input_bucket = self.resources["InputBucket"]
        copy_source = {"Bucket": source_bucket, "Key": source_key}

        self.s3.copy_object(CopySource=copy_source, Bucket=input_bucket, Key=dest_key)

        return dest_key

    def _upload_baseline(
        self, doc: Dict, batch_id: str, base_dir: Optional[str] = None
    ) -> None:
        """
        Upload baseline data for automatic evaluation

        Args:
            doc: Document specification with baseline_source
            batch_id: Batch identifier
            base_dir: Base directory (unused for baselines)
        """
        baseline_source = doc.get("baseline_source")
        if not baseline_source:
            return

        # Get destination key (matches where document will be processed)
        if "relative_path" in doc and doc["relative_path"]:
            # Directory-based: preserve structure
            dest_doc_key = f"{batch_id}/{doc['relative_path']}"
        else:
            # Manifest-based: use filename
            dest_doc_key = f"{batch_id}/{doc['filename']}"

        baseline_bucket = self.resources.get("EvaluationBaselineBucket")
        if not baseline_bucket:
            logger.warning(
                "EvaluationBaselineBucket not found - skipping baseline upload"
            )
            return

        logger.info(
            f"Uploading baseline from {baseline_source} for document key: {dest_doc_key}"
        )

        # Detect source type
        if baseline_source.startswith("s3://"):
            # Copy from S3 (preserves directory structure)
            self._copy_s3_baseline_tree(baseline_source, baseline_bucket, dest_doc_key)
        else:
            # Upload from local directory
            self._upload_local_baseline_tree(
                baseline_source, baseline_bucket, dest_doc_key
            )

    def _copy_s3_baseline_tree(
        self, source_uri: str, dest_bucket: str, dest_doc_key: str
    ) -> None:
        """
        Copy baseline directory tree from S3

        Args:
            source_uri: S3 URI to baseline root (e.g., s3://bucket/doc-001/)
            dest_bucket: Destination bucket (BaselineEvaluationBucket)
            dest_doc_key: Document key for destination path
        """
        # Parse S3 URI
        uri_parts = source_uri[5:].split("/", 1)
        source_bucket = uri_parts[0]
        source_prefix = uri_parts[1] if len(uri_parts) > 1 else ""

        # Ensure prefix ends with /
        if source_prefix and not source_prefix.endswith("/"):
            source_prefix = source_prefix + "/"

        # List all objects under source prefix
        paginator = self.s3.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=source_bucket, Prefix=source_prefix)

        copied_count = 0
        for page in pages:
            for obj in page.get("Contents", []):
                source_key = obj["Key"]

                # Calculate relative path from source prefix
                rel_path = source_key[len(source_prefix) :]

                # Construct destination key
                dest_key = f"{dest_doc_key}/{rel_path}"

                # Copy object
                copy_source = {"Bucket": source_bucket, "Key": source_key}
                self.s3.copy_object(
                    CopySource=copy_source, Bucket=dest_bucket, Key=dest_key
                )
                copied_count += 1
                logger.debug(f"Copied baseline file: {source_key} -> {dest_key}")

        logger.info(f"Copied {copied_count} baseline files from {source_uri}")

    def _upload_local_baseline_tree(
        self, local_dir: str, dest_bucket: str, dest_doc_key: str
    ) -> None:
        """
        Upload baseline directory tree from local filesystem

        Args:
            local_dir: Local directory containing baseline structure
            dest_bucket: Destination bucket (BaselineEvaluationBucket)
            dest_doc_key: Document key for destination path
        """
        if not os.path.isdir(local_dir):
            raise ValueError(f"Baseline directory not found: {local_dir}")

        local_dir = os.path.abspath(local_dir)
        uploaded_count = 0

        # Walk directory tree
        for root, dirs, files in os.walk(local_dir):
            for filename in files:
                local_file_path = os.path.join(root, filename)

                # Calculate relative path from local_dir
                rel_path = os.path.relpath(local_file_path, local_dir)

                # Construct destination key
                dest_key = f"{dest_doc_key}/{rel_path}"

                # Upload file
                self.s3.upload_file(
                    Filename=local_file_path, Bucket=dest_bucket, Key=dest_key
                )
                uploaded_count += 1
                logger.debug(f"Uploaded baseline file: {local_file_path} -> {dest_key}")

        logger.info(f"Uploaded {uploaded_count} baseline files from {local_dir}")

    def _validate_s3_key(self, s3_key: str):
        """Validate that S3 key exists in InputBucket"""
        input_bucket = self.resources["InputBucket"]

        try:
            self.s3.head_object(Bucket=input_bucket, Key=s3_key)
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                raise ValueError(f"Document not found in InputBucket: {s3_key}")
            raise

    def _store_batch_metadata(self, batch_id: str, results: Dict):
        """Store batch metadata for later retrieval"""
        # Store in S3 for persistence
        output_bucket = self.resources["OutputBucket"]
        metadata_key = f"cli-batches/{batch_id}/metadata.json"

        self.s3.put_object(
            Bucket=output_bucket,
            Key=metadata_key,
            Body=json.dumps(results, indent=2),
            ContentType="application/json",
        )

        logger.debug(f"Stored batch metadata at s3://{output_bucket}/{metadata_key}")

    def get_batch_info(self, batch_id: str) -> Optional[Dict]:
        """
        Retrieve batch metadata

        Args:
            batch_id: Batch identifier

        Returns:
            Batch metadata dictionary or None if not found
        """
        output_bucket = self.resources["OutputBucket"]
        metadata_key = f"cli-batches/{batch_id}/metadata.json"

        try:
            response = self.s3.get_object(Bucket=output_bucket, Key=metadata_key)
            metadata = json.loads(response["Body"].read())
            return metadata
        except self.s3.exceptions.NoSuchKey:
            logger.warning(f"Batch metadata not found: {batch_id}")
            return None
        except Exception as e:
            logger.error(f"Error retrieving batch metadata: {e}")
            return None

    def list_batches(self, limit: int = 10) -> List[Dict]:
        """
        List recent batch jobs

        Args:
            limit: Maximum number of batches to return

        Returns:
            List of batch metadata dictionaries
        """
        output_bucket = self.resources["OutputBucket"]
        prefix = "cli-batches/"

        try:
            response = self.s3.list_objects_v2(
                Bucket=output_bucket, Prefix=prefix, Delimiter="/"
            )

            # Get batch directories
            batch_prefixes = [p["Prefix"] for p in response.get("CommonPrefixes", [])]

            # Sort by name (which includes timestamp) - most recent first
            batch_prefixes = sorted(batch_prefixes, reverse=True)[:limit]

            # Load metadata for each batch
            batches = []
            for batch_prefix in batch_prefixes:
                batch_id = batch_prefix.rstrip("/").split("/")[-1]
                batch_info = self.get_batch_info(batch_id)
                if batch_info:
                    batches.append(batch_info)

            return batches

        except Exception as e:
            logger.error(f"Error listing batches: {e}")
            return []

    def download_batch_results(
        self, batch_id: str, output_dir: str, file_types: List[str]
    ) -> Dict:
        """
        Download batch processing results from OutputBucket with progress display

        Args:
            batch_id: Batch identifier
            output_dir: Local directory to download to
            file_types: List of file types to download (pages, sections, summary)

        Returns:
            Dictionary with download statistics
        """
        from rich.console import Console
        from rich.progress import (
            BarColumn,
            Progress,
            SpinnerColumn,
            TextColumn,
        )

        console = Console()
        output_bucket = self.resources["OutputBucket"]

        # Create output directory
        os.makedirs(output_dir, exist_ok=True)

        # First pass: count files to download
        batch_prefix = f"{batch_id}/"
        paginator = self.s3.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=output_bucket, Prefix=batch_prefix)

        files_to_download = []
        for page in pages:
            for obj in page.get("Contents", []):
                s3_key = obj["Key"]

                # Skip if not in requested file types
                if "all" not in file_types:
                    if not any(f"/{file_type}/" in s3_key for file_type in file_types):
                        continue

                files_to_download.append(s3_key)

        total_files = len(files_to_download)
        console.print(f"Found {total_files} files to download")
        console.print()

        # Download with progress bar
        files_downloaded = 0
        documents_downloaded = set()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("•"),
            TextColumn("{task.completed}/{task.total} files"),
            console=console,
        ) as progress:
            task = progress.add_task("Downloading results...", total=total_files)

            for s3_key in files_to_download:
                # Construct local file path
                local_path = os.path.join(output_dir, s3_key)

                # Create directory if needed
                local_dir = os.path.dirname(local_path)
                os.makedirs(local_dir, exist_ok=True)

                # Download file
                self.s3.download_file(
                    Bucket=output_bucket, Key=s3_key, Filename=local_path
                )

                files_downloaded += 1

                # Track document
                doc_key = s3_key.split("/")[1] if "/" in s3_key else s3_key
                documents_downloaded.add(doc_key)

                # Update progress
                progress.update(task, advance=1)
                logger.debug(f"Downloaded: {s3_key}")

        return {
            "files_downloaded": files_downloaded,
            "documents_downloaded": len(documents_downloaded),
            "output_dir": output_dir,
        }
