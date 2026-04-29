# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: LicenseRef-AWS-Proprietary

"""IDPACClient - Client for interacting with an existing IDP Accelerator stack."""

import json
import re
import subprocess
from typing import Optional

import boto3

MIN_IDP_VERSION = "0.5.0"


class IDPACClient:
    """Client for interacting with an existing IDP Accelerator stack."""

    def __init__(
        self,
        stack_name: str,
        region: str = "us-east-1",
        profile: Optional[str] = None,
    ):
        """
        Args:
            stack_name: CloudFormation stack name (must exist)
            region: AWS region
            profile: AWS credentials profile name (uses default if None)

        Raises:
            ValueError: If stack doesn't exist, resources can't be discovered,
                or the IDP Accelerator version is too old
        """
        self.stack_name = stack_name
        self.region = region
        self.profile = profile

        session = boto3.Session(profile_name=profile, region_name=region)
        self._cfn = session.client("cloudformation")
        self._lambda = session.client("lambda")
        self._s3 = session.client("s3")

        self._discover_resources()

    @staticmethod
    def _parse_version(description: str) -> Optional[str]:
        """Extract version from stack description like '... (v0.4.16)'."""
        match = re.search(r'\(v(\d+\.\d+\.\d+)\)', description or "")
        return match.group(1) if match else None

    @staticmethod
    def _version_gte(version: str, minimum: str) -> bool:
        """Check if version >= minimum using tuple comparison."""
        to_tuple = lambda v: tuple(int(x) for x in v.split("."))
        return to_tuple(version) >= to_tuple(minimum)

    def _discover_resources(self):
        """Discover stack resources from CloudFormation outputs."""
        response = self._cfn.describe_stacks(StackName=self.stack_name)
        stack = response["Stacks"][0]

        # Check IDP version from stack description
        self.idp_version = self._parse_version(stack.get("Description", ""))
        if self.idp_version and not self._version_gte(self.idp_version, MIN_IDP_VERSION):
            raise ValueError(
                f"IDP Accelerator stack '{self.stack_name}' is version {self.idp_version}, "
                f"but IDPAC requires >= {MIN_IDP_VERSION}. Please upgrade the stack."
            )

        outputs = {
            o["OutputKey"]: o["OutputValue"]
            for o in stack.get("Outputs", [])
        }

        self.input_bucket = outputs.get("S3InputBucketName")
        self.output_bucket = outputs.get("S3OutputBucketName")
        self.testset_bucket = outputs.get("S3TestSetBucketName")

        # Find TestResultsResolver Lambda using paginator
        self.test_results_lambda = None
        paginator = self._lambda.get_paginator("list_functions")
        for page in paginator.paginate():
            for fn in page["Functions"]:
                if self.stack_name in fn["FunctionName"] and "TestResultsResolver" in fn["FunctionName"]:
                    self.test_results_lambda = fn["FunctionName"]
                    return

    def _run_idp_cli(self, args: list[str], stack_required: bool = True) -> subprocess.CompletedProcess:
        """Run idp-cli command with common options.
        
        Args:
            args: CLI arguments
            stack_required: If True, append stack-name and region
        """
        cmd = ["idp-cli"]
        if self.profile:
            cmd += ["--profile", self.profile]
        cmd += args
        if stack_required:
            cmd += ["--stack-name", self.stack_name, "--region", self.region]
        return subprocess.run(cmd, capture_output=True, text=True)

    def _invoke_test_results_lambda(self, field_name: str, arguments: dict) -> dict:
        """Invoke TestResultsResolver Lambda directly."""
        payload = {"info": {"fieldName": field_name}, "arguments": arguments}
        response = self._lambda.invoke(
            FunctionName=self.test_results_lambda,
            Payload=json.dumps(payload),
        )
        return json.loads(response["Payload"].read().decode())

    def _write_json(self, data: dict, output_file: Optional[str]) -> None:
        """Write data to JSON file if path provided."""
        if output_file:
            with open(output_file, "w") as f:
                json.dump(data, f, indent=2)

    def upload_config(
        self,
        config_path: str,
        config_version: str,
        description: str,
        validate: bool = True,
    ) -> dict:
        """Upload config to deployed stack via DynamoDB (fast).

        Writes the configuration directly to DynamoDB, completing in seconds.
        Each version is a named, independent snapshot.

        Args:
            config_path: Path to config YAML or JSON file
            config_version: Version name to upload to (e.g., 'v1', 'Production').
            description: Description for the version (e.g., 'Switched to Sonnet for extraction')
            validate: Validate config before uploading

        Returns:
            Dict with status, stdout, stderr
        """
        args = [
            "config-upload",
            "--stack-name", self.stack_name,
            "--config-file", config_path,
            "--config-version", config_version,
            "--version-description", description,
            "--region", self.region,
        ]
        if not validate:
            args.append("--no-validate")

        result = self._run_idp_cli(args, stack_required=False)
        return {
            "status": "success" if result.returncode == 0 else "failed",
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def run_inference(
        self,
        documents_dir: str,
        config_version: str,
        monitor: bool = True,
        file_pattern: str = "*.pdf",
        number_of_files: Optional[int] = None,
    ) -> dict:
        """Run inference on documents without a test set or ground truth.

        Processes documents through the full IDP pipeline (OCR → classification →
        extraction) without needing baselines or test studio integration. Use this
        when ground truth is not available.

        Args:
            documents_dir: Local directory containing documents to process
            config_version: Configuration version to use (e.g., 'v1')
            monitor: Monitor until completion
            file_pattern: Glob pattern for document files (default: "*.pdf")
            number_of_files: Limit number of files to process (None = all)

        Returns:
            Dict with batch_id, status, stdout, stderr, returncode
        """
        args = [
            "process",
            "--dir", documents_dir,
            "--config-version", config_version,
            "--file-pattern", file_pattern,
        ]
        if monitor:
            args.append("--monitor")
        if number_of_files is not None:
            args += ["--number-of-files", str(number_of_files)]

        result = self._run_idp_cli(args)

        # Parse batch_id from output
        batch_id = None
        for line in result.stdout.split("\n"):
            if "Batch ID:" in line:
                batch_id = line.split("Batch ID:")[-1].strip()
            elif "batch" in line.lower() and ":" in line:
                # Fallback: try to find batch ID in various output formats
                parts = line.split(":")
                if len(parts) >= 2:
                    candidate = parts[-1].strip()
                    if candidate.startswith("cli-batch"):
                        batch_id = candidate

        return {
            "batch_id": batch_id,
            "status": "success" if result.returncode == 0 else "failed",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    def download_results(
        self,
        batch_id: str,
        output_dir: str,
        file_types: str = "sections",
    ) -> dict:
        """Download processing results (extraction output, pages, etc.).

        Unlike download_evaluation_results which only downloads evaluation files,
        this method downloads extraction results and other processing output.
        Useful when no ground truth is available and there are no evaluation files.

        Args:
            batch_id: Batch ID from run_inference or run_evaluation
            output_dir: Local directory to save results
            file_types: What to download: 'sections' (extraction), 'pages' (OCR),
                       'summary', 'evaluation', or 'all'

        Returns:
            Dict with status, output_dir, stdout, stderr
        """
        args = [
            "download-results",
            "--batch-id", batch_id,
            "--output-dir", output_dir,
            "--file-types", file_types,
        ]

        result = self._run_idp_cli(args)

        return {
            "status": "success" if result.returncode == 0 else "failed",
            "output_dir": output_dir,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    def run_evaluation(
        self,
        test_set_id: str,
        context: str,
        config_version: str,
    ) -> dict:
        """Launch evaluation job on a test set.

        Args:
            test_set_id: Test set ID (not name)
            context: Description of the run
            config_version: Configuration version to use (e.g., 'v1', 'Production').

        Returns:
            Dict with batch_id, status, files_count, completed, failed,
            success_rate, duration info, and full output
        """
        # TODO: Re-enable --monitor once IDP CLI fixes the race condition where
        # batch metadata hasn't propagated to DynamoDB when monitoring starts.
        # Currently errors with "Batch not found" immediately after queuing.
        args = [
            "process",
            "--test-set", test_set_id,
            "--context", context,
            "--config-version", config_version,
        ]

        result = self._run_idp_cli(args)

        # Parse batch_id from output
        batch_id = None
        for line in result.stdout.split("\n"):
            if "Test run started:" in line:
                batch_id = line.split("Test run started:")[-1].strip()
                break

        return {
            "batch_id": batch_id,
            "status": "success" if result.returncode == 0 else "failed",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    def list_evaluations(
        self,
        time_period_hours: int = 168,
    ) -> list[dict]:
        """List recent evaluation runs.

        Args:
            time_period_hours: How far back to look (default: 168 = 7 days)

        Returns:
            List of evaluation run summaries with testRunId, testSetId,
            testSetName, status, filesCount, createdAt, completedAt, context
        """
        return self._invoke_test_results_lambda(
            "getTestRuns", {"timePeriodHours": time_period_hours}
        )

    def check_evaluation_status(self, test_run_id: str) -> dict:
        """Check status of a single evaluation run."""
        return self._invoke_test_results_lambda(
            "getTestRunStatus", {"testRunId": test_run_id}
        )

    def get_evaluation_summary(
        self,
        batch_id: str,
        output_file: Optional[str] = None,
    ) -> dict:
        """Get aggregated metrics for an evaluation job.

        WARNING: Response can be very large (100KB+) due to per-file scores and
        the full config schema. Use output_file to save to disk, or access only
        the specific keys you need.

        Args:
            batch_id: Test run ID
            output_file: Optional path to save JSON results

        Returns:
            Dict with keys:
                - testRunId: str
                - testSetId: str
                - testSetName: str
                - status: str - terminal states indicating the run has finished:
                    'COMPLETE' = all files processed successfully
                    'PARTIAL_COMPLETE' = run finished but some files failed (check failedFiles count)
                    'FAILED' = entire run failed
                  non-terminal state (still in progress):
                    'RUNNING' = run is still processing files
                - filesCount: int (total files in test set)
                - completedFiles: int
                - failedFiles: int
                - overallAccuracy: float (0.0-1.0)
                - weightedOverallScores: dict[filename, float] (per-file accuracy - can be large!)
                - averageConfidence: float
                - accuracyBreakdown: dict (per-class accuracy)
                - splitClassificationMetrics: dict
                - totalCost: float (USD)
                - costBreakdown: dict
                - createdAt: str (ISO timestamp)
                - completedAt: str (ISO timestamp)
                - context: str (user-provided context)
                - config: dict (the full config schema, NOT the test run config - very large!)

        Note:
            The 'config' field contains the IDP config JSON schema definition,
            NOT the actual configuration used for the test run. This is a quirk
            of the API response. To get the config used, download it separately.
        """
        result = self._invoke_test_results_lambda("getTestRun", {"testRunId": batch_id})
        self._write_json(result, output_file)
        return result

    def download_evaluation_results(self, batch_id: str, output_dir: str) -> dict:
        """Download individual evaluation files.

        Args:
            batch_id: Test run ID
            output_dir: Local directory to save results

        Returns:
            Dict with files_downloaded, documents_downloaded, output_dir
        """
        args = [
            "download-results",
            "--batch-id", batch_id,
            "--output-dir", output_dir,
            "--file-types", "evaluation",
        ]

        result = self._run_idp_cli(args)

        return {
            "status": "success" if result.returncode == 0 else "failed",
            "output_dir": output_dir,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    def compare_evaluations(
        self,
        batch_ids: list[str],
        output_file: Optional[str] = None,
    ) -> dict:
        """Compare two or more evaluation jobs.

        Args:
            batch_ids: List of test run IDs to compare
            output_file: Optional path to save JSON results

        Returns:
            Dict with metrics comparison and config diffs
        """
        result = self._invoke_test_results_lambda("compareTestRuns", {"testRunIds": batch_ids})
        self._write_json(result, output_file)
        return result

    def download_input_document(self, document_id: str, local_path: str) -> str:
        """Download a raw input document from S3.

        Args:
            document_id: Full document path (e.g., "batch-id/filename.pdf")
            local_path: Local file path to save to

        Returns:
            Local path of downloaded file
        """
        self._s3.download_file(self.input_bucket, document_id, local_path)
        return local_path

    def download_single_document_results(self, batch_id: str, filename: str, output_dir: str) -> dict:
        """Download all results for a single document from output bucket.

        Args:
            batch_id: Test run ID
            filename: Document filename (e.g., "abc123.pdf")
            output_dir: Local directory to save results

        Returns:
            Dict with downloaded files list
        """
        import os
        prefix = f"{batch_id}/{filename}/"
        paginator = self._s3.get_paginator('list_objects_v2')
        
        downloaded = []
        for page in paginator.paginate(Bucket=self.output_bucket, Prefix=prefix):
            for obj in page.get('Contents', []):
                key = obj['Key']
                rel_path = key[len(f"{batch_id}/"):]
                local_path = os.path.join(output_dir, rel_path)
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                self._s3.download_file(self.output_bucket, key, local_path)
                downloaded.append(local_path)
        
        return {"files": downloaded, "count": len(downloaded)}

    def download_ground_truth(self, test_set_id: str, filename: str, output_path: str) -> str:
        """Download ground truth (baseline) for a single document.

        Args:
            test_set_id: Test set ID (e.g., "cli-uploaded-test-set")
            filename: Document filename (e.g., "abc123.pdf")
            output_path: Local file path to save the ground truth JSON

        Returns:
            Local path of downloaded file
        """
        import os
        key = f"{test_set_id}/baseline/{filename}/sections/1/result.json"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        self._s3.download_file(self.testset_bucket, key, output_path)
        return output_path

    def download_ground_truth_all_sections(
        self, 
        test_set_id: str, 
        filename: str, 
        output_dir: str
    ) -> dict:
        """Download ground truth for all sections of a packet document.
        
        For packet-splitting datasets, each document may have multiple sections.
        This method downloads all of them.
        
        Args:
            test_set_id: Test set ID (e.g., "docsplit")
            filename: Document filename (e.g., "packet_0001.pdf")
            output_dir: Local directory to save ground truth files
            
        Returns:
            Dict with section paths:
            {
                "sections": {
                    1: "/path/to/output_dir/packet_0001.pdf/sections/1/result.json",
                    2: "/path/to/output_dir/packet_0001.pdf/sections/2/result.json",
                },
                "count": 2
            }
        """
        import os
        
        prefix = f"{test_set_id}/baseline/{filename}/sections/"
        paginator = self._s3.get_paginator('list_objects_v2')
        
        sections = {}
        for page in paginator.paginate(Bucket=self.testset_bucket, Prefix=prefix):
            for obj in page.get('Contents', []):
                key = obj['Key']
                if not key.endswith('result.json'):
                    continue
                # Extract section number from path like ".../sections/3/result.json"
                parts = key.split('/')
                section_idx = parts.index('sections')
                section_num = int(parts[section_idx + 1])
                
                local_path = os.path.join(output_dir, filename, 'sections', str(section_num), 'result.json')
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                self._s3.download_file(self.testset_bucket, key, local_path)
                sections[section_num] = local_path
        
        return {"sections": sections, "count": len(sections)}

    # --- Config Operations ---

    def config_create(
        self,
        output: str,
        features: str = "min",
        pattern: str = "pattern-2",
        include_prompts: bool = False,
    ) -> dict:
        """Generate a config template from system defaults.

        Args:
            output: Output file path
            features: Feature set (min, core, all)
            pattern: Pattern name (pattern-1, pattern-2)
            include_prompts: Include full prompt templates

        Returns:
            Dict with status and output path
        """
        args = [
            "config-create",
            "--features", features,
            "--pattern", pattern,
            "--output", output,
        ]
        if include_prompts:
            args.append("--include-prompts")

        result = self._run_idp_cli(args, stack_required=False)
        return {
            "status": "success" if result.returncode == 0 else "failed",
            "output": output,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def config_validate(self, config_path: str, pattern: str = "pattern-2") -> dict:
        """Validate a config file against schema.

        Args:
            config_path: Path to config file
            pattern: Pattern to validate against

        Returns:
            Dict with valid bool, errors, and warnings
        """
        args = [
            "config-validate",
            "--config-file", config_path,
            "--pattern", pattern,
        ]

        result = self._run_idp_cli(args, stack_required=False)
        return {
            "valid": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def config_download(
        self,
        output: str,
        config_version: str,
        format: str = "minimal",
    ) -> dict:
        """Download config from deployed stack.

        Args:
            output: Output file path
            config_version: Version to download (e.g., 'v1', 'Production').
            format: Config format (minimal or full)

        Returns:
            Dict with status and output path
        """
        args = [
            "config-download",
            "--stack-name", self.stack_name,
            "--output", output,
            "--format", format,
            "--config-version", config_version,
            "--region", self.region,
        ]

        result = self._run_idp_cli(args, stack_required=False)
        return {
            "status": "success" if result.returncode == 0 else "failed",
            "output": output,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def config_list(self) -> dict:
        """List all configuration versions in the deployed stack.

        Returns:
            Dict with status, stdout (version table), stderr
        """
        args = [
            "config-list",
            "--stack-name", self.stack_name,
            "--region", self.region,
        ]

        result = self._run_idp_cli(args, stack_required=False)
        return {
            "status": "success" if result.returncode == 0 else "failed",
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def config_activate(self, config_version: str) -> dict:
        """Activate a configuration version.

        Args:
            config_version: Version name to activate

        Returns:
            Dict with status, stdout, stderr
        """
        args = [
            "config-activate",
            "--stack-name", self.stack_name,
            "--config-version", config_version,
            "--region", self.region,
        ]

        result = self._run_idp_cli(args, stack_required=False)
        return {
            "status": "success" if result.returncode == 0 else "failed",
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def config_delete(self, config_version: str) -> dict:
        """Delete a configuration version.

        Cannot delete the 'default' version or the currently active version.

        Args:
            config_version: Version name to delete

        Returns:
            Dict with status, stdout, stderr
        """
        args = [
            "config-delete",
            "--stack-name", self.stack_name,
            "--config-version", config_version,
            "--force",
            "--region", self.region,
        ]

        result = self._run_idp_cli(args, stack_required=False)
        return {
            "status": "success" if result.returncode == 0 else "failed",
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
