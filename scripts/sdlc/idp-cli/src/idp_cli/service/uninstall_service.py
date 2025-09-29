# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import os
import boto3
from typing import Any, Dict, Optional
from botocore.exceptions import ClientError
from idp_cli.util.cfn_util import CfnUtil
from idp_cli.util.s3_util import S3Util
from loguru import logger

class UninstallService():
    def __init__(self, stack_name: str,
                 account_id: str,
                 cfn_prefix: Optional[str] = "idp-dev"):
        self.stack_name = stack_name
        self.account_id = account_id
        self.cfn_prefix = cfn_prefix 
        self.region = os.environ.get('AWS_REGION', 'us-east-1')
        self.install_bucket_name = f"{self.cfn_prefix}-{self.account_id}-{self.region}"
        self.outputs: Optional[Dict[str, str]] = None
        self.bucket_names = []
        logger.debug(f"stack_name: {self.stack_name}\naccount_id: {account_id}\ncfn_prefix: {cfn_prefix}\nregion:{self.region}\ninstall_bucket_name: {self.install_bucket_name}")

    def get_outputs(self):
        self.outputs = CfnUtil.get_stack_outputs(stack_name=self.stack_name)

    def get_buckets(self):

        bucket_keys = [
            "S3LoggingBucket",
            "S3WebUIBucket",
            "S3EvaluationBaselineBucketName",
            "S3InputBucketName",
            "S3OutputBucketName",
        ]

        self.bucket_names = []

        self.bucket_names.append(self.install_bucket_name)

        for key in bucket_keys:
            bucket_name = self.outputs[key]
            self.bucket_names.append(bucket_name)

        logger.debug(f"bucket_names: {self.bucket_names}")

    def delete_buckets(self):
        for bucket_name in self.bucket_names:
            try:
                S3Util.delete_bucket(bucket_name=bucket_name)
            except Exception as e:
                logger.exception(e)

    def delete_stack(self, wait=True):
        response = CfnUtil.delete_stack(stack_name=self.stack_name, wait=wait)
        logger.debug(response)

    def delete_service_role_stack(self):
        """Delete the CloudFormation service role stack if it exists"""
        service_role_stack_name = f"{self.cfn_prefix}-cloudformation-service-role"
        
        try:
            logger.info(f"Attempting to delete service role stack: {service_role_stack_name}")
            response = CfnUtil.delete_stack(stack_name=service_role_stack_name, wait=True)
            logger.info(f"Successfully deleted service role stack: {service_role_stack_name}")
            logger.debug(response)
        except Exception as e:
            if "does not exist" in str(e):
                logger.debug(f"Service role stack {service_role_stack_name} does not exist, skipping")
            else:
                logger.error(f"Failed to delete service role stack {service_role_stack_name}: {e}")

    def delete_permission_boundary_policy(self):
        """Delete the permission boundary policy if it exists"""
        policy_name = f"{self.cfn_prefix}-IDPPermissionBoundary"
        
        try:
            iam = boto3.client('iam')
            policy_arn = f"arn:aws:iam::{self.account_id}:policy/{policy_name}"
            
            logger.info(f"Attempting to delete permission boundary policy: {policy_arn}")
            iam.delete_policy(PolicyArn=policy_arn)
            logger.info(f"Successfully deleted permission boundary policy: {policy_arn}")
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchEntity':
                logger.debug(f"Permission boundary policy {policy_name} does not exist, skipping")
            elif e.response['Error']['Code'] == 'DeleteConflict':
                logger.warning(f"Permission boundary policy {policy_name} is still attached to resources, skipping deletion")
            else:
                logger.error(f"Failed to delete permission boundary policy {policy_name}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error deleting permission boundary policy {policy_name}: {e}")

    def uninstall(self):
        self.get_outputs()
        self.delete_stack(wait=True)
        self.get_buckets()
        self.delete_buckets()
        self.delete_service_role_stack()
        self.delete_permission_boundary_policy()