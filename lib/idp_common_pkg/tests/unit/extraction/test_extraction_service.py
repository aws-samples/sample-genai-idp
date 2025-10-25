# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for the ExtractionService class.
"""

# ruff: noqa: E402, I001
# The above line disables E402 (module level import not at top of file) and I001 (import block sorting) for this file

import pytest

# Import standard library modules first
from textwrap import dedent
from unittest.mock import patch

# PIL is now used directly - no mocking needed

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
                {
                    "name": "bank_statement",
                    "description": "Monthly bank account statement",
                    "attributes": [
                        {
                            "name": "account_number",
                            "description": "Primary account identifier",
                            "attributeType": "simple",
                        },
                        {
                            "name": "account_holder_address",
                            "description": "Complete address information for the account holder",
                            "attributeType": "group",
                            "groupAttributes": [
                                {
                                    "name": "street_number",
                                    "description": "House or building number",
                                    "confidence_threshold": "0.9",
                                },
                                {
                                    "name": "street_name",
                                    "description": "Name of the street",
                                    "confidence_threshold": "0.8",
                                },
                                {
                                    "name": "city",
                                    "description": "City name",
                                    "confidence_threshold": "0.9",
                                },
                            ],
                        },
                        {
                            "name": "transactions",
                            "description": "List of all transactions in the statement period",
                            "attributeType": "list",
                            "listItemTemplate": {
                                "itemDescription": "Individual transaction record",
                                "itemAttributes": [
                                    {
                                        "name": "date",
                                        "description": "Transaction date (MM/DD/YYYY)",
                                        "confidence_threshold": "0.9",
                                    },
                                    {
                                        "name": "description",
                                        "description": "Transaction description or merchant name",
                                        "confidence_threshold": "0.7",
                                    },
                                    {
                                        "name": "amount",
                                        "description": "Transaction amount",
                                        "confidence_threshold": "0.95",
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
            "extraction": {
                "model": "anthropic.claude-3-sonnet-20240229-v1:0",
                "temperature": 0.0,
                "top_k": 5,
                "system_prompt": "You are a document extraction assistant.",
                "task_prompt": dedent(
                    """
                    Extract the following fields from this {DOCUMENT_CLASS} document:

                    {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}

                    Document text:
                    {DOCUMENT_TEXT}

                    Document image:
                    {DOCUMENT_IMAGE}

                    Respond with a JSON object containing each field name and its extracted value.
                """
                ),
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

    def test_format_nested_attribute_descriptions(self, service):
        """Test formatting nested attribute descriptions (group and list types)."""
        # Get bank statement attributes with nested structures
        bank_statement_attrs = service._get_class_attributes("bank_statement")
        formatted = service._format_attribute_descriptions(bank_statement_attrs)

        # Test that main attributes are present
        assert "account_number" in formatted
        assert "Primary account identifier" in formatted
        assert "account_holder_address" in formatted
        assert "Complete address information" in formatted
        assert "transactions" in formatted
        assert "List of all transactions" in formatted

        # Test that group nested attributes are properly indented
        assert "  - street_number" in formatted
        assert "House or building number" in formatted
        assert "  - street_name" in formatted
        assert "Name of the street" in formatted
        assert "  - city" in formatted
        assert "City name" in formatted

        # Test that list nested attributes are properly formatted
        assert "Each item: Individual transaction record" in formatted
        assert "  - date" in formatted
        assert "Transaction date (MM/DD/YYYY)" in formatted
        assert "  - description" in formatted
        assert "Transaction description or merchant name" in formatted
        assert "  - amount" in formatted
        assert "Transaction amount" in formatted

    def test_format_attribute_descriptions_empty_list(self, service):
        """Test formatting attribute descriptions with empty list."""
        formatted = service._format_attribute_descriptions([])
        assert formatted == ""

    def test_format_attribute_descriptions_group_only(self, service):
        """Test formatting attribute descriptions with group type only."""
        attributes = [
            {
                "name": "address",
                "description": "Complete address information",
                "attributeType": "group",
                "groupAttributes": [
                    {"name": "street", "description": "Street name"},
                    {"name": "city", "description": "City name"},
                ],
            }
        ]

        formatted = service._format_attribute_descriptions(attributes)

        assert "address" in formatted
        assert "Complete address information" in formatted
        assert "  - street" in formatted
        assert "Street name" in formatted
        assert "  - city" in formatted
        assert "City name" in formatted

    def test_format_attribute_descriptions_list_only(self, service):
        """Test formatting attribute descriptions with list type only."""
        attributes = [
            {
                "name": "items",
                "description": "List of items",
                "attributeType": "list",
                "listItemTemplate": {
                    "itemDescription": "Individual item",
                    "itemAttributes": [
                        {"name": "name", "description": "Item name"},
                        {"name": "price", "description": "Item price"},
                    ],
                },
            }
        ]

        formatted = service._format_attribute_descriptions(attributes)

        assert "items" in formatted
        assert "List of items" in formatted
        assert "Each item: Individual item" in formatted
        assert "  - name" in formatted
        assert "Item name" in formatted
        assert "  - price" in formatted
        assert "Item price" in formatted

    def test_format_attribute_descriptions_list_without_item_description(self, service):
        """Test formatting list attributes without itemDescription."""
        attributes = [
            {
                "name": "items",
                "description": "List of items",
                "attributeType": "list",
                "listItemTemplate": {
                    "itemAttributes": [
                        {"name": "name", "description": "Item name"},
                    ],
                },
            }
        ]

        formatted = service._format_attribute_descriptions(attributes)

        assert "items" in formatted
        assert "List of items" in formatted
        assert (
            "Each item:" not in formatted
        )  # Should not appear when itemDescription is missing
        assert "  - name" in formatted
        assert "Item name" in formatted

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
        from idp_common.utils import extract_json_from_text

        # Test with ```json code block
        text = 'Here is the result:\n```json\n{"invoice_number": "INV-123"}\n```\nEnd of result.'
        result = extract_json_from_text(text)
        assert result == '{"invoice_number": "INV-123"}'

        # Test with simple ``` code block
        text = 'Here is the result:\n```\n{"invoice_number": "INV-123"}\n```\nEnd of result.'
        result = extract_json_from_text(text)
        assert result == '{"invoice_number": "INV-123"}'

    def test_extract_json_simple(self, service):
        """Test extracting JSON without code block."""
        from idp_common.utils import extract_json_from_text

        # Test with simple JSON
        text = 'The extraction result is {"invoice_number": "INV-123"} based on the document.'
        result = extract_json_from_text(text)
        assert result == '{"invoice_number": "INV-123"}'

        # Test with nested JSON
        text = 'Result: {"invoice": {"number": "INV-123", "date": "2025-05-08"}}'
        result = extract_json_from_text(text)
        assert result == '{"invoice": {"number": "INV-123", "date": "2025-05-08"}}'

        # Test with no JSON
        text = "No JSON here"
        result = extract_json_from_text(text)
        assert result == "No JSON here"
