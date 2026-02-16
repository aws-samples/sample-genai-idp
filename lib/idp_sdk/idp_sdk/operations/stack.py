# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Stack operations for IDP SDK."""

from typing import Dict, Optional, Union

from idp_sdk.exceptions import IDPConfigurationError, IDPStackError
from idp_sdk.models import (
    Pattern,
    StackDeletionResult,
    StackDeploymentResult,
    StackResources,
)


class StackOperation:
    """Stack deployment and management operations."""

    def __init__(self, client):
        self._client = client

    def deploy(
        self,
        stack_name: Optional[str] = None,
        pattern: Optional[Union[str, Pattern]] = None,
        admin_email: Optional[str] = None,
        template_url: Optional[str] = None,
        from_code: Optional[str] = None,
        custom_config: Optional[str] = None,
        max_concurrent: Optional[int] = None,
        log_level: Optional[str] = None,
        enable_hitl: Optional[bool] = None,
        pattern_config: Optional[str] = None,
        parameters: Optional[Dict[str, str]] = None,
        wait: bool = True,
        no_rollback: bool = False,
        role_arn: Optional[str] = None,
        **kwargs,
    ) -> StackDeploymentResult:
        """
        Deploy or update an IDP CloudFormation stack.

        Args:
            stack_name: CloudFormation stack name (uses default if not provided)
            pattern: IDP pattern (pattern-1, pattern-2, pattern-3) - required for new stacks
            admin_email: Admin user email - required for new stacks
            template_url: URL to CloudFormation template in S3
            from_code: Path to project root for building from source
            custom_config: Path to local config file or S3 URI
            max_concurrent: Maximum concurrent workflows
            log_level: Logging level (DEBUG, INFO, WARN, ERROR)
            enable_hitl: Enable Human-in-the-Loop
            pattern_config: Pattern configuration preset
            parameters: Additional parameters as dict
            wait: Wait for operation to complete (default: True)
            no_rollback: Disable rollback on failure
            role_arn: CloudFormation service role ARN
            **kwargs: Additional parameters

        Returns:
            StackDeploymentResult with status and outputs

        Raises:
            IDPConfigurationError: If required parameters missing
            IDPStackError: If deployment fails
        """
        from idp_sdk.core.stack import StackDeployer, build_parameters

        name = self._client._require_stack(stack_name)

        pattern_str = pattern.value if isinstance(pattern, Pattern) else pattern

        additional_params = parameters or {}
        cfn_parameters = build_parameters(
            pattern=pattern_str,
            admin_email=admin_email,
            max_concurrent=max_concurrent,
            log_level=log_level,
            enable_hitl="true" if enable_hitl else None,
            pattern_config=pattern_config,
            custom_config=custom_config,
            additional_params=additional_params,
            region=self._client._region,
            stack_name=name,
        )

        deployer = StackDeployer(region=self._client._region)

        try:
            template_path = None
            if from_code:
                import os
                import subprocess
                import sys

                import boto3

                publish_script = os.path.join(from_code, "publish.py")
                if not os.path.isfile(publish_script):
                    raise IDPConfigurationError(f"publish.py not found in {from_code}")

                sts = boto3.client("sts", region_name=self._client._region)
                account_id = sts.get_caller_identity()["Account"]
                cfn_bucket_basename = f"idp-accelerator-artifacts-{account_id}"
                cfn_prefix = "idp-sdk"

                cmd = [
                    sys.executable,
                    publish_script,
                    cfn_bucket_basename,
                    cfn_prefix,
                    self._client._region or "us-west-2",
                ]
                result = subprocess.run(
                    cmd, cwd=from_code, capture_output=True, text=True
                )

                if result.returncode != 0:
                    raise IDPStackError(f"Build failed: {result.stderr}")

                template_path = os.path.join(from_code, ".aws-sam", "idp-main.yaml")

            if template_path:
                result = deployer.deploy_stack(
                    stack_name=name,
                    template_path=template_path,
                    parameters=cfn_parameters,
                    wait=wait,
                    no_rollback=no_rollback,
                    role_arn=role_arn,
                )
            else:
                result = deployer.deploy_stack(
                    stack_name=name,
                    template_url=template_url,
                    parameters=cfn_parameters,
                    wait=wait,
                    no_rollback=no_rollback,
                    role_arn=role_arn,
                )

            return StackDeploymentResult(
                success=result.get("success", False),
                operation=result.get("operation", "UNKNOWN"),
                status=result.get("status", "UNKNOWN"),
                stack_name=name,
                stack_id=result.get("stack_id"),
                outputs=result.get("outputs", {}),
                error=result.get("error"),
            )

        except Exception as e:
            raise IDPStackError(f"Deployment failed: {e}") from e

    def delete(
        self,
        stack_name: Optional[str] = None,
        empty_buckets: bool = False,
        force_delete_all: bool = False,
        wait: bool = True,
        **kwargs,
    ) -> StackDeletionResult:
        """
        Delete an IDP CloudFormation stack.

        Args:
            stack_name: CloudFormation stack name (uses default if not provided)
            empty_buckets: Empty S3 buckets before deletion
            force_delete_all: Force delete ALL remaining resources
            wait: Wait for deletion to complete
            **kwargs: Additional parameters

        Returns:
            StackDeletionResult with status
        """
        from idp_sdk.core.stack import StackDeployer

        name = self._client._require_stack(stack_name)
        deployer = StackDeployer(region=self._client._region)

        try:
            result = deployer.delete_stack(
                stack_name=name,
                empty_buckets=empty_buckets,
                wait=wait,
            )

            cleanup_result = None
            if force_delete_all:
                stack_identifier = result.get("stack_id", name)
                cleanup_result = deployer.cleanup_retained_resources(stack_identifier)

            return StackDeletionResult(
                success=result.get("success", False),
                status=result.get("status", "UNKNOWN"),
                stack_name=name,
                stack_id=result.get("stack_id"),
                error=result.get("error"),
                cleanup_result=cleanup_result,
            )

        except Exception as e:
            raise IDPStackError(f"Deletion failed: {e}") from e

    def get_resources(
        self, stack_name: Optional[str] = None, **kwargs
    ) -> StackResources:
        """
        Get stack resources.

        Args:
            stack_name: CloudFormation stack name (uses default if not provided)
            **kwargs: Additional parameters

        Returns:
            StackResources with bucket names, ARNs, etc.
        """
        resources = self._client._get_stack_resources(stack_name)
        return StackResources(**resources)
