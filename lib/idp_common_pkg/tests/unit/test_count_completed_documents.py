# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Unit tests for _count_completed_documents function in test_results_resolver
"""
from unittest.mock import MagicMock
import pytest
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
            "../../../../nested/appsync/src/lambda/test_results_resolver/index.py",
        ),
    )
    index = importlib.util.module_from_spec(spec)
    sys.modules["index"] = index
    spec.loader.exec_module(index)
    mock_table = MagicMock()
    mock_table.get_item.return_value = {
        "Item": {"EvaluationStatus": "COMPLETED", "ObjectStatus": "COMPLETED"}
    }
    test_run_id = "test-run-123"
    files = ["file1.pdf", "file2.pdf", "file3.pdf"]
    count = index._count_completed_documents(mock_table, test_run_id, files)
    assert count == 3
    assert mock_table.get_item.call_count == 3
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
            "../../../../nested/appsync/src/lambda/test_results_resolver/index.py",
        ),
    )
    index = importlib.util.module_from_spec(spec)
    sys.modules["index"] = index
    spec.loader.exec_module(index)
    mock_table = MagicMock()
    def mock_get_item(Key):
        object_key = Key["PK"].replace("doc#", "")
        if "file1" in object_key or "file2" in object_key:
            return {
                "Item": {"EvaluationStatus": "COMPLETED", "ObjectStatus": "COMPLETED"}
            }
        else:
            return {"Item": {"EvaluationStatus": None, "ObjectStatus": "ABORTED"}}
    mock_table.get_item.side_effect = mock_get_item
    test_run_id = "test-run-123"
    files = ["file1.pdf", "file2.pdf", "file3.pdf"]
    count = index._count_completed_documents(mock_table, test_run_id, files)
    assert count == 2
    assert mock_table.get_item.call_count == 3
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
            "../../../../nested/appsync/src/lambda/test_results_resolver/index.py",
        ),
    )
    index = importlib.util.module_from_spec(spec)
    sys.modules["index"] = index
    spec.loader.exec_module(index)
    mock_table = MagicMock()
    mock_table.get_item.return_value = {
        "Item": {"EvaluationStatus": None, "ObjectStatus": "ABORTED"}
    }
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
            "../../../../nested/appsync/src/lambda/test_results_resolver/index.py",
        ),
    )
    index = importlib.util.module_from_spec(spec)
    sys.modules["index"] = index
    spec.loader.exec_module(index)
    mock_table = MagicMock()
    mock_table.get_item.return_value = {
        "Item": {
            "ObjectStatus": "COMPLETED"
            # EvaluationStatus field missing
        }
    }
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
            "../../../../nested/appsync/src/lambda/test_results_resolver/index.py",
        ),
    )
    index = importlib.util.module_from_spec(spec)
    sys.modules["index"] = index
    spec.loader.exec_module(index)
    mock_table = MagicMock()
    mock_table.get_item.return_value = {}  # Document not found
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
            "../../../../nested/appsync/src/lambda/test_results_resolver/index.py",
        ),
    )
    index = importlib.util.module_from_spec(spec)
    sys.modules["index"] = index
    spec.loader.exec_module(index)
    mock_table = MagicMock()
    def mock_get_item(Key):
        object_key = Key["PK"].replace("doc#", "")
        if "file1" in object_key:
            return {
                "Item": {"EvaluationStatus": "COMPLETED", "ObjectStatus": "COMPLETED"}
            }
        else:
            raise Exception("DynamoDB error")
    mock_table.get_item.side_effect = mock_get_item
    test_run_id = "test-run-123"
    files = ["file1.pdf", "file2.pdf"]
    count = index._count_completed_documents(mock_table, test_run_id, files)
    # Should still count file1, skip file2 due to exception
    assert count == 1
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
            "../../../../nested/appsync/src/lambda/test_results_resolver/index.py",
        ),
    )
    index = importlib.util.module_from_spec(spec)
    sys.modules["index"] = index
    spec.loader.exec_module(index)
    mock_table = MagicMock()
    mock_table.get_item.return_value = {
        "Item": {"EvaluationStatus": "COMPLETED", "ObjectStatus": "COMPLETED"}
    }
    test_run_id = "test-run-123"
    files = ["file1.pdf"]
    index._count_completed_documents(mock_table, test_run_id, files)
    # Verify correct Key structure
    call_args = mock_table.get_item.call_args
    key = call_args[1]["Key"]
    assert key["PK"] == "doc#test-run-123/file1.pdf"
    assert key["SK"] == "none"  # Not "status"
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
            "../../../../nested/appsync/src/lambda/test_results_resolver/index.py",
        ),
    )
    index = importlib.util.module_from_spec(spec)
    sys.modules["index"] = index
    spec.loader.exec_module(index)
    mock_table = MagicMock()
    def mock_get_item(Key):
        object_key = Key["PK"].replace("doc#", "")
        # Return lowercase status
        if "file1" in object_key:
            return {"Item": {"EvaluationStatus": "completed"}}  # lowercase
        else:
            return {"Item": {"EvaluationStatus": "COMPLETED"}}  # uppercase
    mock_table.get_item.side_effect = mock_get_item
    test_run_id = "test-run-123"
    files = ["file1.pdf", "file2.pdf"]
    count = index._count_completed_documents(mock_table, test_run_id, files)
    # Both should be counted (case-insensitive)
    assert count == 2
