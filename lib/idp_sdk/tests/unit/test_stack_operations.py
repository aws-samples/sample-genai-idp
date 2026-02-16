# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for Stack operations (mocked).
"""

from unittest.mock import Mock, patch

import pytest
from idp_sdk import IDPClient


@pytest.mark.unit
@pytest.mark.stack
class TestStackOperationsMocked:
    """Test stack operations with mocked AWS calls."""

    @patch("idp_sdk.core.stack.StackDeployer")
    def test_deploy_stack(self, mock_deployer):
        """Test stack deployment."""
        # Setup mock
        mock_instance = Mock()
        mock_instance.deploy_stack.return_value = {
            "success": True,
            "operation": "CREATE",
            "status": "CREATE_COMPLETE",
            "stack_id": "arn:aws:cloudformation:...",
            "outputs": {},
        }
        mock_deployer.return_value = mock_instance

        # Test
        client = IDPClient(stack_name="test-stack")
        result = client.stack.deploy(
            pattern="pattern-1", admin_email="test@example.com"
        )

        assert result.success is True
        assert result.operation == "CREATE"
        assert result.stack_name == "test-stack"

    @patch("idp_sdk.core.stack.StackDeployer")
    def test_delete_stack(self, mock_deployer):
        """Test stack deletion."""
        # Setup mock
        mock_instance = Mock()
        mock_instance.delete_stack.return_value = {
            "success": True,
            "status": "DELETE_COMPLETE",
            "stack_id": "arn:aws:cloudformation:...",
        }
        mock_deployer.return_value = mock_instance

        # Test
        client = IDPClient(stack_name="test-stack")
        result = client.stack.delete()

        assert result.success is True
        assert result.status == "DELETE_COMPLETE"

    def test_get_resources_requires_stack(self):
        """Test get_resources requires stack name."""
        client = IDPClient()

        with pytest.raises(Exception):  # Will raise when trying to access AWS
            client.stack.get_resources()
