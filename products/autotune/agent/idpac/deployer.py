# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

"""IDPACDeployer - Handles stack deployment and test set management."""

import glob
import os
import re
import subprocess
from datetime import datetime
from typing import Optional

import boto3

from idpac.client import MIN_IDP_VERSION


class IDPACDeployer:
    """Handles stack deployment and test set management (stack-independent operations)."""

    def __init__(self, region: str = "us-east-1", profile: Optional[str] = None):
        """
        Args:
            region: AWS region
            profile: AWS credentials profile name (uses default if None)

        Raises:
            RuntimeError: If idp-cli is not installed or version < MIN_IDP_VERSION
        """
        self.region = region
        self.profile = profile
        self._check_cli_version()

    def _check_cli_version(self):
        """Verify idp-cli is installed and meets minimum version requirement."""
        try:
            result = subprocess.run(
                ["idp-cli", "--version"], capture_output=True, text=True
            )
        except FileNotFoundError:
            raise RuntimeError(
                "idp-cli is not installed. Install IDP Accelerator CLI first."
            )
        match = re.search(r"(\d+\.\d+\.\d+)", result.stdout)
        if not match:
            raise RuntimeError(
                f"Could not parse idp-cli version from: {result.stdout.strip()}"
            )
        version = match.group(1)
        to_tuple = lambda v: tuple(int(x) for x in v.split("."))
        if to_tuple(version) < to_tuple(MIN_IDP_VERSION):
            raise RuntimeError(
                f"idp-cli version {version} is too old. "
                f"IDPAC requires >= {MIN_IDP_VERSION}. Please upgrade."
            )

    def _run_idp_cli(self, args: list[str]) -> subprocess.CompletedProcess:
        """Run idp-cli command with common options."""
        cmd = ["idp-cli"]
        if self.profile:
            cmd += ["--profile", self.profile]
        cmd += args + ["--region", self.region]
        return subprocess.run(cmd, capture_output=True, text=True)

    def deploy_stack(
        self,
        stack_name: str,
        admin_email: str,
        wait: bool = True,
        max_concurrent_workflows: int = 500,
    ) -> dict:
        """Deploy a new IDP stack (Unified Pattern, v0.5.0+).

        Args:
            stack_name: Name for the new CloudFormation stack (max 25 characters)
            admin_email: Admin user email address
            wait: Wait for deployment to complete
            max_concurrent_workflows: Maximum concurrent Step Function workflows (default: 500)

        Returns:
            Dict with stack_name, status, outputs (web_url, input_bucket, output_bucket)
        """
        if len(stack_name) > 25:
            raise ValueError(f"Stack name '{stack_name}' is {len(stack_name)} chars, max is 25")

        args = [
            "deploy",
            "--stack-name",
            stack_name,
            "--admin-email",
            admin_email,
            "--max-concurrent",
            str(max_concurrent_workflows),
        ]
        if wait:
            args.append("--wait")

        result = self._run_idp_cli(args)

        return {
            "stack_name": stack_name,
            "status": "success" if result.returncode == 0 else "failed",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    def upload_test_set(
        self,
        stack_name: str,
        test_set_name: str,
        documents_dir: str,
        baselines_dir: str,
        file_pattern: str = "*.pdf",
    ) -> dict:
        """Upload a test set to an existing stack.

        Uploads files directly to S3 and creates the DynamoDB tracking entry,
        bypassing the test set resolver to avoid race conditions.

        Args:
            stack_name: Target CloudFormation stack name
            test_set_name: Name for the test set
            documents_dir: Local directory containing test documents
            baselines_dir: Local directory containing baseline files
            file_pattern: Glob pattern for document files (default: "*.pdf")

        Returns:
            Dict with test_set_name, status, file_count, stdout, stderr
        """
        output_lines = []

        def log(msg: str):
            output_lines.append(msg)
            print(msg)

        try:
            # Get stack resources
            session = boto3.Session(profile_name=self.profile, region_name=self.region)
            cf_client = session.client("cloudformation")
            paginator = cf_client.get_paginator("list_stack_resources")

            # Find test set bucket and tracking table
            test_set_bucket = None
            tracking_table_name = None

            for page in paginator.paginate(StackName=stack_name):
                for r in page.get("StackResourceSummaries", []):
                    if r.get("LogicalResourceId") == "TestSetBucket":
                        test_set_bucket = r.get("PhysicalResourceId")
                    elif r.get("LogicalResourceId") == "TrackingTable":
                        tracking_table_name = r.get("PhysicalResourceId")

            if not test_set_bucket:
                return {
                    "test_set_name": test_set_name,
                    "status": "failed",
                    "stdout": "\n".join(output_lines),
                    "stderr": "Could not find TestSetBucket in stack resources",
                }

            if not tracking_table_name:
                return {
                    "test_set_name": test_set_name,
                    "status": "failed",
                    "stdout": "\n".join(output_lines),
                    "stderr": "Could not find TrackingTable in stack resources",
                }

            log(f"Test set bucket: {test_set_bucket}")

            # Find documents
            documents_dir = os.path.abspath(documents_dir)
            baselines_dir = os.path.abspath(baselines_dir)

            doc_files = glob.glob(os.path.join(documents_dir, file_pattern))
            log(f"Found {len(doc_files)} documents matching '{file_pattern}'")

            if not doc_files:
                return {
                    "test_set_name": test_set_name,
                    "status": "failed",
                    "stdout": "\n".join(output_lines),
                    "stderr": f"No documents found matching pattern '{file_pattern}' in {documents_dir}",
                }

            # Match baselines
            baseline_map = {}
            for item in os.listdir(baselines_dir):
                item_path = os.path.join(baselines_dir, item)
                if os.path.isdir(item_path):
                    baseline_map[item] = item_path

            log(f"Found {len(baseline_map)} baseline directories")

            # Validate matching
            doc_names = {os.path.basename(f) for f in doc_files}
            missing_baselines = doc_names - set(baseline_map.keys())
            if missing_baselines:
                return {
                    "test_set_name": test_set_name,
                    "status": "failed",
                    "stdout": "\n".join(output_lines),
                    "stderr": f"Missing baselines for: {', '.join(list(missing_baselines)[:5])}{'...' if len(missing_baselines) > 5 else ''}",
                }

            log(f"Matched {len(doc_files)}/{len(doc_files)} documents to baselines")

            # Normalize test set ID
            test_set_id = test_set_name.replace(" ", "-").lower()

            s3_client = session.client("s3")

            # Check for existing files under this test set prefix
            existing = s3_client.list_objects_v2(
                Bucket=test_set_bucket, Prefix=f"{test_set_id}/", MaxKeys=1
            )
            if existing.get("KeyCount", 0) > 0:
                return {
                    "test_set_name": test_set_name,
                    "status": "failed",
                    "stdout": "\n".join(output_lines),
                    "stderr": (
                        f"Test set '{test_set_id}' already exists in S3 bucket "
                        f"(s3://{test_set_bucket}/{test_set_id}/). "
                        f"Choose a different test set name to avoid mixing files."
                    ),
                }

            # Upload input documents
            log(f"Uploading {len(doc_files)} input documents...")
            for i, doc_path in enumerate(doc_files):
                filename = os.path.basename(doc_path)
                s3_key = f"{test_set_id}/input/{filename}"
                s3_client.upload_file(doc_path, test_set_bucket, s3_key)
                if (i + 1) % 100 == 0 or i == len(doc_files) - 1:
                    log(f"  Uploaded input {i + 1}/{len(doc_files)}")

            # Upload baseline files
            log(f"Uploading baselines for {len(doc_files)} documents...")
            for i, doc_path in enumerate(doc_files):
                filename = os.path.basename(doc_path)
                baseline_path = baseline_map.get(filename)
                if baseline_path:
                    for root, dirs, files in os.walk(baseline_path):
                        for f in files:
                            file_path = os.path.join(root, f)
                            rel_path = os.path.relpath(file_path, baseline_path)
                            s3_key = f"{test_set_id}/baseline/{filename}/{rel_path}"
                            s3_client.upload_file(file_path, test_set_bucket, s3_key)
                if (i + 1) % 100 == 0 or i == len(doc_files) - 1:
                    log(f"  Uploaded baseline {i + 1}/{len(doc_files)}")

            # Create DynamoDB tracking entry directly (bypassing resolver)
            log("Creating test set tracking entry...")
            dynamodb = session.resource("dynamodb")
            table = dynamodb.Table(tracking_table_name)

            timestamp = datetime.utcnow().isoformat() + "Z"
            table.put_item(
                Item={
                    "PK": f"testset#{test_set_id}",
                    "SK": "metadata",
                    "id": test_set_id,
                    "name": test_set_name,
                    "description": "",
                    "filePattern": file_pattern,
                    "fileCount": len(doc_files),
                    "status": "COMPLETED",
                    "createdAt": timestamp,
                }
            )

            log(f"Test set '{test_set_name}' created successfully")
            log(f"  Input files: s3://{test_set_bucket}/{test_set_id}/input/")
            log(f"  Baseline files: s3://{test_set_bucket}/{test_set_id}/baseline/")

            return {
                "test_set_name": test_set_name,
                "test_set_id": test_set_id,
                "status": "success",
                "file_count": len(doc_files),
                "stdout": "\n".join(output_lines),
                "stderr": "",
            }

        except Exception as e:
            return {
                "test_set_name": test_set_name,
                "status": "failed",
                "stdout": "\n".join(output_lines),
                "stderr": str(e),
            }

    def destroy_stack(self, stack_name: str, wait: bool = True) -> dict:
        """Destroy a stack and all associated resources.

        Args:
            stack_name: CloudFormation stack name to destroy
            wait: Wait for deletion to complete

        Returns:
            Dict with stack_name, status, stdout, stderr, returncode
        """
        args = [
            "delete",
            "--stack-name",
            stack_name,
            "--force-delete-all",
            "--force",
            "--empty-buckets",
        ]
        if not wait:
            args.append("--no-wait")

        result = self._run_idp_cli(args)

        return {
            "stack_name": stack_name,
            "status": "success" if result.returncode == 0 else "failed",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
