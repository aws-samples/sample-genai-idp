# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Unit tests for _count_completed_documents function in test_results_resolver
"""

from unittest.mock import MagicMock, patch

import pytest


def _mock_batch_get_response(table_name, items):
    """Helper to create batch_get_item response"""
    return {"Responses": {table_name: items}}


@pytest.mark.unit
def test_count_completed_documents_all_completed():
    """Test counting when all documents completed evaluation"""
    import importlib.util
    import os
    import sys

    spec = importlib.util.spec_from_file_location(
        "index",
        os.path.join(
            os.path.dirname(__file__),
            "../../../../nested/api-resolvers/src/lambda/test_results_resolver/index.py",
        ),
    )
    index = importlib.util.module_from_spec(spec)
    sys.modules["index"] = index
    spec.loader.exec_module(index)
    mock_table = MagicMock()
    mock_table.table_name = "test-table"

    mock_response = _mock_batch_get_response(
        "test-table",
        [
            {
                "PK": {"S": "doc#test-run-123/file1.pdf"},
                "SK": {"S": "none"},
                "EvaluationStatus": {"S": "COMPLETED"},
            },
            {
                "PK": {"S": "doc#test-run-123/file2.pdf"},
                "SK": {"S": "none"},
                "EvaluationStatus": {"S": "COMPLETED"},
            },
            {
                "PK": {"S": "doc#test-run-123/file3.pdf"},
                "SK": {"S": "none"},
                "EvaluationStatus": {"S": "COMPLETED"},
            },
        ],
    )

    mock_dynamodb_client = MagicMock()
    mock_dynamodb_client.batch_get_item.return_value = mock_response

    with patch("boto3.client", return_value=mock_dynamodb_client):
        test_run_id = "test-run-123"
        files = ["file1.pdf", "file2.pdf", "file3.pdf"]
        count = index._count_completed_documents(mock_table, test_run_id, files)
        assert count == 3
        assert mock_dynamodb_client.batch_get_item.call_count == 1


@pytest.mark.unit
def test_count_completed_documents_partial():
    """Test counting when only some documents completed evaluation"""
    import importlib.util
    import os
    import sys

    spec = importlib.util.spec_from_file_location(
        "index",
        os.path.join(
            os.path.dirname(__file__),
            "../../../../nested/api-resolvers/src/lambda/test_results_resolver/index.py",
        ),
    )
    index = importlib.util.module_from_spec(spec)
    sys.modules["index"] = index
    spec.loader.exec_module(index)
    mock_table = MagicMock()
    mock_table.table_name = "test-table"

    mock_response = _mock_batch_get_response(
        "test-table",
        [
            {
                "PK": {"S": "doc#test-run-123/file1.pdf"},
                "SK": {"S": "none"},
                "EvaluationStatus": {"S": "COMPLETED"},
            },
            {
                "PK": {"S": "doc#test-run-123/file2.pdf"},
                "SK": {"S": "none"},
                "EvaluationStatus": {"S": "COMPLETED"},
            },
            {
                "PK": {"S": "doc#test-run-123/file3.pdf"},
                "SK": {"S": "none"},
            },  # No EvaluationStatus
        ],
    )

    mock_dynamodb_client = MagicMock()
    mock_dynamodb_client.batch_get_item.return_value = mock_response

    with patch("boto3.client", return_value=mock_dynamodb_client):
        test_run_id = "test-run-123"
        files = ["file1.pdf", "file2.pdf", "file3.pdf"]
        count = index._count_completed_documents(mock_table, test_run_id, files)
        assert count == 2


@pytest.mark.unit
def test_count_completed_documents_none_completed():
    """Test counting when no documents completed evaluation"""
    import importlib.util
    import os
    import sys

    spec = importlib.util.spec_from_file_location(
        "index",
        os.path.join(
            os.path.dirname(__file__),
            "../../../../nested/api-resolvers/src/lambda/test_results_resolver/index.py",
        ),
    )
    index = importlib.util.module_from_spec(spec)
    sys.modules["index"] = index
    spec.loader.exec_module(index)
    mock_table = MagicMock()
    mock_table.table_name = "test-table"

    mock_response = _mock_batch_get_response(
        "test-table",
        [
            {"PK": {"S": "doc#test-run-123/file1.pdf"}, "SK": {"S": "none"}},
            {"PK": {"S": "doc#test-run-123/file2.pdf"}, "SK": {"S": "none"}},
        ],
    )

    mock_dynamodb_client = MagicMock()
    mock_dynamodb_client.batch_get_item.return_value = mock_response

    with patch("boto3.client", return_value=mock_dynamodb_client):
        test_run_id = "test-run-123"
        files = ["file1.pdf", "file2.pdf"]
        count = index._count_completed_documents(mock_table, test_run_id, files)
        assert count == 0


@pytest.mark.unit
def test_count_completed_documents_missing_evaluation_status():
    """Test counting when EvaluationStatus field is missing"""
    import importlib.util
    import os
    import sys

    spec = importlib.util.spec_from_file_location(
        "index",
        os.path.join(
            os.path.dirname(__file__),
            "../../../../nested/api-resolvers/src/lambda/test_results_resolver/index.py",
        ),
    )
    index = importlib.util.module_from_spec(spec)
    sys.modules["index"] = index
    spec.loader.exec_module(index)
    mock_table = MagicMock()
    mock_table.table_name = "test-table"

    mock_response = _mock_batch_get_response(
        "test-table",
        [
            {
                "PK": {"S": "doc#test-run-123/file1.pdf"},
                "SK": {"S": "none"},
                "ObjectStatus": {"S": "COMPLETED"},
            }
        ],
    )

    mock_dynamodb_client = MagicMock()
    mock_dynamodb_client.batch_get_item.return_value = mock_response

    with patch("boto3.client", return_value=mock_dynamodb_client):
        test_run_id = "test-run-123"
        files = ["file1.pdf"]
        count = index._count_completed_documents(mock_table, test_run_id, files)
        assert count == 0


@pytest.mark.unit
def test_count_completed_documents_document_not_found():
    """Test counting when document not found in tracking table"""
    import importlib.util
    import os
    import sys

    spec = importlib.util.spec_from_file_location(
        "index",
        os.path.join(
            os.path.dirname(__file__),
            "../../../../nested/api-resolvers/src/lambda/test_results_resolver/index.py",
        ),
    )
    index = importlib.util.module_from_spec(spec)
    sys.modules["index"] = index
    spec.loader.exec_module(index)
    mock_table = MagicMock()
    mock_table.table_name = "test-table"

    mock_response = _mock_batch_get_response("test-table", [])

    mock_dynamodb_client = MagicMock()
    mock_dynamodb_client.batch_get_item.return_value = mock_response

    with patch("boto3.client", return_value=mock_dynamodb_client):
        test_run_id = "test-run-123"
        files = ["file1.pdf"]
        count = index._count_completed_documents(mock_table, test_run_id, files)
        assert count == 0


@pytest.mark.unit
def test_count_completed_documents_handles_exceptions():
    """Test counting gracefully handles exceptions"""
    import importlib.util
    import os
    import sys

    spec = importlib.util.spec_from_file_location(
        "index",
        os.path.join(
            os.path.dirname(__file__),
            "../../../../nested/api-resolvers/src/lambda/test_results_resolver/index.py",
        ),
    )
    index = importlib.util.module_from_spec(spec)
    sys.modules["index"] = index
    spec.loader.exec_module(index)
    mock_table = MagicMock()
    mock_table.table_name = "test-table"

    mock_dynamodb_client = MagicMock()
    mock_dynamodb_client.batch_get_item.side_effect = Exception("DynamoDB error")

    with patch("boto3.client", return_value=mock_dynamodb_client):
        test_run_id = "test-run-123"
        files = ["file1.pdf", "file2.pdf"]
        count = index._count_completed_documents(mock_table, test_run_id, files)
        # Should handle exception gracefully
        assert count == 0


@pytest.mark.unit
def test_count_completed_documents_uses_correct_sk():
    """Test that counting uses SK='none' not SK='status'"""
    import importlib.util
    import os
    import sys

    spec = importlib.util.spec_from_file_location(
        "index",
        os.path.join(
            os.path.dirname(__file__),
            "../../../../nested/api-resolvers/src/lambda/test_results_resolver/index.py",
        ),
    )
    index = importlib.util.module_from_spec(spec)
    sys.modules["index"] = index
    spec.loader.exec_module(index)
    mock_table = MagicMock()
    mock_table.table_name = "test-table"

    mock_response = _mock_batch_get_response(
        "test-table",
        [
            {
                "PK": {"S": "doc#test-run-123/file1.pdf"},
                "SK": {"S": "none"},
                "EvaluationStatus": {"S": "COMPLETED"},
            }
        ],
    )

    mock_dynamodb_client = MagicMock()
    mock_dynamodb_client.batch_get_item.return_value = mock_response

    with patch("boto3.client", return_value=mock_dynamodb_client):
        test_run_id = "test-run-123"
        files = ["file1.pdf"]
        index._count_completed_documents(mock_table, test_run_id, files)
        # Verify correct Key structure in batch_get_item call
        call_args = mock_dynamodb_client.batch_get_item.call_args
        request_items = call_args[1]["RequestItems"]["test-table"]
        keys = request_items["Keys"]
        assert keys[0]["PK"]["S"] == "doc#test-run-123/file1.pdf"
        assert keys[0]["SK"]["S"] == "none"  # Not "status"


@pytest.mark.unit
def test_count_completed_documents_case_insensitive():
    """Test that evaluation status comparison is case-insensitive"""
    import importlib.util
    import os
    import sys

    spec = importlib.util.spec_from_file_location(
        "index",
        os.path.join(
            os.path.dirname(__file__),
            "../../../../nested/api-resolvers/src/lambda/test_results_resolver/index.py",
        ),
    )
    index = importlib.util.module_from_spec(spec)
    sys.modules["index"] = index
    spec.loader.exec_module(index)
    mock_table = MagicMock()
    mock_table.table_name = "test-table"

    mock_response = _mock_batch_get_response(
        "test-table",
        [
            {
                "PK": {"S": "doc#test-run-123/file1.pdf"},
                "SK": {"S": "none"},
                "EvaluationStatus": {"S": "completed"},
            },  # lowercase
            {
                "PK": {"S": "doc#test-run-123/file2.pdf"},
                "SK": {"S": "none"},
                "EvaluationStatus": {"S": "COMPLETED"},
            },  # uppercase
        ],
    )

    mock_dynamodb_client = MagicMock()
    mock_dynamodb_client.batch_get_item.return_value = mock_response

    with patch("boto3.client", return_value=mock_dynamodb_client):
        test_run_id = "test-run-123"
        files = ["file1.pdf", "file2.pdf"]
        count = index._count_completed_documents(mock_table, test_run_id, files)
        # Both should be counted (case-insensitive)
        assert count == 2
