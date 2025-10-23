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
from botocore.exceptions import ClientError
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

LIB_DEPENDENCY = "./lib/idp_common_pkg/idp_common"


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

    def clean_checksums(self):
        """Delete all .checksum files in main, patterns, options, and lib directories"""
        self.console.print("[yellow]🧹 Cleaning all .checksum files...[/yellow]")

        checksum_paths = [
            ".checksum",  # main
            "lib/.checksum",  # lib
        ]

        # Add patterns checksum files
        patterns_dir = "patterns"
        if os.path.exists(patterns_dir):
            for item in os.listdir(patterns_dir):
                pattern_path = os.path.join(patterns_dir, item)
                if os.path.isdir(pattern_path):
                    checksum_paths.append(f"{pattern_path}/.checksum")

        # Add options checksum files
        options_dir = "options"
        if os.path.exists(options_dir):
            for item in os.listdir(options_dir):
                option_path = os.path.join(options_dir, item)
                if os.path.isdir(option_path):
                    checksum_paths.append(f"{option_path}/.checksum")

        deleted_count = 0
        for checksum_path in checksum_paths:
            if os.path.exists(checksum_path):
                os.remove(checksum_path)
                self.console.print(f"[green]  ✓ Deleted {checksum_path}[/green]")
                deleted_count += 1

        if deleted_count == 0:
            self.console.print("[dim]  No .checksum files found to delete[/dim]")
        else:
            self.console.print(
                f"[green]✅ Deleted {deleted_count} .checksum files - full rebuild will be triggered[/green]"
            )

    def log_verbose(self, message, style="dim"):
        """Log verbose messages if verbose mode is enabled"""
        if self.verbose:
            self.console.print(f"[{style}]{message}[/{style}]")

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
                # Verbose flag is already handled by Typer, just acknowledge it here
                pass
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

        # Generate content-based Lambda image version
        # Must be after bucket/prefix are set (needed for checksum cache key)
        self.lambda_image_version = self._generate_lambda_image_version()

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

    def _generate_lambda_image_version(self):
        """Generate content-based version for Lambda container images.

        Uses content hash of relevant source files to ensure builds are reproducible
        and only change when actual code changes.

        Hash includes:
        - lib/idp_common_pkg source code
        - Dockerfile.optimized
        - patterns/pattern-2/src (all function code)

        Format: <content-hash>
        Example: a1b2c3d4

        Returns:
            str: Content-based version string (8-char hash)
        """
        import hashlib

        # Compute hash of all relevant content
        paths_to_hash = [
            "lib/idp_common_pkg/idp_common",
            "Dockerfile.optimized",
            "patterns/pattern-2/src",
        ]

        combined_hash = hashlib.sha256()

        for path in paths_to_hash:
            if os.path.isfile(path):
                # Single file
                file_hash = self.get_file_checksum(path)
                if file_hash:
                    combined_hash.update(file_hash.encode())
            elif os.path.isdir(path):
                # Directory - use existing component checksum
                dir_hash = self.get_component_checksum(path)
                if dir_hash:
                    combined_hash.update(dir_hash.encode())

        # Return first 8 characters of hash for readability
        content_hash = combined_hash.hexdigest()[:8]

        self.log_verbose(f"Generated content-based image version: {content_hash}")
        return content_hash

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

            # Pattern-2 needs --image-repository even though images are built in CodeBuild
            if directory == "patterns/pattern-2" and self.pattern2_use_containers:
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
        """Build patterns or options with smart detection and lib dependency handling"""
        # Filter components by type
        components_to_build = []
        for item in components_needing_rebuild:
            if component_type in item["component"]:
                if (
                    self._is_lib_changed
                    and LIB_DEPENDENCY in item["dependencies"]
                    and max_workers != 1
                ):
                    max_workers = 1
                components_to_build.append(item["component"])

        if not components_to_build:
            self.console.print(f"[green]✅ All {component_type} are up to date[/green]")
            return True

        # Force sequential builds if lib changed
        if self._is_lib_changed and max_workers == 1:
            self.console.print(
                f"[yellow]⚠️  lib dependencies detected - using sequential builds for {component_type}[/yellow]"
            )

        if max_workers == 1:
            self.console.print(
                f"[cyan]Building {len(components_to_build)} {component_type} with 1 worker...[/cyan]"
            )
        else:
            self.console.print(
                f"[cyan]Building {len(components_to_build)} {component_type} with {max_workers} workers...[/cyan]"
            )

        return self._build_components_concurrently(
            components_to_build, component_type, max_workers
        )

    def _build_components_concurrently(self, components, component_type, max_workers):
        """Generic method to build components concurrently with progress display"""
        # Create progress display
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=self.console,
            transient=False,
        ) as progress:
            # Create main task for overall progress
            main_task = progress.add_task(
                f"[cyan]Building {component_type}...", total=len(components)
            )

            # Create individual tasks for each component
            component_tasks = {}
            for component in components:
                task_id = progress.add_task(
                    f"[yellow]{component}[/yellow] - Waiting...", total=1
                )
                component_tasks[component] = task_id

            # Use ThreadPoolExecutor for I/O bound operations (sam build/package)
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=max_workers
            ) as executor:
                # Submit all component build tasks
                future_to_component = {}
                for component in components:
                    # Update task status to building
                    progress.update(
                        component_tasks[component],
                        description=f"[yellow]{component}[/yellow] - Building...",
                    )
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
                            progress.update(
                                component_tasks[component],
                                description=f"[red]{component}[/red] - Failed!",
                                completed=1,
                            )
                            all_successful = False
                        else:
                            progress.update(
                                component_tasks[component],
                                description=f"[green]{component}[/green] - Complete!",
                                completed=1,
                            )

                        # Update main progress
                        progress.update(main_task, completed=completed)

                    except Exception as e:
                        # Log detailed error information

                        error_output = f"Exception: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
                        self.log_error_details(
                            f"{component_type.title()} {component} build exception",
                            error_output,
                        )

                        progress.update(
                            component_tasks[component],
                            description=f"[red]{component}[/red] - Error: {str(e)[:30]}...",
                            completed=1,
                        )
                        all_successful = False
                        progress.update(main_task, completed=completed)

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

    def validate_lambda_builds(self):
        """Validate that Lambda functions with idp_common_pkg in requirements.txt have the library included."""
        self.console.print(
            "\n[bold cyan]🔍 VALIDATING Lambda builds for idp_common inclusion[/bold cyan]"
        )

        try:
            # Discover functions with idp_common_pkg in requirements.txt
            functions = self._discover_lambda_functions_with_idp_common()

            if not functions:
                self.console.print(
                    "[yellow]No Lambda functions found with idp_common_pkg in requirements.txt[/yellow]"
                )
                return

            self.console.print(
                f"[cyan]📋 Found {len(functions)} Lambda functions with idp_common_pkg in requirements.txt:[/cyan]"
            )
            for func_key, func_info in functions.items():
                self.console.print(f"   • {func_key} → {func_info['function_name']}")
                self.log_verbose(f"     Requirements: {func_info['requirements_msg']}")

            # Validate each function
            all_passed = True
            results = []

            for func_key, func_info in functions.items():
                function_name = func_info["function_name"]
                template_dir = func_info["template_dir"]
                source_path = func_info["source_path"]

                self.log_verbose(f"Validating function: {func_key} → {function_name}")

                # Skip validation for Pattern-2 functions when using containers
                if "pattern-2" in func_key and self.pattern2_use_containers:
                    results.append((func_key, True, "Skipped (container deployment)"))
                    self.log_verbose(
                        f"⏭️  {func_key}: Skipping validation for container deployment"
                    )
                    continue

                # Check if build directory exists and has idp_common
                has_package, issues = self._validate_idp_common_in_build(
                    template_dir, function_name, source_path
                )

                if not has_package:
                    error_msg = f"Missing idp_common: {'; '.join(issues)}"
                    results.append((func_key, False, error_msg))
                    all_passed = False
                    self.log_verbose(f"❌ {func_key}: {error_msg}")
                    continue

                # Test import functionality
                import_success, import_msg = self._test_import_functionality(
                    template_dir, function_name
                )

                if import_success:
                    results.append((func_key, True, "Validation passed"))
                    self.log_verbose(f"✅ {func_key}: All validations passed")
                else:
                    results.append(
                        (func_key, False, f"Import test failed: {import_msg}")
                    )
                    all_passed = False
                    self.log_verbose(f"❌ {func_key}: Import test failed")

            # Print summary
            self.console.print("\n[cyan]📊 Validation Results Summary:[/cyan]")
            self.console.print("=" * 60)

            passed_count = sum(1 for _, passed, _ in results if passed)
            total_count = len(results)

            for func_key, passed, message in results:
                status = "[green]✅ PASS[/green]" if passed else "[red]❌ FAIL[/red]"
                self.console.print(f"{status} {func_key}: {message}")

            self.console.print("=" * 60)
            self.console.print(
                f"Results: {passed_count}/{total_count} functions passed validation"
            )

            if all_passed:
                self.console.print(
                    "[bold green]🎉 All Lambda functions with idp_common_pkg in requirements.txt have the library properly included![/bold green]"
                )
                self.console.print(
                    "[bold green]✅ Lambda build validation passed![/bold green]"
                )
            else:
                self.console.print(
                    "[bold red]💥 Some Lambda functions are missing idp_common library in their builds.[/bold red]"
                )
                self.console.print(
                    "[bold red]❌ Lambda build validation failed![/bold red]"
                )
                self.console.print(
                    "[bold red]🚫 Publish process aborted due to validation failures![/bold red]"
                )
                self.console.print(
                    "[yellow]Fix the missing idp_common dependencies and rebuild before publishing.[/yellow]"
                )
                sys.exit(1)

        except Exception as e:
            self.console.print("[red]❌ Error running lambda build validation:[/red]")
            self.console.print(str(e), style="red", markup=False)
            if self.verbose:
                self.console.print(f"[red]{traceback.format_exc()}[/red]")
            self.console.print(
                "[bold red]🚫 Publish process aborted due to validation error![/bold red]"
            )
            sys.exit(1)

    def _discover_lambda_functions_with_idp_common(self):
        """Discover all Lambda functions that have idp_common_pkg in requirements.txt."""
        functions = {}
        project_root = Path(__file__).parent.resolve()

        # Check main template Lambda functions
        main_src_dir = project_root / "src" / "lambda"
        if main_src_dir.exists():
            functions.update(
                self._scan_lambda_directory(
                    main_src_dir, project_root / "template.yaml", "main"
                )
            )

        # Check pattern Lambda functions
        patterns_dir = project_root / "patterns"
        if patterns_dir.exists():
            for pattern_dir in patterns_dir.iterdir():
                if pattern_dir.is_dir() and (pattern_dir / "template.yaml").exists():
                    # Skip Pattern-2 validation since it uses containers
                    if pattern_dir.name == "pattern-2" and self.pattern2_use_containers:
                        self.console.print(
                            "[dim]Skipping validation for Pattern-2 (uses containers)[/dim]"
                        )
                        continue
                    pattern_src = pattern_dir / "src"
                    if pattern_src.exists():
                        functions.update(
                            self._scan_lambda_directory(
                                pattern_src,
                                pattern_dir / "template.yaml",
                                pattern_dir.name,
                            )
                        )

        # Check options Lambda functions
        options_dir = project_root / "options"
        if options_dir.exists():
            for option_dir in options_dir.iterdir():
                if option_dir.is_dir() and (option_dir / "template.yaml").exists():
                    option_src = option_dir / "src"
                    if option_src.exists():
                        functions.update(
                            self._scan_lambda_directory(
                                option_src,
                                option_dir / "template.yaml",
                                option_dir.name,
                            )
                        )

        return functions

    def _scan_lambda_directory(self, src_dir, template_path, context):
        """Scan a directory for Lambda functions that have idp_common_pkg in requirements.txt."""
        functions = {}

        for func_dir in src_dir.iterdir():
            if not func_dir.is_dir():
                continue

            has_idp_common_req, req_msg = self._check_requirements_has_idp_common_pkg(
                func_dir
            )
            if has_idp_common_req:
                function_key = f"{context}/{func_dir.name}"
                functions[function_key] = {
                    "template_path": template_path,
                    "function_name": self._extract_function_name(
                        func_dir.name, template_path
                    ),
                    "source_path": func_dir,
                    "context": context,
                    "template_dir": template_path.parent,
                    "requirements_msg": req_msg,
                }

        return functions

    def _check_requirements_has_idp_common_pkg(self, func_dir):
        """Check if requirements.txt contains idp_common_pkg dependency."""
        requirements_file = func_dir / "requirements.txt"
        if not requirements_file.exists():
            return False, "No requirements.txt found"

        try:
            content = requirements_file.read_text(encoding="utf-8")
            lines = [
                line.strip()
                for line in content.split("\n")
                if line.strip() and not line.strip().startswith("#")
            ]

            # Look for idp_common_pkg reference
            for line in lines:
                if "idp_common_pkg" in line or "lib/idp_common_pkg" in line:
                    return True, f"Found dependency: {line}"

            return False, "No idp_common_pkg found in requirements.txt"
        except Exception as e:
            self.console.print(
                f"[red]❌ Error reading requirements.txt in {func_dir}:[/red]"
            )
            self.console.print(str(e), style="red", markup=False)
            sys.exit(1)

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

    def _validate_idp_common_in_build(self, template_dir, function_name, source_path):
        """Validate that idp_common package exists in the built Lambda function."""
        build_dir = template_dir / ".aws-sam" / "build" / function_name
        issues = []

        if not build_dir.exists():
            issues.append(f"Build directory not found: {build_dir}")
            return False, issues

        # Check for idp_common directory in build
        idp_common_dir = build_dir / "idp_common"
        if not idp_common_dir.exists():
            issues.append("idp_common directory not found in build")
            return False, issues

        # Check core files
        core_files = ["__init__.py", "models.py"]
        for core_file in core_files:
            file_path = idp_common_dir / core_file
            if not file_path.exists():
                issues.append(f"Missing core file: {core_file}")

        return len(issues) == 0, issues

    def _test_import_functionality(self, template_dir, function_name):
        """Test that idp_common can actually be imported in the built function."""
        build_dir = template_dir / ".aws-sam" / "build" / function_name

        if not build_dir.exists():
            return False, "Build directory not found"

        # Create a test script
        test_script = build_dir / "test_imports.py"
        test_content = """
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

try:
    import idp_common
    from idp_common import models
    print("SUCCESS: All imports working")
except ImportError as e:
    print(f"IMPORT_ERROR: {str(e)}")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: {str(e)}")
    sys.exit(1)
"""

        try:
            test_script.write_text(test_content)

            result = subprocess.run(
                [sys.executable, str(test_script)],
                capture_output=True,
                text=True,
                timeout=30,
            )

            test_script.unlink()  # Clean up

            if result.returncode == 0:
                return True, "Import test passed"
            else:
                return False, f"Import failed: {result.stdout} {result.stderr}"

        except Exception as e:
            if test_script.exists():
                test_script.unlink()
            return False, f"Test execution failed: {str(e)}"

    def upload_config_library(self):
        """Upload configuration library to S3"""
        self.console.print("[bold cyan]UPLOADING config_library to S3[/bold cyan]")
        config_dir = "config_library"

        if not os.path.exists(config_dir):
            self.console.print(
                f"[yellow]Warning: {config_dir} directory not found[/yellow]"
            )
            return

        self.console.print("[cyan]Uploading configuration library to S3[/cyan]")

        # Upload all files in config_library
        for root, dirs, files in os.walk(config_dir):
            for file in files:
                local_path = os.path.join(root, file)
                relative_path = os.path.relpath(local_path, config_dir)
                s3_key = f"{self.prefix_and_version}/config_library/{relative_path}"

                try:
                    self.s3_client.upload_file(local_path, self.bucket, s3_key)
                except ClientError as e:
                    self.console.print(f"[red]Error uploading {local_path}:[/red]")
                    self.console.print(str(e), style="red", markup=False)
                    sys.exit(1)

        self.console.print(
            f"[green]Configuration library uploaded to s3://{self.bucket}/{self.prefix_and_version}/config_library[/green]"
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
        self, webui_zipfile, pattern2_source_zipfile, components_needing_rebuild
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

                # Build main template
                """run sam build"""
                cmd = [
                    "sam",
                    "build",
                    "--template-file",
                    "template.yaml",
                ]
                if self.use_container_flag and self.use_container_flag.strip():
                    cmd.append(self.use_container_flag)

                success, result = self.run_subprocess_with_logging(
                    cmd, "Main template SAM build"
                )
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
                    "<PATTERN2_SOURCE_ZIPFILE_TOKEN>": pattern2_source_zipfile,
                    "<LAMBDA_IMAGE_VERSION>": self.lambda_image_version,
                    "<HASH_TOKEN>": self.get_directory_checksum("./lib")[:16],
                    "<CONFIG_LIBRARY_HASH_TOKEN>": self.get_directory_checksum(
                        "config_library"
                    )[:16],
                    "<CONFIG_FILES_LIST_TOKEN>": config_files_json,
                    "<WORKFORCE_URL_HASH_TOKEN>": workforce_url_hash,
                    "<A2I_RESOURCES_HASH_TOKEN>": a2i_resources_hash,
                    "<COGNITO_CLIENT_HASH_TOKEN>": cognito_client_hash,
                }

                self.console.print("[cyan]Inline edit main template to replace:[/cyan]")
                for token, value in replacements.items():
                    self.console.print(
                        f"   [yellow]{token}[/yellow] with: [green]{value}[/green]"
                    )
                    template_content = template_content.replace(token, value)

                # Write the modified template to the build directory
                build_packaged_template_path = ".aws-sam/build/idp-main.yaml"
                with open(build_packaged_template_path, "w") as f:
                    f.write(template_content)

                # Package the template from the build directory
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
                success, result = self.run_subprocess_with_logging(
                    cmd, "Main template SAM package"
                )
                os.chdir(original_cwd)
                if not success:
                    raise Exception("SAM package failed")
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
            ".md",
            ".toml",
            ".cfg",
            ".ini",
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
                            if (
                                entry.name not in exclude_dirs
                                and not entry.name.startswith(".")
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
            "".join(checksums) + self.bucket + self.prefix_and_version + self.region
        )
        result = hashlib.sha256(combined.encode()).hexdigest()

        # Cache the result
        self._component_checksum_cache[cache_key] = result
        return result

    def get_component_dependencies(self):
        """Map each component to its dependencies for smart rebuild detection"""
        dependencies = {
            # Main template components
            "main": ["./src", "template.yaml", "./config_library", LIB_DEPENDENCY],
            # Pattern components
            "patterns/pattern-1": [
                LIB_DEPENDENCY,
                "patterns/pattern-1/src",
                "patterns/pattern-1/template.yaml",
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
            ],
            # Option components (no lib dependency - they don't use idp_common)
            "options/bda-lending-project": [
                "options/bda-lending-project/src",
                "options/bda-lending-project/template.yaml",
            ],
            "options/bedrockkb": [
                "options/bedrockkb/src",
                "options/bedrockkb/template.yaml",
            ],
            "lib": [LIB_DEPENDENCY],
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

            current_checksum = self.get_component_checksum(*deps)

            needs_rebuild = True
            if os.path.exists(checksum_file):
                with open(checksum_file, "r") as f:
                    stored_checksum = f.read().strip()
                needs_rebuild = current_checksum != stored_checksum

            if needs_rebuild:
                components_to_rebuild.append(
                    {
                        "component": component,
                        "dependencies": deps,
                        "checksum_file": checksum_file,
                        "current_checksum": current_checksum,
                    }
                )
                if component == "lib":  # update _is_lib_changed
                    self._is_lib_changed = True

                self.console.print(
                    f"[yellow]📝 {component} needs rebuild due to changes in any of these dependencies:[/yellow]"
                )
                for dep in deps:
                    self.console.print(f"[yellow]   • {dep}[/yellow]")

        return components_to_rebuild

    def clear_component_cache(self, component):
        """Clear build cache for a specific component"""
        if component == "main":
            sam_dir = ".aws-sam"
        else:
            sam_dir = os.path.join(component, ".aws-sam")

        if os.path.exists(sam_dir):
            self.log_verbose(f"Clearing entire SAM cache for {component}: {sam_dir}")
            shutil.rmtree(sam_dir)

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

    def build_lib_package(self):
        """Build lib package with syntax validation"""
        try:
            self.console.print("[bold yellow]📚 Building lib package[/bold yellow]")
            lib_dir = "lib/idp_common_pkg"

            # Validate Python syntax in lib source code before building
            if not self._validate_python_syntax("lib/idp_common_pkg/idp_common"):
                raise Exception("Python syntax validation failed")

            result = subprocess.run(
                ["python", "setup.py", "build"],
                cwd=lib_dir,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise Exception(f"Build failed: {result.stderr}")
            self.console.print("[green]✅ Lib package built successfully[/green]")

        except Exception as e:
            self._delete_checksum_file("lib/.checksum")
            self.console.print("[red]❌ Failed to build lib package:[/red]")
            self.console.print(str(e), style="red", markup=False)
            sys.exit(1)

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
        """Update checksum"""
        for item in components_needing_rebuild:
            current_checksum = item["current_checksum"]
            checksum_file = item["checksum_file"]
            with open(os.path.join(".", checksum_file), "w") as f:
                f.write(current_checksum)
            self.log_verbose(f"Updated checksum for {item['component']}")

    def smart_rebuild_detection(self):
        self.console.print(
            "[cyan]🔍 Analyzing component dependencies for smart rebuilds...[/cyan]"
        )
        components_to_rebuild = self.get_components_needing_rebuild()
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
        try:
            # Parse and validate parameters
            self.check_parameters(args)

            # Container deployment is now handled within this script

            # Set up environment
            self.setup_environment()

            # Check prerequisites
            self.check_prerequisites()

            # Validate Python linting if enabled
            if not self._validate_python_linting():
                raise Exception("Python linting validation failed")

            # Set up S3 bucket
            self.setup_artifacts_bucket()

            # Get AWS account ID (needed for ECR placeholder)
            if not self.account_id:
                if not self.sts_client:
                    self.sts_client = boto3.client("sts", region_name=self.region)
                self.account_id = self.sts_client.get_caller_identity()["Account"]

            # Perform smart rebuild detection and cache management
            components_needing_rebuild = self.smart_rebuild_detection()

            # Start UI validation early in parallel
            ui_validation_future, ui_executor = self.start_ui_validation_parallel()

            # clear component cache
            for comp_info in components_needing_rebuild:
                if comp_info["component"] != "lib":  # lib doesnt have sam build
                    self.clear_component_cache(comp_info["component"])

            # Build lib package if changed
            if self._is_lib_changed:
                self.build_lib_package()

            # Build patterns and options with smart detection
            self.console.print(
                "[bold cyan]Building components with smart dependency detection...[/bold cyan]"
            )
            start_time = time.time()

            # Determine optimal number of workers
            if self.max_workers is None:
                # Auto-detect: typically CPU count or a bit less, capped at 4
                self.max_workers = min(4, (os.cpu_count() or 1) + 1)
                self.console.print(
                    f"[green]Auto-detected {self.max_workers} concurrent workers[/green]"
                )

            # Build and push Pattern-2 container images FIRST if Pattern-2 needs rebuilding
            # This MUST happen before SAM build/package since the images need to exist
            # Pattern-2 Docker images are now built during CloudFormation deployment via CodeBuild
            # No pre-build required - CodeBuild will download source from S3 and build images
            self.console.print(
                "\n[cyan]ℹ️  Pattern-2 Docker images will be built during stack deployment via CodeBuild[/cyan]"
            )

            # Build patterns with smart detection
            self.console.print("\n[bold yellow]📦 Building Patterns[/bold yellow]")
            patterns_start = time.time()
            patterns_success = self.build_components_with_smart_detection(
                components_needing_rebuild, "patterns", max_workers=self.max_workers
            )
            patterns_time = time.time() - patterns_start

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

            # Build options with smart detection
            self.console.print("\n[bold yellow]⚙️  Building Options[/bold yellow]")
            options_start = time.time()
            options_success = self.build_components_with_smart_detection(
                components_needing_rebuild, "options", max_workers=self.max_workers
            )
            options_time = time.time() - options_start

            if not options_success:
                self.print_error_summary()
                self.console.print(
                    "[red]❌ Error: Failed to build one or more options[/red]"
                )
                if not self.verbose:
                    self.console.print(
                        "[dim]Use --verbose flag for detailed error information[/dim]"
                    )
                sys.exit(1)

            total_build_time = time.time() - start_time
            self.console.print(
                f"\n[bold green]✅ Smart build completed in {total_build_time:.2f}s[/bold green]"
            )
            self.console.print(f"   [dim]• Patterns: {patterns_time:.2f}s[/dim]")
            self.console.print(f"   [dim]• Options: {options_time:.2f}s[/dim]")

            if components_needing_rebuild:
                # Upload configuration library
                self.upload_config_library()

            # Wait for UI validation to complete if it was started
            if ui_validation_future:
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

            # Package UI and start validation in parallel if needed
            webui_zipfile = self.package_ui()

            # Package Pattern-2 source for CodeBuild Docker builds
            pattern2_source_zipfile = self.package_pattern2_source()

            # Build main template
            self.build_main_template(
                webui_zipfile, pattern2_source_zipfile, components_needing_rebuild
            )

            # Validate Lambda builds for idp_common inclusion (after all builds complete)
            self.validate_lambda_builds()

            # All builds completed successfully if we reach here
            self.console.print("[green]✅ All builds completed successfully[/green]")

            # Update checksum for components needing rebuild upon success
            self.update_component_checksum(components_needing_rebuild)

            # Print outputs
            self.print_outputs()

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
