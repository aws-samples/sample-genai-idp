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
