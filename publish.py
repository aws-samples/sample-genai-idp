#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Create new Cfn artifacts bucket if not already existing
Build artifacts
Upload artifacts to S3 bucket for deployment with CloudFormation
"""

import concurrent.futures
import hashlib
import json
import os
import py_compile
import shutil
import subprocess
import sys
import time
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import boto3
import yaml
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError
from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

LIB_DEPENDENCY = "./lib/idp_common_pkg/idp_common"
LIB_PKG_PATH = "./lib/idp_common_pkg"


class IDPPublisher:
    def __init__(self, verbose=False):
        self.console = Console()
        self.verbose = verbose
        self.bucket_basename = None
        self.prefix = None
        self.region = None
        self.acl = None
        self.bucket = None
        self.prefix_and_version = None
        self.version = None
        self.build_errors = []  # Track build errors for verbose reporting
        self.public_sample_udop_model = ""
        self.public = False
        self.main_template = "idp-main.yaml"
        self.use_container_flag = ""
        self.pattern2_use_containers = True  # Default to containers for Pattern-2

        self.s3_client = None
        self.cf_client = None
        self.sts_client = None
        self._is_lib_changed = False
        self.skip_validation = False
        self.lint_enabled = True
        self.account_id = None
        self._layer_arns = {}  # Store built layer ARNs for template injection

    def clean_checksums(self):
        """Delete all .checksum files and Lambda layer caches for full rebuild"""
        self.console.print(
            "[yellow]🧹 Cleaning build cache for full rebuild...[/yellow]"
        )

        checksum_paths = [
            ".checksum",  # main
            "lib/.checksum",  # lib
        ]

        # Add nested stack checksum files
        nested_dir = "nested"
        if os.path.exists(nested_dir):
            for item in os.listdir(nested_dir):
                nested_path = os.path.join(nested_dir, item)
                if os.path.isdir(nested_path):
                    checksum_paths.append(f"{nested_path}/.checksum")

        # Add patterns checksum files
        patterns_dir = "patterns"
        if os.path.exists(patterns_dir):
            for item in os.listdir(patterns_dir):
                pattern_path = os.path.join(patterns_dir, item)
                if os.path.isdir(pattern_path):
                    checksum_paths.append(f"{pattern_path}/.checksum")

        deleted_count = 0
        for checksum_path in checksum_paths:
            if os.path.exists(checksum_path):
                os.remove(checksum_path)
                self.console.print(f"[green]  ✓ Deleted {checksum_path}[/green]")
                deleted_count += 1

        # Delete cached Lambda layer zips to force layer rebuilds
        layers_dir = ".aws-sam/layers"
        if os.path.exists(layers_dir):
            layer_zips = [f for f in os.listdir(layers_dir) if f.endswith(".zip")]
            for layer_zip in layer_zips:
                layer_path = os.path.join(layers_dir, layer_zip)
                os.remove(layer_path)
                self.console.print(f"[green]  ✓ Deleted {layer_path}[/green]")
                deleted_count += 1

        if deleted_count == 0:
            self.console.print("[dim]  No cache files found to delete[/dim]")
        else:
            self.console.print(
                f"[green]✅ Deleted {deleted_count} cache files - full rebuild will be triggered[/green]"
            )

    def _find_all_requirements_files(self):
        """Find all requirements.txt files in the project"""
        requirements_files = []

        # Main Lambda functions
        src_lambda_dir = Path("src/lambda")
        if src_lambda_dir.exists():
            for func_dir in src_lambda_dir.iterdir():
                req_file = func_dir / "requirements.txt"
                if req_file.exists():
                    requirements_files.append(str(req_file))

        # Nested Lambda functions
        nested_dir = Path("nested")
        if nested_dir.exists():
            for nested_item in nested_dir.iterdir():
                nested_src = nested_item / "src"
                if nested_src.exists():
                    for func_dir in nested_src.iterdir():
                        req_file = func_dir / "requirements.txt"
                        if req_file.exists():
                            requirements_files.append(str(req_file))

        # Pattern Lambda functions
        patterns_dir = Path("patterns")
        if patterns_dir.exists():
            for pattern_dir in patterns_dir.iterdir():
                pattern_src = pattern_dir / "src"
                if pattern_src.exists():
                    for func_dir in pattern_src.iterdir():
                        req_file = func_dir / "requirements.txt"
                        if req_file.exists():
                            requirements_files.append(str(req_file))

        return requirements_files

    def _prepare_for_build_at_start(self):
        """Run at script startup - placeholder for future startup checks"""
        self.log_verbose("✅ Build startup checks complete")

    def log_verbose(self, message, style="dim"):
        """Log verbose messages if verbose mode is enabled"""
        if self.verbose:
            # Use markup=False to prevent Rich from eating brackets like [extras]
            self.console.print(message, style=style, markup=False)

    # ========================================================================
    # LOGGING HELPERS - Consistent styling for all output
    # ========================================================================

    def log_phase(self, title, emoji=""):
        """Print a major phase header with separators"""
        separator = "═" * 65
        self.console.print(f"\n[bold cyan]{separator}[/bold cyan]")
        if emoji:
            self.console.print(f"[bold cyan] {emoji} {title.upper()}[/bold cyan]")
        else:
            self.console.print(f"[bold cyan] {title.upper()}[/bold cyan]")
        self.console.print(f"[bold cyan]{separator}[/bold cyan]")

    def log_task(self, message, thread=None):
        """Print task start (cyan with arrow)"""
        prefix = f"[{thread}] " if thread else ""
        self.console.print(f"[cyan]▶ {prefix}{message}[/cyan]")

    def log_detail(self, message, thread=None):
        """Print indented detail info (dim)"""
        prefix = f"[{thread}] " if thread else ""
        self.console.print(f"[dim]  └─ {prefix}{message}[/dim]")

    def log_success(self, message, thread=None):
        """Print success message (green checkmark)"""
        prefix = f"[{thread}] " if thread else ""
        self.console.print(f"[green]✓ {prefix}{message}[/green]")

    def log_cached(self, message, thread=None):
        """Print cached/skipped message (blue arrow)"""
        prefix = f"[{thread}] " if thread else ""
        self.console.print(f"[blue]→ {prefix}{message}[/blue]")

    def log_warning(self, message, thread=None):
        """Print warning message (yellow)"""
        prefix = f"[{thread}] " if thread else ""
        self.console.print(f"[yellow]⚠ {prefix}{message}[/yellow]")

    def log_error(self, message, thread=None):
        """Print error message (red X)"""
        prefix = f"[{thread}] " if thread else ""
        self.console.print(f"[red]✗ {prefix}{message}[/red]")

    def upload_to_s3_with_timer(self, local_path, s3_key, description):
        """Upload file to S3 with a spinner, elapsed time display, and optimized transfer config.

        Uses multi-threaded, multipart uploads for better performance on slow connections.
        Shows progress during upload and final timing on completion.
        """
        # Optimized transfer config for better upload performance
        # Matches AWS CLI's optimized defaults for parallel uploads
        transfer_config = TransferConfig(
            multipart_threshold=5
            * 1024
            * 1024,  # 5 MB - enable multipart for smaller files
            max_concurrency=10,  # Use 10 threads for parallel chunk uploads
            multipart_chunksize=5 * 1024 * 1024,  # 5 MB chunks
            use_threads=True,  # Enable multi-threading
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=self.console,
            transient=True,  # Clears spinner after completion
        ) as progress:
            progress.add_task(f"[cyan]Uploading {description}...", total=None)
            start = time.time()
            self.s3_client.upload_file(
                local_path, self.bucket, s3_key, Config=transfer_config
            )
            elapsed = time.time() - start
        self.log_success(f"Uploaded {description} ({elapsed:.1f}s)")

    def log_error_details(self, component, error_output):
        """Log detailed error information and store for summary"""
        error_info = {"component": component, "error": error_output}
        self.build_errors.append(error_info)

        if self.verbose:
            self.console.print(f"[red]❌ {component} build failed:[/red]")
            self.console.print(f"[red]{error_output}[/red]")
        else:
            self.console.print(
                f"[red]❌ {component} build failed (use --verbose for details)[/red]"
            )

    def run_subprocess_with_logging(
        self, cmd, component_name, cwd=None, realtime=False
    ):
        """Run subprocess with standardized logging"""
        if realtime:
            # Real-time output for long-running processes like npm install
            self.console.print(f"[cyan]Running: {' '.join(cmd)}[/cyan]")

            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=cwd,
                    bufsize=1,
                    universal_newlines=True,
                )

                output_lines = []
                while True:
                    output = process.stdout.readline()
                    if output == "" and process.poll() is not None:
                        break
                    if output:
                        line = output.strip()
                        output_lines.append(line)
                        # Show progress for npm commands
                        if "npm" in " ".join(cmd):
                            if any(
                                keyword in line.lower()
                                for keyword in [
                                    "downloading",
                                    "installing",
                                    "added",
                                    "updated",
                                    "audited",
                                ]
                            ):
                                self.console.print(f"[dim]  {line}[/dim]")
                            elif "warn" in line.lower():
                                self.console.print(f"[yellow]  {line}[/yellow]")
                            elif "error" in line.lower():
                                self.console.print(f"[red]  {line}[/red]")

                return_code = process.poll()

                if return_code != 0:
                    error_msg = f"""Command failed: {" ".join(cmd)}
Working directory: {cwd or os.getcwd()}
Return code: {return_code}

OUTPUT:
{chr(10).join(output_lines)}"""
                    print(error_msg)
                    self.log_error_details(component_name, error_msg)
                    return False, error_msg

                return True, None  # Success, no result object needed for real-time

            except Exception as e:
                error_msg = (
                    f"Failed to execute command: {' '.join(cmd)}\nError: {str(e)}"
                )
                self.log_error_details(component_name, error_msg)
                return False, error_msg
        else:
            # Original behavior - capture all output
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
            if result.returncode != 0:
                error_msg = f"""Command failed: {" ".join(cmd)}
Working directory: {cwd or os.getcwd()}
Return code: {result.returncode}

STDOUT:
{result.stdout}

