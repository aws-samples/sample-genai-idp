"""
Unit tests for delete_tests Lambda function.
"""

import json
import os
import sys
from unittest.mock import Mock, patch

import pytest
from botocore.exceptions import ClientError

# Mock the logger before importing index
sys.modules["idp_common_pkg"] = Mock()
sys.modules["idp_common_pkg.logger"] = Mock()

# Mock boto3 before importing the Lambda module to prevent NoRegionError
# The Lambda creates boto3 clients at module level which requires AWS region
with patch("boto3.resource") as mock_resource, patch("boto3.client") as mock_client:
    mock_resource.return_value = Mock()
    mock_client.return_value = Mock()

    # Add the lambda directory to the path for importing
    lambda_path = os.path.join(
        os.path.dirname(__file__),
        "../../../../nested/api-resolvers/src/lambda/delete_tests",
    )
    sys.path.insert(0, lambda_path)

    import index  # type: ignore[import-untyped]  # noqa: E402


@pytest.mark.unit
@patch.dict(
    os.environ,
    {
        "TRACKING_TABLE_NAME": "test-table",
        "DELETE_DOCUMENT_FUNCTION_NAME": "delete-func",
        "BASELINE_BUCKET": "test-baseline-bucket",
    },
)
def test_lambda_handler_success():
    """Test successful deletion of test runs."""
    # Setup - configure the already-mocked clients
    mock_table = Mock()
    index.dynamodb.Table.return_value = mock_table

    # Mock S3 paginator for baseline file deletion
    mock_paginator = Mock()
    index.s3.get_paginator.return_value = mock_paginator
    mock_paginator.paginate.return_value = [
        {"Contents": [{"Key": "test1/baseline1.json"}]},
        {"Contents": [{"Key": "test2/baseline2.json"}]},
    ]

    # Mock get_item responses
    mock_table.get_item.side_effect = [
        {"Item": {"Files": ["file1.pdf", "file2.pdf"]}},
        {"Item": {"Files": ["file3.pdf"]}},
    ]

    event = {
        "identity": {"claims": {"cognito:groups": ["Admin"]}},
        "arguments": {"testRunIds": ["test1", "test2"]},
    }
    context = Mock()

    # Execute
    result = index.lambda_handler(event, context)

    # Verify
    assert result is True
    assert mock_table.get_item.call_count == 2
    assert mock_table.delete_item.call_count == 2

    # Verify lambda invocation with all document keys
    index.lambda_client.invoke.assert_called_once()
    call_args = index.lambda_client.invoke.call_args
    payload = json.loads(call_args[1]["Payload"])
    expected_keys = ["test1/file1.pdf", "test1/file2.pdf", "test2/file3.pdf"]
    assert payload["arguments"]["objectKeys"] == expected_keys


@pytest.mark.unit
@patch.dict(
    os.environ,
    {
        "TRACKING_TABLE_NAME": "test-table",
        "DELETE_DOCUMENT_FUNCTION_NAME": "delete-func",
        "BASELINE_BUCKET": "test-baseline-bucket",
    },
)
def test_lambda_handler_test_run_not_found():
    """Test handling when test run is not found."""
    mock_table = Mock()
    index.dynamodb.Table.return_value = mock_table
    mock_table.get_item.return_value = {}  # No Item key

    # Mock S3 paginator
    mock_paginator = Mock()
    index.s3.get_paginator.return_value = mock_paginator
    mock_paginator.paginate.return_value = []

    # Reset mock for this test
    index.lambda_client.reset_mock()

    event = {
        "identity": {"claims": {"cognito:groups": ["Admin"]}},
        "arguments": {"testRunIds": ["nonexistent"]},
    }
    context = Mock()

    result = index.lambda_handler(event, context)

    assert result is False
    mock_table.delete_item.assert_not_called()
    index.lambda_client.invoke.assert_not_called()


