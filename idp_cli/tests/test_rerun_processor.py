# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Tests for rerun processor module
"""

from unittest.mock import MagicMock, patch


class TestRerunProcessor:
    """Test rerun processing functionality"""

    @patch("idp_cli.stack_info.StackInfo")
    @patch("boto3.client")
    def test_init_success(self, mock_boto_client, mock_stack_info_class):
        """Test successful initialization"""
        from idp_cli.rerun_processor import RerunProcessor

        mock_stack_info = MagicMock()
        mock_stack_info.validate_stack.return_value = True
        mock_stack_info.get_resources.return_value = {
            "DocumentQueue": "https://sqs.us-east-1.amazonaws.com/123/queue",
            "InputBucket": "input-bucket",
            "OutputBucket": "output-bucket",
        }
        mock_stack_info_class.return_value = mock_stack_info

        processor = RerunProcessor("test-stack")

        assert processor.stack_name == "test-stack"
        assert processor.resources["DocumentQueue"] is not None

    @patch("idp_cli.stack_info.StackInfo")
    @patch("boto3.client")
    def test_prepare_for_classification_rerun(
        self, mock_boto_client, mock_stack_info_class
    ):
        """Test document preparation for classification rerun"""
        from idp_cli.rerun_processor import RerunProcessor
        from idp_common.models import Document, Page, Section, Status

        mock_stack_info = MagicMock()
        mock_stack_info.validate_stack.return_value = True
        mock_stack_info.get_resources.return_value = {
            "DocumentQueueUrl": "https://sqs.us-east-1.amazonaws.com/123/queue",
            "InputBucket": "input-bucket",
        }
        mock_stack_info_class.return_value = mock_stack_info

        processor = RerunProcessor("test-stack")

        # Create mock document with classifications and sections
        document = Document(
            id="test-doc",
            pages={
                "1": Page(page_id="1", classification="Invoice"),
                "2": Page(page_id="2", classification="Invoice"),
            },
            sections=[
                Section(
                    section_id="1",
                    classification="Invoice",
                    extraction_result_uri="s3://bucket/result.json",
                    page_ids=["1"],
                )
            ],
            status=Status.COMPLETED,
        )

        # Prepare for classification rerun
        result = processor._prepare_for_classification_rerun(document)

        # Verify page classifications cleared (may be None or empty string)
        assert result.pages["1"].classification in (None, "")
        assert result.pages["2"].classification in (None, "")

        # Verify sections modified (placeholder section created)
        # Note: Original had 1 section, should still have 1 (placeholder)
        assert len(result.sections) == 1
        # Placeholder section should have no page assignments
        assert len(result.sections[0].page_ids) == 0

        # Verify status reset
        assert result.status == Status.QUEUED
        assert result.start_time is None

    @patch("idp_cli.stack_info.StackInfo")
    @patch("boto3.client")
    def test_prepare_for_extraction_rerun(
        self, mock_boto_client, mock_stack_info_class
    ):
        """Test document preparation for extraction rerun"""
        from idp_cli.rerun_processor import RerunProcessor
        from idp_common.models import Document, Page, Section, Status

        mock_stack_info = MagicMock()
        mock_stack_info.validate_stack.return_value = True
        mock_stack_info.get_resources.return_value = {
            "DocumentQueueUrl": "https://sqs.us-east-1.amazonaws.com/123/queue",
            "InputBucket": "input-bucket",
        }
        mock_stack_info_class.return_value = mock_stack_info

        processor = RerunProcessor("test-stack")

        # Create mock document with extraction results
        document = Document(
            id="test-doc",
            pages={
                "1": Page(page_id="1", classification="Invoice"),
            },
            sections=[
                Section(
                    section_id="1",
                    classification="Invoice",
                    extraction_result_uri="s3://bucket/result.json",
                    attributes={"field1": "value1"},
                    confidence_threshold_alerts=["alert1"],
                    page_ids=["1"],
                )
            ],
            status=Status.COMPLETED,
        )

        # Prepare for extraction rerun
        result = processor._prepare_for_extraction_rerun(document)

        # Verify page classifications KEPT
        assert result.pages["1"].classification == "Invoice"

        # Verify sections structure KEPT
        assert len(result.sections) == 1
        assert result.sections[0].classification == "Invoice"

        # Verify extraction data CLEARED
        assert result.sections[0].extraction_result_uri is None
        assert result.sections[0].attributes is None
        assert len(result.sections[0].confidence_threshold_alerts) == 0

        # Verify status reset
        assert result.status == Status.QUEUED

    @patch("idp_cli.stack_info.StackInfo")
    @patch("boto3.client")
    def test_send_to_queue(self, mock_boto_client, mock_stack_info_class):
        """Test sending document to SQS queue"""
        from idp_cli.rerun_processor import RerunProcessor
        from idp_common.models import Document, Status

        mock_stack_info = MagicMock()
        mock_stack_info.validate_stack.return_value = True
        mock_stack_info.get_resources.return_value = {
            "DocumentQueueUrl": "https://sqs.us-east-1.amazonaws.com/123/queue",
            "InputBucket": "input-bucket",
        }
        mock_stack_info_class.return_value = mock_stack_info

        mock_sqs = MagicMock()
        mock_sqs.send_message.return_value = {"MessageId": "msg-123"}
        mock_boto_client.return_value = mock_sqs

        processor = RerunProcessor("test-stack")

        # Create mock document
        document = Document(id="test-doc", status=Status.QUEUED)

        # Send to queue
        processor._send_to_queue(document)

        # Verify SQS send_message was called
        mock_sqs.send_message.assert_called_once()
        call_args = mock_sqs.send_message.call_args
        assert (
            call_args[1]["QueueUrl"] == "https://sqs.us-east-1.amazonaws.com/123/queue"
        )
        assert "test-doc" in call_args[1]["MessageBody"]

    @patch("idp_cli.stack_info.StackInfo")
    @patch("idp_cli.rerun_processor.RerunProcessor._get_document")
    @patch("idp_cli.rerun_processor.RerunProcessor._send_to_queue")
    @patch("boto3.client")
    def test_rerun_documents_classification(
        self,
        mock_boto_client,
        mock_send_to_queue,
        mock_get_document,
        mock_stack_info_class,
    ):
        """Test rerun documents for classification"""
        from idp_cli.rerun_processor import RerunProcessor

        mock_stack_info = MagicMock()
        mock_stack_info.validate_stack.return_value = True
        mock_stack_info.get_resources.return_value = {
            "DocumentQueueUrl": "https://sqs.us-east-1.amazonaws.com/123/queue",
        }
        mock_stack_info_class.return_value = mock_stack_info

        # Mock document retrieval
        from idp_common.models import Document, Page, Section, Status

        mock_document = Document(
            id="doc1",
            pages={"1": Page(page_id="1", classification="Invoice")},
            sections=[
                Section(section_id="1", classification="Invoice", page_ids=["1"])
            ],
            status=Status.COMPLETED,
        )
        mock_get_document.return_value = mock_document

        processor = RerunProcessor("test-stack")

        # Rerun classification
        results = processor.rerun_documents(
            document_ids=["doc1"], step="classification", monitor=False
        )

        # Verify results
        assert results["documents_queued"] == 1
        assert results["documents_failed"] == 0
        assert results["step"] == "classification"

        # Verify send_to_queue was called
        mock_send_to_queue.assert_called_once()

    @patch("idp_cli.stack_info.StackInfo")
    @patch("idp_cli.rerun_processor.RerunProcessor._get_document")
    @patch("boto3.client")
    def test_rerun_documents_document_not_found(
        self, mock_boto_client, mock_get_document, mock_stack_info_class
    ):
        """Test rerun when document not found"""
        from idp_cli.rerun_processor import RerunProcessor

        mock_stack_info = MagicMock()
        mock_stack_info.validate_stack.return_value = True
        mock_stack_info.get_resources.return_value = {
            "DocumentQueueUrl": "https://sqs.us-east-1.amazonaws.com/123/queue",
        }
        mock_stack_info_class.return_value = mock_stack_info

        # Mock document not found
        mock_get_document.return_value = None

        processor = RerunProcessor("test-stack")

        # Rerun should handle gracefully
        results = processor.rerun_documents(
            document_ids=["missing-doc"], step="classification", monitor=False
        )

        # Verify failure tracked
        assert results["documents_queued"] == 0
        assert results["documents_failed"] == 1
        assert len(results["failed_documents"]) == 1
        assert results["failed_documents"][0]["object_key"] == "missing-doc"

    @patch("idp_cli.stack_info.StackInfo")
    @patch("idp_cli.batch_processor.BatchProcessor")
    @patch("boto3.client")
    def test_get_batch_document_ids(
        self, mock_boto_client, mock_batch_processor_class, mock_stack_info_class
    ):
        """Test getting document IDs from batch"""
        from idp_cli.rerun_processor import RerunProcessor

        mock_stack_info = MagicMock()
        mock_stack_info.validate_stack.return_value = True
        mock_stack_info.get_resources.return_value = {}
        mock_stack_info_class.return_value = mock_stack_info

        # Mock batch processor
        mock_processor = MagicMock()
        mock_processor.get_batch_info.return_value = {
            "batch_id": "test-batch",
            "document_ids": ["doc1", "doc2", "doc3"],
        }
        mock_batch_processor_class.return_value = mock_processor

        processor = RerunProcessor("test-stack")

        # Get batch document IDs
        doc_ids = processor.get_batch_document_ids("test-batch")

        # Verify results
        assert len(doc_ids) == 3
        assert "doc1" in doc_ids
        assert "doc2" in doc_ids
        assert "doc3" in doc_ids
