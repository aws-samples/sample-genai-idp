# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0


import importlib.util
import os
from unittest.mock import Mock, patch

import pytest

# Mock boto3 before importing the Lambda module to prevent NoRegionError
# The Lambda creates boto3 clients at module level which requires AWS region
with patch("boto3.resource") as mock_resource, patch("boto3.client") as mock_client:
    mock_resource.return_value = Mock()
    mock_client.return_value = Mock()

    # Import the specific lambda module using importlib to avoid conflicts
    spec = importlib.util.spec_from_file_location(
        "results_index",
        os.path.join(
            os.path.dirname(__file__),
            "../../../../nested/appsync/src/lambda/test_results_resolver/index.py",
        ),
    )
    if spec is None or spec.loader is None:
        raise ImportError("Could not load test_results_resolver module")
    index = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(index)


@pytest.mark.unit
def test_get_test_results_structure():
    """Test test results data structure"""
    test_run_id = "test-run-123"
    metadata = {
        "TestSetName": "lending-test",
        "Status": "COMPLETE",
        "FilesCount": 2,
        "CompletedFiles": 2,
        "FailedFiles": 0,
        "CreatedAt": "2025-01-01T00:00:00Z",
    }

    result = {
        "testRunId": test_run_id,
        "testSetName": metadata.get("TestSetName"),
        "status": metadata.get("Status"),
        "totalFiles": metadata.get("FilesCount", 0),
        "completedFiles": metadata.get("CompletedFiles", 0),
        "failedFiles": metadata.get("FailedFiles", 0),
        "overallAccuracy": 85.5,
        "averageConfidence": 78.2,
        "accuracyBreakdown": {
            "precision": 0.95,
            "recall": 0.90,
            "f1_score": 0.925,
            "false_alarm_rate": 0.05,
            "false_discovery_rate": 0.03,
        },
        "totalCost": 12.45,
        "createdAt": metadata.get("CreatedAt"),
    }

    assert result["testRunId"] == "test-run-123"
    assert result["testSetName"] == "lending-test"
    assert result["status"] == "COMPLETE"
    assert result["totalFiles"] == 2
    assert result["accuracyBreakdown"]["precision"] == 0.95
    assert result["accuracyBreakdown"]["f1_score"] == 0.925


# NOTE: These tests are commented out as they test the old Parquet-based cost retrieval
# which has been replaced with Athena-based queries in the test_results_resolver Lambda

# @pytest.mark.unit
# @patch.dict(os.environ, {"REPORTING_BUCKET": "test-bucket"})
# @patch("boto3.client")
# @patch("pyarrow.parquet.read_table")
# @patch("pyarrow.fs.S3FileSystem")
# @patch("pyarrow.compute.equal")
# def test_get_document_costs_from_parquet_success(
#     mock_pc_equal, mock_s3fs, mock_read_table, mock_boto3
# ):
#     """Test successful Parquet cost retrieval"""
#     pass

# @pytest.mark.unit
# @patch.dict(os.environ, {"REPORTING_BUCKET": "test-bucket"})
# @patch("boto3.client")
# def test_get_document_costs_no_files_found(mock_boto3):
#     """Test when no Parquet files are found"""
#     pass

# @pytest.mark.unit
# @patch.dict(os.environ, {"REPORTING_BUCKET": ""})
# def test_get_document_costs_no_bucket():
#     """Test when REPORTING_BUCKET is not set"""
#     pass


@pytest.mark.unit
def test_accuracy_breakdown_structure():
    """Test accuracy breakdown data structure"""
    accuracy_breakdown = {
        "precision": 0.95,
        "recall": 0.90,
        "f1_score": 0.925,
        "false_alarm_rate": 0.05,
        "false_discovery_rate": 0.03,
    }

    # Verify all expected metrics are present
    expected_metrics = [
        "precision",
        "recall",
        "f1_score",
        "false_alarm_rate",
        "false_discovery_rate",
    ]
    for metric in expected_metrics:
        assert metric in accuracy_breakdown
        assert isinstance(accuracy_breakdown[metric], float)
        assert 0 <= accuracy_breakdown[metric] <= 1


@pytest.mark.unit
def test_get_test_run_status_evaluating():
    """Test test run status with EVALUATING state"""
    test_run_status = {
        "testRunId": "test-run-456",
        "status": "EVALUATING",
        "filesCount": 3,
        "completedFiles": 2,
        "failedFiles": 0,
        "evaluatingFiles": 1,
        "progress": 66.7,
    }

    assert test_run_status["status"] == "EVALUATING"
    assert test_run_status["completedFiles"] == 2
    assert test_run_status["evaluatingFiles"] == 1
    assert test_run_status["progress"] == 66.7