@pytest.mark.unit
@patch.dict(
    os.environ,
    {
        "TRACKING_TABLE_NAME": "test-table",
        "DELETE_DOCUMENT_FUNCTION_NAME": "delete-func",
        "BASELINE_BUCKET": "test-baseline-bucket",
    },
)
def test_lambda_handler_no_files():
    """Test handling when test run has no files."""
    mock_table = Mock()
    index.dynamodb.Table.return_value = mock_table
    mock_table.get_item.return_value = {"Item": {}}  # No Files key

    # Mock S3 paginator
    mock_paginator = Mock()
    index.s3.get_paginator.return_value = mock_paginator
    mock_paginator.paginate.return_value = []

    # Reset mock for this test
    index.lambda_client.reset_mock()

    event = {
        "identity": {"claims": {"cognito:groups": ["Admin"]}},
        "arguments": {"testRunIds": ["test1"]},
    }
    context = Mock()

    result = index.lambda_handler(event, context)

    assert result is True
    mock_table.delete_item.assert_called_once()
    index.lambda_client.invoke.assert_not_called()


@pytest.mark.unit
@patch.dict(
    os.environ,
    {
        "TRACKING_TABLE_NAME": "test-table",
        "DELETE_DOCUMENT_FUNCTION_NAME": "delete-func",
        "BASELINE_BUCKET": "test-baseline-bucket",
    },
)
def test_lambda_handler_client_error():
    """Test handling of DynamoDB client errors."""
    mock_table = Mock()
    index.dynamodb.Table.return_value = mock_table
    mock_table.get_item.side_effect = ClientError(
        {"Error": {"Code": "ResourceNotFoundException"}}, "GetItem"
    )

    # Mock S3 paginator
    mock_paginator = Mock()
    index.s3.get_paginator.return_value = mock_paginator
    mock_paginator.paginate.return_value = []

    # Reset mock for this test
    index.lambda_client.reset_mock()

    event = {
        "identity": {"claims": {"cognito:groups": ["Admin"]}},
        "arguments": {"testRunIds": ["test1"]},
    }
    context = Mock()

    result = index.lambda_handler(event, context)

    assert result is False
    index.lambda_client.invoke.assert_not_called()


@pytest.mark.unit
def test_lambda_handler_missing_env_vars():
    """Test handling of missing environment variables."""
    mock_table = Mock()
    index.dynamodb.Table.return_value = mock_table
    mock_table.get_item.return_value = {}  # Test run not found

    event = {
        "identity": {"claims": {"cognito:groups": ["Admin"]}},
        "arguments": {"testRunIds": ["test1"]},
    }
    context = Mock()

    # Without environment variables, the Lambda handles gracefully
    result = index.lambda_handler(event, context)
    assert result is False


@pytest.mark.unit
@patch.dict(
    os.environ,
    {
        "TRACKING_TABLE_NAME": "test-table",
        "DELETE_DOCUMENT_FUNCTION_NAME": "delete-func",
        "BASELINE_BUCKET": "test-baseline-bucket",
    },
)
def test_document_cascade_forwards_caller_identity():
    """The fan-out payload must carry the caller's identity.

    Regression test. deleteDocument enforces Admin/Author on the identity in its
    event, so a payload without one is rejected with PermissionError. The invoke
    is asynchronous ('Event'), so that rejection never surfaces here: deleteTests
    returned True while every document silently leaked. Asserting only on
    objectKeys -- as test_lambda_handler_success does -- cannot catch that.
    """
    mock_table = Mock()
    index.dynamodb.Table.return_value = mock_table
    index.lambda_client.invoke.reset_mock()

    mock_paginator = Mock()
    index.s3.get_paginator.return_value = mock_paginator
    mock_paginator.paginate.return_value = [{}]

    mock_table.get_item.return_value = {"Item": {"Files": ["file1.pdf"]}}

    identity = {"claims": {"cognito:groups": ["Admin"], "email": "admin@example.com"}}
    result = index.lambda_handler(
        {"identity": identity, "arguments": {"testRunIds": ["test1"]}}, Mock()
    )

    assert result is True
    payload = json.loads(index.lambda_client.invoke.call_args[1]["Payload"])
    assert payload["identity"] == identity, (
        "fan-out payload dropped the caller identity; deleteDocument will reject it"
    )
    # The downstream check reads exactly this path -- assert its shape, not just presence.
    assert payload["identity"]["claims"]["cognito:groups"] == ["Admin"]
    assert payload["arguments"]["objectKeys"] == ["test1/file1.pdf"]
