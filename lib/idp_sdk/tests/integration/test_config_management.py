# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Integration tests for Config management operations.

AWS Services Integrated:
- SSM Parameter Store (Config storage and retrieval)
- S3 (Config file uploads)

Operations Tested:
- config.create() - Generate config files
- config.validate() - Validate config structure
- config.upload() - Upload config to SSM Parameter Store
- config.download() - Download config from SSM Parameter Store

Prerequisites:
- Deployed IDP stack (for upload/download tests)
- AWS credentials configured
- No stack required for create/validate tests
"""

import os
import tempfile

import pytest


@pytest.mark.integration
@pytest.mark.config
class TestConfigManagement:
    """Test config management operations."""

    def test_create_config(self, client_no_stack):
        """Test creating a config file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            temp_path = f.name

        try:
            result = client_no_stack.config.create(features="min", output=temp_path)

            assert result.yaml_content
            assert result.output_path == temp_path
            assert os.path.exists(temp_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_validate_config(self, client_no_stack):
        """Test validating a config file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            temp_path = f.name

        try:
            # Create config
            client_no_stack.config.create(features="min", output=temp_path)

            # Validate it
            result = client_no_stack.config.validate(config_file=temp_path)

            assert hasattr(result, "valid")
            assert hasattr(result, "errors")
            assert hasattr(result, "warnings")
            assert isinstance(result.errors, list)
            assert isinstance(result.warnings, list)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_upload_config(self, client, stack_name):
        """Test uploading config to stack."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            temp_path = f.name

        try:
            # Create config
            client.config.create(features="min", output=temp_path)

            # Upload it
            result = client.config.upload(config_file=temp_path, stack_name=stack_name)

            assert hasattr(result, "success")
            assert result.success is True
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_download_config(self, client, stack_name):
        """Test downloading config from stack."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            temp_path = f.name

        try:
            result = client.config.download(output=temp_path, stack_name=stack_name)

            assert result.output_path == temp_path
            assert result.yaml_content
            assert os.path.exists(temp_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
