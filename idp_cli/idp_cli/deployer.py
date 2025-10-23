# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Deployer Module

Handles CloudFormation stack deployment from CLI.
"""

import logging
import os
import random
import string
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import boto3

logger = logging.getLogger(__name__)


class StackDeployer:
    """Manages CloudFormation stack deployment"""

    def __init__(self, region: Optional[str] = None):
        """
        Initialize stack deployer

        Args:
            region: AWS region (optional)
        """
        self.region = region
        self.cfn = boto3.client("cloudformation", region_name=region)

    def deploy_stack(
        self,
        stack_name: str,
        template_path: Optional[str] = None,
        template_url: Optional[str] = None,
        parameters: Dict[str, str] = None,
        wait: bool = False,
    ) -> Dict:
        """
        Deploy CloudFormation stack

        Args:
            stack_name: Name for the stack
            template_path: Path to local CloudFormation template (optional)
            template_url: URL to CloudFormation template in S3 (optional)
            parameters: Stack parameters
            wait: Whether to wait for stack creation to complete

        Returns:
            Dictionary with deployment result
        """
        logger.info(f"Deploying stack: {stack_name}")

        if not template_path and not template_url:
            raise ValueError("Either template_path or template_url must be provided")

        # Determine template source
        if template_url:
            logger.info(f"Using template URL: {template_url}")
            template_param = {"TemplateURL": template_url}
        else:
            # Read template from local file
            template_body = self._read_template(template_path)
            template_param = {"TemplateBody": template_body}

        # Convert parameters dict to CloudFormation format
        cfn_parameters = [
            {"ParameterKey": k, "ParameterValue": v}
            for k, v in (parameters or {}).items()
        ]

        # Check if stack exists
        stack_exists = self._stack_exists(stack_name)

        try:
            if stack_exists:
                logger.info(f"Stack {stack_name} exists - updating")
                response = self.cfn.update_stack(
                    StackName=stack_name,
                    **template_param,
                    Parameters=cfn_parameters,
                    Capabilities=[
                        "CAPABILITY_IAM",
                        "CAPABILITY_NAMED_IAM",
                        "CAPABILITY_AUTO_EXPAND",
                    ],
                )
                operation = "UPDATE"
            else:
                logger.info(f"Creating new stack: {stack_name}")
                response = self.cfn.create_stack(
                    StackName=stack_name,
                    **template_param,
                    Parameters=cfn_parameters,
                    Capabilities=[
                        "CAPABILITY_IAM",
                        "CAPABILITY_NAMED_IAM",
                        "CAPABILITY_AUTO_EXPAND",
                    ],
                    OnFailure="ROLLBACK",
                )
                operation = "CREATE"

            result = {
                "stack_name": stack_name,
                "stack_id": response.get("StackId", ""),
                "operation": operation,
                "status": "INITIATED",
            }

            if wait:
                result = self._wait_for_completion(stack_name, operation)

            return result

        except self.cfn.exceptions.AlreadyExistsException:
            raise ValueError(
                f"Stack {stack_name} already exists. Use --update flag to update."
            )
        except Exception as e:
            logger.error(f"Error deploying stack: {e}")
            raise

    def _read_template(self, template_path: str) -> str:
        """Read CloudFormation template file"""
        template_file = Path(template_path)

        if not template_file.exists():
            raise FileNotFoundError(f"Template not found: {template_path}")

        return template_file.read_text()

    def _stack_exists(self, stack_name: str) -> bool:
        """Check if stack exists"""
        try:
            self.cfn.describe_stacks(StackName=stack_name)
            return True
        except self.cfn.exceptions.ClientError as e:
            if "does not exist" in str(e):
                return False
            raise

    def _wait_for_completion(self, stack_name: str, operation: str) -> Dict:
        """
        Wait for stack operation to complete with progress display

        Args:
            stack_name: Stack name
            operation: CREATE or UPDATE

        Returns:
            Dictionary with final status
        """
        from rich.console import Console
        from rich.progress import Progress, SpinnerColumn, TextColumn

        console = Console()
        logger.info(f"Waiting for {operation} to complete...")

        complete_statuses = {
            "CREATE": [
                "CREATE_COMPLETE",
                "CREATE_FAILED",
                "ROLLBACK_COMPLETE",
                "ROLLBACK_FAILED",
            ],
            "UPDATE": [
                "UPDATE_COMPLETE",
                "UPDATE_FAILED",
                "UPDATE_ROLLBACK_COMPLETE",
                "UPDATE_ROLLBACK_FAILED",
            ],
        }

        success_statuses = {
            "CREATE": ["CREATE_COMPLETE"],
            "UPDATE": ["UPDATE_COMPLETE"],
        }

        target_statuses = complete_statuses[operation]
        success_set = success_statuses[operation]

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(
                f"[cyan]{operation} stack: {stack_name}", total=None
            )
            last_event_time = None

            while True:
                try:
                    response = self.cfn.describe_stacks(StackName=stack_name)
                    stacks = response.get("Stacks", [])

                    if not stacks:
                        raise ValueError(f"Stack {stack_name} not found")

                    stack = stacks[0]
                    status = stack.get("StackStatus", "")

                    # Get recent events
                    events = self.get_stack_events(stack_name, limit=5)
                    if events and events[0]["timestamp"] != last_event_time:
                        last_event_time = events[0]["timestamp"]
                        # Show most recent event
                        latest = events[0]
                        resource = latest["resource"]
                        resource_status = latest["status"]
                        progress.update(
                            task,
                            description=f"[cyan]{operation}: {resource} - {resource_status}",
                        )

                    if status in target_statuses:
                        # Operation complete
                        is_success = status in success_set

                        result = {
                            "stack_name": stack_name,
                            "operation": operation,
                            "status": status,
                            "success": is_success,
                            "outputs": self._get_stack_outputs(stack),
                        }

                        if not is_success:
                            result["error"] = self._get_stack_failure_reason(stack_name)

                        return result

                    # Wait before next check
                    time.sleep(10)

                except Exception as e:
                    logger.error(f"Error waiting for stack: {e}")
                    raise

    def _get_stack_outputs(self, stack: Dict) -> Dict[str, str]:
        """Extract stack outputs as dictionary"""
        outputs = {}
        for output in stack.get("Outputs", []):
            key = output.get("OutputKey", "")
            value = output.get("OutputValue", "")
            outputs[key] = value
        return outputs

    def _get_stack_failure_reason(self, stack_name: str) -> str:
        """Get failure reason from stack events"""
        try:
            response = self.cfn.describe_stack_events(StackName=stack_name)
            events = response.get("StackEvents", [])

            # Find first failed event
            for event in events:
                status = event.get("ResourceStatus", "")
                if "FAILED" in status:
                    reason = event.get("ResourceStatusReason", "Unknown")
                    resource = event.get("LogicalResourceId", "Unknown")
                    return f"{resource}: {reason}"

            return "Unknown failure reason"
        except Exception as e:
            return str(e)

    def get_stack_events(self, stack_name: str, limit: int = 20) -> List[Dict]:
        """
        Get recent stack events

        Args:
            stack_name: Stack name
            limit: Maximum number of events to return

        Returns:
            List of event dictionaries
        """
        try:
            response = self.cfn.describe_stack_events(StackName=stack_name)
            events = response.get("StackEvents", [])[:limit]

            return [
                {
                    "timestamp": event.get("Timestamp", ""),
                    "resource": event.get("LogicalResourceId", ""),
                    "status": event.get("ResourceStatus", ""),
                    "reason": event.get("ResourceStatusReason", ""),
                }
                for event in events
            ]
        except Exception as e:
            logger.error(f"Error getting stack events: {e}")
            return []

    def delete_stack(
        self,
        stack_name: str,
        empty_buckets: bool = False,
        wait: bool = True,
    ) -> Dict:
        """
        Delete CloudFormation stack

        Args:
            stack_name: Name of stack to delete
            empty_buckets: Whether to empty S3 buckets before deletion
            wait: Whether to wait for deletion to complete

        Returns:
            Dictionary with deletion result
        """
        logger.info(f"Deleting stack: {stack_name}")

        # Check if stack exists
        if not self._stack_exists(stack_name):
            raise ValueError(f"Stack '{stack_name}' does not exist")

        # Get stack resources to find buckets
        bucket_info = self._get_stack_buckets(stack_name)

        # Empty buckets if requested
        if empty_buckets and bucket_info:
            self._empty_buckets(bucket_info)

        # Delete stack
        try:
            self.cfn.delete_stack(StackName=stack_name)
            logger.info(f"Stack deletion initiated: {stack_name}")

            result = {
                "stack_name": stack_name,
                "operation": "DELETE",
                "status": "INITIATED",
            }

            if wait:
                result = self._wait_for_deletion(stack_name)

            return result

        except Exception as e:
            logger.error(f"Error deleting stack: {e}")
            raise

    def _get_stack_buckets(self, stack_name: str) -> List[Dict]:
        """
        Get S3 buckets from stack

        Args:
            stack_name: Stack name

        Returns:
            List of bucket information dictionaries
        """
        buckets = []

        try:
            # Get stack resources
            paginator = self.cfn.get_paginator("list_stack_resources")
            pages = paginator.paginate(StackName=stack_name)

            for page in pages:
                for resource in page.get("StackResourceSummaries", []):
                    if resource.get("ResourceType") == "AWS::S3::Bucket":
                        bucket_name = resource.get("PhysicalResourceId")
                        if bucket_name:
                            buckets.append(
                                {
                                    "logical_id": resource.get("LogicalResourceId"),
                                    "bucket_name": bucket_name,
                                }
                            )

            return buckets

        except Exception as e:
            logger.error(f"Error getting stack buckets: {e}")
            return []

    def _empty_buckets(self, bucket_info: List[Dict]) -> None:
        """
        Empty S3 buckets

        Args:
            bucket_info: List of bucket information dictionaries
        """
        s3 = boto3.resource("s3", region_name=self.region)

        for bucket_dict in bucket_info:
            bucket_name = bucket_dict["bucket_name"]
            logical_id = bucket_dict["logical_id"]

            try:
                logger.info(f"Emptying bucket {logical_id}: {bucket_name}")
                bucket = s3.Bucket(bucket_name)

                # Delete all objects and versions
                bucket.object_versions.all().delete()
                logger.info(f"Emptied bucket: {bucket_name}")

            except Exception as e:
                logger.error(f"Error emptying bucket {bucket_name}: {e}")
                raise Exception(
                    f"Failed to empty bucket {bucket_name}. You may need to empty it manually."
                )

    def _wait_for_deletion(self, stack_name: str) -> Dict:
        """
        Wait for stack deletion to complete

        Args:
            stack_name: Stack name

        Returns:
            Dictionary with final status
        """
        from rich.console import Console
        from rich.progress import Progress, SpinnerColumn, TextColumn

        console = Console()
        logger.info("Waiting for DELETE to complete...")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"[cyan]DELETE stack: {stack_name}", total=None)

            while True:
                try:
                    response = self.cfn.describe_stacks(StackName=stack_name)
                    stacks = response.get("Stacks", [])

                    if not stacks:
                        # Stack no longer exists - deletion complete
                        return {
                            "stack_name": stack_name,
                            "operation": "DELETE",
                            "status": "DELETE_COMPLETE",
                            "success": True,
                        }

                    stack = stacks[0]
                    status = stack.get("StackStatus", "")

                    # Update progress with current status
                    progress.update(task, description=f"[cyan]DELETE: {status}")

                    if status == "DELETE_FAILED":
                        return {
                            "stack_name": stack_name,
                            "operation": "DELETE",
                            "status": status,
                            "success": False,
                            "error": self._get_stack_failure_reason(stack_name),
                        }

                    # Wait before next check
                    time.sleep(10)

                except self.cfn.exceptions.ClientError as e:
                    if "does not exist" in str(e):
                        # Stack deleted successfully
                        return {
                            "stack_name": stack_name,
                            "operation": "DELETE",
                            "status": "DELETE_COMPLETE",
                            "success": True,
                        }
                    raise

    def get_bucket_info(self, stack_name: str) -> List[Dict]:
        """
        Get information about S3 buckets in stack

        Args:
            stack_name: Stack name

        Returns:
            List of bucket information with object counts and sizes
        """
        buckets = self._get_stack_buckets(stack_name)
        s3 = boto3.client("s3", region_name=self.region)

        for bucket_dict in buckets:
            bucket_name = bucket_dict["bucket_name"]

            try:
                # Get bucket statistics
                response = s3.list_objects_v2(Bucket=bucket_name)
                objects = response.get("Contents", [])

                bucket_dict["object_count"] = len(objects)
                bucket_dict["total_size"] = sum(obj.get("Size", 0) for obj in objects)

                # Convert size to human-readable format
                size_mb = bucket_dict["total_size"] / (1024 * 1024)
                bucket_dict["size_display"] = f"{size_mb:.2f} MB"

            except Exception as e:
                logger.warning(f"Could not get stats for {bucket_name}: {e}")
                bucket_dict["object_count"] = 0
                bucket_dict["total_size"] = 0
                bucket_dict["size_display"] = "Unknown"

        return buckets


def is_local_file_path(path: str) -> bool:
    """
    Determine if path is a local file vs S3 URI

    Args:
        path: Path to check

    Returns:
        True if local file path, False if S3 URI
    """
    return not path.startswith("s3://")


def validate_s3_uri(uri: str) -> bool:
    """
    Validate S3 URI format

    Args:
        uri: S3 URI to validate

    Returns:
        True if valid S3 URI format
    """
    if not uri.startswith("s3://"):
        return False

    # Remove s3:// prefix and check for bucket/key structure
    path = uri[5:]
    parts = path.split("/", 1)

    # Must have bucket and key
    return len(parts) == 2 and parts[0] and parts[1]


def get_or_create_config_bucket(region: str) -> str:
    """
    Get or create temporary S3 bucket for CLI config uploads

    Args:
        region: AWS region

    Returns:
        Bucket name
    """
    s3 = boto3.client("s3", region_name=region)
    sts = boto3.client("sts")

    try:
        account_id = sts.get_caller_identity()["Account"]
    except Exception as e:
        raise Exception(f"Failed to get AWS account ID: {e}")

    # Normalize region name for bucket (replace hyphens with nothing for cleaner name)
    region_normalized = region.replace("-", "")

    # Check for existing bucket with pattern
    bucket_prefix = f"idp-cli-config-{account_id}-{region_normalized}-"

    try:
        response = s3.list_buckets()
        for bucket in response.get("Buckets", []):
            bucket_name = bucket["Name"]
            if bucket_name.startswith(bucket_prefix):
                logger.info(f"Using existing config bucket: {bucket_name}")
                return bucket_name
    except Exception as e:
        logger.warning(f"Error listing buckets: {e}")

    # Create new bucket with random suffix
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    bucket_name = f"{bucket_prefix}{suffix}"

    logger.info(f"Creating new config bucket: {bucket_name}")

    try:
        # Create bucket
        if region == "us-east-1":
            s3.create_bucket(Bucket=bucket_name)
        else:
            s3.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={"LocationConstraint": region},
            )

        # Enable versioning
        s3.put_bucket_versioning(
            Bucket=bucket_name, VersioningConfiguration={"Status": "Enabled"}
        )

        # Enable encryption
        s3.put_bucket_encryption(
            Bucket=bucket_name,
            ServerSideEncryptionConfiguration={
                "Rules": [
                    {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
                ]
            },
        )

        # Set lifecycle policy (30-day expiration)
        s3.put_bucket_lifecycle_configuration(
            Bucket=bucket_name,
            LifecycleConfiguration={
                "Rules": [
                    {
                        "ID": "DeleteOldConfigs",
                        "Status": "Enabled",
                        "Prefix": "idp-cli/custom-configurations/",
                        "Expiration": {"Days": 30},
                    }
                ]
            },
        )

        # Add tags
        s3.put_bucket_tagging(
            Bucket=bucket_name,
            Tagging={
                "TagSet": [
                    {"Key": "CreatedBy", "Value": "idp-cli"},
                    {"Key": "Purpose", "Value": "config-staging"},
                ]
            },
        )

        logger.info(f"Successfully created config bucket: {bucket_name}")
        return bucket_name

    except Exception as e:
        raise Exception(f"Failed to create config bucket: {e}")


def upload_local_config(
    file_path: str, region: str, stack_name: Optional[str] = None
) -> str:
    """
    Upload local config file to temporary S3 bucket

    Args:
        file_path: Path to local config file
        region: AWS region
        stack_name: CloudFormation stack name (unused, kept for compatibility)

    Returns:
        S3 URI of uploaded file
    """
    # Validate file exists
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Config file not found: {file_path}")

    logger.info(f"Uploading local config file: {file_path}")

    # Always use temp bucket
    bucket_name = get_or_create_config_bucket(region)

    # Generate timestamped key - use underscores instead of hyphens in filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    original_name = os.path.basename(file_path)
    # Sanitize filename - replace hyphens with underscores for maximum compatibility
    safe_name = original_name.replace("-", "_")
    s3_key = f"idp-cli/custom-configurations/config_{timestamp}_{safe_name}"

    # Upload file
    s3 = boto3.client("s3", region_name=region)
    try:
        with open(file_path, "rb") as f:
            s3.put_object(
                Bucket=bucket_name, Key=s3_key, Body=f, ServerSideEncryption="AES256"
            )

        # Return S3 URI
        s3_uri = f"s3://{bucket_name}/{s3_key}"
        logger.info(f"Uploaded config file to: {s3_uri}")
        return s3_uri

    except Exception as e:
        raise Exception(f"Failed to upload config file: {e}")


def build_parameters(
    pattern: str,
    admin_email: str,
    max_concurrent: int = 100,
    log_level: str = "INFO",
    enable_hitl: str = "false",
    pattern_config: Optional[str] = None,
    custom_config: Optional[str] = None,
    additional_params: Optional[Dict[str, str]] = None,
    region: Optional[str] = None,
    stack_name: Optional[str] = None,
) -> Dict[str, str]:
    """
    Build CloudFormation parameters dictionary

    If custom_config is a local file path, it will be uploaded to S3:
    - For existing stacks: Uses the stack's ConfigurationBucket
    - For new stacks: Creates a temporary bucket

    Args:
        pattern: IDP pattern (pattern-1, pattern-2, pattern-3)
        admin_email: Admin user email
        max_concurrent: Maximum concurrent workflows
        log_level: Logging level
        enable_hitl: Enable HITL (true/false)
        pattern_config: Pattern configuration preset
        custom_config: Custom configuration (local file path or S3 URI)
        additional_params: Additional parameters as dict
        region: AWS region (auto-detected if not provided)
        stack_name: Stack name (helps determine upload bucket for updates)

    Returns:
        Dictionary of parameter key-value pairs
    """
    # Map pattern names to CloudFormation values
    pattern_map = {
        "pattern-1": "Pattern1 - Packet or Media processing with Bedrock Data Automation (BDA)",
        "pattern-2": "Pattern2 - Packet processing with Textract and Bedrock",
        "pattern-3": "Pattern3 - Packet processing with Textract, SageMaker(UDOP), and Bedrock",
    }

    parameters = {
        "AdminEmail": admin_email,
        "IDPPattern": pattern_map.get(pattern, pattern),
        "MaxConcurrentWorkflows": str(max_concurrent),
        "LogLevel": log_level,
        "EnableHITL": enable_hitl,
    }

    # Add pattern-specific configuration
    if pattern_config:
        if pattern == "pattern-1":
            parameters["Pattern1Configuration"] = pattern_config
        elif pattern == "pattern-2":
            parameters["Pattern2Configuration"] = pattern_config
        elif pattern == "pattern-3":
            parameters["Pattern3Configuration"] = pattern_config

    # Handle custom config - support both local files and S3 URIs
    if custom_config:
        if is_local_file_path(custom_config):
            # Local file - need to upload it
            if not region:
                # Auto-detect region from boto3 session
                import boto3

                session = boto3.session.Session()
                region = session.region_name
                if not region:
                    raise ValueError(
                        "Region could not be determined. Please specify --region or configure AWS_DEFAULT_REGION"
                    )

            logger.info(f"Detected local config file: {custom_config}")
            logger.info(f"Using region: {region}")

            # Upload to S3 bucket (stack's ConfigurationBucket if exists, else temp bucket)
            s3_uri = upload_local_config(custom_config, region, stack_name)
            parameters["CustomConfigPath"] = s3_uri

            logger.info(f"Using uploaded config: {s3_uri}")
        else:
            # Already an S3 URI - validate and use
            if not validate_s3_uri(custom_config):
                raise ValueError(
                    f"Invalid S3 URI format: {custom_config}. Expected format: s3://bucket/key"
                )

            parameters["CustomConfigPath"] = custom_config
            logger.info(f"Using S3 config: {custom_config}")

    # Add any additional parameters
    if additional_params:
        parameters.update(additional_params)

    return parameters
