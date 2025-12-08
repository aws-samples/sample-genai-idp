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
        os.path.dirname(__file__), "../../../../src/lambda/delete_tests"
    )
    sys.path.insert(0, lambda_path)

    import index  # type: ignore[import-untyped]  # noqa: E402


@pytest.mark.unit
@patch("index.lambda_client")
@patch("index.dynamodb")
def test_lambda_handler_success(mock_dynamodb, mock_lambda_client):
    """Test successful deletion of test runs."""
    # Setup
    mock_table = Mock()
    mock_dynamodb.Table.return_value = mock_table

    # Mock get_item responses
    mock_table.get_item.side_effect = [
        {"Item": {"Files": ["file1.pdf", "file2.pdf"]}},
        {"Item": {"Files": ["file3.pdf"]}},
    ]

    event = {"arguments": {"testRunIds": ["test1", "test2"]}}
    context = Mock()
    context.get.side_effect = lambda key: {
        "TRACKING_TABLE_NAME": "test-table",
        "DELETE_DOCUMENT_FUNCTION_NAME": "delete-func",
    }[key]

    # Execute
    result = index.lambda_handler(event, context)

    # Verify
    assert result is True
    assert mock_table.get_item.call_count == 2
    assert mock_table.delete_item.call_count == 2

    # Verify lambda invocation with all document keys
    mock_lambda_client.invoke.assert_called_once()
    call_args = mock_lambda_client.invoke.call_args
    payload = json.loads(call_args[1]["Payload"])
    expected_keys = ["test1/file1.pdf", "test1/file2.pdf", "test2/file3.pdf"]
    assert payload["arguments"]["objectKeys"] == expected_keys


@pytest.mark.unit
@patch("index.lambda_client")
@patch("index.dynamodb")
def test_lambda_handler_test_run_not_found(mock_dynamodb, mock_lambda_client):
    """Test handling when test run is not found."""
    mock_table = Mock()
    mock_dynamodb.Table.return_value = mock_table
    mock_table.get_item.return_value = {}  # No Item key

    event = {"arguments": {"testRunIds": ["nonexistent"]}}
    context = Mock()
    context.get.side_effect = lambda key: {
        "TRACKING_TABLE_NAME": "test-table",
        "DELETE_DOCUMENT_FUNCTION_NAME": "delete-func",
    }[key]

    result = index.lambda_handler(event, context)

    assert result is False
    mock_table.delete_item.assert_not_called()
    mock_lambda_client.invoke.assert_not_called()


@pytest.mark.unit
@patch("index.lambda_client")
@patch("index.dynamodb")
def test_lambda_handler_no_files(mock_dynamodb, mock_lambda_client):
    """Test handling when test run has no files."""
    mock_table = Mock()
    mock_dynamodb.Table.return_value = mock_table
    mock_table.get_item.return_value = {"Item": {}}  # No Files key

    event = {"arguments": {"testRunIds": ["test1"]}}
    context = Mock()
    context.get.side_effect = lambda key: {
        "TRACKING_TABLE_NAME": "test-table",
        "DELETE_DOCUMENT_FUNCTION_NAME": "delete-func",
    }[key]

    result = index.lambda_handler(event, context)

    assert result is True
    mock_table.delete_item.assert_called_once()
    mock_lambda_client.invoke.assert_not_called()


@pytest.mark.unit
@patch("index.lambda_client")
@patch("index.dynamodb")
def test_lambda_handler_client_error(mock_dynamodb, mock_lambda_client):
    """Test handling of DynamoDB client errors."""
    mock_table = Mock()
    mock_dynamodb.Table.return_value = mock_table
    mock_table.get_item.side_effect = ClientError(
        {"Error": {"Code": "ResourceNotFoundException"}}, "GetItem"
    )

    event = {"arguments": {"testRunIds": ["test1"]}}
    context = Mock()
    context.get.side_effect = lambda key: {
        "TRACKING_TABLE_NAME": "test-table",
        "DELETE_DOCUMENT_FUNCTION_NAME": "delete-func",
    }[key]

    result = index.lambda_handler(event, context)

    assert result is False
    mock_lambda_client.invoke.assert_not_called()


@pytest.mark.unit
@patch("index.dynamodb")
def test_lambda_handler_missing_env_vars(mock_dynamodb):
    """Test handling of missing environment variables."""
    event = {"arguments": {"testRunIds": ["test1"]}}
    context = Mock()
    context.get.return_value = None

    # The actual error occurs when trying to create DynamoDB table with None name
    result = index.lambda_handler(event, context)
    assert result is False
