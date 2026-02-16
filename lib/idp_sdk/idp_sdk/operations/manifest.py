# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Manifest operations for IDP SDK."""

import csv
import fnmatch
import glob as glob_module
import os
from typing import Optional

import boto3

from idp_sdk.exceptions import IDPConfigurationError, IDPResourceNotFoundError
from idp_sdk.models import ManifestResult, ManifestValidationResult


class ManifestOperation:
    """Manifest file operations."""

    def __init__(self, client):
        self._client = client

    def generate(
        self,
        directory: Optional[str] = None,
        s3_uri: Optional[str] = None,
        baseline_dir: Optional[str] = None,
        output: Optional[str] = None,
        file_pattern: str = "*.pdf",
        recursive: bool = True,
        test_set: Optional[str] = None,
        stack_name: Optional[str] = None,
        **kwargs,
    ) -> ManifestResult:
        """Generate a manifest file from directory or S3 URI.

        Args:
            directory: Local directory path
            s3_uri: S3 URI (s3://bucket/prefix/)
            baseline_dir: Directory containing baseline data
            output: Output manifest file path
            file_pattern: File pattern for matching
            recursive: Recursively scan directories
            test_set: Test set identifier
            stack_name: Optional stack name (required for test_set)
            **kwargs: Additional parameters

        Returns:
            ManifestResult with generation statistics
        """
        if not directory and not s3_uri:
            raise IDPConfigurationError("Must specify either directory or s3_uri")

        if test_set and not stack_name:
            raise IDPConfigurationError("stack_name is required when using test_set")

        documents = []
        baseline_map = {}

        if directory:
            dir_path = os.path.abspath(directory)
            search_pattern = os.path.join(
                dir_path, "**" if recursive else "", file_pattern
            )
            for file_path in glob_module.glob(search_pattern, recursive=recursive):
                if os.path.isfile(file_path):
                    documents.append({"document_path": file_path})
        else:
            if not s3_uri.startswith("s3://"):
                raise IDPConfigurationError("Invalid S3 URI")

            uri_parts = s3_uri[5:].split("/", 1)
            bucket = uri_parts[0]
            prefix = uri_parts[1] if len(uri_parts) > 1 else ""

            s3 = boto3.client("s3", region_name=self._client._region)
            paginator = s3.get_paginator("list_objects_v2")

            if prefix and not prefix.endswith("/"):
                prefix = prefix + "/"

            for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if key.endswith("/"):
                        continue
                    if not recursive and "/" in key[len(prefix) :]:
                        continue
                    filename = os.path.basename(key)
                    if not fnmatch.fnmatch(filename, file_pattern):
                        continue
                    documents.append({"document_path": f"s3://{bucket}/{key}"})

        if baseline_dir and directory:
            baseline_path = os.path.abspath(baseline_dir)
            for item in os.listdir(baseline_path):
                item_path = os.path.join(baseline_path, item)
                if os.path.isdir(item_path):
                    baseline_map[item] = item_path

        test_set_created = False
        if test_set:
            name = self._client._require_stack(stack_name)
            resources = self._client._get_stack_resources(name)
            test_set_bucket = resources.get("TestSetBucket")

            if not test_set_bucket:
                raise IDPResourceNotFoundError("TestSetBucket not found")

            s3_client = boto3.client("s3", region_name=self._client._region)

            for doc in documents:
                doc_path = doc["document_path"]
                filename = os.path.basename(doc_path)
                s3_key = f"{test_set}/input/{filename}"
                s3_client.upload_file(doc_path, test_set_bucket, s3_key)
                doc["document_path"] = f"s3://{test_set_bucket}/{s3_key}"

            for filename, baseline_path in baseline_map.items():
                for root, dirs, files in os.walk(baseline_path):
                    for f in files:
                        local_file = os.path.join(root, f)
                        rel_path = os.path.relpath(local_file, baseline_path)
                        s3_key = f"{test_set}/baseline/{filename}/{rel_path}"
                        s3_client.upload_file(local_file, test_set_bucket, s3_key)
                baseline_map[filename] = (
                    f"s3://{test_set_bucket}/{test_set}/baseline/{filename}/"
                )

            test_set_created = True

        if output:
            with open(output, "w", newline="") as f:
                writer = csv.DictWriter(
                    f, fieldnames=["document_path", "baseline_source"]
                )
                writer.writeheader()
                for doc in documents:
                    filename = os.path.basename(doc["document_path"])
                    baseline_source = baseline_map.get(filename, "")
                    writer.writerow(
                        {
                            "document_path": doc["document_path"],
                            "baseline_source": baseline_source,
                        }
                    )

        return ManifestResult(
            output_path=output,
            document_count=len(documents),
            baselines_matched=len(baseline_map),
            test_set_created=test_set_created,
            test_set_name=test_set if test_set_created else None,
        )

    def validate(self, manifest_path: str, **kwargs) -> ManifestValidationResult:
        """Validate a manifest file without processing.

        Args:
            manifest_path: Path to manifest file
            **kwargs: Additional parameters

        Returns:
            ManifestValidationResult with validation status
        """
        from idp_sdk.core.manifest_parser import parse_manifest, validate_manifest

        is_valid, error = validate_manifest(manifest_path)

        document_count = None
        has_baselines = False
        if is_valid:
            documents = parse_manifest(manifest_path)
            document_count = len(documents)
            has_baselines = any(d.get("baseline_source") for d in documents)

        return ManifestValidationResult(
            valid=is_valid,
            error=error,
            document_count=document_count,
            has_baselines=has_baselines,
        )