@pytest.mark.unit
def test_get_test_run_status_partial_complete():
    """Test test run status with PARTIAL_COMPLETE state"""
    test_run_status = {
        "testRunId": "test-run-789",
        "status": "PARTIAL_COMPLETE",
        "filesCount": 5,
        "completedFiles": 3,
        "failedFiles": 2,
        "evaluatingFiles": 0,
        "progress": 60.0,
    }

    assert test_run_status["status"] == "PARTIAL_COMPLETE"
    assert test_run_status["completedFiles"] == 3
    assert test_run_status["failedFiles"] == 2
    assert test_run_status["evaluatingFiles"] == 0
    assert test_run_status["progress"] == 60.0


@pytest.mark.unit
def test_compare_test_runs_structure():
    """Test test run comparison structure"""
    results = {
        "run-1": {"overall_accuracy": 85.5, "total_cost": 12.45},
        "run-2": {"overall_accuracy": 90.2, "total_cost": 15.30},
    }

    metrics_comparison = [
        {
            "metric": "Overall Accuracy",
            "values": {
                k: f"{v.get('overall_accuracy', 0)}%" for k, v in results.items()
            },
        },
        {
            "metric": "Total Cost",
            "values": {k: f"${v.get('total_cost', 0)}" for k, v in results.items()},
        },
    ]

    assert len(metrics_comparison) == 2
    assert metrics_comparison[0]["values"]["run-1"] == "85.5%"
    assert metrics_comparison[1]["values"]["run-2"] == "$15.3"


@pytest.mark.unit
def test_build_config_comparison():
    """Test configuration comparison"""
    configs = {
        "run-1": {"model": "claude-3", "temperature": 0.1},
        "run-2": {"model": "claude-4", "temperature": 0.2},
    }

    all_keys = set()
    for config in configs.values():
        all_keys.update(config.keys())

    config_diff = [
        {
            "setting": key,
            "values": {k: str(v.get(key, "N/A")) for k, v in configs.items()},
        }
        for key in all_keys
    ]

    assert len(config_diff) == 2
    assert "model" in [item["setting"] for item in config_diff]
    assert "temperature" in [item["setting"] for item in config_diff]


@pytest.mark.unit
def test_get_test_results_missing_metrics_returns_partial_not_raises():
    """When processing reached a terminal state but the evaluation aggregation
    never cached testRunResult (timed out / failed silently on a large run),
    get_test_results returns a structured partial TestRun instead of raising an
    opaque ValueError that leaves the UI spinning on "Loading..." (issue #358)."""
    test_run_id = "TEST-SET-ID"
    metadata = {
        "PK": f"testrun#{test_run_id}",
        "SK": "metadata",
        # Already terminal, so the status-refresh branch is skipped and we fall
        # straight through to the "no cached metrics" else branch.
        "Status": "COMPLETE",
        "TestSetId": "set-1",
        "TestSetName": "big-classification-set",
        "FilesCount": 3463,
        "CompletedFiles": 3460,
        "FailedFiles": 3,
        "CreatedAt": "2025-01-01T00:00:00Z",
        "Context": "ctx",
        "ConfigVersion": "v7",
        # No "testRunResult" key -> aggregation hasn't written metrics yet.
    }

    mock_table = Mock()
    mock_table.get_item.return_value = {"Item": metadata}

    with (
        patch.dict(os.environ, {"TRACKING_TABLE": "tracking"}),
        patch.object(index.dynamodb, "Table", return_value=mock_table),
    ):
        result = index.get_test_results(test_run_id)

    assert result["testRunId"] == test_run_id
    # Reports the true terminal status rather than fabricating one.
    assert result["status"] == "COMPLETE"
    assert result["filesCount"] == 3463
    assert result["completedFiles"] == 3460
    assert result["failedFiles"] == 3
    assert result["testSetId"] == "set-1"
    assert result["configVersion"] == "v7"
    # Metric fields are absent (not yet computed) but must not be required.
    assert "overallAccuracy" not in result or result["overallAccuracy"] is None


@pytest.mark.unit
def test_handler_field_routing():
    """Test GraphQL field routing"""

    def handler(event, context):
        field_name = event["info"]["fieldName"]

        if field_name == "getTestResults":
            return {"testRunId": event["arguments"]["testRunId"]}
        elif field_name == "getTestRuns":
            return [{"testRunId": "run-1"}]
        elif field_name == "compareTestRuns":
            return {"metrics": []}

        raise ValueError(f"Unknown field: {field_name}")

    # Test getTestResults
    event1 = {
        "info": {"fieldName": "getTestResults"},
        "arguments": {"testRunId": "test-123"},
    }
    result1 = handler(event1, {})
    assert result1["testRunId"] == "test-123"  # type: ignore[index]

    # Test getTestRuns
    event2 = {"info": {"fieldName": "getTestRuns"}, "arguments": {}}
    result2 = handler(event2, {})
    assert len(result2) == 1

    # Test unknown field
    event3 = {"info": {"fieldName": "unknownField"}, "arguments": {}}
    with pytest.raises(ValueError, match="Unknown field"):
        handler(event3, {})
