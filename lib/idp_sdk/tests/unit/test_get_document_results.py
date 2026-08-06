# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for BatchOperation.get_document_results (mocked).

Single-document result retrieval addressed by document id alone — no batch id.
Consumers such as post-processing hook subscribers only receive a document
reference (object key or s3:// output prefix), never a batch id.
"""

import json
from unittest.mock import Mock, patch

import pytest

from idp_sdk import IDPClient
from idp_sdk.operations.batch import BatchOperation

RESULT_JSON = {
    "document_class": {"type": "Borrowing Notice"},
    "inference_result": {
        "notice_number": "3",
        "amount": "1000.00",
        "metadata": {"ignored": True},
    },
    "explainability_info": [
        {"notice_number": {"confidence": 0.98}},
    ],
    "split_document": {"page_indices": [0, 1]},
}


@pytest.mark.unit
@pytest.mark.batch
class TestDocumentIdFromRef:
    """Normalization of document references to bare document ids."""

    def test_bare_id_passthrough(self):
        assert BatchOperation._document_id_from_ref(document_id="doc.pdf") == "doc.pdf"

    def test_s3_uri_with_trailing_slash(self):
        assert (
            BatchOperation._document_id_from_ref(
                document_id="s3://output-bucket/Borrowing_Notice_#3.pdf/"
            )
            == "Borrowing_Notice_#3.pdf"
        )

    def test_s3_uri_hash_in_key_not_truncated(self):
        # '#' must survive: urlparse-style parsing would truncate at the '#'.
        assert (
            BatchOperation._document_id_from_ref(
                document_id="s3://bucket/Report_#2.pdf"
            )
            == "Report_#2.pdf"
        )

    def test_s3_uri_without_key_raises(self):
        with pytest.raises(ValueError, match="Invalid document reference"):
            BatchOperation._document_id_from_ref(document_id="s3://bucket-only")


def _mock_stack(mock_processor_cls, mock_monitor_cls, mock_boto_client, status_data):
    """Wire the three mocked collaborators for get_document_results."""
    processor = Mock()
    processor.resources = {"OutputBucket": "output-bucket"}
    mock_processor_cls.return_value = processor

    monitor = Mock()
    monitor.get_batch_status.return_value = status_data
    mock_monitor_cls.return_value = monitor

    s3 = Mock()
    s3.get_object.return_value = {
        "Body": Mock(read=Mock(return_value=json.dumps(RESULT_JSON).encode()))
    }
    mock_boto_client.return_value = s3
    return s3


@pytest.mark.unit
@pytest.mark.batch
class TestGetDocumentResults:
    """Single-document retrieval through the public client API."""

    @patch("boto3.client")
    @patch("idp_sdk._core.progress_monitor.ProgressMonitor")
    @patch("idp_sdk._core.batch_processor.BatchProcessor")
    def test_completed_document_returns_fields(
        self, mock_processor_cls, mock_monitor_cls, mock_boto_client
    ):
        s3 = _mock_stack(
            mock_processor_cls,
            mock_monitor_cls,
            mock_boto_client,
            status_data={"completed": ["Borrowing_Notice_#3.pdf"]},
        )

        client = IDPClient(stack_name="test-stack")
        result = client.batch.get_document_results(
            document_id="s3://output-bucket/Borrowing_Notice_#3.pdf/"
        )

        assert result["document_id"] == "Borrowing_Notice_#3.pdf"
        assert result["status"] == "COMPLETED"
        assert result["document_class"] == "Borrowing Notice"
        assert result["fields"] == {"notice_number": "3", "amount": "1000.00"}
        assert result["confidence"] == {"notice_number": 0.98}
        assert result["page_count"] == 2

        # The results key must preserve '#' in the document id.
        s3.get_object.assert_called_once_with(
            Bucket="output-bucket",
            Key="Borrowing_Notice_#3.pdf/sections/1/result.json",
        )

    @patch("boto3.client")
    @patch("idp_sdk._core.progress_monitor.ProgressMonitor")
    @patch("idp_sdk._core.batch_processor.BatchProcessor")
    def test_running_document_has_status_only(
        self, mock_processor_cls, mock_monitor_cls, mock_boto_client
    ):
        s3 = _mock_stack(
            mock_processor_cls,
            mock_monitor_cls,
            mock_boto_client,
            status_data={"running": ["doc.pdf"]},
        )

        client = IDPClient(stack_name="test-stack")
        result = client.batch.get_document_results(document_id="doc.pdf")

        assert result["status"] == "RUNNING"
        assert result["fields"] is None
        # Results are only fetched for COMPLETED documents.
        s3.get_object.assert_not_called()
