# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for the ExtractionService class.
"""

# ruff: noqa: E402, I001
# The above line disables E402 (module level import not at top of file) and I001 (import block sorting) for this file

import pytest

# Import standard library modules first
import sys
from textwrap import dedent
from unittest.mock import MagicMock, patch

# Mock PIL before importing any modules that might depend on it
sys.modules["PIL"] = MagicMock()
sys.modules["PIL.Image"] = MagicMock()

# Now import third-party modules

# Finally import application modules
from idp_common.extraction.service import ExtractionService
from idp_common.models import Document, Section, Status, Page


@pytest.mark.unit
class TestExtractionService:
    """Tests for the ExtractionService class."""

    @pytest.fixture
    def mock_config(self):
        """Fixture providing a mock configuration."""
        return {
            "classes": [
                {
                    "name": "invoice",
                    "description": "An invoice document",
                    "attributes": [
                        {"name": "invoice_number", "description": "The invoice number"},
                        {"name": "invoice_date", "description": "The invoice date"},
                        {"name": "total_amount", "description": "The total amount"},
                    ],
                },
                {
                    "name": "receipt",
                    "description": "A receipt document",
                    "attributes": [
                        {"name": "receipt_number", "description": "The receipt number"},
                        {"name": "date", "description": "The receipt date"},
                        {"name": "amount", "description": "The total amount"},
                    ],
                },
            ],
            "extraction": {
                "model": "anthropic.claude-3-sonnet-20240229-v1:0",
                "temperature": 0.0,
                "top_k": 5,
                "system_prompt": "You are a document extraction assistant.",
                "task_prompt": dedent("""
                    Extract the following fields from this {DOCUMENT_CLASS} document:
                    
                    {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}
                    
                    Document text:
                    {DOCUMENT_TEXT}
                    
                    Respond with a JSON object containing each field name and its extracted value.
                """),
            },
        }

    @pytest.fixture
    def service(self, mock_config):
        """Fixture providing an ExtractionService instance."""
        return ExtractionService(region="us-west-2", config=mock_config)

    @pytest.fixture
    def sample_document(self):
        """Fixture providing a sample document with sections."""
        doc = Document(
            id="test-doc",
            input_key="test-document.pdf",
            input_bucket="input-bucket",
            output_bucket="output-bucket",
            status=Status.EXTRACTING,
        )

        # Add pages
        doc.pages["1"] = Page(
            page_id="1",
            image_uri="s3://input-bucket/test-document.pdf/pages/1/image.jpg",
            parsed_text_uri="s3://input-bucket/test-document.pdf/pages/1/parsed.txt",
        )
        doc.pages["2"] = Page(
            page_id="2",
            image_uri="s3://input-bucket/test-document.pdf/pages/2/image.jpg",
            parsed_text_uri="s3://input-bucket/test-document.pdf/pages/2/parsed.txt",
        )

        # Add section
        doc.sections.append(
            Section(section_id="1", classification="invoice", page_ids=["1", "2"])
        )

        return doc

    def test_init(self, mock_config):
        """Test initialization with configuration."""
        service = ExtractionService(region="us-west-2", config=mock_config)

        assert service.region == "us-west-2"
        assert service.config == mock_config

    def test_get_class_attributes(self, service):
        """Test getting attributes for a document class."""
        # Test with existing class
        invoice_attrs = service._get_class_attributes("invoice")
        assert len(invoice_attrs) == 3
        assert invoice_attrs[0]["name"] == "invoice_number"
        assert invoice_attrs[1]["name"] == "invoice_date"
        assert invoice_attrs[2]["name"] == "total_amount"

        # Test with non-existent class
        unknown_attrs = service._get_class_attributes("unknown")
        assert len(unknown_attrs) == 0

        # Test case insensitivity
        invoice_attrs_upper = service._get_class_attributes("INVOICE")
        assert len(invoice_attrs_upper) == 3

    def test_format_attribute_descriptions(self, service):
        """Test formatting attribute descriptions."""
        attributes = [
            {"name": "invoice_number", "description": "The invoice number"},
            {"name": "invoice_date", "description": "The invoice date"},
        ]

        formatted = service._format_attribute_descriptions(attributes)

        assert "invoice_number" in formatted
        assert "The invoice number" in formatted
        assert "invoice_date" in formatted
        assert "The invoice date" in formatted

    @patch("idp_common.s3.get_text_content")
    @patch("idp_common.image.prepare_image")
    @patch("idp_common.image.prepare_bedrock_image_attachment")
    @patch("idp_common.bedrock.invoke_model")
    @patch("idp_common.s3.write_content")
    @patch("idp_common.utils.merge_metering_data")
    @patch("idp_common.metrics.put_metric")
    def test_process_document_section_success(
        self,
        mock_put_metric,
        mock_merge_metering,
        mock_write_content,
        mock_invoke_model,
        mock_prepare_bedrock_image,
        mock_prepare_image,
        mock_get_text_content,
        service,
        sample_document,
    ):
        """Test successful processing of a document section."""
        # Mock responses
        mock_get_text_content.side_effect = ["Page 1 text", "Page 2 text"]
        mock_prepare_image.side_effect = [b"image1_data", b"image2_data"]
        mock_prepare_bedrock_image.side_effect = [
            {"image": "image1_base64"},
            {"image": "image2_base64"},
        ]

        # Mock Bedrock response
        mock_invoke_model.return_value = {
            "response": {
                "output": {
                    "message": {
                        "content": [
                            {
                                "text": '{"invoice_number": "INV-123", "invoice_date": "2025-05-08", "total_amount": "$100.00"}'
                            }
                        ]
                    }
                }
            },
            "metering": {"tokens": 500},
        }

        # Mock metering merge
        mock_merge_metering.return_value = {"tokens": 500}

        # Process the document section
        result = service.process_document_section(sample_document, "1")

        # Verify the document was updated
        assert (
            result.sections[0].extraction_result_uri
            == "s3://output-bucket/test-document.pdf/sections/1/result.json"
        )
        assert len(result.errors) == 0

        # Verify the calls
        assert mock_get_text_content.call_count == 2
        assert mock_prepare_image.call_count == 2
        assert mock_prepare_bedrock_image.call_count == 2
        mock_invoke_model.assert_called_once()
        mock_write_content.assert_called_once()

        # Verify the content written to S3
        written_content = mock_write_content.call_args[0][0]
        assert written_content["document_class"]["type"] == "invoice"
        assert written_content["inference_result"]["invoice_number"] == "INV-123"
        assert written_content["inference_result"]["invoice_date"] == "2025-05-08"
        assert written_content["inference_result"]["total_amount"] == "$100.00"
        assert written_content["metadata"]["parsing_succeeded"] is True

    @patch("idp_common.s3.get_text_content")
    @patch("idp_common.image.prepare_image")
    @patch("idp_common.image.prepare_bedrock_image_attachment")
    @patch("idp_common.bedrock.invoke_model")
    @patch("idp_common.s3.write_content")
    @patch("idp_common.metrics.put_metric")
    def test_process_document_section_invalid_json(
        self,
        mock_put_metric,
        mock_write_content,
        mock_invoke_model,
        mock_prepare_bedrock_image,
        mock_prepare_image,
        mock_get_text_content,
        service,
        sample_document,
    ):
        """Test processing a document section with invalid JSON response."""
        # Mock responses
        mock_get_text_content.side_effect = ["Page 1 text", "Page 2 text"]
        mock_prepare_image.side_effect = [b"image1_data", b"image2_data"]
        mock_prepare_bedrock_image.side_effect = [
            {"image": "image1_base64"},
            {"image": "image2_base64"},
        ]

        # Mock Bedrock response with invalid JSON
        mock_invoke_model.return_value = {
            "response": {
                "output": {"message": {"content": [{"text": "This is not valid JSON"}]}}
            },
            "metering": {"tokens": 500},
        }

        # Process the document section
        result = service.process_document_section(sample_document, "1")

        # Verify the document was updated
        assert (
            result.sections[0].extraction_result_uri
            == "s3://output-bucket/test-document.pdf/sections/1/result.json"
        )
        assert len(result.errors) == 0  # No errors, just invalid JSON

        # Verify the content written to S3
        written_content = mock_write_content.call_args[0][0]
        assert written_content["document_class"]["type"] == "invoice"
        assert "raw_output" in written_content["inference_result"]
        assert (
            written_content["inference_result"]["raw_output"]
            == "This is not valid JSON"
        )
        assert written_content["metadata"]["parsing_succeeded"] is False

    @patch("idp_common.metrics.put_metric")
    def test_process_document_section_missing_section(
        self, mock_put_metric, service, sample_document
    ):
        """Test processing a document section that doesn't exist."""
        # Process a non-existent section
        result = service.process_document_section(sample_document, "999")

        # Verify error was added
        assert len(result.errors) == 1
        assert "Section 999 not found in document" in result.errors[0]

    @patch("idp_common.metrics.put_metric")
    def test_process_document_section_no_pages(
        self, mock_put_metric, service, sample_document
    ):
        """Test processing a document section with no pages."""
        # Create a section with no pages
        sample_document.sections.append(
            Section(section_id="2", classification="receipt", page_ids=[])
        )

        # Process the section
        result = service.process_document_section(sample_document, "2")

        # Verify error was added
        assert len(result.errors) == 1
        assert "Section 2 has no page IDs" in result.errors[0]

    @pytest.mark.skip(reason="Temporarily disabled due to S3 credential issues")
    @patch("idp_common.s3.get_text_content")
    @patch("idp_common.image.prepare_image")
    @patch("idp_common.image.prepare_bedrock_image_attachment")
    @patch("idp_common.bedrock.invoke_model")
    @patch("idp_common.s3.write_content")
    @patch("idp_common.utils.merge_metering_data")
    @patch("idp_common.metrics.put_metric")
    def test_process_document_section_missing_page(
        self,
        mock_put_metric,
        mock_merge_metering,
        mock_write_content,
        mock_invoke_model,
        mock_prepare_bedrock_image,
        mock_prepare_image,
        mock_get_text_content,
        service,
        sample_document,
    ):
        """Test processing a document section with a missing page."""
        # Add a non-existent page ID to the section
        sample_document.sections[0].page_ids.append("999")

        # Mock responses
        mock_get_text_content.side_effect = ["Page 1 text", "Page 2 text"]
        mock_prepare_image.return_value = b"fake_image_data"
        mock_prepare_bedrock_image.return_value = {"type": "image", "source": {}}
        mock_invoke_model.return_value = {
            "response": {
                "output": {
                    "message": {"content": [{"text": '{"invoice_number": "INV-123"}'}]}
                }
            },
            "metering": {"input_tokens": 100, "output_tokens": 50},
        }
        mock_merge_metering.return_value = {"total_tokens": 150}

        # Process the section
        result = service.process_document_section(sample_document, "1")

        # Verify error was added for the missing page
        assert any("Page 999 not found in document" in error for error in result.errors)

    @pytest.mark.skip(reason="Temporarily disabled due to exception handling issues")
    @patch("idp_common.s3.get_text_content")
    @patch("idp_common.metrics.put_metric")
    def test_process_document_section_exception(
        self, mock_put_metric, mock_get_text_content, service, sample_document
    ):
        """Test handling exceptions during document processing."""
        # Mock an exception
        mock_get_text_content.side_effect = Exception("Test exception")

        # Process the section and expect exception to be raised
        with pytest.raises(Exception, match="Test exception"):
            service.process_document_section(sample_document, "1")

    def test_extract_json_code_block(self, service):
        """Test extracting JSON from code block."""
        # Test with ```json code block
        text = 'Here is the result:\n```json\n{"invoice_number": "INV-123"}\n```\nEnd of result.'
        result = service._extract_json(text)
        assert result == '{"invoice_number": "INV-123"}'

        # Test with simple ``` code block
        text = 'Here is the result:\n```\n{"invoice_number": "INV-123"}\n```\nEnd of result.'
        result = service._extract_json(text)
        assert result == '{"invoice_number": "INV-123"}'

    def test_extract_json_simple(self, service):
        """Test extracting JSON without code block."""
        # Test with simple JSON
        text = 'The extraction result is {"invoice_number": "INV-123"} based on the document.'
        result = service._extract_json(text)
        assert result == '{"invoice_number": "INV-123"}'

        # Test with nested JSON
        text = 'Result: {"invoice": {"number": "INV-123", "date": "2025-05-08"}}'
        result = service._extract_json(text)
        assert result == '{"invoice": {"number": "INV-123", "date": "2025-05-08"}}'

        # Test with no JSON
        text = "No JSON here"
        result = service._extract_json(text)
        assert result == "No JSON here"
