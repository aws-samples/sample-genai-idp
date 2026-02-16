# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for IDPClient initialization and basic functionality.
"""

import pytest
from idp_sdk import IDPClient, IDPConfigurationError


@pytest.mark.unit
class TestClientInitialization:
    """Test client initialization."""

    def test_init_without_params(self):
        """Client can be created without parameters."""
        client = IDPClient()
        assert client.stack_name is None
        assert client.region is None

    def test_init_with_stack_name(self):
        """Client can be created with stack name."""
        client = IDPClient(stack_name="test-stack")
        assert client.stack_name == "test-stack"

    def test_init_with_region(self):
        """Client can be created with region."""
        client = IDPClient(region="us-west-2")
        assert client.region == "us-west-2"

    def test_init_with_all_params(self):
        """Client can be created with all parameters."""
        client = IDPClient(stack_name="test-stack", region="eu-west-1")
        assert client.stack_name == "test-stack"
        assert client.region == "eu-west-1"

    def test_set_stack_name(self):
        """Stack name can be set after initialization."""
        client = IDPClient()
        client.stack_name = "new-stack"
        assert client.stack_name == "new-stack"

    def test_set_stack_name_clears_cache(self):
        """Setting stack name clears resource cache."""
        client = IDPClient(stack_name="old-stack")
        client._resources_cache = {"key": "value"}
        client.stack_name = "new-stack"
        assert client._resources_cache is None


@pytest.mark.unit
class TestRequireStack:
    """Test _require_stack method."""

    def test_require_stack_with_default(self):
        """Returns default stack name when set."""
        client = IDPClient(stack_name="default-stack")
        assert client._require_stack() == "default-stack"

    def test_require_stack_with_override(self):
        """Override takes precedence over default."""
        client = IDPClient(stack_name="default-stack")
        assert client._require_stack("override-stack") == "override-stack"

    def test_require_stack_raises_without_stack(self):
        """Raises error when no stack available."""
        client = IDPClient()
        with pytest.raises(IDPConfigurationError) as exc_info:
            client._require_stack()
        assert "stack_name is required" in str(exc_info.value)


@pytest.mark.unit
class TestOperationNamespaces:
    """Test operation namespaces are initialized."""

    def test_stack_operation_exists(self):
        """Stack operation namespace exists."""
        client = IDPClient()
        assert hasattr(client, "stack")
        assert client.stack is not None

    def test_batch_operation_exists(self):
        """Batch operation namespace exists."""
        client = IDPClient()
        assert hasattr(client, "batch")
        assert client.batch is not None

    def test_document_operation_exists(self):
        """Document operation namespace exists."""
        client = IDPClient()
        assert hasattr(client, "document")
        assert client.document is not None

    def test_config_operation_exists(self):
        """Config operation namespace exists."""
        client = IDPClient()
        assert hasattr(client, "config")
        assert client.config is not None

    def test_all_operations_exist(self):
        """All operation namespaces exist."""
        client = IDPClient()
        operations = [
            "stack",
            "batch",
            "document",
            "config",
            "manifest",
            "testing",
            "search",
            "evaluation",
            "assessment",
        ]
        for op in operations:
            assert hasattr(client, op), f"Missing operation: {op}"
