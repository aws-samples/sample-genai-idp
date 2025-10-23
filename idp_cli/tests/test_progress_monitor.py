# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Tests for progress monitor module
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from idp_cli.progress_monitor import ProgressMonitor


class TestProgressMonitor:
    """Test progress monitoring functionality"""

    @patch("boto3.client")
    def test_init_success(self, mock_boto_client):
        """Test successful initialization"""
        resources = {
            "LookupFunctionName": "test-lookup-function",
            "InputBucket": "input-bucket",
        }

        monitor = ProgressMonitor("test-stack", resources)

        assert monitor.stack_name == "test-stack"
        assert monitor.lookup_function == "test-lookup-function"

    def test_init_missing_lookup_function(self):
        """Test initialization fails without LookupFunctionName"""
        resources = {}

        with pytest.raises(ValueError, match="LookupFunctionName not found"):
            ProgressMonitor("test-stack", resources)

    @patch("boto3.client")
    def test_get_document_status_completed(self, mock_boto_client):
        """Test getting status of completed document"""
        mock_lambda = MagicMock()
        mock_boto_client.return_value = mock_lambda

        # Mock Lambda response
        lookup_result = {
            "status": "COMPLETED",
            "WorkflowExecutionArn": "arn:aws:states:us-east-1:123456789012:execution:test",
            "StartTime": "2025-01-10T10:00:00Z",
            "EndTime": "2025-01-10T10:05:00Z",
            "Duration": 300,
            "NumSections": 3,
        }

        mock_lambda.invoke.return_value = {
            "Payload": MagicMock(read=lambda: json.dumps(lookup_result).encode())
        }

        resources = {"LookupFunctionName": "test-function"}
        monitor = ProgressMonitor("test-stack", resources)

        status = monitor.get_document_status("doc1")

        assert status["status"] == "COMPLETED"
        assert status["document_id"] == "doc1"
        assert status["duration"] == 300
        assert status["num_sections"] == 3

    @patch("boto3.client")
    def test_get_document_status_running(self, mock_boto_client):
        """Test getting status of running document"""
        mock_lambda = MagicMock()
        mock_boto_client.return_value = mock_lambda

        lookup_result = {
            "status": "RUNNING",
            "CurrentStep": "Extraction",
            "StartTime": "2025-01-10T10:00:00Z",
        }

        mock_lambda.invoke.return_value = {
            "Payload": MagicMock(read=lambda: json.dumps(lookup_result).encode())
        }

        resources = {"LookupFunctionName": "test-function"}
        monitor = ProgressMonitor("test-stack", resources)

        status = monitor.get_document_status("doc1")

        assert status["status"] == "RUNNING"
        assert status["current_step"] == "Extraction"

    @patch("boto3.client")
    def test_get_document_status_failed(self, mock_boto_client):
        """Test getting status of failed document"""
        mock_lambda = MagicMock()
        mock_boto_client.return_value = mock_lambda

        lookup_result = {
            "status": "FAILED",
            "Error": "Classification timeout",
            "FailedStep": "Classification",
        }

        mock_lambda.invoke.return_value = {
            "Payload": MagicMock(read=lambda: json.dumps(lookup_result).encode())
        }

        resources = {"LookupFunctionName": "test-function"}
        monitor = ProgressMonitor("test-stack", resources)

        status = monitor.get_document_status("doc1")

        assert status["status"] == "FAILED"
        assert status["error"] == "Classification timeout"
        assert status["failed_step"] == "Classification"

    @patch("boto3.client")
    def test_get_batch_status(self, mock_boto_client):
        """Test getting batch status"""
        mock_lambda = MagicMock()
        mock_boto_client.return_value = mock_lambda

        # Mock different document statuses
        def mock_invoke(FunctionName, InvocationType, Payload):
            payload_data = json.loads(Payload)
            doc_id = payload_data["object_key"]

            if doc_id == "doc1":
                result = {"status": "COMPLETED", "Duration": 100}
            elif doc_id == "doc2":
                result = {"status": "RUNNING", "CurrentStep": "Extraction"}
            elif doc_id == "doc3":
                result = {"status": "FAILED", "Error": "Test error"}
            else:
                result = {"status": "QUEUED"}

            return {"Payload": MagicMock(read=lambda: json.dumps(result).encode())}

        mock_lambda.invoke.side_effect = mock_invoke

        resources = {"LookupFunctionName": "test-function"}
        monitor = ProgressMonitor("test-stack", resources)

        status_data = monitor.get_batch_status(["doc1", "doc2", "doc3", "doc4"])

        assert len(status_data["completed"]) == 1
        assert len(status_data["running"]) == 1
        assert len(status_data["failed"]) == 1
        assert len(status_data["queued"]) == 1
        assert status_data["total"] == 4
        assert status_data["all_complete"] is False

    @patch("boto3.client")
    def test_get_batch_status_all_complete(self, mock_boto_client):
        """Test batch status when all documents are complete"""
        mock_lambda = MagicMock()
        mock_boto_client.return_value = mock_lambda

        def mock_invoke(FunctionName, InvocationType, Payload):
            # Return batch query response
            return {
                "Payload": MagicMock(
                    read=lambda: json.dumps(
                        {
                            "results": [
                                {
                                    "object_key": "doc1",
                                    "status": "COMPLETED",
                                    "timing": {"elapsed": {"total": 100000}},
                                },
                                {
                                    "object_key": "doc2",
                                    "status": "COMPLETED",
                                    "timing": {"elapsed": {"total": 200000}},
                                },
                            ]
                        }
                    ).encode()
                )
            }

        mock_lambda.invoke.side_effect = mock_invoke

        resources = {"LookupFunctionName": "test-function"}
        monitor = ProgressMonitor("test-stack", resources)

        status_data = monitor.get_batch_status(["doc1", "doc2"])

        assert len(status_data["completed"]) == 2
        assert status_data["all_complete"] is True

    @patch("boto3.client")
    def test_calculate_statistics(self, mock_boto_client):
        """Test statistics calculation"""
        resources = {"LookupFunctionName": "test-function"}
        monitor = ProgressMonitor("test-stack", resources)

        status_data = {
            "total": 10,
            "completed": [{"duration": 100}, {"duration": 200}, {"duration": 300}],
            "running": [{}],
            "queued": [{}] * 4,
            "failed": [{}] * 2,
            "all_complete": False,
        }

        stats = monitor.calculate_statistics(status_data)

        assert stats["total"] == 10
        assert stats["completed"] == 3
        assert stats["failed"] == 2
        assert stats["running"] == 1
        assert stats["queued"] == 4
        assert stats["completion_percentage"] == 50.0  # (3 + 2) / 10 * 100
        assert stats["success_rate"] == 60.0  # 3 / (3 + 2) * 100
        assert stats["avg_duration_seconds"] == 200.0  # (100 + 200 + 300) / 3

    @patch("boto3.client")
    def test_get_recent_completions(self, mock_boto_client):
        """Test getting recent completions"""
        resources = {"LookupFunctionName": "test-function"}
        monitor = ProgressMonitor("test-stack", resources)

        status_data = {
            "completed": [
                {"document_id": "doc1", "end_time": "2025-01-10T10:00:00Z"},
                {"document_id": "doc2", "end_time": "2025-01-10T10:05:00Z"},
                {"document_id": "doc3", "end_time": "2025-01-10T10:03:00Z"},
            ]
        }

        recent = monitor.get_recent_completions(status_data, limit=2)

        # Should return 2 most recent (sorted by end_time)
        assert len(recent) == 2
        assert recent[0]["document_id"] == "doc2"  # Most recent
        assert recent[1]["document_id"] == "doc3"

    @patch("boto3.client")
    def test_get_failed_documents(self, mock_boto_client):
        """Test getting failed documents"""
        resources = {"LookupFunctionName": "test-function"}
        monitor = ProgressMonitor("test-stack", resources)

        status_data = {
            "failed": [
                {"document_id": "doc1", "error": "Timeout", "failed_step": "OCR"},
                {
                    "document_id": "doc2",
                    "error": "Invalid format",
                    "failed_step": "Classification",
                },
            ]
        }

        failed = monitor.get_failed_documents(status_data)

        assert len(failed) == 2
        assert failed[0]["document_id"] == "doc1"
        assert failed[0]["error"] == "Timeout"
        assert failed[1]["document_id"] == "doc2"
