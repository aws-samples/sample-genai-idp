# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Tests for stack info module
"""

import json
from unittest.mock import MagicMock, patch

from idp_cli.stack_info import StackInfo, get_stack_resources


class TestStackInfo:
    """Test stack information discovery"""

    @patch("boto3.client")
    def test_init(self, mock_boto_client):
        """Test StackInfo initialization"""
        stack_info = StackInfo("test-stack", region="us-east-1")

        assert stack_info.stack_name == "test-stack"
        assert stack_info.region == "us-east-1"

    @patch("boto3.client")
    def test_get_resources(self, mock_boto_client):
        """Test resource discovery"""
        # Mock CloudFormation client
        mock_cfn = MagicMock()
        mock_ssm = MagicMock()
        mock_sts = MagicMock()

        def client_factory(service, **kwargs):
            if service == "cloudformation":
                return mock_cfn
            elif service == "ssm":
                return mock_ssm
            elif service == "sts":
                return mock_sts
            return MagicMock()

        mock_boto_client.side_effect = client_factory

        # Mock stack outputs
        mock_cfn.describe_stacks.return_value = {
            "Stacks": [
                {
                    "StackStatus": "CREATE_COMPLETE",
                    "Outputs": [
                        {
                            "OutputKey": "S3InputBucketName",
                            "OutputValue": "input-bucket",
                        },
                        {
                            "OutputKey": "S3OutputBucketName",
                            "OutputValue": "output-bucket",
                        },
                        {
                            "OutputKey": "S3ConfigurationBucketName",
                            "OutputValue": "config-bucket",
                        },
                        {
                            "OutputKey": "S3EvaluationBaselineBucketName",
                            "OutputValue": "baseline-bucket",
                        },
                        {
                            "OutputKey": "LambdaLookupFunctionName",
                            "OutputValue": "lookup-function",
                        },
                        {
                            "OutputKey": "StateMachineArn",
                            "OutputValue": "arn:aws:states:us-east-1:123456789012:stateMachine:test",
                        },
                    ],
                }
            ]
        }

        # Mock queue discovery
        paginator = MagicMock()
        paginator.paginate.return_value = [
            {
                "StackResourceSummaries": [
                    {
                        "LogicalResourceId": "DocumentQueue",
                        "PhysicalResourceId": "test-queue",
                    }
                ]
            }
        ]
        mock_cfn.get_paginator.return_value = paginator

        # Mock STS for account ID
        mock_sts.get_caller_identity.return_value = {"Account": "123456789012"}

        stack_info = StackInfo("test-stack", region="us-east-1")
        resources = stack_info.get_resources()

        assert resources["InputBucket"] == "input-bucket"
        assert resources["OutputBucket"] == "output-bucket"
        assert resources["LookupFunctionName"] == "lookup-function"
        assert "DocumentQueueUrl" in resources

    @patch("boto3.client")
    def test_get_resources_caching(self, mock_boto_client):
        """Test that resources are cached after first retrieval"""
        mock_cfn = MagicMock()
        mock_boto_client.return_value = mock_cfn

        mock_cfn.describe_stacks.return_value = {
            "Stacks": [
                {
                    "StackStatus": "CREATE_COMPLETE",
                    "Outputs": [
                        {
                            "OutputKey": "S3InputBucketName",
                            "OutputValue": "input-bucket",
                        }
                    ],
                }
            ]
        }

        paginator = MagicMock()
        paginator.paginate.return_value = [
            {
                "StackResourceSummaries": [
                    {
                        "LogicalResourceId": "DocumentQueue",
                        "PhysicalResourceId": "test-queue",
                    }
                ]
            }
        ]
        mock_cfn.get_paginator.return_value = paginator

        with patch("boto3.client") as mock_client:
            mock_client.return_value.get_caller_identity.return_value = {
                "Account": "123456789012"
            }
            mock_client.return_value.describe_stacks = mock_cfn.describe_stacks
            mock_client.return_value.get_paginator = mock_cfn.get_paginator

            stack_info = StackInfo("test-stack")
            resources1 = stack_info.get_resources()
            resources2 = stack_info.get_resources()

        # Should only call describe_stacks once due to caching
        assert mock_cfn.describe_stacks.call_count == 1
        assert resources1 == resources2

    @patch("boto3.client")
    def test_validate_stack_success(self, mock_boto_client):
        """Test stack validation with valid status"""
        mock_cfn = MagicMock()
        mock_boto_client.return_value = mock_cfn

        mock_cfn.describe_stacks.return_value = {
            "Stacks": [{"StackStatus": "CREATE_COMPLETE"}]
        }

        stack_info = StackInfo("test-stack")
        assert stack_info.validate_stack() is True

    @patch("boto3.client")
    def test_validate_stack_invalid_status(self, mock_boto_client):
        """Test stack validation with invalid status"""
        mock_cfn = MagicMock()
        mock_boto_client.return_value = mock_cfn

        mock_cfn.describe_stacks.return_value = {
            "Stacks": [{"StackStatus": "CREATE_IN_PROGRESS"}]
        }

        stack_info = StackInfo("test-stack")
        assert stack_info.validate_stack() is False

    @patch("boto3.client")
    def test_validate_stack_not_found(self, mock_boto_client):
        """Test stack validation when stack doesn't exist"""
        mock_cfn = MagicMock()
        mock_boto_client.return_value = mock_cfn

        mock_cfn.describe_stacks.return_value = {"Stacks": []}

        stack_info = StackInfo("test-stack")
        assert stack_info.validate_stack() is False

    @patch("boto3.client")
    def test_get_settings(self, mock_boto_client):
        """Test getting stack settings from SSM"""
        mock_ssm = MagicMock()
        mock_boto_client.return_value = mock_ssm

        settings_data = {"key": "value", "another": "setting"}
        mock_ssm.get_parameter.return_value = {
            "Parameter": {"Value": json.dumps(settings_data)}
        }

        stack_info = StackInfo("test-stack")
        settings = stack_info.get_settings()

        assert settings == settings_data

    @patch("boto3.client")
    def test_get_settings_not_found(self, mock_boto_client):
        """Test getting settings when parameter doesn't exist"""
        mock_ssm = MagicMock()
        mock_boto_client.return_value = mock_ssm

        mock_ssm.get_parameter.side_effect = Exception("Parameter not found")

        stack_info = StackInfo("test-stack")
        settings = stack_info.get_settings()

        # Should return empty dict on error
        assert settings == {}

    @patch("idp_cli.stack_info.StackInfo")
    def test_get_stack_resources_convenience(self, mock_stack_info_class):
        """Test convenience function get_stack_resources"""
        mock_instance = MagicMock()
        mock_instance.get_resources.return_value = {"key": "value"}
        mock_stack_info_class.return_value = mock_instance

        resources = get_stack_resources("test-stack", "us-west-2")

        mock_stack_info_class.assert_called_once_with("test-stack", "us-west-2")
        assert resources == {"key": "value"}
