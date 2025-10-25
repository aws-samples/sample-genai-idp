# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for the AssessmentService class.
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
from idp_common.assessment.service import AssessmentService
from idp_common.models import Document, Section, Status, Page


@pytest.mark.unit
class TestAssessmentService:
    """Tests for the AssessmentService class."""

    @pytest.fixture
    def mock_config(self):
        """Fixture providing a mock configuration."""
        return {
            "classes": [
                {
                    "name": "invoice",
                    "description": "An invoice document",
                    "attributes": [
                        {
                            "name": "invoice_number",
                            "description": "The invoice number",
                            "confidence_threshold": "0.95",
                        },
                        {
                            "name": "invoice_date",
                            "description": "The invoice date",
                            "confidence_threshold": "0.85",
                        },
                        {
                            "name": "total_amount",
                            "description": "The total amount",
                            "confidence_threshold": "0.9",
                        },
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
                            "confidence_threshold": "0.95",
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
                                {
                                    "name": "state",
                                    "description": "State abbreviation",
                                    # No confidence_threshold - should use default
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
                                    {
                                        "name": "balance",
                                        "description": "Account balance after transaction",
                                        # No confidence_threshold - should use default
                                    },
                                ],
                            },
                        },
                    ],
                },
            ],
            "assessment": {
                "model": "anthropic.claude-3-sonnet-20240229-v1:0",
                "temperature": 0.0,
                "top_k": 5,
                "default_confidence_threshold": 0.8,
                "system_prompt": "You are a document assessment assistant.",
                "task_prompt": dedent(
                    """
                    Assess the confidence of the following extraction results from this {DOCUMENT_CLASS} document:
                    
                    Expected fields:
                    {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}
                    
                    Extraction results:
                    {EXTRACTION_RESULTS}
                    
                    Document text:
                    {DOCUMENT_TEXT}
                    
                    Respond with a JSON object containing confidence scores and reasons for each field.
                """
                ),
            },
        }

    @pytest.fixture
    def service(self, mock_config):
        """Fixture providing an AssessmentService instance."""
        return AssessmentService(region="us-west-2", config=mock_config)

    @pytest.fixture
    def sample_document_with_extraction(self):
        """Fixture providing a sample document with extraction results."""
        doc = Document(
            id="test-doc",
            input_key="test-document.pdf",
            input_bucket="input-bucket",
            output_bucket="output-bucket",
            status=Status.ASSESSING,
        )

        # Add pages
        doc.pages["1"] = Page(
            page_id="1",
            image_uri="s3://input-bucket/test-document.pdf/pages/1/image.jpg",
            parsed_text_uri="s3://input-bucket/test-document.pdf/pages/1/parsed.txt",
        )

        # Add section with extraction results
        section = Section(section_id="1", classification="invoice", page_ids=["1"])
        section.extraction_result_uri = (
            "s3://output-bucket/test-document.pdf/sections/1/result.json"
        )
        doc.sections.append(section)

        return doc

    def test_init(self, mock_config):
        """Test initialization with configuration."""
        service = AssessmentService(region="us-west-2", config=mock_config)

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
        """Test formatting attribute descriptions for simple attributes."""
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
        assert "  - state" in formatted
        assert "State abbreviation" in formatted

        # Test that list nested attributes are properly formatted
        assert "Each item: Individual transaction record" in formatted
        assert "  - date" in formatted
        assert "Transaction date (MM/DD/YYYY)" in formatted
        assert "  - description" in formatted
        assert "Transaction description or merchant name" in formatted
        assert "  - amount" in formatted
        assert "Transaction amount" in formatted
        assert "  - balance" in formatted
        assert "Account balance after transaction" in formatted

    def test_get_attribute_confidence_threshold_simple(self, service):
        """Test getting confidence threshold for simple attributes."""
        invoice_attrs = service._get_class_attributes("invoice")
        default_threshold = 0.8

        # Test existing attribute with threshold
        threshold = service._get_attribute_confidence_threshold(
            "invoice_number", invoice_attrs, default_threshold
        )
        assert threshold == 0.95

        # Test existing attribute with different threshold
        threshold = service._get_attribute_confidence_threshold(
            "invoice_date", invoice_attrs, default_threshold
        )
        assert threshold == 0.85

        # Test non-existent attribute (should return default)
        threshold = service._get_attribute_confidence_threshold(
            "unknown_field", invoice_attrs, default_threshold
        )
        assert threshold == default_threshold

    def test_get_attribute_confidence_threshold_nested(self, service):
        """Test getting confidence threshold for nested attributes."""
        bank_statement_attrs = service._get_class_attributes("bank_statement")
        default_threshold = 0.8

        # Test top-level attribute
        threshold = service._get_attribute_confidence_threshold(
            "account_number", bank_statement_attrs, default_threshold
        )
        assert threshold == 0.95

        # Test group nested attributes
        threshold = service._get_attribute_confidence_threshold(
            "street_number", bank_statement_attrs, default_threshold
        )
        assert threshold == 0.9

        threshold = service._get_attribute_confidence_threshold(
            "street_name", bank_statement_attrs, default_threshold
        )
        assert threshold == 0.8

        threshold = service._get_attribute_confidence_threshold(
            "city", bank_statement_attrs, default_threshold
        )
        assert threshold == 0.9

        # Test group nested attribute without threshold (should use default)
        threshold = service._get_attribute_confidence_threshold(
            "state", bank_statement_attrs, default_threshold
        )
        assert threshold == default_threshold

        # Test list nested attributes
        threshold = service._get_attribute_confidence_threshold(
            "date", bank_statement_attrs, default_threshold
        )
        assert threshold == 0.9

        threshold = service._get_attribute_confidence_threshold(
            "description", bank_statement_attrs, default_threshold
        )
        assert threshold == 0.7

        threshold = service._get_attribute_confidence_threshold(
            "amount", bank_statement_attrs, default_threshold
        )
        assert threshold == 0.95

        # Test list nested attribute without threshold (should use default)
        threshold = service._get_attribute_confidence_threshold(
            "balance", bank_statement_attrs, default_threshold
        )
        assert threshold == default_threshold

        # Test completely unknown attribute
        threshold = service._get_attribute_confidence_threshold(
            "unknown_field", bank_statement_attrs, default_threshold
        )
        assert threshold == default_threshold

    def test_format_attribute_descriptions_edge_cases(self, service):
        """Test formatting attribute descriptions with edge cases."""
        # Test empty list
        formatted = service._format_attribute_descriptions([])
        assert formatted == ""

        # Test group with no groupAttributes
        attributes = [
            {
                "name": "address",
                "description": "Complete address information",
                "attributeType": "group",
            }
        ]
        formatted = service._format_attribute_descriptions(attributes)
        assert "address" in formatted
        assert "Complete address information" in formatted

        # Test list with no itemAttributes
        attributes = [
            {
                "name": "items",
                "description": "List of items",
                "attributeType": "list",
                "listItemTemplate": {"itemDescription": "Individual item"},
            }
        ]
        formatted = service._format_attribute_descriptions(attributes)
        assert "items" in formatted
        assert "List of items" in formatted
        assert "Each item: Individual item" in formatted

        # Test list with no listItemTemplate
        attributes = [
            {
                "name": "items",
                "description": "List of items",
                "attributeType": "list",
            }
        ]
        formatted = service._format_attribute_descriptions(attributes)
        assert "items" in formatted
        assert "List of items" in formatted

    @patch("idp_common.s3.get_json_content")
    @patch("idp_common.s3.get_text_content")
    @patch("idp_common.image.prepare_image")
    @patch("idp_common.bedrock.invoke_model")
    @patch("idp_common.s3.write_content")
    @patch("idp_common.utils.parse_s3_uri")
    @patch("idp_common.utils.merge_metering_data")
    @patch("idp_common.metrics.put_metric")
    def test_process_document_section_success(
        self,
        mock_put_metric,
        mock_merge_metering,
        mock_parse_s3_uri,
        mock_write_content,
        mock_invoke_model,
        mock_prepare_image,
        mock_get_text_content,
        mock_get_json_content,
        service,
        sample_document_with_extraction,
    ):
        """Test successful assessment of a document section."""
        # Mock S3 responses
        mock_get_json_content.side_effect = [
            # Extraction results
            {
                "document_class": {"type": "invoice"},
                "inference_result": {
                    "invoice_number": "INV-123",
                    "invoice_date": "2025-05-08",
                    "total_amount": "$100.00",
                },
                "metadata": {"parsing_succeeded": True},
            }
        ]
        mock_get_text_content.return_value = "Page 1 text"
        mock_prepare_image.return_value = b"image_data"
        mock_parse_s3_uri.return_value = (
            "output-bucket",
            "test-document.pdf/sections/1/result.json",
        )

        # Mock Bedrock response
        mock_invoke_model.return_value = {
            "response": {
                "output": {
                    "message": {
                        "content": [
                            {
                                "text": """{
                                    "invoice_number": {
                                        "confidence": 0.98,
                                        "confidence_reason": "Clear and legible invoice number"
                                    },
                                    "invoice_date": {
                                        "confidence": 0.90,
                                        "confidence_reason": "Date format is standard"
                                    },
                                    "total_amount": {
                                        "confidence": 0.95,
                                        "confidence_reason": "Amount clearly visible"
                                    }
                                }"""
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
        result = service.process_document_section(sample_document_with_extraction, "1")

        # Verify the document was processed without errors
        assert len(result.errors) == 0

        # Verify the calls
        mock_get_json_content.assert_called_once()
        mock_get_text_content.assert_called_once()
        mock_invoke_model.assert_called_once()
        mock_write_content.assert_called_once()

        # Verify the content written to S3 includes assessment data
        written_content = mock_write_content.call_args[0][0]
        assert "explainability_info" in written_content
        assert len(written_content["explainability_info"]) == 1

        assessment_data = written_content["explainability_info"][0]

        # Check that confidence thresholds are added to assessment data
        assert "invoice_number" in assessment_data
        assert assessment_data["invoice_number"]["confidence"] == 0.98
        assert assessment_data["invoice_number"]["confidence_threshold"] == 0.95

        assert "invoice_date" in assessment_data
        assert assessment_data["invoice_date"]["confidence"] == 0.90
        assert assessment_data["invoice_date"]["confidence_threshold"] == 0.85

        assert "total_amount" in assessment_data
        assert assessment_data["total_amount"]["confidence"] == 0.95
        assert assessment_data["total_amount"]["confidence_threshold"] == 0.9

    @patch("idp_common.metrics.put_metric")
    def test_process_document_section_no_extraction_results(
        self, mock_put_metric, service, sample_document_with_extraction
    ):
        """Test processing a document section with no extraction results."""
        # Remove extraction result URI
        sample_document_with_extraction.sections[0].extraction_result_uri = None

        # Process the section
        result = service.process_document_section(sample_document_with_extraction, "1")

        # Verify error was added
        assert len(result.errors) == 1
        assert "Section 1 has no extraction results to assess" in result.errors[0]

    @patch("idp_common.metrics.put_metric")
    def test_process_document_section_missing_section(
        self, mock_put_metric, service, sample_document_with_extraction
    ):
        """Test processing a document section that doesn't exist."""
        # Process a non-existent section
        result = service.process_document_section(
            sample_document_with_extraction, "999"
        )

        # Verify error was added
        assert len(result.errors) == 1
        assert "Section 999 not found in document" in result.errors[0]

    @patch("idp_common.s3.get_json_content")
    @patch("idp_common.metrics.put_metric")
    def test_process_document_section_empty_extraction_results(
        self,
        mock_put_metric,
        mock_get_json_content,
        service,
        sample_document_with_extraction,
    ):
        """Test processing a document section with empty extraction results."""
        # Mock empty extraction results
        mock_get_json_content.return_value = {
            "document_class": {"type": "invoice"},
            "inference_result": {},
            "metadata": {"parsing_succeeded": True},
        }

        # Process the section
        result = service.process_document_section(sample_document_with_extraction, "1")

        # Should return without error but log warning
        assert len(result.errors) == 0
        mock_get_json_content.assert_called_once()
