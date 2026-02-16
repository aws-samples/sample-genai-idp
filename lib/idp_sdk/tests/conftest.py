# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Pytest configuration and shared fixtures.
"""

import os

import pytest
from idp_sdk import IDPClient


@pytest.fixture(scope="session")
def stack_name():
    """Get stack name from environment."""
    return os.environ.get("IDP_STACK_NAME", "idp-stack-01")


@pytest.fixture(scope="session")
def region():
    """Get AWS region from environment."""
    return os.environ.get("AWS_REGION", "us-east-1")


@pytest.fixture
def client(stack_name, region):
    """Create IDP client instance."""
    return IDPClient(stack_name=stack_name, region=region)


@pytest.fixture
def client_no_stack():
    """Create IDP client without stack (for config/manifest operations)."""
    return IDPClient()


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "unit: Unit tests (fast, mocked, no AWS required)"
    )
    config.addinivalue_line(
        "markers",
        "integration: Integration tests (slow, real AWS, requires credentials)",
    )
    config.addinivalue_line("markers", "stack: Stack operation tests")
    config.addinivalue_line("markers", "batch: Batch operation tests")
    config.addinivalue_line("markers", "document: Document operation tests")
    config.addinivalue_line("markers", "config: Config operation tests")
