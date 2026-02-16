# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Integration tests for Stack resource operations.

AWS Services Integrated:
- CloudFormation (Stack resource discovery)
- SSM Parameter Store (Stack configuration)

Operations Tested:
- stack.get_resources() - Get stack resources from CloudFormation
- Resource caching - Verify resources are cached correctly

Prerequisites:
- Deployed IDP stack
- AWS credentials configured
- Stack in CREATE_COMPLETE or UPDATE_COMPLETE state
"""

import pytest


@pytest.mark.integration
@pytest.mark.stack
class TestStackResources:
    """Test stack resource discovery operations."""

    def test_get_resources(self, client):
        """Test getting stack resources."""
        resources = client.stack.get_resources()

        # Validate required resources exist
        assert resources.input_bucket, "Input bucket missing"
        assert resources.output_bucket, "Output bucket missing"
        assert resources.documents_table, "Documents table missing"
        assert resources.state_machine_arn, "State machine ARN missing"

        # Validate resource names are strings
        assert isinstance(resources.input_bucket, str)
        assert isinstance(resources.output_bucket, str)
        assert isinstance(resources.documents_table, str)

    def test_resource_caching(self, client):
        """Test that resources are cached."""
        # First call
        resources1 = client.stack.get_resources()

        # Second call (should use cache)
        resources2 = client.stack.get_resources()

        # Verify same values
        assert resources1.input_bucket == resources2.input_bucket
        assert resources1.output_bucket == resources2.output_bucket
        assert resources1.documents_table == resources2.documents_table

    def test_get_resources_with_override(self, client, stack_name):
        """Test getting resources with stack name override."""
        resources = client.stack.get_resources(stack_name=stack_name)

        assert resources.input_bucket
        assert resources.output_bucket