STDERR:
{result.stderr}"""
                print(error_msg)
                self.log_error_details(component_name, error_msg)
                return False, error_msg
            return True, result

    def print_error_summary(self):
        """Print summary of all build errors"""
        if not self.build_errors:
            return

        self.console.print("\n[red]❌ Build Error Summary:[/red]")
        for i, error_info in enumerate(self.build_errors, 1):
            self.console.print(f"\n[red]{i}. {error_info['component']}:[/red]")
            if self.verbose:
                self.console.print(f"[red]{error_info['error']}[/red]")
            else:
                # Show first few lines of error for non-verbose mode
                error_lines = error_info["error"].strip().split("\n")
                preview_lines = error_lines[:3]  # Show first 3 lines
                for line in preview_lines:
                    self.console.print(f"[red]  {line}[/red]")
                if len(error_lines) > 3:
                    self.console.print(
                        f"[dim]  ... ({len(error_lines) - 3} more lines, use --verbose for full output)[/dim]"
                    )

    def print_usage(self):
        """Print usage information with Rich formatting"""
        self.console.print("\n[bold cyan]Usage:[/bold cyan]")
        self.console.print(
            "  python3 publish.py <cfn_bucket_basename> <cfn_prefix> <region> [public] [--max-workers N] [--verbose] [--no-validate] [--lint on|off]"
        )

        self.console.print("\n[bold cyan]Parameters:[/bold cyan]")
        self.console.print(
            "  [yellow]<cfn_bucket_basename>[/yellow]: Base name for the CloudFormation artifacts bucket"
        )
        self.console.print("  [yellow]<cfn_prefix>[/yellow]: S3 prefix for artifacts")
        self.console.print("  [yellow]<region>[/yellow]: AWS region for deployment")
        self.console.print(
            "  [yellow][public][/yellow]: Optional. If 'public', artifacts will be made publicly readable"
        )
        self.console.print(
            "  [yellow][--max-workers N][/yellow]: Optional. Maximum number of concurrent workers (default: auto-detect)"
        )
        self.console.print(
            "                     Use 1 for sequential processing, higher numbers for more concurrency"
        )
        self.console.print(
            "  [yellow][--verbose, -v][/yellow]: Optional. Enable verbose output for debugging"
        )
        self.console.print(
            "  [yellow][--no-validate][/yellow]: Optional. Skip CloudFormation template validation"
        )
        self.console.print(
            "  [yellow][--clean-build][/yellow]: Optional. Delete all .checksum files to force full rebuild"
        )
        self.console.print(
            "  [yellow][--lint on|off][/yellow]: Optional. Enable/disable UI linting and build validation (default: on)"
        )

    def check_parameters(self, args):
        """Check and validate input parameters"""
        if len(args) < 3:
            self.console.print("[red]Error: Missing required parameters[/red]")
            self.print_usage()
            sys.exit(1)

        # Parse arguments
        self.bucket_basename = args[0]
        self.prefix = args[1].rstrip("/")  # Remove trailing slash
        self.region = args[2]

        # Default values
        self.public = False
        self.acl = "bucket-owner-full-control"
        self.max_workers = None  # Auto-detect

        # Parse optional arguments
        remaining_args = args[3:]
        i = 0
        while i < len(remaining_args):
            arg = remaining_args[i]

            if arg.lower() == "public":
                self.public = True
                self.acl = "public-read"
                self.console.print(
                    "[green]Published S3 artifacts will be accessible by public.[/green]"
                )
            elif arg == "--max-workers":
                if i + 1 >= len(remaining_args):
                    self.console.print(
                        "[red]Error: --max-workers requires a number[/red]"
                    )
                    self.print_usage()
                    sys.exit(1)
                try:
                    self.max_workers = int(remaining_args[i + 1])
                    if self.max_workers < 1:
                        self.console.print(
                            "[red]Error: --max-workers must be at least 1[/red]"
                        )
                        sys.exit(1)
                    self.console.print(
                        f"[green]Using {self.max_workers} concurrent workers[/green]"
                    )
                    i += 1  # Skip the next argument (the number)
                except ValueError:
                    self.console.print(
                        "[red]Error: --max-workers must be followed by a valid number[/red]"
                    )
                    self.print_usage()
                    sys.exit(1)
            elif arg in ["--verbose", "-v"]:
                self.verbose = True
                self.console.print("[green]Verbose mode enabled[/green]")
            elif arg == "--no-validate":
                self.skip_validation = True
                self.console.print(
                    "[yellow]CloudFormation template validation will be skipped[/yellow]"
                )
            elif arg == "--lint":
                if i + 1 >= len(remaining_args):
                    self.console.print(
                        "[red]Error: --lint requires 'on' or 'off'[/red]"
                    )
                    self.print_usage()
                    sys.exit(1)
                lint_value = remaining_args[i + 1].lower()
                if lint_value not in ["on", "off"]:
                    self.console.print("[red]Error: --lint must be 'on' or 'off'[/red]")
                    self.print_usage()
                    sys.exit(1)
                self.lint_enabled = lint_value == "on"
                i += 1  # increment arg counter to avoid parsing "on/off" as an arg of its own
            elif arg == "--clean-build":
                self.clean_checksums()
            else:
                self.console.print(
                    f"[yellow]Warning: Unknown argument '{arg}' ignored[/yellow]"
                )

            i += 1

        if not self.public:
            self.console.print(
                "[yellow]Published S3 artifacts will NOT be accessible by public.[/yellow]"
            )

    def setup_environment(self):
        """Set up environment variables and derived values"""
        os.environ["AWS_DEFAULT_REGION"] = self.region

        # Initialize AWS clients
        self.s3_client = boto3.client("s3", region_name=self.region)
        self.cf_client = boto3.client("cloudformation", region_name=self.region)

        # Read version
        try:
            with open("./VERSION", "r") as f:
                self.version = f.read().strip()
        except FileNotFoundError:
            self.console.print("[red]Error: VERSION file not found[/red]")
            sys.exit(1)

        self.prefix_and_version = f"{self.prefix}/{self.version}"
        self.bucket = f"{self.bucket_basename}-{self.region}"

        # Set UDOP model path based on region
        self.public_sample_udop_model = f"s3://aws-ml-blog-{self.region}/artifacts/genai-idp/udop-finetuning/rvl-cdip/model.tar.gz"

    def check_prerequisites(self):
        """Check for required commands and versions"""
        # Check required commands
        required_commands = ["aws", "sam"]
        for cmd in required_commands:
            if not shutil.which(cmd):
                self.console.print(
                    f"[red]Error: {cmd} is required but not installed[/red]"
                )
                sys.exit(1)

        # Check SAM version
        try:
            result = subprocess.run(
                ["sam", "--version"], capture_output=True, text=True, check=True
            )
            sam_version = result.stdout.split()[3]  # Extract version from output
            min_sam_version = "1.129.0"
            if self.version_compare(sam_version, min_sam_version) < 0:
                self.console.print(
                    f"[red]Error: sam version >= {min_sam_version} is required. (Installed version is {sam_version})[/red]"
                )
                self.console.print(
                    "[yellow]Install: https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/manage-sam-cli-versions.html[/yellow]"
                )
                sys.exit(1)
        except subprocess.CalledProcessError:
            self.console.print("[red]Error: Could not determine SAM version[/red]")
            sys.exit(1)

        # Check Python version
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
        min_python_version = "3.12"
        if self.version_compare(python_version, min_python_version) < 0:
            self.console.print(
                f"[red]Error: Python version >= {min_python_version} is required. (Installed version is {python_version})[/red]"
            )
            sys.exit(1)

    def version_compare(self, version1, version2):
        """Compare two version strings. Returns -1 if v1 < v2, 0 if equal, 1 if v1 > v2"""

        def normalize(v):
            return [int(x) for x in v.split(".")]

        v1_parts = normalize(version1)
        v2_parts = normalize(version2)

        # Pad shorter version with zeros
        max_len = max(len(v1_parts), len(v2_parts))
        v1_parts.extend([0] * (max_len - len(v1_parts)))
        v2_parts.extend([0] * (max_len - len(v2_parts)))

        for i in range(max_len):
            if v1_parts[i] < v2_parts[i]:
                return -1
            elif v1_parts[i] > v2_parts[i]:
                return 1
        return 0

    def setup_artifacts_bucket(self):
        """Create bucket if necessary"""
        try:
            self.s3_client.head_bucket(Bucket=self.bucket)
            self.console.print(f"[green]Using existing bucket: {self.bucket}[/green]")
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "404":
                self.console.print(
                    f"[yellow]Creating s3 bucket: {self.bucket}[/yellow]"
                )
                try:
                    if self.region == "us-east-1":
                        self.s3_client.create_bucket(Bucket=self.bucket)
                    else:
                        self.s3_client.create_bucket(
                            Bucket=self.bucket,
                            CreateBucketConfiguration={
                                "LocationConstraint": self.region
                            },
                        )

                    # Enable versioning
                    self.s3_client.put_bucket_versioning(
                        Bucket=self.bucket,
                        VersioningConfiguration={"Status": "Enabled"},
                    )
                except ClientError as create_error:
                    self.console.print(
                        f"[red]Failed to create bucket: {create_error}[/red]"
                    )
                    sys.exit(1)
            else:
                self.console.print("[red]Error accessing bucket:[/red]")
                self.console.print(str(e), style="red", markup=False)
                sys.exit(1)

    def get_file_checksum(self, file_path):
        """Get SHA256 checksum of a file"""
        if not os.path.exists(file_path):
            return ""

        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def get_directory_checksum(self, directory):
        """Get combined checksum of all files in a directory, excluding development artifacts"""
        if not os.path.exists(directory):
            return ""

        # Define patterns to exclude from checksum calculation
        exclude_dirs = {
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            "build",
            "dist",
            ".aws-sam",
            "node_modules",
            ".git",
            ".vscode",
            ".idea",
            "test-reports",  # Exclude test report directories
        }

        exclude_file_patterns = {
            ".checksum",
            ".build_checksum",
            "lib/.checksum",
            ".pyc",
            ".pyo",
            ".pyd",
            ".so",
            ".egg-info",
            ".coverage",
            ".DS_Store",
            "Thumbs.db",
            "coverage.xml",  # Coverage reports
            "test-results.xml",  # Test result reports
            ".gitkeep",  # Git placeholder files
        }

        exclude_file_suffixes = (
            ".pyc",
            ".pyo",
            ".pyd",
            ".so",
            ".coverage",
            ".log",  # Log files
        )
        exclude_dir_suffixes = (".egg-info",)

        def should_exclude_dir(dir_name):
            """Check if directory should be excluded from checksum"""
            if dir_name in exclude_dirs:
                return True
            if any(dir_name.endswith(suffix) for suffix in exclude_dir_suffixes):
                return True
            # Exclude test directories for library checksum only
            if "lib" in directory and (
                dir_name == "tests" or dir_name.startswith("test_")
            ):
                return True
            return False

        def should_exclude_file(file_name):
            """Check if file should be excluded from checksum"""
            if file_name in exclude_file_patterns:
                return True
            if any(file_name.endswith(suffix) for suffix in exclude_file_suffixes):
                return True
            # Exclude test files for library checksum only
            if "lib" in directory and (
                file_name.startswith("test_")
                or file_name.endswith("_test.py")
                or file_name == "nodeids"  # pytest cache files
                or file_name == "lastfailed"  # pytest cache files
                or file_name
                in ["coverage.xml", "test-results.xml"]  # specific test report files
            ):
                return True
            return False

        checksums = []
        for root, dirs, files in os.walk(directory):
            # Filter out excluded directories in-place to prevent os.walk from descending into them
            dirs[:] = [d for d in dirs if not should_exclude_dir(d)]

            # Sort to ensure consistent ordering
            dirs.sort()
            files.sort()

            for file in files:
                if not should_exclude_file(file):
                    file_path = os.path.join(root, file)
                    if os.path.isfile(file_path):
                        checksums.append(self.get_file_checksum(file_path))

        # Combine all checksums
        combined = "".join(checksums)
        return hashlib.sha256(combined.encode()).hexdigest()

    def build_and_package_template(self, directory, force_rebuild=False):
        """Build and package a template directory with smart rebuild detection"""
        # Track build time
        build_start = time.time()

        try:
            # Pattern-2 uses containers - images built separately by build_and_push_pattern2_containers()
            # SAM build with SkipBuild: True just prepares template
            cmd = ["sam", "build", "--template-file", "template.yaml"]

            # Add container flag if needed
            if self.use_container_flag and self.use_container_flag.strip():
                cmd.append(self.use_container_flag)

            if self.verbose:
                cmd.append("--debug")

            sam_build_start = time.time()

            # Validate Python syntax before building
            if not self._validate_python_syntax(directory):
                raise Exception("Python syntax validation failed")

            self.log_verbose(
                f"Running SAM build command in {directory}: {' '.join(cmd)}"
            )
            # Run SAM build from the pattern directory
            success, result = self.run_subprocess_with_logging(
                cmd, f"SAM build for {directory}", directory
            )
            sam_build_time = time.time() - sam_build_start

            if not success:
                raise Exception("SAM build failed")

            # Package the template (using absolute paths)
            build_template_path = os.path.join(
                directory, ".aws-sam", "build", "template.yaml"
            )
            # Use different name for pattern-2 container deployment
            if directory == "patterns/pattern-2" and self.pattern2_use_containers:
                packaged_template_path = os.path.join(
                    directory, ".aws-sam", "packaged-container.yaml"
                )
            else:
                # Use standard packaged.yaml name
                packaged_template_path = os.path.join(
                    directory, ".aws-sam", "packaged.yaml"
                )

            cmd = [
                "sam",
                "package",
                "--template-file",
                build_template_path,
                "--output-template-file",
                packaged_template_path,
                "--s3-bucket",
                self.bucket,
                "--s3-prefix",
                self.prefix_and_version,
            ]
            if self.verbose:
                cmd.append("--debug")

            # Pattern-1, Pattern-2, and Pattern-3 need --image-repository even with SkipBuild: True
            # SAM package uses this to generate correct ImageUri references in the template
            if directory in ["patterns/pattern-1", "patterns/pattern-3"] or (
                directory == "patterns/pattern-2" and self.pattern2_use_containers
            ):
                placeholder_ecr = (
                    f"{self.account_id}.dkr.ecr.{self.region}.amazonaws.com/placeholder"
                )
                cmd.extend(["--image-repository", placeholder_ecr])

            sam_package_start = time.time()
            self.log_verbose(f"Running SAM package command: {' '.join(cmd)}")
            # Run SAM package from project root (no cwd change needed)
            success, result = self.run_subprocess_with_logging(
                cmd, f"SAM package for {directory}"
            )
            sam_package_time = time.time() - sam_package_start

            if not success:
                raise Exception("SAM package failed")

            # For Pattern-2 with containers, ensure packaged.yaml exists with standard name
            if directory == "patterns/pattern-2" and self.pattern2_use_containers:
                standard_packaged_path = os.path.join(
                    directory, ".aws-sam", "packaged.yaml"
                )
                # If using a different packaged name, copy to standard name for main template compatibility
                if packaged_template_path != standard_packaged_path:
                    import shutil

                    shutil.copy2(packaged_template_path, standard_packaged_path)
                    self.log_verbose(
                        "Created packaged.yaml copy for Pattern-2 compatibility"
                    )

            # Log S3 upload location for Lambda artifacts
            self.console.print(
                f"[dim]  📤 Lambda artifacts uploaded to s3://{self.bucket}/{self.prefix_and_version}/[/dim]"
            )

            # Log timing information
            total_time = time.time() - build_start
            pattern_name = os.path.basename(directory)
            self.console.print(
                f"[dim]  {pattern_name}: build={sam_build_time:.1f}s, package={sam_package_time:.1f}s, total={total_time:.1f}s[/dim]"
            )

        except Exception as e:
            # Delete checksum on any failure to force rebuild next time
            self._delete_checksum_file(directory)
            self.log_verbose(f"Exception in build_and_package_template: {str(e)}")
            self.log_verbose(f"Traceback: {traceback.format_exc()}")
            self.console.print(f"[red]❌ Build failed for {directory}:[/red]")
            self.console.print(str(e), style="red", markup=False)
            sys.exit(1)

        return True

    def build_components_with_smart_detection(
        self, components_needing_rebuild, component_type, max_workers=None
    ):
        """Build patterns or options with smart detection using Lambda Layers."""
        # Filter components by type
        components_to_build = []
        for item in components_needing_rebuild:
            if component_type in item["component"]:
                components_to_build.append(item["component"])

        if not components_to_build:
            self.console.print(f"[green]✅ All {component_type} are up to date[/green]")
            return True

        self.console.print(
            f"[cyan]Building {len(components_to_build)} {component_type} with {max_workers} workers...[/cyan]"
        )

        return self._build_components_concurrently(
            components_to_build, component_type, max_workers
        )

    def _build_components_concurrently(self, components, component_type, max_workers):
        """Generic method to build components concurrently with simple logging.

        Note: Progress bars removed to avoid Rich LiveDisplay conflicts when building
        categories concurrently. Simple status logging used instead.
        """
        # Use ThreadPoolExecutor for I/O bound operations (sam build/package)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all component build tasks
            future_to_component = {}
            for component in components:
                self.log_task("Building...", thread=component)
                future = executor.submit(
                    self.build_and_package_template, component, force_rebuild=True
                )
                future_to_component[future] = component

            # Wait for all tasks to complete and check results
            all_successful = True
            completed = 0

            for future in concurrent.futures.as_completed(future_to_component):
                component = future_to_component[future]
                completed += 1

                try:
                    success = future.result()
                    if not success:
                        self.log_error("Build failed!", thread=component)
                        all_successful = False
                    else:
                        self.log_success(
                            f"Complete ({completed}/{len(components)})",
                            thread=component,
                        )

                except Exception as e:
                    # Log detailed error information
                    error_output = (
                        f"Exception: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
                    )
                    self.log_error_details(
                        f"{component_type.title()} {component} build exception",
                        error_output,
                    )
                    self.log_error(f"Error: {str(e)[:50]}...", thread=component)
                    all_successful = False

        return all_successful

    def generate_config_file_list(self):
        """Generate list of configuration files for explicit copying"""
        config_dir = "config_library"
        file_list = []

        for root, dirs, files in os.walk(config_dir):
            for file in files:
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, config_dir)
                file_list.append(relative_path)

        return sorted(file_list)

    def _extract_function_name(self, dir_name, template_path):
        """Extract CloudFormation function name from template by matching CodeUri."""
        try:
            # Create a custom loader that ignores CloudFormation intrinsic functions
            class CFLoader(yaml.SafeLoader):
                pass

            def construct_unknown(loader, node):
                if isinstance(node, yaml.ScalarNode):
                    return loader.construct_scalar(node)
                elif isinstance(node, yaml.SequenceNode):
                    return loader.construct_sequence(node)
                elif isinstance(node, yaml.MappingNode):
                    return loader.construct_mapping(node)
                return None

            # Add constructors for CloudFormation intrinsic functions
            cf_functions = [
                "!Ref",
                "!GetAtt",
                "!Join",
                "!Sub",
                "!Select",
                "!Split",
                "!Base64",
                "!GetAZs",
                "!ImportValue",
                "!FindInMap",
                "!Equals",
                "!And",
                "!Or",
                "!Not",
                "!If",
                "!Condition",
            ]

            for func in cf_functions:
                CFLoader.add_constructor(func, construct_unknown)

            with open(template_path, "r", encoding="utf-8") as f:
                template = yaml.load(f, Loader=CFLoader)

            if not template or not isinstance(template, dict):
                raise Exception(f"Failed to parse YAML template: {template_path}")

            resources = template.get("Resources", {})
            for resource_name, resource_config in resources.items():
                if (
                    resource_config
                    and isinstance(resource_config, dict)
                    and resource_config.get("Type") == "AWS::Serverless::Function"
                ):
                    properties = resource_config.get("Properties", {})
                    if properties and isinstance(properties, dict):
                        code_uri = properties.get("CodeUri", "")
                        if isinstance(code_uri, str):
                            code_uri = code_uri.rstrip("/")
                            code_dir = (
                                code_uri.split("/")[-1] if "/" in code_uri else code_uri
                            )
                            if code_dir == dir_name:
                                return resource_name
            raise Exception(
                f"No CloudFormation function found for directory {dir_name} in template {template_path}"
            )

        except Exception as e:
            self.console.print(
                f"[yellow]⚠ Warning: Could not extract function name for {dir_name} from {template_path}:[/yellow]"
            )
            self.console.print(f"[dim]{str(e)}[/dim]")
            # Don't exit - just skip this function
            return None

    def upload_config_library(self):
        """Upload configuration library to S3 using aws s3 sync.

        Uses AWS CLI's built-in concurrency and delta sync for optimal performance.
        AWS CLI automatically skips unchanged files and uses parallel uploads.
        """
        self.log_phase("Uploading Config Library", "📂")
        config_dir = "config_library"

        if not os.path.exists(config_dir):
            self.log_warning(f"{config_dir} directory not found")
            return

        # Count files for reporting
        file_count = sum(len(files) for _, _, files in os.walk(config_dir))
        s3_dest = f"s3://{self.bucket}/{self.prefix_and_version}/config_library"

        self.log_task(f"Syncing {file_count} config files to S3...")

        # Use aws s3 sync with progress spinner and timing
        cmd = [
            "aws",
            "s3",
            "sync",
            config_dir,
            s3_dest,
            "--region",
            self.region,
        ]

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=self.console,
            transient=True,
        ) as progress:
            progress.add_task("[cyan]Syncing config library to S3...", total=None)
            start = time.time()

            result = subprocess.run(cmd, capture_output=True, text=True)
            elapsed = time.time() - start

        if result.returncode != 0:
            self.log_error(f"Failed to sync config library: {result.stderr}")
            sys.exit(1)

        self.log_success(
            f"Config library synced ({file_count} files in {elapsed:.1f}s)"
        )

    def ui_changed(self):
        """Check if UI has changed based on zipfile hash, returns (changed, zipfile_path)"""
        ui_hash = self.compute_ui_hash()
        zipfile_name = f"src-{ui_hash[:16]}.zip"
        zipfile_path = os.path.join(".aws-sam", zipfile_name)

        existing_zipfiles = (
            [
                f
                for f in os.listdir(".aws-sam")
                if f.startswith("src-") and f.endswith(".zip")
            ]
            if os.path.exists(".aws-sam")
            else []
        )

        if zipfile_name not in existing_zipfiles:
            # Remove old zipfiles
            for old_zip in existing_zipfiles:
                old_path = os.path.join(".aws-sam", old_zip)
                if os.path.exists(old_path):
                    os.remove(old_path)
            return True, zipfile_path

        return not os.path.exists(zipfile_path), zipfile_path

    def start_ui_validation_parallel(self):
        """Start UI validation in parallel if needed, returns (future, executor)"""
        if not self.lint_enabled or not os.path.exists("src/ui"):
            return None, None

        changed, _ = self.ui_changed()
        if not changed:
            return None, None

        ui_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        ui_validation_future = ui_executor.submit(self.validate_ui_build)
        self.console.print(
            "[cyan]🔍 Starting UI validation in parallel with builds...[/cyan]"
        )
        return ui_validation_future, ui_executor

    def compute_ui_hash(self):
        """Compute hash of UI folder contents"""
        self.console.print("[cyan]Computing hash of ui folder contents[/cyan]")
        ui_dir = "src/ui"
        return self.get_directory_checksum(ui_dir)

    def validate_ui_build(self):
        """Validate UI build to catch ESLint/Prettier errors before packaging"""
        try:
            self.console.print("[bold cyan]🔍 VALIDATING UI build[/bold cyan]")
            ui_dir = "src/ui"

            if not os.path.exists(ui_dir):
                self.console.print(
                    "[yellow]No UI directory found, skipping UI validation[/yellow]"
                )
                return

            # Run npm ci first (clean install from lock file)
            self.console.print(
                "[cyan]📦 Installing UI dependencies (this may take a while)...[/cyan]"
            )
            success, result = self.run_subprocess_with_logging(
                ["npm", "ci"], "UI npm ci", ui_dir, realtime=True
            )

            if not success:
                raise Exception("npm ci failed")

            # Run npm run build to validate ESLint/Prettier
            self.console.print(
                "[cyan]🔨 Building UI (validating ESLint/Prettier)...[/cyan]"
            )
            success, result = self.run_subprocess_with_logging(
                ["npm", "run", "build"], "UI build validation", ui_dir, realtime=True
            )

            if not success:
                raise Exception("UI build validation failed")

            self.console.print("[green]✅ UI build validation passed[/green]")

        except Exception as e:
            self.console.print("[red]❌ UI build validation failed:[/red]")
            self.console.print(str(e), style="red", markup=False)
            sys.exit(1)

    def package_ui(self):
        """Package UI source code"""
        _, zipfile_path = self.ui_changed()

        if not os.path.exists(zipfile_path):
            os.makedirs(".aws-sam", exist_ok=True)
            with zipfile.ZipFile(zipfile_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                ui_dir = "src/ui"
                exclude_dirs = {"node_modules", "build", ".aws-sam"}
                for root, dirs, files in os.walk(ui_dir):
                    dirs[:] = [d for d in dirs if d not in exclude_dirs]
                    for file in files:
                        if file == ".env" or file.startswith(".env."):
                            continue
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, ui_dir)
                        zipf.write(file_path, arcname)

        # Check if file exists in S3 and upload if needed
        zipfile_name = os.path.basename(zipfile_path)
        s3_key = f"{self.prefix_and_version}/{zipfile_name}"
        try:
            self.s3_client.head_object(Bucket=self.bucket, Key=s3_key)
            self.console.print(
                f"[green]WebUI zipfile already exists in S3: {zipfile_name}[/green]"
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                self.console.print("[cyan]Upload source to S3[/cyan]")
                try:
                    self.s3_client.upload_file(zipfile_path, self.bucket, s3_key)
                    self.console.print(
                        f"[green]Uploaded WebUI zipfile to S3: {zipfile_name}[/green]"
                    )
                except ClientError as upload_error:
                    self.console.print(
                        f"[red]Error uploading UI zipfile: {upload_error}[/red]"
                    )
                    sys.exit(1)
            else:
                self.console.print("[red]Error checking S3 for UI zipfile:[/red]")
                self.console.print(str(e), style="red", markup=False)
                sys.exit(1)

        return zipfile_name

    def package_pattern1_source(self):
        """Package Pattern-1 source code for CodeBuild to build Docker images"""
        self.console.print(
            "[bold cyan]📦 Packaging Pattern-1 source for Docker builds[/bold cyan]"
        )

        # Calculate content hash for versioning
        paths_to_hash = [
            "Dockerfile.optimized",
            "patterns/pattern-1/buildspec.yml",
            "lib/idp_common_pkg",
            "patterns/pattern-1/src",
        ]

        combined_hash = hashlib.sha256()
        for path in paths_to_hash:
            if os.path.isfile(path):
                file_hash = self.get_file_checksum(path)
                if file_hash:
                    combined_hash.update(file_hash.encode())
            elif os.path.isdir(path):
                dir_hash = self.get_component_checksum(path)
                if dir_hash:
                    combined_hash.update(dir_hash.encode())

        content_hash = combined_hash.hexdigest()[:8]
        zipfile_name = f"pattern-1-source-{content_hash}.zip"
        zipfile_path = os.path.join(".aws-sam", zipfile_name)

        # Create zip if it doesn't exist
        if not os.path.exists(zipfile_path):
            os.makedirs(".aws-sam", exist_ok=True)
            self.console.print(
                f"[cyan]Creating Pattern-1 source zip: {zipfile_name}[/cyan]"
            )

            with zipfile.ZipFile(zipfile_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                # Add Dockerfile
                zipf.write("Dockerfile.optimized", "Dockerfile.optimized")

                # Add buildspec.yml
                zipf.write(
                    "patterns/pattern-1/buildspec.yml",
                    "patterns/pattern-1/buildspec.yml",
                )

                # Add lib/idp_common_pkg
                for root, dirs, files in os.walk("lib/idp_common_pkg"):
                    # Exclude build artifacts and cache
                    dirs[:] = [
                        d
                        for d in dirs
                        if d
                        not in {
                            "__pycache__",
                            ".pytest_cache",
                            "dist",
                            "build",
                            "*.egg-info",
                        }
                    ]
                    for file in files:
                        if file.endswith((".pyc", ".pyo")):
                            continue
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, ".")
                        zipf.write(file_path, arcname)

                # Add patterns/pattern-1/src
                for root, dirs, files in os.walk("patterns/pattern-1/src"):
                    dirs[:] = [
                        d
                        for d in dirs
                        if d not in {"__pycache__", ".pytest_cache", ".aws-sam"}
                    ]
                    for file in files:
                        if file.endswith((".pyc", ".pyo")):
                            continue
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, ".")
                        zipf.write(file_path, arcname)

            self.console.print(
                f"[green]✅ Created Pattern-1 source zip ({os.path.getsize(zipfile_path) / 1024 / 1024:.2f} MB)[/green]"
            )

        # Upload to S3 if needed
        s3_key = f"{self.prefix_and_version}/{zipfile_name}"
        try:
            self.s3_client.head_object(Bucket=self.bucket, Key=s3_key)
            self.console.print(
                f"[green]Pattern-1 source already exists in S3: {zipfile_name}[/green]"
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                self.console.print(
                    f"[cyan]Uploading Pattern-1 source to S3: {s3_key}[/cyan]"
                )
                try:
                    self.s3_client.upload_file(zipfile_path, self.bucket, s3_key)
                    self.console.print(
                        "[green]✅ Uploaded Pattern-1 source to S3[/green]"
                    )
                except ClientError as upload_error:
                    self.console.print(
                        f"[red]❌ Error uploading Pattern-1 source: {upload_error}[/red]"
                    )
                    sys.exit(1)
            else:
                self.console.print(
                    f"[red]❌ Error checking S3 for Pattern-1 source: {e}[/red]"
                )
                sys.exit(1)

        return zipfile_name

    def package_pattern2_source(self):
        """Package Pattern-2 source code for CodeBuild to build Docker images"""
        self.console.print(
            "[bold cyan]📦 Packaging Pattern-2 source for Docker builds[/bold cyan]"
        )

        # Calculate content hash for versioning
        paths_to_hash = [
            "Dockerfile.optimized",
            "patterns/pattern-2/buildspec.yml",
            "lib/idp_common_pkg",
            "patterns/pattern-2/src",
        ]

        combined_hash = hashlib.sha256()
        for path in paths_to_hash:
            if os.path.isfile(path):
                file_hash = self.get_file_checksum(path)
                if file_hash:
                    combined_hash.update(file_hash.encode())
            elif os.path.isdir(path):
                dir_hash = self.get_component_checksum(path)
                if dir_hash:
                    combined_hash.update(dir_hash.encode())

        content_hash = combined_hash.hexdigest()[:8]
        zipfile_name = f"pattern-2-source-{content_hash}.zip"
        zipfile_path = os.path.join(".aws-sam", zipfile_name)

        # Create zip if it doesn't exist
        if not os.path.exists(zipfile_path):
            os.makedirs(".aws-sam", exist_ok=True)
            self.console.print(
                f"[cyan]Creating Pattern-2 source zip: {zipfile_name}[/cyan]"
            )

            with zipfile.ZipFile(zipfile_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                # Add Dockerfile
                zipf.write("Dockerfile.optimized", "Dockerfile.optimized")

                # Add buildspec.yml
                zipf.write(
                    "patterns/pattern-2/buildspec.yml",
                    "patterns/pattern-2/buildspec.yml",
                )

                # Add lib/idp_common_pkg
                for root, dirs, files in os.walk("lib/idp_common_pkg"):
                    # Exclude build artifacts and cache
                    dirs[:] = [
                        d
                        for d in dirs
                        if d
                        not in {
                            "__pycache__",
                            ".pytest_cache",
                            "dist",
                            "build",
                            "*.egg-info",
                        }
                    ]
                    for file in files:
                        if file.endswith((".pyc", ".pyo")):
                            continue
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, ".")
                        zipf.write(file_path, arcname)

                # Add patterns/pattern-2/src
                for root, dirs, files in os.walk("patterns/pattern-2/src"):
                    dirs[:] = [
                        d
                        for d in dirs
                        if d not in {"__pycache__", ".pytest_cache", ".aws-sam"}
                    ]
                    for file in files:
                        if file.endswith((".pyc", ".pyo")):
                            continue
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, ".")
                        zipf.write(file_path, arcname)

            self.console.print(
                f"[green]✅ Created Pattern-2 source zip ({os.path.getsize(zipfile_path) / 1024 / 1024:.2f} MB)[/green]"
            )

        # Upload to S3 if needed
        s3_key = f"{self.prefix_and_version}/{zipfile_name}"
        try:
            self.s3_client.head_object(Bucket=self.bucket, Key=s3_key)
            self.console.print(
                f"[green]Pattern-2 source already exists in S3: {zipfile_name}[/green]"
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                self.console.print(
                    f"[cyan]Uploading Pattern-2 source to S3: {s3_key}[/cyan]"
                )
                try:
                    self.s3_client.upload_file(zipfile_path, self.bucket, s3_key)
                    self.console.print(
                        "[green]✅ Uploaded Pattern-2 source to S3[/green]"
                    )
                except ClientError as upload_error:
                    self.console.print(
                        f"[red]❌ Error uploading Pattern-2 source: {upload_error}[/red]"
                    )
                    sys.exit(1)
            else:
                self.console.print(
                    f"[red]❌ Error checking S3 for Pattern-2 source: {e}[/red]"
                )
                sys.exit(1)

        return zipfile_name

    def package_pattern3_source(self):
        """Package Pattern-3 source code for CodeBuild to build Docker images"""
        self.console.print(
            "[bold cyan]📦 Packaging Pattern-3 source for Docker builds[/bold cyan]"
        )

        # Calculate content hash for versioning
        paths_to_hash = [
            "Dockerfile.optimized",
            "patterns/pattern-3/buildspec.yml",
            "lib/idp_common_pkg",
            "patterns/pattern-3/src",
        ]

        combined_hash = hashlib.sha256()
        for path in paths_to_hash:
            if os.path.isfile(path):
                file_hash = self.get_file_checksum(path)
                if file_hash:
                    combined_hash.update(file_hash.encode())
            elif os.path.isdir(path):
                dir_hash = self.get_component_checksum(path)
                if dir_hash:
                    combined_hash.update(dir_hash.encode())

        content_hash = combined_hash.hexdigest()[:8]
        zipfile_name = f"pattern-3-source-{content_hash}.zip"
        zipfile_path = os.path.join(".aws-sam", zipfile_name)

        # Create zip if it doesn't exist
        if not os.path.exists(zipfile_path):
            os.makedirs(".aws-sam", exist_ok=True)
            self.console.print(
                f"[cyan]Creating Pattern-3 source zip: {zipfile_name}[/cyan]"
            )

            with zipfile.ZipFile(zipfile_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                # Add Dockerfile
                zipf.write("Dockerfile.optimized", "Dockerfile.optimized")

                # Add buildspec.yml
                zipf.write(
                    "patterns/pattern-3/buildspec.yml",
                    "patterns/pattern-3/buildspec.yml",
                )

                # Add lib/idp_common_pkg
                for root, dirs, files in os.walk("lib/idp_common_pkg"):
                    # Exclude build artifacts and cache
                    dirs[:] = [
                        d
                        for d in dirs
                        if d
                        not in {
                            "__pycache__",
                            ".pytest_cache",
                            "dist",
                            "build",
                            "*.egg-info",
                        }
                    ]
                    for file in files:
                        if file.endswith((".pyc", ".pyo")):
                            continue
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, ".")
                        zipf.write(file_path, arcname)

                # Add patterns/pattern-3/src
                for root, dirs, files in os.walk("patterns/pattern-3/src"):
                    dirs[:] = [
                        d
                        for d in dirs
                        if d not in {"__pycache__", ".pytest_cache", ".aws-sam"}
                    ]
                    for file in files:
                        if file.endswith((".pyc", ".pyo")):
                            continue
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, ".")
                        zipf.write(file_path, arcname)

            self.console.print(
                f"[green]✅ Created Pattern-3 source zip ({os.path.getsize(zipfile_path) / 1024 / 1024:.2f} MB)[/green]"
            )

        # Upload to S3 if needed
        s3_key = f"{self.prefix_and_version}/{zipfile_name}"
        try:
            self.s3_client.head_object(Bucket=self.bucket, Key=s3_key)
            self.console.print(
                f"[green]Pattern-3 source already exists in S3: {zipfile_name}[/green]"
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                self.console.print(
                    f"[cyan]Uploading Pattern-3 source to S3: {s3_key}[/cyan]"
                )
                try:
                    self.s3_client.upload_file(zipfile_path, self.bucket, s3_key)
                    self.console.print(
                        "[green]✅ Uploaded Pattern-3 source to S3[/green]"
                    )
                except ClientError as upload_error:
                    self.console.print(
                        f"[red]❌ Error uploading Pattern-3 source: {upload_error}[/red]"
                    )
                    sys.exit(1)
            else:
                self.console.print(
                    f"[red]❌ Error checking S3 for Pattern-3 source: {e}[/red]"
                )
                sys.exit(1)

        return zipfile_name

    def _upload_template_to_s3(self, template_path, s3_key, description):
        """Helper method to upload template to S3 with error handling"""
        self.console.print(f"[cyan]Uploading {description} to S3: {s3_key}[/cyan]")
        try:
            self.s3_client.upload_file(template_path, self.bucket, s3_key)
            self.console.print(f"[green]✅ {description} uploaded successfully[/green]")
        except Exception as e:
            self.console.print(f"[red]Failed to upload {description}:[/red]")
            self.console.print(str(e), style="red", markup=False)
            sys.exit(1)

    def _check_and_upload_template(self, template_path, s3_key, description):
        """Helper method to check if template exists in S3 and upload if missing"""
        try:
            self.s3_client.head_object(Bucket=self.bucket, Key=s3_key)
            self.console.print(f"[green]✅ {description} already exists in S3[/green]")
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                self.console.print(
                    f"[yellow]{description} missing from S3, uploading: {s3_key}[/yellow]"
                )
                if not os.path.exists(template_path):
                    self.console.print(
                        f"[red]Error: No template to upload at {template_path}[/red]"
                    )
                    sys.exit(1)
                self._upload_template_to_s3(template_path, s3_key, description)
            else:
                self.console.print(
                    f"[yellow]Could not check {description} existence:[/yellow]"
                )
                self.console.print(str(e), style="red", markup=False)

    def build_main_template(
        self,
        webui_zipfile,
        pattern1_source_zipfile,
        pattern2_source_zipfile,
        pattern3_source_zipfile,
        components_needing_rebuild,
    ):
        """Build and package main template with smart detection"""
        try:
            self.console.print("[bold cyan]BUILDING main[/bold cyan]")
            # Main template needs rebuilding, if any component needs rebuilding
            if components_needing_rebuild:
                self.console.print("[yellow]Main template needs rebuilding[/yellow]")
                # Validate Python syntax in src directory before building
                if not self._validate_python_syntax("src"):
                    raise Exception("Python syntax validation failed")

                # Build main template with progress indicator
                # Lambda functions now use Lambda Layers instead of bundled dependencies
                cmd = [
                    "sam",
                    "build",
                    "--parallel",  # Safe with Lambda Layers
                    "--template-file",
                    "template.yaml",
                ]
                if self.use_container_flag and self.use_container_flag.strip():
                    cmd.append(self.use_container_flag)

                # Use spinner progress indicator for SAM build
                sam_build_start = time.time()
                success = False
                try:
                    with Progress(
                        SpinnerColumn(),
                        TextColumn("[progress.description]{task.description}"),
                        TimeElapsedColumn(),
                        console=self.console,
                        transient=False,
                    ) as progress:
                        task = progress.add_task(
                            "[cyan]Building main template (SAM build --parallel)...",
                            total=None,
                        )
                        success, result = self.run_subprocess_with_logging(
                            cmd, "Main template SAM build"
                        )
                        sam_build_elapsed = time.time() - sam_build_start
                        if success:
                            progress.update(
                                task,
                                description=f"[green]✓ SAM build completed in {sam_build_elapsed:.1f}s",
                            )
                        else:
                            progress.update(
                                task,
                                description=f"[red]✗ SAM build failed after {sam_build_elapsed:.1f}s",
                            )
                except Exception:
                    # Re-raise the exception to be caught by outer try/finally
                    raise

                if not success:
                    # Delete main template checksum on build failure
                    raise Exception("SAM build failed")

                self.console.print("[bold cyan]PACKAGING main[/bold cyan]")

                # Read the template
                with open(".aws-sam/build/template.yaml", "r") as f:
                    template_content = f.read()

                # Get configuration file list
                config_files_list = self.generate_config_file_list()
                config_files_json = json.dumps(config_files_list)

                # Extract content-based hashes from zipfile names for per-pattern ImageVersions
                # Format: pattern-X-source-{hash}.zip -> extract {hash}
                pattern1_image_version = pattern1_source_zipfile.replace(
                    "pattern-1-source-", ""
                ).replace(".zip", "")
                pattern2_image_version = pattern2_source_zipfile.replace(
                    "pattern-2-source-", ""
                ).replace(".zip", "")
                pattern3_image_version = pattern3_source_zipfile.replace(
                    "pattern-3-source-", ""
                ).replace(".zip", "")

                # Get various hashes
                workforce_url_file = "src/lambda/get-workforce-url/index.py"
                a2i_resources_file = "src/lambda/create_a2i_resources/index.py"
                cognito_client_file = "src/lambda/cognito_updater_hitl/index.py"

                workforce_url_hash = (
                    self.get_file_checksum(workforce_url_file)[:16]
                    if os.path.exists(workforce_url_file)
                    else ""
                )
                a2i_resources_hash = (
                    self.get_file_checksum(a2i_resources_file)[:16]
                    if os.path.exists(a2i_resources_file)
                    else ""
                )
                cognito_client_hash = (
                    self.get_file_checksum(cognito_client_file)[:16]
                    if os.path.exists(cognito_client_file)
                    else ""
                )

                # Replace tokens in template

                build_date_time = datetime.now(timezone.utc).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

                replacements = {
                    "<VERSION>": self.version,
                    "<BUILD_DATE_TIME>": build_date_time,
                    "<PUBLIC_SAMPLE_UDOP_MODEL>": self.public_sample_udop_model,
                    "<ARTIFACT_BUCKET_TOKEN>": self.bucket,
                    "<ARTIFACT_PREFIX_TOKEN>": self.prefix_and_version,
                    "<WEBUI_ZIPFILE_TOKEN>": webui_zipfile,
                    "<PATTERN1_SOURCE_ZIPFILE_TOKEN>": pattern1_source_zipfile,
                    "<PATTERN2_SOURCE_ZIPFILE_TOKEN>": pattern2_source_zipfile,
                    "<PATTERN3_SOURCE_ZIPFILE_TOKEN>": pattern3_source_zipfile,
                    # Use pattern-specific image versions extracted from zipfile hashes
                    "<PATTERN1_IMAGE_VERSION>": pattern1_image_version,
                    "<PATTERN2_IMAGE_VERSION>": pattern2_image_version,
                    "<PATTERN3_IMAGE_VERSION>": pattern3_image_version,
                    # Lambda Layer zip filenames
                    "<IDP_COMMON_BASE_LAYER_ZIP>": self._layer_arns.get("base", {}).get(
                        "zip_name", "idp-common-base.zip"
                    ),
                    "<IDP_COMMON_REPORTING_LAYER_ZIP>": self._layer_arns.get(
                        "reporting", {}
                    ).get("zip_name", "idp-common-reporting.zip"),
                    "<IDP_COMMON_AGENTS_LAYER_ZIP>": self._layer_arns.get(
                        "agents", {}
                    ).get("zip_name", "idp-common-agents.zip"),
                    "<HASH_TOKEN>": self.get_directory_checksum("./lib")[:16],
                    "<LAMBDA_HASH_TOKEN>": self.get_directory_checksum(
                        "./src/lambda/agentcore_gateway_manager"
                    )[:16],
                    # Include config_library + config processing code (Lambda, models, system defaults)
                    # This ensures UpdateConfiguration custom resource re-runs when processing logic changes
                    "<CONFIG_LIBRARY_HASH_TOKEN>": hashlib.sha256(
                        (
                            self.get_directory_checksum("config_library")
                            + self.get_directory_checksum(
                                "src/lambda/update_configuration"
                            )
                            + self.get_directory_checksum(
                                "lib/idp_common_pkg/idp_common/config"
                            )
                        ).encode()
                    ).hexdigest()[:16],
                    "<CONFIG_FILES_LIST_TOKEN>": config_files_json,
                    "<WORKFORCE_URL_HASH_TOKEN>": workforce_url_hash,
                    "<A2I_RESOURCES_HASH_TOKEN>": a2i_resources_hash,
                    "<COGNITO_CLIENT_HASH_TOKEN>": cognito_client_hash,
                    "<FCC_DATASET_DEPLOYER_HASH_TOKEN>": self.get_directory_checksum(
                        "src/lambda/fcc_dataset_deployer"
                    )[:16],
                    "<OCR_BENCHMARK_DEPLOYER_HASH_TOKEN>": self.get_directory_checksum(
                        "src/lambda/ocr_benchmark_deployer"
                    )[:16],
                }

                # Debug: show layer ARNs being used
                self.console.print(
                    f"[dim]Layer ARNs for token replacement: {list(self._layer_arns.keys())}[/dim]"
                )
                for layer_name, layer_info in self._layer_arns.items():
                    self.console.print(
                        f"[dim]  {layer_name}: {layer_info.get('zip_name', 'NOT SET')}[/dim]"
                    )

                self.log_verbose("Inline edit main template to replace:")
                for token, value in replacements.items():
                    self.log_verbose(f"   {token} with: {value}")
                    template_content = template_content.replace(token, value)

                # Write the modified template to the build directory
                build_packaged_template_path = ".aws-sam/build/idp-main.yaml"
                with open(build_packaged_template_path, "w") as f:
                    f.write(template_content)

                # Package the template from the build directory with progress indicator
                original_cwd = os.getcwd()
                os.chdir(".aws-sam/build")
                cmd = [
                    "sam",
                    "package",
                    "--template-file",
                    "idp-main.yaml",
                    "--output-template-file",
                    "../../.aws-sam/idp-main.yaml",
                    "--s3-bucket",
                    self.bucket,
                    "--s3-prefix",
                    self.prefix_and_version,
                ]
                self.log_verbose(
                    f"Running main template SAM package command: {' '.join(cmd)}"
                )

                # Use spinner progress indicator for SAM package
                sam_package_start = time.time()
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    TimeElapsedColumn(),
                    console=self.console,
                    transient=False,
                ) as progress:
                    task = progress.add_task(
                        "[cyan]Packaging main template (SAM package)...", total=None
                    )
                    success, result = self.run_subprocess_with_logging(
                        cmd, "Main template SAM package"
                    )
                    sam_package_elapsed = time.time() - sam_package_start
                    if success:
                        progress.update(
                            task,
                            description=f"[green]✓ SAM package completed in {sam_package_elapsed:.1f}s",
                        )
                    else:
                        progress.update(
                            task,
                            description=f"[red]✗ SAM package failed after {sam_package_elapsed:.1f}s",
                        )

                os.chdir(original_cwd)
                if not success:
                    raise Exception("SAM package failed")

                # Print main template build summary
                total_main_build_time = sam_build_elapsed + sam_package_elapsed
                self.console.print(
                    f"[dim]Main template: build={sam_build_elapsed:.1f}s, package={sam_package_elapsed:.1f}s, total={total_main_build_time:.1f}s[/dim]"
                )
            else:
                self.console.print("[green]✅ Main template is up to date[/green]")

            # Upload templates
            packaged_template_path = ".aws-sam/idp-main.yaml"
            templates = [
                (f"{self.prefix}/{self.main_template}", "Main template"),
                (
                    f"{self.prefix}/{self.main_template.replace('.yaml', f'_{self.version}.yaml')}",
                    "Versioned main template",
                ),
            ]

            for s3_key, description in templates:
                if components_needing_rebuild:
                    if not os.path.exists(packaged_template_path):
                        self.console.print(
                            f"[red]Error: Packaged template not found at {packaged_template_path}[/red]"
                        )
                        raise Exception(packaged_template_path + " missing")
                    self._upload_template_to_s3(
                        packaged_template_path, s3_key, description
                    )
                else:
                    self._check_and_upload_template(
                        packaged_template_path, s3_key, description
                    )

            # Validate the template
            if self.skip_validation:
                self.console.print(
                    "[yellow]⚠️  Skipping CloudFormation template validation[/yellow]"
                )
            else:
                template_url = f"https://s3.{self.region}.amazonaws.com/{self.bucket}/{templates[0][0]}"
                self.console.print(f"[cyan]Validating template: {template_url}[/cyan]")
                self.cf_client.validate_template(TemplateURL=template_url)
                self.console.print("[green]✅ Template validation passed[/green]")

        except ClientError as e:
            # Delete checksum on template validation failure
            self._delete_checksum_file(".checksum")
            self.console.print(
                "[red]❌ CloudFormation template validation failed[/red]"
            )
            self.console.print(str(e), style="red", markup=False)
            sys.exit(1)
        except Exception as e:
            # Delete checksum on any failure to force rebuild next time
            self._delete_checksum_file(".checksum")
            self.console.print("[red]❌ Main template build failed:[/red]")
            self.console.print(str(e), style="red", markup=False)
            sys.exit(1)

    def get_source_files_checksum(self, directory):
        """Get checksum of only source code files in a directory"""
        if not os.path.exists(directory):
            return ""

        # Cache directory checksums to avoid recalculation
        cache_key = f"source_checksum_{directory}"
        if hasattr(self, "_checksum_cache") and cache_key in self._checksum_cache:
            return self._checksum_cache[cache_key]

        if not hasattr(self, "_checksum_cache"):
            self._checksum_cache = {}

        # Use os.scandir for better performance than os.walk
        checksums = []
        file_count = 0

        # Define patterns once
        source_extensions = {
            ".py",
            ".js",
            ".ts",
            ".jsx",
            ".tsx",
            ".yaml",
            ".yml",
            ".json",
            ".txt",
            ".toml",
            ".cfg",
            ".ini",
            ".graphql",
        }
        exclude_dirs = {
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            "build",
            "dist",
            ".aws-sam",
            "node_modules",
            ".git",
            ".vscode",
            ".idea",
            "test-reports",
            ".coverage",
            "htmlcov",
            "coverage_html_report",
            "tests",
            "test",
        }

        def process_directory(dir_path):
            nonlocal file_count
            files_to_process = []
            try:
                with os.scandir(dir_path) as entries:
                    for entry in entries:
                        if entry.is_dir():
                            # Skip excluded directories by name and by suffix (e.g., *.egg-info)
                            if (
                                entry.name not in exclude_dirs
                                and not entry.name.startswith(".")
                                and not entry.name.endswith(".egg-info")
                            ):
                                process_directory(entry.path)
                        elif entry.is_file():
                            name = entry.name
                            if (
                                not name.startswith(".")
                                and not name.endswith(
                                    (".pyc", ".pyo", ".pyd", ".so", ".log", ".checksum")
                                )
                                and not name.startswith("test_")
                                and not name.endswith("_test.py")
                            ):
                                _, ext = os.path.splitext(name)
                                if (
                                    ext.lower() in source_extensions
                                    or name
                                    in {
                                        "Dockerfile",
                                        "Makefile",
                                        "requirements.txt",
                                        "setup.py",
                                        "setup.cfg",
                                    }
                                    or "template" in name.lower()
                                ):
                                    files_to_process.append(entry.path)

                # Sort files for deterministic order
                for file_path in sorted(files_to_process):
                    relative_path = os.path.relpath(file_path, directory)
                    file_checksum = self.get_file_checksum(file_path)
                    combined = f"{relative_path}:{file_checksum}"
                    checksums.append(hashlib.sha256(combined.encode()).hexdigest())
                    file_count += 1

            except (OSError, PermissionError):
                pass  # Skip inaccessible directories

        process_directory(directory)

        if self.verbose:
            self.console.print(
                f"[dim]Checksummed {file_count} source files in {directory}[/dim]"
            )

        # Combine all checksums
        combined = "".join(sorted(checksums))  # Sort for consistency
        result = hashlib.sha256(combined.encode()).hexdigest()

        # Cache the result
        self._checksum_cache[cache_key] = result
        return result

    def get_component_checksum(self, *paths):
        """Get combined checksum for component paths (source files only)"""
        # Use instance-level cache to avoid recalculating same paths
        if not hasattr(self, "_component_checksum_cache"):
            self._component_checksum_cache = {}

        # Include bucket and prefix in cache key to force rebuild when they change
        cache_key = (
            tuple(sorted(paths)),
            self.bucket,
            self.prefix_and_version,
            self.region,
        )
        if cache_key in self._component_checksum_cache:
            return self._component_checksum_cache[cache_key]

        checksums = []
        for path in paths:
            if os.path.isfile(path):
                # For individual files, use file checksum
                checksums.append(self.get_file_checksum(path))
            elif os.path.isdir(path):
                # For directories, use source files checksum
                checksums.append(self.get_source_files_checksum(path))

        # Include deployment context in checksum calculation
        combined = (
            "".join(checksums)
            + (self.bucket or "")
            + (self.prefix_and_version or "")
            + (self.region or "")
        )
        result = hashlib.sha256(combined.encode()).hexdigest()

        # Cache the result
        self._component_checksum_cache[cache_key] = result
        return result

    def get_component_dependencies(self):
        """Map each component to its dependencies for smart rebuild detection"""
        main_deps = ["./src", "template.yaml", "./config_library", LIB_DEPENDENCY]

        dependencies = {
            # Main template components
            "main": main_deps,
            # Nested components (includes all nested stacks - core and optional)
            "nested/appsync": [
                LIB_DEPENDENCY,
                "nested/appsync/src",
                "nested/appsync/template.yaml",
            ],
            "nested/bda-lending-project": [
                "nested/bda-lending-project/src",
                "nested/bda-lending-project/template.yaml",
            ],
            "nested/bedrockkb": [
                "nested/bedrockkb/src",
                "nested/bedrockkb/template.yaml",
            ],
            # Pattern components
            "patterns/pattern-1": [
                LIB_DEPENDENCY,
                "patterns/pattern-1/src",
                "patterns/pattern-1/template.yaml",
                "Dockerfile.optimized",
            ],
            "patterns/pattern-2": [
                LIB_DEPENDENCY,
                "patterns/pattern-2/src",
                "patterns/pattern-2/template.yaml",
                "Dockerfile.optimized",
            ],
            "patterns/pattern-3": [
                LIB_DEPENDENCY,
                "patterns/pattern-3/src",
                "patterns/pattern-3/template.yaml",
                "Dockerfile.optimized",
            ],
            "lib": [
                "./lib/idp_common_pkg"
            ],  # Include entire package, not just idp_common subdir
        }
        return dependencies

    def get_components_needing_rebuild(self):
        """Determine which components need rebuilding based on dependency changes"""
        dependencies = self.get_component_dependencies()
        components_to_rebuild = []

        # Cache checksums to avoid recalculating for shared dependencies (like ./lib)

        for component, deps in dependencies.items():
            # Use standard checksum file format: directory/.checksum
            if component == "main":
                checksum_file = ".checksum"
            elif component == "lib":
                checksum_file = "lib/.checksum"
            else:
                checksum_file = f"{component}/.checksum"

            # Calculate individual checksums for each dependency
            current_dep_checksums = {}
            for dep in deps:
                if os.path.isfile(dep):
                    current_dep_checksums[dep] = self.get_file_checksum(dep)
                elif os.path.isdir(dep):
                    current_dep_checksums[dep] = self.get_source_files_checksum(dep)
                else:
                    current_dep_checksums[dep] = ""

            # Combine checksums for overall comparison (include deployment context)
            combined_checksum = hashlib.sha256(
                (
                    "".join(current_dep_checksums.values())
                    + (self.bucket or "")
                    + (self.prefix_and_version or "")
                    + (self.region or "")
                ).encode()
            ).hexdigest()

            needs_rebuild = True
            changed_deps = []

            if os.path.exists(checksum_file):
                try:
                    with open(checksum_file, "r") as f:
                        stored_data = json.load(f)
                    stored_checksum = stored_data.get("combined", "")
                    stored_dep_checksums = stored_data.get("dependencies", {})

                    needs_rebuild = combined_checksum != stored_checksum

                    # Identify which specific dependencies changed
                    if needs_rebuild:
                        for dep, current_cs in current_dep_checksums.items():
                            stored_cs = stored_dep_checksums.get(dep, "")
                            if current_cs != stored_cs:
                                changed_deps.append(dep)
                except (json.JSONDecodeError, KeyError):
                    # Old format or corrupted - rebuild and show all deps
                    changed_deps = deps
            else:
                # No checksum file - show all deps as changed
                changed_deps = deps

            if needs_rebuild:
                components_to_rebuild.append(
                    {
                        "component": component,
                        "dependencies": deps,
                        "changed_dependencies": changed_deps,
                        "checksum_file": checksum_file,
                        "current_checksum": combined_checksum,
                        "current_dep_checksums": current_dep_checksums,
                    }
                )
                if component == "lib":  # update _is_lib_changed
                    self._is_lib_changed = True

                # Show only changed dependencies
                if changed_deps:
                    change_msg = (
                        "changed"
                        if len(changed_deps) < len(deps)
                        else "new/no previous build"
                    )
                    self.console.print(
                        f"[yellow]📝 {component} needs rebuild ({change_msg}):[/yellow]"
                    )
                    for dep in changed_deps:
                        self.console.print(f"[yellow]   • {dep}[/yellow]")

        return components_to_rebuild

    def clear_component_cache(self, component):
        """Clear build cache for a specific component.

        For main component, only clears the 'build' subdirectory to preserve
        the 'layers' subdirectory which contains Lambda layer zips.
        """
        if component == "main":
            # For main, only clear the build subdirectory, NOT the layers directory
            sam_build_dir = ".aws-sam/build"
            if os.path.exists(sam_build_dir):
                self.log_verbose(
                    f"Clearing SAM build cache for {component}: {sam_build_dir}"
                )
                try:
                    shutil.rmtree(sam_build_dir)
                except (FileNotFoundError, OSError) as e:
                    self.log_verbose(f"Warning: Error clearing SAM cache: {e}")
        else:
            sam_dir = os.path.join(component, ".aws-sam")
            if os.path.exists(sam_dir):
                self.log_verbose(
                    f"Clearing entire SAM cache for {component}: {sam_dir}"
                )
                try:
                    shutil.rmtree(sam_dir)
                except (FileNotFoundError, OSError) as e:
                    self.log_verbose(
                        f"Warning: Error clearing SAM cache (may already be deleted): {e}"
                    )
                    # Try alternative cleanup method for broken symlinks
                    try:
                        subprocess.run(["rm", "-rf", sam_dir], check=False)
                    except Exception as e2:
                        self.log_verbose(f"Alternative cleanup also failed: {e2}")

    def _validate_python_syntax(self, directory):
        """Validate Python syntax in all .py files in the directory"""

        for root, dirs, files in os.walk(directory):
            for file in files:
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    try:
                        py_compile.compile(file_path, doraise=True)
                    except py_compile.PyCompileError as e:
                        self.console.print(
                            f"[red]❌ Python syntax error in {file_path}[/red]"
                        )
                        self.console.print(str(e), style="red", markup=False)
                        return False
        return True

    def _validate_python_linting(self):
        """Validate Python linting"""
        if not self.lint_enabled:
            return True

        self.console.print("[cyan]🔍 Running Python linting...[/cyan]")

        # Run ruff check (same as GitLab CI lint-cicd)
        result = subprocess.run(["ruff", "check"], capture_output=True, text=True)
        if result.returncode != 0:
            self.console.print("[red]❌ Ruff linting failed![/red]")
            self.console.print(result.stdout, style="red", markup=False)
            return False

        # Run ruff format check (same as GitLab CI lint-cicd)
        result = subprocess.run(
            ["ruff", "format", "--check"], capture_output=True, text=True
        )
        if result.returncode != 0:
            self.console.print("[red]❌ Code formatting check failed![/red]")
            self.console.print(result.stdout, style="red", markup=False)
            return False

        self.console.print("[green]✅ Python linting passed[/green]")
        return True

    def _validate_cfn_lint(self):
        """Validate CloudFormation templates with cfn-lint after build/package"""
        if not self.lint_enabled:
            return True

        self.console.print(
            "[cyan]🔍 Running CloudFormation linting (cfn-lint) on packaged templates...[/cyan]"
        )

        # Check if cfn-lint is installed
        if not shutil.which("cfn-lint"):
            self.console.print(
                "[yellow]⚠️  cfn-lint not installed, skipping CloudFormation linting[/yellow]"
            )
            self.console.print("[dim]Install with: pip install cfn-lint[/dim]")
            return True

        all_errors = []
        all_warnings = []

        # List of templates to lint (packaged templates after token replacement)
        templates_to_lint = []

        # Main packaged template
        main_packaged = ".aws-sam/idp-main.yaml"
        if os.path.exists(main_packaged):
            templates_to_lint.append(("Main template", main_packaged))

        # Nested templates (packaged versions)
        nested_dir = "nested"
        if os.path.exists(nested_dir):
            for nested_name in os.listdir(nested_dir):
                nested_packaged = os.path.join(
                    nested_dir, nested_name, ".aws-sam", "packaged.yaml"
                )
                if os.path.exists(nested_packaged):
                    templates_to_lint.append((f"Nested/{nested_name}", nested_packaged))

        # Pattern templates (packaged versions)
        patterns_dir = "patterns"
        if os.path.exists(patterns_dir):
            for pattern_name in os.listdir(patterns_dir):
                pattern_packaged = os.path.join(
                    patterns_dir, pattern_name, ".aws-sam", "packaged.yaml"
                )
                if os.path.exists(pattern_packaged):
                    templates_to_lint.append(
                        (f"Patterns/{pattern_name}", pattern_packaged)
                    )

        if not templates_to_lint:
            self.console.print(
                "[yellow]⚠️  No packaged templates found to lint[/yellow]"
            )
            return True

        # Lint each template
        for template_name, template_path in templates_to_lint:
            self.log_verbose(f"Linting {template_name}: {template_path}")

            result = subprocess.run(
                ["cfn-lint", template_path], capture_output=True, text=True
            )

            if result.returncode != 0:
                output = result.stdout + result.stderr
                lines = output.strip().split("\n") if output.strip() else []

                # Separate errors from warnings
                for line in lines:
                    if not line.strip():
                        continue
                    if line.strip().startswith("E") or ":E" in line:
                        all_errors.append(f"[{template_name}] {line}")
                    elif line.strip().startswith("W") or ":W" in line:
                        all_warnings.append(f"[{template_name}] {line}")

        # Report results
        if all_errors:
            self.console.print("[red]❌ CloudFormation linting found errors:[/red]")
            for line in all_errors[:10]:  # Show first 10 errors
                self.console.print(f"[red]  {line}[/red]")
            if len(all_errors) > 10:
                self.console.print(
                    f"[red]  ... and {len(all_errors) - 10} more errors[/red]"
                )
            return False

        if all_warnings:
            self.console.print(
                f"[yellow]⚠️  CloudFormation linting found {len(all_warnings)} warnings (continuing):[/yellow]"
            )
            for line in all_warnings[:5]:  # Show first 5 warnings
                self.console.print(f"[dim]  {line}[/dim]")
            if len(all_warnings) > 5:
                self.console.print(
                    f"[dim]  ... and {len(all_warnings) - 5} more warnings[/dim]"
                )

        self.console.print(
            f"[green]✅ CloudFormation linting passed ({len(templates_to_lint)} templates checked)[/green]"
        )
        return True

    def compute_directory_hash(self, directory):
        """Compute hash of actual directory contents for layer versioning."""
        if not os.path.exists(directory):
            return ""

        checksums = []
        for root, dirs, files in os.walk(directory):
            dirs.sort()  # Consistent ordering
            for file in sorted(files):
                file_path = os.path.join(root, file)
                if os.path.isfile(file_path):
                    # Include relative path and content in hash for accuracy
                    rel_path = os.path.relpath(file_path, directory)
                    file_hash = self.get_file_checksum(file_path)
                    checksums.append(f"{rel_path}:{file_hash}")

        combined = "\n".join(checksums)
        return hashlib.sha256(combined.encode()).hexdigest()[:8]

    def build_lambda_layer(self, layer_name, layer_extras):
        """Build a single Lambda layer with specified extras.

        The hash is computed from:
        1. Source code hash of lib/idp_common_pkg (to detect when source changes)
        2. Layer content hash AFTER removing boto packages (to verify installed content)

        This dual-hash approach ensures:
        - When source changes, old layer zips won't be reused (source hash differs)
        - Layer content is accurately reflected (content hash)

        Layer zip naming: idp-common-{name}-{source_hash[:8]}-{content_hash[:8]}.zip

        Args:
            layer_name: Name of the layer (e.g., 'base', 'reporting', 'agents')
            layer_extras: List of extras to install (e.g., ['docs_service', 'image'])

        Returns:
            Tuple of (layer_zip_path, layer_zip_name)
        """
        try:
            # Create layer directory structure
            layer_build_dir = os.path.join(".aws-sam", "layers", f"{layer_name}-build")
            layer_python_dir = os.path.join(layer_build_dir, "python")

            # Clean and recreate directories
            if os.path.exists(layer_build_dir):
                shutil.rmtree(layer_build_dir)
            os.makedirs(layer_python_dir, exist_ok=True)

            # Build pip install command with extras
            if layer_extras:
                extras_str = ",".join(layer_extras)
                install_spec = f"./lib/idp_common_pkg[{extras_str}]"
            else:
                install_spec = "./lib/idp_common_pkg"

            # Install dependencies into layer python directory
            # Use platform-specific flags to ensure x86_64 Lambda compatibility
            # regardless of the local machine's architecture (e.g., ARM64 Mac)
            cmd = [
                sys.executable,
                "-m",
                "pip",
                "install",
                install_spec,
                "--platform",
                "manylinux2014_x86_64",
                "--implementation",
                "cp",
                "--python-version",
                "312",
                "--only-binary=:all:",
                "-t",
                layer_python_dir,
                "--upgrade",
            ]

            # Show what's being installed
            extras_info = (
                f" [{', '.join(layer_extras)}]" if layer_extras else " (core only)"
            )
            self.console.print(
                f"[cyan]Building layer '{layer_name}'{extras_info}...[/cyan]"
            )
            self.console.print(f"Installing: {install_spec}", style="dim", markup=False)

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(f"Layer build failed: {result.stderr}")

            # Copy idp_sdk to layers
            self.console.print("[cyan]  Copying idp_sdk package files...[/cyan]")
            sdk_source = "./lib/idp_sdk/idp_sdk"
            sdk_dest = os.path.join(layer_python_dir, "idp_sdk")
            if os.path.exists(sdk_dest):
                shutil.rmtree(sdk_dest)
            shutil.copytree(sdk_source, sdk_dest)

            # Remove Lambda runtime packages (already provided by Lambda runtime)
            # This saves ~100+ MB per layer and prevents size limit issues
            self.console.print(
                "[dim]  Removing packages already included in Lambda runtime (boto3, botocore, etc.)...[/dim]"
            )
            runtime_packages = [
                "boto3",
                "botocore",
                "s3transfer",
                "awscli",
                "urllib3",  # Included with botocore
                "jmespath",  # Included with botocore
                "python_dateutil",  # Included with botocore
                "dateutil",  # Included with botocore
            ]

            removed_packages = []
            for pkg in runtime_packages:
                # Remove package directories and dist-info directories
                for pattern in [pkg, f"{pkg}-*", f"{pkg.replace('-', '_')}-*"]:
                    import glob

                    matches = glob.glob(os.path.join(layer_python_dir, pattern))
                    for match in matches:
                        if os.path.isdir(match):
                            shutil.rmtree(match)
                            removed_packages.append(os.path.basename(match))
                        elif os.path.isfile(match):
                            os.remove(match)
                            removed_packages.append(os.path.basename(match))

            if removed_packages:
                self.log_verbose(
                    f"  Removed Lambda runtime packages: {', '.join(set(removed_packages))}"
                )

            # Compute SOURCE hash from both idp_common_pkg and idp_sdk
            common_hash = self.get_source_files_checksum("./lib/idp_common_pkg")[:8]
            sdk_hash = self.get_source_files_checksum("./lib/idp_sdk")[:8]
            source_hash = hashlib.sha256(
                f"{common_hash}{sdk_hash}".encode()
            ).hexdigest()[:8]

            layer_zip_name = f"idp-common-{layer_name}-{source_hash}.zip"
            layer_zip_path = os.path.join(".aws-sam", "layers", layer_zip_name)

            # Check if layer with this source hash already exists
            if os.path.exists(layer_zip_path):
                self.console.print(
                    f"[green]Layer {layer_name} already built with same source: {layer_zip_name}[/green]"
                )
                shutil.rmtree(layer_build_dir)
                return layer_zip_path, layer_zip_name

            # Create zip file
            self.console.print(f"[cyan]Creating layer zip: {layer_zip_name}[/cyan]")
            with zipfile.ZipFile(layer_zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(layer_build_dir):
                    # Exclude unnecessary files
                    dirs[:] = [
                        d for d in dirs if d not in {"__pycache__", "*.dist-info"}
                    ]
                    for file in files:
                        if file.endswith((".pyc", ".pyo", ".dist-info")):
                            continue
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, layer_build_dir)
                        zipf.write(file_path, arcname)

            # Clean up build directory
            shutil.rmtree(layer_build_dir)

            layer_size_mb = os.path.getsize(layer_zip_path) / 1024 / 1024
            self.console.print(
                f"[green]✅ Layer '{layer_name}' built: {layer_size_mb:.2f} MB[/green]"
            )

            return layer_zip_path, layer_zip_name

        except Exception as e:
            self.console.print(f"[red]❌ Failed to build layer '{layer_name}':[/red]")
            self.console.print(str(e), style="red", markup=False)
            sys.exit(1)

    def _verify_packaged_templates_exist(self, components_needing_rebuild):
        """Verify that packaged templates exist for components NOT needing rebuild.

        If a component's checksum says it's up-to-date but the packaged.yaml is missing,
        add it to the rebuild list. This handles cases where .aws-sam/ was deleted
        but .checksum file still exists.
        """
        dependencies = self.get_component_dependencies()

        for component in dependencies.keys():
            if component in ["main", "lib"]:
                continue  # Main and lib don't have packaged templates

            # Check if component is already marked for rebuild
            already_marked = any(
                item["component"] == component for item in components_needing_rebuild
            )
            if already_marked:
                continue

            # Check if packaged.yaml exists
            packaged_path = os.path.join(component, ".aws-sam", "packaged.yaml")
            if not os.path.exists(packaged_path):
                self.console.print(
                    f"[yellow]⚠️  {component}/packaged.yaml missing - forcing rebuild[/yellow]"
                )

                # Get component's dependencies for rebuild info
                deps = dependencies.get(component, [])
                current_dep_checksums = {}
                for dep in deps:
                    if os.path.isfile(dep):
                        current_dep_checksums[dep] = self.get_file_checksum(dep)
                    elif os.path.isdir(dep):
                        current_dep_checksums[dep] = self.get_source_files_checksum(dep)

                combined_checksum = hashlib.sha256(
                    (
                        "".join(current_dep_checksums.values())
                        + (self.bucket or "")
                        + (self.prefix_and_version or "")
                        + (self.region or "")
                    ).encode()
                ).hexdigest()

                components_needing_rebuild.append(
                    {
                        "component": component,
                        "dependencies": deps,
                        "changed_dependencies": ["packaged.yaml missing"],
                        "checksum_file": f"{component}/.checksum",
                        "current_checksum": combined_checksum,
                        "current_dep_checksums": current_dep_checksums,
                    }
                )

    def _discover_existing_layer_zips(self):
        """Discover existing layer zips in .aws-sam/layers/ directory.

        Used when lib hasn't changed but we need to populate _layer_arns
        with the correct layer zip names for template token replacement.

        IMPORTANT: Verifies that the SOURCE HASH in the layer zip filename matches
        the current source code hash. If it doesn't match (source changed but checksum
        didn't detect it), this returns empty dict to force a rebuild.

        Also verifies that layers exist in S3 at the current version path.
        If a layer exists locally but not in S3 (e.g., VERSION changed), it uploads it.

        Returns:
            Dict mapping layer names to layer info dicts with zip_name, etc.
            Empty dict if source hash doesn't match (triggers rebuild)
        """
        layers_dir = ".aws-sam/layers"
        layer_info = {}

        self.console.print(
            f"[cyan]🔍 Discovering existing layer zips in {layers_dir}...[/cyan]"
        )

        if not os.path.exists(layers_dir):
            self.console.print(
                "[yellow]⚠️  Layers directory not found - cannot discover existing layers[/yellow]"
            )
            return layer_info

        # Compute current source hash to verify existing layers match current source
        current_source_hash = self.get_source_files_checksum("./lib/idp_common_pkg")[:8]
        self.console.print(
            f"[dim]   Current lib source hash: {current_source_hash}[/dim]"
        )

        # Find existing layer zips
        layer_zips = [
            f
            for f in os.listdir(layers_dir)
            if f.startswith("idp-common-") and f.endswith(".zip")
        ]

        self.console.print(
            f"[dim]   Found {len(layer_zips)} layer zip files: {layer_zips}[/dim]"
        )

        # Map each layer name to its zip file
        expected_layers = ["base", "reporting", "agents"]
        for layer_name in expected_layers:
            # Find the zip for this layer (format: idp-common-{name}-{source_hash}.zip)
            # Match based on current source hash to ensure we use up-to-date layers
            expected_zip_name = f"idp-common-{layer_name}-{current_source_hash}.zip"

            if expected_zip_name in layer_zips:
                zip_name = expected_zip_name
                zip_path = os.path.join(layers_dir, zip_name)
                layer_hash = current_source_hash
                s3_key = f"{self.prefix_and_version}/layers/{zip_name}"

                # Verify layer exists in S3 at current version path
                try:
                    self.s3_client.head_object(Bucket=self.bucket, Key=s3_key)
                    self.console.print(
                        f"[green]   ✓ Layer '{layer_name}': {zip_name} (source hash matches, in S3)[/green]"
                    )
                except ClientError as e:
                    if e.response["Error"]["Code"] == "404":
                        # Layer exists locally but not in S3 - upload it
                        self.console.print(
                            f"[yellow]   ⚠️  Layer '{layer_name}' not in S3 at current version path - uploading[/yellow]"
                        )
                        self.upload_to_s3_with_timer(
                            zip_path, s3_key, f"layer '{layer_name}'"
                        )
                    else:
                        raise

                layer_info[layer_name] = {
                    "zip_path": zip_path,
                    "zip_name": zip_name,
                    "hash": layer_hash,
                    "s3_key": s3_key,
                }
            else:
                # Layer with matching source hash not found
                # Check if there's an OLD layer (different hash) - indicates source changed
                old_matching = [
                    z for z in layer_zips if f"idp-common-{layer_name}-" in z
                ]
                if old_matching:
                    old_hash = (
                        old_matching[0]
                        .replace(f"idp-common-{layer_name}-", "")
                        .replace(".zip", "")
                    )
                    self.console.print(
                        f"[yellow]⚠️  Layer '{layer_name}' has stale source hash ({old_hash} != {current_source_hash}) - needs rebuild[/yellow]"
                    )
                else:
                    self.console.print(
                        f"[yellow]⚠️  No existing layer zip found for '{layer_name}'[/yellow]"
                    )
                # Don't add to layer_info - will trigger rebuild

        if len(layer_info) == len(expected_layers):
            self.console.print(
                f"[green]✅ Discovered {len(layer_info)} existing layer zips with matching source hash[/green]"
            )
        else:
            self.console.print(
                f"[yellow]⚠️  Only {len(layer_info)}/{len(expected_layers)} layers have matching source hash - will rebuild[/yellow]"
            )

        return layer_info

    def _verify_layer_zips_exist(self):
        """Verify that all layer zip files exist locally.

        Returns True if any layer zips are missing, requiring a rebuild.
        This prevents the situation where lib/.checksum exists but layer zips were deleted.
        """
        layers_dir = ".aws-sam/layers"
        if not os.path.exists(layers_dir):
            self.console.print(
                "[yellow]⚠️  Layers directory missing - forcing layer rebuild[/yellow]"
            )
            return True  # Need rebuild

        # Check if any idp-common-*.zip files exist
        layer_zips = [
            f
            for f in os.listdir(layers_dir)
            if f.startswith("idp-common-") and f.endswith(".zip")
        ]
        if not layer_zips:
            self.console.print(
                "[yellow]⚠️  No layer zips found in .aws-sam/layers/ - forcing layer rebuild[/yellow]"
            )
            return True  # Need rebuild

        # We have at least some layer zips, check we have all 3
        expected_layers = ["base", "reporting", "agents"]
        for layer_name in expected_layers:
            found = any(f"idp-common-{layer_name}-" in z for z in layer_zips)
            if not found:
                self.console.print(
                    f"[yellow]⚠️  Layer zip for '{layer_name}' missing - forcing layer rebuild[/yellow]"
                )
                return True  # Need rebuild

        return False  # All layers exist

    def build_all_lambda_layers(self):
        """Build all 3 Lambda layers for idp_common.

        Returns:
            Dict mapping layer names to (zip_path, zip_name, hash) tuples
        """
        self.log_phase("Building Lambda Layers", "📦")

        # Ensure layers directory exists
        os.makedirs(".aws-sam/layers", exist_ok=True)

        # Define the 3 layers
        layers_config = {
            "base": ["docs_service", "image"],
            "reporting": ["reporting"],
            "agents": ["agents"],
        }

        built_layers = {}

        for layer_name, layer_extras in layers_config.items():
            # Build the layer (hash is computed from actual contents after removing boto packages)
            self.log_task(f"Building layer '{layer_name}' [{', '.join(layer_extras)}]")
            zip_path, zip_name = self.build_lambda_layer(layer_name, layer_extras)

            # Extract hash from zip_name (format: idp-common-{name}-{hash}.zip)
            layer_hash = zip_name.split("-")[-1].replace(".zip", "")

            # Upload to S3
            s3_key = f"{self.prefix_and_version}/layers/{zip_name}"
            try:
                self.s3_client.head_object(Bucket=self.bucket, Key=s3_key)
                self.log_cached(f"Layer '{layer_name}' already in S3: {zip_name}")
            except ClientError as e:
                if e.response["Error"]["Code"] == "404":
                    self.upload_to_s3_with_timer(
                        zip_path, s3_key, f"layer '{layer_name}'"
                    )
                else:
                    raise

            # Store layer info for template injection
            built_layers[layer_name] = {
                "zip_path": zip_path,
                "zip_name": zip_name,
                "hash": layer_hash,
                "s3_key": s3_key,
            }

        self.log_success("All Lambda layers built and uploaded")
        return built_layers

    def _delete_checksum_file(self, checksum_path):
        """Delete checksum file - handles both component paths and direct file paths"""
        if os.path.isdir(checksum_path):
            # If it's a directory, look for .checksum inside it
            checksum_file = os.path.join(checksum_path, ".checksum")
        else:
            # If it's already a file path, use it directly
            checksum_file = checksum_path

        if os.path.exists(checksum_file):
            os.remove(checksum_file)
            self.log_verbose(f"Deleted checksum file: {checksum_file}")

    def update_component_checksum(self, components_needing_rebuild):
        """Update checksum with individual dependency tracking"""
        for item in components_needing_rebuild:
            current_checksum = item["current_checksum"]
            current_dep_checksums = item["current_dep_checksums"]
            checksum_file = item["checksum_file"]

            # Store both combined checksum and individual dependency checksums
            checksum_data = {
                "combined": current_checksum,
                "dependencies": current_dep_checksums,
            }

            with open(os.path.join(".", checksum_file), "w") as f:
                json.dump(checksum_data, f, indent=2)
            self.log_verbose(f"Updated checksum for {item['component']}")

    def smart_rebuild_detection(self):
        self.console.print(
            "[cyan]🔍 Analyzing component dependencies for smart rebuilds...[/cyan]"
        )

        # Safety check: verify layer zips exist even if checksum says they're up to date
        layers_missing = self._verify_layer_zips_exist()
        if layers_missing:
            self._is_lib_changed = True  # Force layer rebuild

        components_to_rebuild = self.get_components_needing_rebuild()

        # Safety check: verify packaged.yaml files exist for components marked as up-to-date
        # This handles cases where .aws-sam/ was deleted but .checksum file still exists
        self._verify_packaged_templates_exist(components_to_rebuild)

        components_names = []
        for item in components_to_rebuild:
            components_names.append(item["component"])

        if not components_to_rebuild:
            self.console.print("[green]✅ No components need rebuilding[/green]")
            return []
        self.console.print(
            f"[yellow]📦 {len(components_to_rebuild)} components need rebuilding:[/yellow]"
        )
        self.console.print(f"   📚 Components: {', '.join(components_names)}")
        return components_to_rebuild

    def print_outputs(self):
        """Print final outputs using Rich table formatting"""

        # Generate S3 URL for the main template
        template_url = f"https://s3.{self.region}.amazonaws.com/{self.bucket}/{self.prefix}/{self.main_template}"

        # URL encode the template URL for use in the CloudFormation console URL
        encoded_template_url = quote(template_url, safe=":/?#[]@!$&'()*+,;=")
        launch_url = f"https://{self.region}.console.aws.amazon.com/cloudformation/home?region={self.region}#/stacks/create/review?templateURL={encoded_template_url}&stackName=IDP"

        # Display deployment information first
        self.console.print("\n[bold cyan]Deployment Information:[/bold cyan]")
        self.console.print(f"  • Region: [yellow]{self.region}[/yellow]")
        self.console.print(f"  • Bucket: [yellow]{self.bucket}[/yellow]")
        self.console.print(
            f"  • Template Path: [yellow]{self.prefix}/{self.main_template}[/yellow]"
        )
        self.console.print(
            f"  • Public Access: [yellow]{'Yes' if self.public else 'No'}[/yellow]"
        )

        # Set public ACLs if requested
        self.set_public_acls()

        # Display hyperlinks with complete URLs as the display text
        self.console.print("\n[bold green]Deployment Outputs[/bold green]")

        # 1-Click Launch hyperlink with full URL as display text
        self.console.print("\n[cyan]1-Click Launch (creates new stack):[/cyan]")
        launch_link = f"[link={launch_url}]{launch_url}[/link]"
        self.console.print(f"  {launch_link}")

        # Template URL hyperlink with full URL as display text
        self.console.print("\n[cyan]Template URL (for updating existing stack):[/cyan]")
        template_link = f"[link={template_url}]{template_url}[/link]"
        self.console.print(f"  {template_link}")

    def set_public_acls(self):
        """Set public read ACLs on all uploaded artifacts if public option is enabled"""
        if not self.public:
            return

        self.console.print(
            "[cyan]Setting public read ACLs on published artifacts...[/cyan]"
        )

        try:
            # Get all objects with the prefix
            paginator = self.s3_client.get_paginator("list_objects_v2")
            page_iterator = paginator.paginate(
                Bucket=self.bucket, Prefix=self.prefix_and_version
            )

            objects = []
            for page in page_iterator:
                if "Contents" in page:
                    objects.extend(page["Contents"])

            if not objects:
                self.console.print("[yellow]No objects found to set ACLs on[/yellow]")
                return

            total_files = len(objects)
            self.console.print(f"[cyan]Setting ACLs on {total_files} files...[/cyan]")

            for i, obj in enumerate(objects, 1):
                self.s3_client.put_object_acl(
                    Bucket=self.bucket, Key=obj["Key"], ACL="public-read"
                )
                if i % 10 == 0 or i == total_files:
                    self.console.print(
                        f"[cyan]Progress: {i}/{total_files} files processed[/cyan]"
                    )

            # Set ACL for main template files
            main_template_keys = [
                f"{self.prefix}/{self.main_template}",
                f"{self.prefix}/{self.main_template.replace('.yaml', f'_{self.version}.yaml')}",
            ]

            for key in main_template_keys:
                self.s3_client.head_object(Bucket=self.bucket, Key=key)
                self.s3_client.put_object_acl(
                    Bucket=self.bucket, Key=key, ACL="public-read"
                )

            self.console.print("[green]✅ Public ACLs set successfully[/green]")

        except Exception as e:
            raise Exception(f"Failed to set public ACLs: {str(e)}")

    def run(self, args):
        """Main execution method"""
        # Track overall timing
        overall_start_time = time.time()
        timing_breakdown = {}

        try:
            # Parse and validate parameters
            step_start = time.time()
            self.check_parameters(args)
            timing_breakdown["Parameter validation"] = time.time() - step_start

            # Check for interrupted build state at startup - recover from any previous crash
            step_start = time.time()
            self._prepare_for_build_at_start()
            timing_breakdown["Build state recovery"] = time.time() - step_start

            # Container deployment is now handled within this script

            # Set up environment
            step_start = time.time()
            self.setup_environment()
            timing_breakdown["Environment setup"] = time.time() - step_start

            # Check prerequisites
            step_start = time.time()
            self.check_prerequisites()
            timing_breakdown["Prerequisites check"] = time.time() - step_start

            # Validate Python linting if enabled
            step_start = time.time()
            if not self._validate_python_linting():
                raise Exception("Python linting validation failed")
            timing_breakdown["Python linting"] = time.time() - step_start

            # Set up S3 bucket
            step_start = time.time()
            self.setup_artifacts_bucket()
            timing_breakdown["S3 bucket setup"] = time.time() - step_start

            # Get AWS account ID (needed for ECR placeholder)
            if not self.account_id:
                if not self.sts_client:
                    self.sts_client = boto3.client("sts", region_name=self.region)
                self.account_id = self.sts_client.get_caller_identity()["Account"]

            # Perform smart rebuild detection and cache management
            step_start = time.time()
            components_needing_rebuild = self.smart_rebuild_detection()
            timing_breakdown["Smart rebuild detection"] = time.time() - step_start

            # Start UI validation early in parallel
            step_start = time.time()
            ui_validation_future, ui_executor = self.start_ui_validation_parallel()
            timing_breakdown["Start UI validation"] = time.time() - step_start

            # clear component cache
            step_start = time.time()
            for comp_info in components_needing_rebuild:
                if comp_info["component"] != "lib":  # lib doesnt have sam build
                    self.clear_component_cache(comp_info["component"])
            timing_breakdown["Clear component cache"] = time.time() - step_start

            # Build Lambda layers if lib has changed, otherwise discover existing layers
            if self._is_lib_changed:
                step_start = time.time()
                self._layer_arns = self.build_all_lambda_layers()
                timing_breakdown["Build & upload Lambda layers"] = (
                    time.time() - step_start
                )
            else:
                # Discover existing layer zips to get their names for template replacement
                self._layer_arns = self._discover_existing_layer_zips()

                # If discovery failed to find layers, force rebuild
                if not self._layer_arns or len(self._layer_arns) < 3:
                    self.console.print(
                        "[yellow]⚠️  Layer discovery incomplete - forcing layer rebuild[/yellow]"
                    )
                    self._layer_arns = self.build_all_lambda_layers()

            # Build patterns and options with smart detection
            self.console.print(
                "[bold cyan]Building components with smart dependency detection...[/bold cyan]"
            )
            concurrent_build_start = time.time()

            # Determine optimal number of workers
            if self.max_workers is None:
                # Auto-detect: SAM builds are I/O bound, so use 2x CPU count, capped at 8
                cpu_count = os.cpu_count() or 4
                self.max_workers = min(cpu_count * 2, 8)
                self.console.print(
                    f"[green]Auto-detected {self.max_workers} concurrent workers (CPUs: {cpu_count})[/green]"
                )

            # All pattern Docker images (Pattern-1, Pattern-2, Pattern-3) are built during CloudFormation deployment via CodeBuild
            # CodeBuild will download source from S3 and build images - no pre-build required
            self.console.print(
                "\n[cyan]ℹ️  Pattern Docker images (Pattern-1/2/3) will be built during stack deployment via CodeBuild[/cyan]"
            )

            # Build nested and patterns concurrently (no dependencies on each other)
            self.console.print(
                "\n[bold yellow]🚀 Building Nested Stacks and Patterns Concurrently[/bold yellow]"
            )

            # Submit both category builds concurrently
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=2
            ) as category_executor:
                # Submit builds for both categories
                nested_future = category_executor.submit(
                    self.build_components_with_smart_detection,
                    components_needing_rebuild,
                    "nested",
                    self.max_workers,
                )
                patterns_future = category_executor.submit(
                    self.build_components_with_smart_detection,
                    components_needing_rebuild,
                    "patterns",
                    self.max_workers,
                )

                # Wait for both categories to complete and collect results
                nested_start = time.time()
                nested_success = nested_future.result()
                nested_time = time.time() - nested_start

                patterns_start = time.time()
                patterns_success = patterns_future.result()
                patterns_time = time.time() - patterns_start

            # Check if any category failed
            if not nested_success:
                self.print_error_summary()
                self.console.print(
                    "[red]❌ Error: Failed to build one or more nested stacks[/red]"
                )
                if not self.verbose:
                    self.console.print(
                        "[dim]Use --verbose flag for detailed error information[/dim]"
                    )
                sys.exit(1)

            if not patterns_success:
                self.print_error_summary()
                self.console.print(
                    "[red]❌ Error: Failed to build one or more patterns[/red]"
                )
                if not self.verbose:
                    self.console.print(
                        "[dim]Use --verbose flag for detailed error information[/dim]"
                    )
                sys.exit(1)

            total_build_time = time.time() - concurrent_build_start
            timing_breakdown["Concurrent builds (nested + patterns)"] = total_build_time
            self.console.print(
                f"\n[bold green]✅ Concurrent build completed in {total_build_time:.2f}s[/bold green]"
            )
            self.console.print(f"   [dim]• Nested: {nested_time:.2f}s[/dim]")
            self.console.print(f"   [dim]• Patterns: {patterns_time:.2f}s[/dim]")
            self.console.print(
                f"   [dim]• Wall-clock time saved by concurrency: {max(nested_time, patterns_time) - total_build_time:.2f}s[/dim]"
            )

            if components_needing_rebuild:
                # Upload configuration library
                step_start = time.time()
                self.upload_config_library()
                timing_breakdown["Upload config library"] = time.time() - step_start

            # Wait for UI validation to complete if it was started
            if ui_validation_future:
                step_start = time.time()
                try:
                    self.console.print(
                        "[cyan]⏳ Waiting for UI validation to complete...[/cyan]"
                    )
                    ui_validation_future.result()
                    self.console.print(
                        "[green]✅ UI validation completed successfully[/green]"
                    )
                except Exception as e:
                    self.console.print("[red]❌ UI validation failed:[/red]")
                    self.console.print(str(e), style="red", markup=False)
                    sys.exit(1)
                finally:
                    ui_executor.shutdown(wait=True)
                timing_breakdown["UI validation (wait)"] = time.time() - step_start

            # Package UI and start validation in parallel if needed
            step_start = time.time()
            webui_zipfile = self.package_ui()
            timing_breakdown["Package UI"] = time.time() - step_start

            # Package Pattern-1 source for CodeBuild Docker builds
            step_start = time.time()
            pattern1_source_zipfile = self.package_pattern1_source()
            timing_breakdown["Package Pattern-1 source"] = time.time() - step_start

            # Package Pattern-2 source for CodeBuild Docker builds
            step_start = time.time()
            pattern2_source_zipfile = self.package_pattern2_source()
            timing_breakdown["Package Pattern-2 source"] = time.time() - step_start

            # Package Pattern-3 source for CodeBuild Docker builds
            step_start = time.time()
            pattern3_source_zipfile = self.package_pattern3_source()
            timing_breakdown["Package Pattern-3 source"] = time.time() - step_start

            # Build main template
            step_start = time.time()
            self.build_main_template(
                webui_zipfile,
                pattern1_source_zipfile,
                pattern2_source_zipfile,
                pattern3_source_zipfile,
                components_needing_rebuild,
            )
            timing_breakdown["Build & upload main template"] = time.time() - step_start

            # Validate CloudFormation templates with cfn-lint (after all templates are built/packaged)
            step_start = time.time()
            if not self._validate_cfn_lint():
                raise Exception("CloudFormation linting validation failed")
            timing_breakdown["CloudFormation linting"] = time.time() - step_start

            # All builds completed successfully if we reach here
            self.console.print("[green]✅ All builds completed successfully[/green]")

            # Update checksum for components needing rebuild upon success
            step_start = time.time()
            self.update_component_checksum(components_needing_rebuild)
            timing_breakdown["Update checksums"] = time.time() - step_start

            # Print outputs
            step_start = time.time()
            self.print_outputs()
            timing_breakdown["Print outputs"] = time.time() - step_start

            # Calculate total time
            total_time = time.time() - overall_start_time

            # Print timing breakdown - show top 4 steps and "Other"
            self.console.print("\n[bold cyan]⏱️  Timing Breakdown:[/bold cyan]")
            self.console.print("=" * 60)

            # Sort by duration (longest first)
            sorted_steps = sorted(
                timing_breakdown.items(), key=lambda x: x[1], reverse=True
            )

            # Show top 4 steps
            top_steps = sorted_steps[:4]
            for step_name, duration in top_steps:
                percentage = (duration / total_time * 100) if total_time > 0 else 0
                self.console.print(
                    f"  • {step_name:<40} {duration:>6.2f}s ({percentage:>5.1f}%)"
                )

            # Combine remaining steps as "Other"
            if len(sorted_steps) > 4:
                other_time = sum(duration for _, duration in sorted_steps[4:])
                other_percentage = (
                    (other_time / total_time * 100) if total_time > 0 else 0
                )
                self.console.print(
                    f"  • {'Other':<40} {other_time:>6.2f}s ({other_percentage:>5.1f}%)"
                )

            self.console.print("=" * 60)
            self.console.print(
                f"  [bold green]TOTAL TIME: {total_time:.2f}s ({total_time / 60:.1f} minutes)[/bold green]"
            )

            self.console.print("\n[bold green]✅ Done![/bold green]")

        except KeyboardInterrupt:
            self.console.print("\n[yellow]Operation cancelled by user[/yellow]")
            sys.exit(1)
        except Exception as e:
            self.console.print("[red]Error:[/red]")
            self.console.print(str(e), style="red", markup=False)
            import traceback

            self.console.print("\n[yellow]Traceback:[/yellow]")
            traceback.print_exc()
            sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        publisher = IDPPublisher()
        publisher.print_usage()
        sys.exit(1)

    publisher = IDPPublisher()
    publisher.run(sys.argv[1:])
