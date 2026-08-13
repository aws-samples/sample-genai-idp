# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Pytest configuration and shared fixtures.
"""

import os
import sys
from pathlib import Path

import pytest

from idp_sdk import IDPClient

# Make the in-repo idp_common importable so the DocumentState-superset test can
# compare against the runtime's real Status enum. Without this it silently
# skips via importorskip — and a skipped test protects nothing, which is how
# four runtime statuses came to be missing from DocumentState.
_IDP_COMMON = Path(__file__).resolve().parents[2] / "idp_common_pkg"
if _IDP_COMMON.is_dir() and str(_IDP_COMMON) not in sys.path:
    sys.path.append(str(_IDP_COMMON))


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
