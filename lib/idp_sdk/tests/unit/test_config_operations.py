# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for Config operations (mocked).
"""

from unittest.mock import patch

import pytest
from idp_sdk import IDPClient
from idp_sdk.models import ConfigCreateResult, ConfigValidationResult


@pytest.mark.unit
@pytest.mark.config
class TestConfigOperationsMocked:
    """Test config operations with mocked file I/O."""

    @patch("idp_common.config.merge_utils.generate_config_template")
    def test_create_config(self, mock_generate):
        """Test creating config file."""
        # Setup mock
        mock_generate.return_value = "key: value"

        # Test
        client = IDPClient()
        result = client.config.create(features="min", output="config.yaml")

        assert isinstance(result, ConfigCreateResult)
        assert result.yaml_content
        assert result.output_path == "config.yaml"

    @patch("idp_common.config.merge_utils.validate_config")
    @patch("idp_common.config.merge_utils.load_yaml_file")
    def test_validate_config(self, mock_load, mock_validate):
        """Test validating config file."""
        # Setup mocks
        mock_load.return_value = {"key": "value"}
        mock_validate.return_value = {"valid": True, "errors": [], "warnings": []}

        # Test
        client = IDPClient()
        result = client.config.validate(config_file="config.yaml")

        assert isinstance(result, ConfigValidationResult)
        assert result.valid is True
        assert len(result.errors) == 0

    def test_config_no_stack_required(self):
        """Test config operations don't require stack."""
        client = IDPClient()  # No stack name

        # Should not raise - config operations are stack-independent
        assert client.config is not None

    @patch("boto3.client")
    @patch("idp_common.config.configuration_manager.ConfigurationManager")
    def test_list_config(self, mock_manager_class, mock_boto3):
        """Test listing configuration versions."""
        # Setup mocks
        mock_cfn = mock_boto3.return_value
        mock_paginator = mock_cfn.get_paginator.return_value
        mock_paginator.paginate.return_value = [
            {
                "StackResourceSummaries": [
                    {
                        "LogicalResourceId": "ConfigurationTable",
                        "PhysicalResourceId": "test-table",
                    }
                ]
            }
        ]

        mock_manager = mock_manager_class.return_value
        mock_manager.list_config_versions.return_value = [
            {"versionName": "default", "isActive": False},
            {"versionName": "v1", "isActive": True},
        ]

        # Test
        client = IDPClient(stack_name="test-stack")
        result = client.config.list()

        assert result["count"] == 2
        assert len(result["versions"]) == 2
        assert result["versions"][0]["versionName"] == "default"

    @patch("boto3.client")
    @patch("idp_common.config.configuration_manager.ConfigurationManager")
    def test_activate_config(self, mock_manager_class, mock_boto3):
        """Test activating configuration version."""
        # Setup mocks
        mock_cfn = mock_boto3.return_value
        mock_paginator = mock_cfn.get_paginator.return_value
        mock_paginator.paginate.return_value = [
            {
                "StackResourceSummaries": [
                    {
                        "LogicalResourceId": "ConfigurationTable",
                        "PhysicalResourceId": "test-table",
                    }
                ]
            }
        ]

        mock_manager = mock_manager_class.return_value
        mock_manager.get_configuration.return_value = {
            "version": "v1"
        }  # Version exists
        mock_manager.activate_version.return_value = None

        # Test
        client = IDPClient(stack_name="test-stack")
        result = client.config.activate("v1")

        assert result["success"] is True
        assert result["activated_version"] == "v1"
        mock_manager.activate_version.assert_called_once_with("v1")

    @patch("boto3.client")
    @patch("idp_common.config.configuration_manager.ConfigurationManager")
    def test_activate_config_not_found(self, mock_manager_class, mock_boto3):
        """Test activating non-existent configuration version."""
        # Setup mocks
        mock_cfn = mock_boto3.return_value
        mock_paginator = mock_cfn.get_paginator.return_value
        mock_paginator.paginate.return_value = [
            {
                "StackResourceSummaries": [
                    {
                        "LogicalResourceId": "ConfigurationTable",
                        "PhysicalResourceId": "test-table",
                    }
                ]
            }
        ]

        mock_manager = mock_manager_class.return_value
        mock_manager.get_configuration.return_value = None  # Version doesn't exist

        # Test
        client = IDPClient(stack_name="test-stack")
        result = client.config.activate("nonexistent")

        assert result["success"] is False
        assert "does not exist" in result["error"]

    @patch("boto3.client")
    @patch("idp_common.config.configuration_manager.ConfigurationManager")
    def test_delete_config(self, mock_manager_class, mock_boto3):
        """Test deleting configuration version."""
        # Setup mocks
        mock_cfn = mock_boto3.return_value
        mock_paginator = mock_cfn.get_paginator.return_value
        mock_paginator.paginate.return_value = [
            {
                "StackResourceSummaries": [
                    {
                        "LogicalResourceId": "ConfigurationTable",
                        "PhysicalResourceId": "test-table",
                    }
                ]
            }
        ]

        mock_manager = mock_manager_class.return_value
        mock_manager.delete_configuration.return_value = None

        # Test
        client = IDPClient(stack_name="test-stack")
        result = client.config.delete("old-version")

        assert result["success"] is True
        assert result["deleted_version"] == "old-version"
        mock_manager.delete_configuration.assert_called_once_with(
            "Config", version="old-version"
        )

    @patch("boto3.client")
    @patch("idp_common.config.configuration_manager.ConfigurationManager")
    def test_delete_config_error(self, mock_manager_class, mock_boto3):
        """Test deleting configuration version with error."""
        # Setup mocks
        mock_cfn = mock_boto3.return_value
        mock_paginator = mock_cfn.get_paginator.return_value
        mock_paginator.paginate.return_value = [
            {
                "StackResourceSummaries": [
                    {
                        "LogicalResourceId": "ConfigurationTable",
                        "PhysicalResourceId": "test-table",
                    }
                ]
            }
        ]

        mock_manager = mock_manager_class.return_value
        mock_manager.delete_configuration.side_effect = ValueError(
            "Cannot delete active version"
        )

        # Test
        client = IDPClient(stack_name="test-stack")
        result = client.config.delete("active-version")

        assert result["success"] is False
        assert "Cannot delete active version" in result["error"]
