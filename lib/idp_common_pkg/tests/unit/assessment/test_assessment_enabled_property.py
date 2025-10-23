# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for assessment service enabled property.

Tests that the assessment service correctly respects the 'enabled' property
in configuration and skips processing when disabled.
"""

import unittest
from unittest.mock import patch

from idp_common.assessment.service import AssessmentService
from idp_common.models import Document, Page, Section, Status


class TestAssessmentEnabledProperty(unittest.TestCase):
    """Test assessment service enabled property behavior."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a mock document with sections
        self.document = Document(
            id="test-doc-001",
            pages={
                "1": Page(
                    page_id="1",
                    image_uri="s3://test-bucket/test-doc/page-1.png",
                    parsed_text_uri="s3://test-bucket/test-doc/text-1.txt",
                    raw_text_uri="s3://test-bucket/test-doc/raw-1.json",
                )
            },
            sections=[
                Section(
                    section_id="section-1",
                    classification="Invoice",
                    page_ids=["1"],
                    extraction_result_uri="s3://test-bucket/test-doc/extraction-1.json",
                )
            ],
            status=Status.EXTRACTING,
            errors=[],
            metering={},
        )
        self.section_id = "section-1"

        # Base configuration for assessment
        self.base_config = {
            "classes": [
                {
                    "name": "Invoice",
                    "attributes": [
                        {
                            "name": "invoice_number",
                            "description": "The invoice number",
                            "attributeType": "simple",
                        }
                    ],
                }
            ],
            "assessment": {
                "model": "eu.anthropic.claude-3-haiku-20240307-v1:0",
                "temperature": 0.0,
                "top_k": 5,
                "top_p": 0.1,
                "max_tokens": 4096,
                "default_confidence_threshold": 0.9,
                "system_prompt": "You are an assessment expert.",
                "task_prompt": "Assess the confidence of extraction results for this {DOCUMENT_CLASS} document.\n\n<attributes-definitions>\n{ATTRIBUTE_NAMES_AND_DESCRIPTIONS}\n</attributes-definitions>\n\n<document-text>\n{DOCUMENT_TEXT}\n</document-text>\n\n<extraction-results>\n{EXTRACTION_RESULTS}\n</extraction-results>",
            },
        }

    def test_assessment_enabled_true(self):
        """Test assessment runs when enabled=true."""
        # Configure assessment as enabled
        config = self.base_config.copy()
        config["assessment"]["enabled"] = True

        # Initialize assessment service
        assessment_service = AssessmentService(config=config)

        with (
            patch("idp_common.s3.get_json_content") as mock_get_json,
            patch("idp_common.s3.get_text_content") as mock_get_text,
            patch("idp_common.s3.write_content") as mock_write_content,
            patch("idp_common.image.prepare_image") as mock_prepare_image,
            patch("idp_common.bedrock.invoke_model") as mock_invoke_model,
        ):
            # Mock S3 responses
            mock_get_json.return_value = {
                "inference_result": {"invoice_number": "INV-12345"},
                "metadata": {},
            }
            mock_get_text.return_value = "Invoice #INV-12345\nAmount: $100.00"
            mock_prepare_image.return_value = b"mock_image_data"

            # Mock Bedrock response
            mock_invoke_model.return_value = {
                "content": [
                    {
                        "text": '{"invoice_number": {"confidence": 0.95, "confidence_reason": "Clear text"}}'
                    }
                ],
                "metering": {
                    "inputTokens": 1000,
                    "outputTokens": 200,
                    "totalTokens": 1200,
                },
            }

            # Process document section
            result_document = assessment_service.process_document_section(
                self.document, self.section_id
            )

            # Verify the service processed normally (Bedrock was called)
            self.assertIsNotNone(result_document)
            mock_invoke_model.assert_called_once()
            mock_write_content.assert_called_once()

    def test_assessment_enabled_false(self):
        """Test assessment skips processing when enabled=false."""
        # Configure assessment as disabled
        config = self.base_config.copy()
        config["assessment"]["enabled"] = False

        # Initialize assessment service
        assessment_service = AssessmentService(config=config)

        with (
            patch("idp_common.s3.get_json_content") as mock_get_json,
            patch("idp_common.s3.get_text_content") as mock_get_text,
            patch("idp_common.s3.write_content") as mock_write_content,
            patch("idp_common.bedrock.invoke_model") as mock_invoke_model,
        ):
            # Process document section
            result_document = assessment_service.process_document_section(
                self.document, self.section_id
            )

            # Verify the service returned early (no API calls made)
            self.assertIsNotNone(result_document)
            self.assertEqual(result_document.id, self.document.id)

            # Verify no expensive operations were performed
            mock_get_json.assert_not_called()
            mock_get_text.assert_not_called()
            mock_write_content.assert_not_called()
            mock_invoke_model.assert_not_called()

    def test_assessment_enabled_missing_defaults_true(self):
        """Test assessment runs when enabled property is missing (backward compatibility)."""
        # Configure assessment without enabled property
        config = self.base_config.copy()
        # Explicitly do not set 'enabled' property

        # Initialize assessment service
        assessment_service = AssessmentService(config=config)

        with (
            patch("idp_common.s3.get_json_content") as mock_get_json,
            patch("idp_common.s3.get_text_content") as mock_get_text,
            patch("idp_common.s3.write_content") as mock_write_content,
            patch("idp_common.image.prepare_image") as mock_prepare_image,
            patch("idp_common.bedrock.invoke_model") as mock_invoke_model,
        ):
            # Mock S3 responses
            mock_get_json.return_value = {
                "inference_result": {"invoice_number": "INV-12345"},
                "metadata": {},
            }
            mock_get_text.return_value = "Invoice #INV-12345\nAmount: $100.00"
            mock_prepare_image.return_value = b"mock_image_data"

            # Mock Bedrock response
            mock_invoke_model.return_value = {
                "content": [
                    {
                        "text": '{"invoice_number": {"confidence": 0.95, "confidence_reason": "Clear text"}}'
                    }
                ],
                "metering": {
                    "inputTokens": 1000,
                    "outputTokens": 200,
                    "totalTokens": 1200,
                },
            }

            # Process document section
            result_document = assessment_service.process_document_section(
                self.document, self.section_id
            )

            # Verify the service processed normally (defaults to enabled)
            self.assertIsNotNone(result_document)
            mock_invoke_model.assert_called_once()
            mock_write_content.assert_called_once()

    def test_assessment_enabled_string_true(self):
        """Test assessment handles string 'true' value."""
        # Configure assessment with string 'true'
        config = self.base_config.copy()
        config["assessment"]["enabled"] = "true"

        # Initialize assessment service
        assessment_service = AssessmentService(config=config)

        with (
            patch("idp_common.s3.get_json_content") as mock_get_json,
            patch("idp_common.s3.get_text_content") as mock_get_text,
            patch("idp_common.s3.write_content") as mock_write_content,
            patch("idp_common.image.prepare_image") as mock_prepare_image,
            patch("idp_common.bedrock.invoke_model") as mock_invoke_model,
        ):
            # Mock S3 responses
            mock_get_json.return_value = {
                "inference_result": {"invoice_number": "INV-12345"},
                "metadata": {},
            }
            mock_get_text.return_value = "Invoice #INV-12345\nAmount: $100.00"
            mock_prepare_image.return_value = b"mock_image_data"

            # Mock Bedrock response
            mock_invoke_model.return_value = {
                "content": [
                    {
                        "text": '{"invoice_number": {"confidence": 0.95, "confidence_reason": "Clear text"}}'
                    }
                ],
                "metering": {
                    "inputTokens": 1000,
                    "outputTokens": 200,
                    "totalTokens": 1200,
                },
            }

            # Process document section
            result_document = assessment_service.process_document_section(
                self.document, self.section_id
            )

            # Verify the service processed normally
            self.assertIsNotNone(result_document)
            mock_invoke_model.assert_called_once()
            mock_write_content.assert_called_once()

    def test_assessment_enabled_string_false(self):
        """Test assessment handles string 'false' value."""
        # Configure assessment with string 'false'
        config = self.base_config.copy()
        config["assessment"]["enabled"] = "false"

        # Initialize assessment service
        assessment_service = AssessmentService(config=config)

        with (
            patch("idp_common.s3.get_json_content") as mock_get_json,
            patch("idp_common.s3.get_text_content") as mock_get_text,
            patch("idp_common.s3.write_content") as mock_write_content,
            patch("idp_common.bedrock.invoke_model") as mock_invoke_model,
        ):
            # Process document section
            result_document = assessment_service.process_document_section(
                self.document, self.section_id
            )

            # Verify the service returned early (disabled)
            self.assertIsNotNone(result_document)
            self.assertEqual(result_document.id, self.document.id)

            # Verify no expensive operations were performed
            mock_get_json.assert_not_called()
            mock_get_text.assert_not_called()
            mock_write_content.assert_not_called()
            mock_invoke_model.assert_not_called()

    def test_assessment_missing_config_section(self):
        """Test assessment runs when assessment config section is missing."""
        # Configure without assessment section
        config = {"classes": self.base_config["classes"]}

        # Initialize assessment service
        assessment_service = AssessmentService(config=config)

        with (
            patch("idp_common.s3.get_json_content") as mock_get_json,
            patch("idp_common.s3.get_text_content") as mock_get_text,
            patch("idp_common.s3.write_content") as mock_write_content,
            patch("idp_common.image.prepare_image") as mock_prepare_image,
            patch("idp_common.bedrock.invoke_model") as mock_invoke_model,
        ):
            # Mock S3 responses
            mock_get_json.return_value = {
                "inference_result": {"invoice_number": "INV-12345"},
                "metadata": {},
            }
            mock_get_text.return_value = "Invoice #INV-12345\nAmount: $100.00"
            mock_prepare_image.return_value = b"mock_image_data"

            # Mock Bedrock response
            mock_invoke_model.return_value = {
                "content": [
                    {
                        "text": '{"invoice_number": {"confidence": 0.95, "confidence_reason": "Clear text"}}'
                    }
                ],
                "metering": {
                    "inputTokens": 1000,
                    "outputTokens": 200,
                    "totalTokens": 1200,
                },
            }

            # Process document section
            result_document = assessment_service.process_document_section(
                self.document, self.section_id
            )

            # Verify the service processed normally (defaults to enabled)
            self.assertIsNotNone(result_document)
            mock_invoke_model.assert_called_once()
            mock_write_content.assert_called_once()

    @patch("idp_common.assessment.service.logger")
    def test_assessment_disabled_logging(self, mock_logger):
        """Test that appropriate logging occurs when assessment is disabled."""
        # Configure assessment as disabled
        config = self.base_config.copy()
        config["assessment"]["enabled"] = False

        # Initialize assessment service
        assessment_service = AssessmentService(config=config)

        # Process document section
        result_document = assessment_service.process_document_section(
            self.document, self.section_id
        )

        # Verify logging occurred
        mock_logger.info.assert_called_with("Assessment is disabled via configuration")
        self.assertIsNotNone(result_document)


if __name__ == "__main__":
    unittest.main()
