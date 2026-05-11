#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Ephemeral CodeBuild deployment script for FAST.

Deploys the full FAST stack using a temporary CodeBuild project.
Only requires Python 3.8+, AWS CLI, and git — no other dependencies.

Flow: zip source → temp S3 bucket → temp IAM role → temp CodeBuild project →
      stream logs → cleanup all temp resources.

Usage: python scripts/deploy-with-codebuild.py
"""

import atexit
import io
import json
import os
import re
import subprocess  # nosec B404 - subprocess used securely with explicit parameters
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

if sys.version_info < (3, 8):
    print("Error: Python 3.8 or higher is required")
    sys.exit(1)

RESOURCE_PREFIX: str = "fast-deploy-tmp"
LOG_POLL_INTERVAL: int = 5


# --- Logging helpers ---


def log_info(message: str) -> None:
    """Print an info message."""
    print(f"ℹ {message}")


def log_success(message: str) -> None:
    """Print a success message."""
    print(f"✓ {message}")


def log_error(message: str) -> None:
    """Print an error message to stderr."""
    print(f"✗ {message}", file=sys.stderr)


# --- Utility functions ---


def run_command(
    command: list,
    capture_output: bool = True,
    check: bool = True,
    cwd: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """
    Execute a command securely via subprocess.

    Args:
        command: List of command arguments
        capture_output: Whether to capture stdout/stderr
        check: Whether to raise on non-zero exit
        cwd: Working directory for the command

    Returns:
        CompletedProcess instance with command results
    """
    return subprocess.run(  # nosec B603
        command,
        capture_output=capture_output,
        text=True,
        check=check,
        shell=False,
        timeout=300,
        cwd=cwd,
    )


def parse_config_yaml(config_path: Path) -> Dict[str, str]:
    """
    Parse config.yaml using regex (no PyYAML dependency).

    Args:
        config_path: Path to config.yaml file

    Returns:
        Dictionary with stack_name_base value
    """
    config: Dict[str, str] = {"stack_name_base": ""}
    if not config_path.exists():
        return config

    content = config_path.read_text()
    match = re.search(r"^stack_name_base:\s*(\S+)", content, re.MULTILINE)
    if match:
        config["stack_name_base"] = match.group(1).strip("\"'")

    return config


def get_stack_outputs(stack_name: str) -> Dict[str, str]:
    """
    Fetch CloudFormation stack outputs via AWS CLI.

    Args:
        stack_name: Name of the CloudFormation stack

    Returns:
        Dictionary mapping output keys to values
    """
    result = run_command(
        [
            "aws",
            "cloudformation",
            "describe-stacks",
            "--stack-name",
            stack_name,
            "--output",
            "json",
        ]
    )
    stacks = json.loads(result.stdout).get("Stacks", [])
    if not stacks:
        raise ValueError(f"Stack '{stack_name}' not found")
    outputs = stacks[0].get("Outputs", [])
    return {o["OutputKey"]: o["OutputValue"] for o in outputs}


# --- Source packaging ---


def create_source_zip() -> bytes:
    """
    Create an in-memory zip of the repo using git ls-files.

    Returns:
        Raw bytes of the zip archive
    """
    repo_root: Path = Path(__file__).parent.parent
    result = run_command(command=["git", "ls-files", "-z"], cwd=str(repo_root))
    files: List[str] = [f for f in result.stdout.split("\0") if f]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            full = repo_root / rel
            if full.is_file():
                zf.write(filename=str(full), arcname=rel)

    log_success(
        f"Zipped {len(files)} files ({len(buf.getvalue()) / 1024 / 1024:.1f} MB)"
    )
    return buf.getvalue()


# --- AWS resource creation ---


def create_s3_bucket(bucket_name: str, region: str) -> None:
    """
    Create a temporary S3 bucket.

    Args:
        bucket_name: Name of the bucket to create
        region: AWS region for the bucket
    """
    log_info(f"Creating temp S3 bucket: {bucket_name}")
    cmd = ["aws", "s3api", "create-bucket", "--bucket", bucket_name, "--output", "json"]
    # us-east-1 does not accept a LocationConstraint
    if region != "us-east-1":
        cmd += ["--create-bucket-configuration", f"LocationConstraint={region}"]
    run_command(cmd)


def create_permission_boundary(policy_name: str) -> str:
    """
    Create an IAM permission boundary policy that denies dangerous actions.

    Even though the CodeBuild role gets AdministratorAccess, this boundary
    acts as a ceiling — the role cannot perform any action denied here.
    Blocks privilege escalation paths like creating IAM users/access keys,
    modifying KMS key policies, and organization-level operations.

    Args:
        policy_name: Name for the IAM boundary policy

    Returns:
        The ARN of the created permission boundary policy
    """
    log_info(f"Creating permission boundary: {policy_name}")

    # Deny dangerous actions that a CDK deployment should never need.
    # The Allow statement is required for a permission boundary to work —
    # it defines the maximum permissions ceiling, while the Deny statements
    # carve out explicit exceptions that cannot be overridden.
    boundary_policy: Dict[str, Any] = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "DenyDangerousActions",
                "Effect": "Deny",
                "Action": [
                    "iam:CreateUser",
                    "iam:CreateAccessKey",
                    "iam:CreateLoginProfile",
                    "iam:AttachUserPolicy",
                    "iam:PutUserPolicy",
                    "organizations:*",
                    "account:*",
                    "kms:PutKeyPolicy",
                    "kms:CreateGrant",
                ],
                "Resource": "*",
            },
            {
                "Sid": "AllowEverythingElse",
                "Effect": "Allow",
                "Action": "*",
                "Resource": "*",
            },
        ],
    }

    result = run_command(
        [
            "aws",
            "iam",
            "create-policy",
            "--policy-name",
            policy_name,
            "--policy-document",
            json.dumps(boundary_policy),
            "--output",
            "json",
        ]
    )
    boundary_arn: str = json.loads(result.stdout)["Policy"]["Arn"]
    log_success(f"Permission boundary created: {boundary_arn}")
    return boundary_arn


def create_codebuild_iam_role(role_name: str, boundary_arn: str) -> str:
    """
    Create a temporary IAM role for CodeBuild with AdministratorAccess,
    constrained by a permission boundary that blocks dangerous actions.

    CDK needs broad permissions to create all resource types, so we attach
    AdministratorAccess but use a permission boundary as a safety ceiling
    to prevent privilege escalation (e.g. creating IAM users, access keys).

    The role is deleted after the build completes.

    Args:
        role_name: Name for the IAM role
        boundary_arn: ARN of the permission boundary policy to attach

    Returns:
        The ARN of the created role
    """
    log_info(f"Creating temp IAM role: {role_name}")

    trust_policy: Dict[str, Any] = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "codebuild.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }

    result = run_command(
        [
            "aws",
            "iam",
            "create-role",
            "--role-name",
            role_name,
            "--assume-role-policy-document",
            json.dumps(trust_policy),
            "--permissions-boundary",
            boundary_arn,
            "--output",
            "json",
        ]
    )
    role_arn: str = json.loads(result.stdout)["Role"]["Arn"]

    run_command(
        [
            "aws",
            "iam",
            "attach-role-policy",
            "--role-name",
            role_name,
            "--policy-arn",
            "arn:aws:iam::aws:policy/AdministratorAccess",
            "--output",
            "json",
        ]
    )

    # IAM is eventually consistent — CodeBuild will fail to assume the role
    # if we proceed too quickly after creation.
    log_info("Waiting 10s for IAM role propagation...")
    time.sleep(10)
    return role_arn


def create_codebuild_project(
    project_name: str,
    role_arn: str,
    bucket_name: str,
    source_key: str,
    stack_name: str,
    region: str,
) -> None:
    """
    Create a temporary ARM64 CodeBuild project for CDK deployment.

    Args:
        project_name: Name for the CodeBuild project
        role_arn: ARN of the IAM service role
        bucket_name: S3 bucket containing the source zip
        source_key: S3 key of the source zip
        stack_name: CDK stack name base (passed as env var)
        region: AWS region
    """
    log_info(f"Creating CodeBuild project: {project_name}")

    buildspec: str = (
        "version: 0.2\n"
        "phases:\n"
        "  install:\n"
        "    runtime-versions:\n"
        "      python: 3.12\n"
        "      nodejs: 20\n"
        "    commands:\n"
        "      - npm install -g aws-cdk\n"
        "      - cd $CODEBUILD_SRC_DIR/infra-cdk && npm ci\n"
        "  build:\n"
        "    commands:\n"
        '      - echo "Source dir contents:" && ls -la $CODEBUILD_SRC_DIR/\n'
        "      - cd $CODEBUILD_SRC_DIR/infra-cdk && cdk bootstrap\n"
        "      - cd $CODEBUILD_SRC_DIR/infra-cdk && cdk deploy --all --require-approval never\n"
        "  post_build:\n"
        "    commands:\n"
        "      - cd $CODEBUILD_SRC_DIR && python scripts/deploy-frontend.py\n"
    )

    project_input: Dict[str, Any] = {
        "name": project_name,
        "source": {
            "type": "S3",
            "location": f"{bucket_name}/{source_key}",
            "buildspec": buildspec,
        },
        "artifacts": {"type": "NO_ARTIFACTS"},
        "environment": {
            "type": "ARM_CONTAINER",
            "image": "aws/codebuild/amazonlinux2-aarch64-standard:3.0",
            "computeType": "BUILD_GENERAL1_LARGE",
            "privilegedMode": True,
            "environmentVariables": [
                {"name": "STACK_NAME", "value": stack_name, "type": "PLAINTEXT"},
                {"name": "AWS_DEFAULT_REGION", "value": region, "type": "PLAINTEXT"},
            ],
        },
        "serviceRole": role_arn,
        "timeoutInMinutes": 60,
    }

    run_command(
        [
            "aws",
            "codebuild",
            "create-project",
            "--cli-input-json",
            json.dumps(project_input),
            "--output",
            "json",
        ]
    )


def start_codebuild(project_name: str) -> str:
    """
    Start a CodeBuild build and return the build ID.

    Args:
        project_name: Name of the CodeBuild project

    Returns:
        The build ID string
    """
    log_info("Starting CodeBuild build...")
    result = run_command(
        [
            "aws",
            "codebuild",
            "start-build",
            "--project-name",
            project_name,
            "--output",
            "json",
        ]
    )
    build_id: str = json.loads(result.stdout)["build"]["id"]
    log_success(f"Build ID: {build_id}")
    return build_id


# --- Log streaming ---


def poll_log_events(
    log_group: str, log_stream: str, next_token: Optional[str]
) -> Optional[str]:
    """
    Fetch and print new CloudWatch log events.

    Args:
        log_group: CloudWatch log group name
        log_stream: CloudWatch log stream name
        next_token: Forward token from previous poll (None for first call)

    Returns:
        Updated forward token for the next poll
    """
    cmd = [
        "aws",
        "logs",
        "get-log-events",
        "--log-group-name",
        log_group,
        "--log-stream-name",
        log_stream,
        "--start-from-head",
        "--output",
        "json",
    ]
    if next_token:
        cmd += ["--next-token", next_token]

    try:
        result = run_command(command=cmd, check=True)
    except subprocess.CalledProcessError:
        return next_token  # log stream may not exist yet

    data: Dict[str, Any] = json.loads(result.stdout)
    for event in data.get("events", []):
        print(event.get("message", "").rstrip("\n"))

    return data.get("nextForwardToken", next_token)


def stream_build_logs(build_id: str) -> str:
    """
    Poll CodeBuild status and stream CloudWatch logs until completion.

    Args:
        build_id: The CodeBuild build ID to monitor

    Returns:
        Final build status string (e.g. 'SUCCEEDED', 'FAILED')
    """
    log_group: Optional[str] = None
    log_stream: Optional[str] = None
    next_token: Optional[str] = None

    while True:
        result = run_command(
            [
                "aws",
                "codebuild",
                "batch-get-builds",
                "--ids",
                build_id,
                "--output",
                "json",
            ]
        )
        build_info: Dict[str, Any] = json.loads(result.stdout)["builds"][0]
        status: str = build_info["buildStatus"]
        phase: str = build_info.get("currentPhase", "UNKNOWN")

        # Discover log group/stream once available
        if log_group is None:
            logs_info = build_info.get("logs", {})
            log_group = logs_info.get("groupName")
            log_stream = logs_info.get("streamName")

        # Stream new log events
        if log_group and log_stream:
            next_token = poll_log_events(
                log_group=log_group,
                log_stream=log_stream,
                next_token=next_token,
            )

        if status != "IN_PROGRESS":
            # Final poll to catch remaining lines
            if log_group and log_stream:
                poll_log_events(
                    log_group=log_group,
                    log_stream=log_stream,
                    next_token=next_token,
                )
            break

        log_info(f"Phase: {phase} | Status: {status}")
        time.sleep(LOG_POLL_INTERVAL)

    return status


# --- Cleanup ---


def cleanup_resources(
    role_name: Optional[str],
    boundary_arn: Optional[str],
    bucket_name: Optional[str],
) -> None:
    """
    Delete temporary AWS resources (S3 bucket, IAM role, and permission boundary).
    Best-effort — errors are logged, not raised.

    The CodeBuild project is intentionally retained for debugging via the AWS console.

    Args:
        role_name: IAM role name (or None to skip)
        boundary_arn: ARN of the permission boundary policy (or None to skip)
        bucket_name: S3 bucket name (or None to skip)
    """
    if not any([role_name, boundary_arn, bucket_name]):
        return

    log_info(
        "Cleaning up temporary resources (keeping CodeBuild project for debugging)..."
    )

    if bucket_name:
        try:
            run_command(["aws", "s3", "rm", f"s3://{bucket_name}", "--recursive"])
            run_command(
                [
                    "aws",
                    "s3api",
                    "delete-bucket",
                    "--bucket",
                    bucket_name,
                    "--output",
                    "json",
                ]
            )
            log_success(f"Deleted S3 bucket: {bucket_name}")
        except subprocess.CalledProcessError as exc:
            log_error(f"Failed to delete S3 bucket: {exc}")

    if role_name:
        try:
            run_command(
                [
                    "aws",
                    "iam",
                    "detach-role-policy",
                    "--role-name",
                    role_name,
                    "--policy-arn",
                    "arn:aws:iam::aws:policy/AdministratorAccess",
                    "--output",
                    "json",
                ]
            )
            run_command(
                [
                    "aws",
                    "iam",
                    "delete-role",
                    "--role-name",
                    role_name,
                    "--output",
                    "json",
                ]
            )
            log_success(f"Deleted IAM role: {role_name}")
        except subprocess.CalledProcessError as exc:
            log_error(f"Failed to delete IAM role: {exc}")

    # Delete the permission boundary policy after the role is gone.
    # The role must be deleted first since IAM won't delete a policy
    # that is still attached as a permissions boundary.
    if boundary_arn:
        try:
            run_command(
                [
                    "aws",
                    "iam",
                    "delete-policy",
                    "--policy-arn",
                    boundary_arn,
                    "--output",
                    "json",
                ]
            )
            log_success(f"Deleted permission boundary policy: {boundary_arn}")
        except subprocess.CalledProcessError as exc:
            log_error(f"Failed to delete permission boundary policy: {exc}")


# --- Main ---


def main() -> int:
    """
    Main deployment function.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    # Track resource names for atexit cleanup
    resources: Dict[str, Optional[str]] = {
        "project": None,
        "role": None,
        "boundary_arn": None,
        "bucket": None,
    }

    def _cleanup() -> None:
        cleanup_resources(
            role_name=resources["role"],
            boundary_arn=resources["boundary_arn"],
            bucket_name=resources["bucket"],
        )

    atexit.register(_cleanup)

    config_path = Path(__file__).parent.parent / "infra-cdk" / "config.yaml"

    log_info("🚀 Starting ephemeral CodeBuild deployment...")
    print()

    # Verify AWS credentials
    log_info("Verifying AWS credentials...")
    try:
        result = run_command(["aws", "sts", "get-caller-identity", "--output", "json"])
        account_id: str = json.loads(result.stdout)["Account"]
        log_success(f"Account: {account_id}")
    except subprocess.CalledProcessError:
        log_error("AWS credentials not configured or invalid")
        return 1

    # Detect region — precedence: AWS_REGION > AWS_DEFAULT_REGION > aws configure.
    # This matches the AWS SDK's own resolution order and allows callers to
    # override the profile's default region via environment variables.
    region: str = (
        os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or ""
    )
    if not region:
        try:
            region = run_command(["aws", "configure", "get", "region"]).stdout.strip()
        except subprocess.CalledProcessError:
            region = ""
    if not region:
        log_error("AWS region not configured")
        return 1
    log_success(f"Region: {region}")

    # Load stack name
    stack_name = parse_config_yaml(config_path=config_path).get("stack_name_base")
    if not stack_name:
        log_error("'stack_name_base' not found in infra-cdk/config.yaml")
        return 1
    log_success(f"Stack name: {stack_name}")

    # Generate unique resource names
    ts: str = str(int(time.time()))
    resources["project"] = f"{RESOURCE_PREFIX}-{ts}"
    resources["role"] = f"{RESOURCE_PREFIX}-role-{ts}"
    resources["bucket"] = f"{RESOURCE_PREFIX}-{account_id}-{ts}"
    boundary_name: str = f"{RESOURCE_PREFIX}-boundary-{ts}"

    # Package source
    log_info("Packaging source...")
    zip_bytes: bytes = create_source_zip()

    # Create temp S3 bucket and upload
    create_s3_bucket(bucket_name=resources["bucket"], region=region)
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(zip_bytes)
        tmp_path = tmp.name
    try:
        log_info(f"Uploading source to s3://{resources['bucket']}/source.zip")
        run_command(
            [
                "aws",
                "s3",
                "cp",
                tmp_path,
                f"s3://{resources['bucket']}/source.zip",
                "--no-progress",
            ]
        )
        log_success("Source uploaded")
    finally:
        os.unlink(tmp_path)

    # Create permission boundary and temp IAM role
    boundary_arn: str = create_permission_boundary(policy_name=boundary_name)
    resources["boundary_arn"] = boundary_arn
    role_arn: str = create_codebuild_iam_role(
        role_name=resources["role"],
        boundary_arn=boundary_arn,
    )

    # Create project and start build
    create_codebuild_project(
        project_name=resources["project"],
        role_arn=role_arn,
        bucket_name=resources["bucket"],
        source_key="source.zip",
        stack_name=stack_name,
        region=region,
    )
    build_id: str = start_codebuild(project_name=resources["project"])

    # Stream logs
    final_status: str = stream_build_logs(build_id=build_id)

    # Report result
    print()
    if final_status == "SUCCEEDED":
        log_success(f"Build finished with status: {final_status}")
        try:
            outputs = get_stack_outputs(stack_name=stack_name)
            app_url = outputs.get("AmplifyUrl")
            if app_url:
                log_success(f"App URL: {app_url}")
        except (subprocess.CalledProcessError, ValueError):
            log_info("Could not retrieve App URL - check the AWS console")
    else:
        log_error(f"Build finished with status: {final_status}")
        log_info("Check the build output above for details")

    # CodeBuild project is retained for debugging — inform the user
    log_info(
        f"CodeBuild project '{resources['project']}' retained for debugging. "
        f"View in console: https://{region}.console.aws.amazon.com/codesuite/codebuild/projects/{resources['project']}"
    )
    log_info(
        f"To delete it manually: aws codebuild delete-project --name {resources['project']}"
    )

    return 0 if final_status == "SUCCEEDED" else 1


if __name__ == "__main__":
    sys.exit(main())
