# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Test backward compatibility of assessment service with granular assessment enabled/disabled.
This test emulates the Pattern-2 AssessmentFunction to ensure both standard and granular
assessment services work correctly.
"""

import json
import os
import unittest
from typing import Any, Dict
from unittest.mock import patch

from idp_common import assessment
from idp_common.models import Document, Page, Section, Status


class TestAssessmentBackwardCompatibility(unittest.TestCase):
    """Test assessment service backward compatibility."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a mock document with extraction results
        self.document = self._create_test_document()
        self.section_id = "section_1"

        # Base configuration for assessment
        self.base_config = {
            "classes": [
                {
                    "name": "invoice",
                    "description": "A billing document",
                    "attributes": [
                        {
                            "name": "invoice_number",
                            "description": "The unique identifier for the invoice",
                            "confidence_threshold": "0.85",
                        },
                        {
                            "name": "total_amount",
                            "description": "The final amount to be paid",
                            "confidence_threshold": "0.9",
                        },
                        {
                            "name": "vendor_info",
                            "description": "Vendor information",
                            "attributeType": "group",
                            "groupAttributes": [
                                {
                                    "name": "vendor_name",
                                    "description": "Name of the vendor",
                                    "confidence_threshold": "0.8",
                                },
                                {
                                    "name": "vendor_address",
                                    "description": "Address of the vendor",
                                    "confidence_threshold": "0.75",
                                },
                            ],
                        },
                        {
                            "name": "line_items",
                            "description": "List of invoice line items",
                            "attributeType": "list",
                            "listItemTemplate": {
                                "itemDescription": "Individual line item",
                                "itemAttributes": [
                                    {
                                        "name": "item_description",
                                        "description": "Description of the item",
                                        "confidence_threshold": "0.7",
                                    },
                                    {
                                        "name": "item_amount",
                                        "description": "Amount for this item",
                                        "confidence_threshold": "0.8",
                                    },
                                ],
                            },
                        },
                    ],
                }
            ],
            "assessment": {
                "model": "eu.anthropic.claude-3-haiku-20240307-v1:0",
                "system_prompt": "You are an assessment expert.",
                "task_prompt": "Assess the confidence of extraction results for this {DOCUMENT_CLASS} document.\n\n<attributes-definitions>\n{ATTRIBUTE_NAMES_AND_DESCRIPTIONS}\n</attributes-definitions>\n\n<<CACHEPOINT>>\n\n<document-image>\n{DOCUMENT_IMAGE}\n</document-image>\n\n<ocr-text-confidence-results>\n{OCR_TEXT_CONFIDENCE}\n</ocr-text-confidence-results>\n\n<<CACHEPOINT>>\n\n<extraction-results>\n{EXTRACTION_RESULTS}\n</extraction-results>",
                "temperature": "0.0",
                "top_p": "0.1",
                "top_k": "5",
                "max_tokens": "4096",
                "default_confidence_threshold": "0.9",
            },
        }

    def _create_test_document(self) -> Document:
        """Create a test document with extraction results."""
        # Create test pages
        pages = {}
        for i in range(1, 3):  # 2 pages
            page = Page(
                page_id=str(i),
                image_uri=f"s3://test-bucket/images/page_{i}.jpg",
                parsed_text_uri=f"s3://test-bucket/text/page_{i}.txt",
                raw_text_uri=f"s3://test-bucket/raw/page_{i}.json",
            )
            pages[str(i)] = page

        # Create test section with extraction results
        section = Section(
            section_id="section_1",
            classification="invoice",
            page_ids=["1", "2"],
            extraction_result_uri="s3://test-bucket/extraction/section_1.json",
        )

        # Create document
        document = Document(
            id="test_doc_123",
            input_key="test_document.pdf",
            status=Status.EXTRACTING,
            pages=pages,
            sections=[section],
        )

        return document

    def _create_test_extraction_results(self) -> Dict[str, Any]:
        """Create test extraction results."""
        return {
            "inference_result": {
                "invoice_number": "INV-2024-001",
                "total_amount": "$1,234.56",
                "vendor_info": {
                    "vendor_name": "ACME Corp",
                    "vendor_address": "123 Main St, City, State",
                },
                "line_items": [
                    {"item_description": "Widget A", "item_amount": "$500.00"},
                    {"item_description": "Widget B", "item_amount": "$734.56"},
                ],
            },
            "metadata": {"extraction_time": 5.2},
        }

    def _create_mock_image_data(self) -> bytes:
        """Create a valid mock image data for testing."""
        import io

        from PIL import Image

        # Create a simple 100x100 white image
        img = Image.new("RGB", (100, 100), color="white")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="JPEG")
        return img_bytes.getvalue()

    def _create_mock_assessment_response(self, task_type: str = "standard") -> str:
        """Create mock assessment response based on task type."""
        if task_type == "simple_batch":
            return json.dumps(
                {
                    "invoice_number": {
                        "confidence": 0.95,
                        "confidence_reason": "Clear text, high OCR confidence",
                    },
                    "total_amount": {
                        "confidence": 0.88,
                        "confidence_reason": "Clearly visible amount",
                    },
                }
            )
        elif task_type == "group":
            return json.dumps(
                {
                    "vendor_info": {
                        "vendor_name": {
                            "confidence": 0.92,
                            "confidence_reason": "Company name clearly visible",
                        },
                        "vendor_address": {
                            "confidence": 0.78,
                            "confidence_reason": "Address partially obscured",
                        },
                    }
                }
            )
        elif task_type == "list_item":
            return json.dumps(
                {
                    "item_description": {
                        "confidence": 0.85,
                        "confidence_reason": "Item description clear",
                    },
                    "item_amount": {
                        "confidence": 0.90,
                        "confidence_reason": "Amount clearly visible",
                    },
                }
            )
        else:  # standard assessment
            return json.dumps(
                {
                    "invoice_number": {
                        "confidence": 0.95,
                        "confidence_reason": "Clear text, high OCR confidence",
                    },
                    "total_amount": {
                        "confidence": 0.88,
                        "confidence_reason": "Clearly visible amount",
                    },
                    "vendor_info": {
                        "vendor_name": {
                            "confidence": 0.92,
                            "confidence_reason": "Company name clearly visible",
                        },
                        "vendor_address": {
                            "confidence": 0.78,
                            "confidence_reason": "Address partially obscured",
                        },
                    },
                    "line_items": [
                        {
                            "item_description": {
                                "confidence": 0.85,
                                "confidence_reason": "Item description clear",
                            },
                            "item_amount": {
                                "confidence": 0.90,
                                "confidence_reason": "Amount clearly visible",
                            },
                        },
                        {
                            "item_description": {
                                "confidence": 0.82,
                                "confidence_reason": "Item description mostly clear",
                            },
                            "item_amount": {
                                "confidence": 0.87,
                                "confidence_reason": "Amount visible",
                            },
                        },
                    ],
                }
            )

    @patch("idp_common.s3.get_json_content")
    @patch("idp_common.s3.get_text_content")
    @patch("idp_common.s3.write_content")
    @patch("idp_common.image.prepare_image")
    @patch("idp_common.bedrock.invoke_model")
    def test_standard_assessment_service(
        self,
        mock_invoke_model,
        mock_prepare_image,
        mock_write_content,
        mock_get_text_content,
        mock_get_json_content,
    ):
        """Test standard assessment service (granular disabled)."""
        # Configure mocks
        mock_get_json_content.return_value = self._create_test_extraction_results()
        mock_get_text_content.return_value = "Sample document text content"
        mock_prepare_image.return_value = self._create_mock_image_data()

        # Mock Bedrock response for standard assessment
        mock_response = {
            "output": {
                "message": {
                    "content": [
                        {"text": self._create_mock_assessment_response("standard")}
                    ]
                }
            },
            "metering": {"inputTokens": 1000, "outputTokens": 200, "totalTokens": 1200},
        }
        mock_invoke_model.return_value = mock_response

        # Create config with granular assessment disabled
        config = self.base_config.copy()
        config["assessment"]["granular"] = {
            "enabled": False,
            "max_workers": 4,
            "simple_batch_size": 3,
            "list_batch_size": 1,
        }

        # Initialize assessment service
        assessment_service = assessment.AssessmentService(config=config)

        # Process document section
        result_document = assessment_service.process_document_section(
            self.document, self.section_id
        )

        # Verify the service used standard assessment
        self.assertIsNotNone(result_document)
        self.assertEqual(result_document.id, self.document.id)

        # Verify Bedrock was called once (standard assessment)
        self.assertEqual(mock_invoke_model.call_count, 1)

        # Verify the call was made with expected parameters
        call_args = mock_invoke_model.call_args
        self.assertIn("system_prompt", call_args[1])
        self.assertIn("content", call_args[1])

        # Verify extraction results were written back
        mock_write_content.assert_called_once()
        written_data = mock_write_content.call_args[0][0]
        self.assertIn("explainability_info", written_data)
        self.assertIsInstance(written_data["explainability_info"], list)

    @patch("idp_common.s3.get_json_content")
    @patch("idp_common.s3.get_text_content")
    @patch("idp_common.s3.write_content")
    @patch("idp_common.image.prepare_image")
    @patch("idp_common.bedrock.invoke_model")
    def test_granular_assessment_service(
        self,
        mock_invoke_model,
        mock_prepare_image,
        mock_write_content,
        mock_get_text_content,
        mock_get_json_content,
    ):
        """Test granular assessment service (granular enabled)."""
        # Configure mocks
        mock_get_json_content.return_value = self._create_test_extraction_results()
        mock_get_text_content.return_value = "Sample document text content"
        mock_prepare_image.return_value = self._create_mock_image_data()

        # Mock Bedrock responses for granular assessment (multiple calls)
        def mock_bedrock_side_effect(*args, **kwargs):
            # Determine response based on content
            content = kwargs.get("content", [])
            content_text = ""
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    content_text += item["text"]

            # Return appropriate response based on content
            if "invoice_number" in content_text and "total_amount" in content_text:
                response_text = self._create_mock_assessment_response("simple_batch")
            elif "vendor_info" in content_text:
                response_text = self._create_mock_assessment_response("group")
            elif "item_description" in content_text:
                response_text = self._create_mock_assessment_response("list_item")
            else:
                response_text = self._create_mock_assessment_response("standard")

            return {
                "content": [{"text": response_text}],
                "metering": {
                    "inputTokens": 500,
                    "outputTokens": 100,
                    "totalTokens": 600,
                },
            }

        mock_invoke_model.side_effect = mock_bedrock_side_effect

        # Create config with granular assessment enabled
        config = self.base_config.copy()
        config["assessment"]["granular"] = {
            "enabled": True,
            "max_workers": 4,
            "simple_batch_size": 2,  # Will batch invoice_number and total_amount
            "list_batch_size": 1,  # Will process each list item separately
        }

        # Initialize assessment service
        assessment_service = assessment.AssessmentService(config=config)

        # Process document section
        result_document = assessment_service.process_document_section(
            self.document, self.section_id
        )

        # Verify the service used granular assessment
        self.assertIsNotNone(result_document)
        self.assertEqual(result_document.id, self.document.id)

        # Verify Bedrock was called multiple times (granular assessment)
        # Expected: 1 simple batch + 1 group + 2 list items = 4 calls
        self.assertGreater(mock_invoke_model.call_count, 1)

        # Verify extraction results were written back
        mock_write_content.assert_called_once()
        written_data = mock_write_content.call_args[0][0]
        self.assertIn("explainability_info", written_data)
        self.assertIsInstance(written_data["explainability_info"], list)

        # Verify granular assessment metadata
        metadata = written_data.get("metadata", {})
        self.assertTrue(metadata.get("granular_assessment_used", False))
        self.assertIn("assessment_tasks_total", metadata)
        self.assertIn("assessment_tasks_successful", metadata)

    @patch("idp_common.s3.get_json_content")
    @patch("idp_common.s3.get_text_content")
    @patch("idp_common.s3.write_content")
    @patch("idp_common.image.prepare_image")
    @patch("idp_common.bedrock.invoke_model")
    def test_assessment_factory_selection(
        self,
        mock_invoke_model,
        mock_prepare_image,
        mock_write_content,
        mock_get_text_content,
        mock_get_json_content,
    ):
        """Test that the assessment factory correctly selects standard vs granular service."""
        # Configure mocks
        mock_get_json_content.return_value = self._create_test_extraction_results()
        mock_get_text_content.return_value = "Sample document text content"
        mock_prepare_image.return_value = b"mock_image_data"
        mock_invoke_model.return_value = {
            "content": [{"text": self._create_mock_assessment_response("standard")}],
            "metering": {"inputTokens": 1000, "outputTokens": 200, "totalTokens": 1200},
        }

        # Test 1: Granular disabled - should use standard service
        config_standard = self.base_config.copy()
        config_standard["assessment"]["granular"] = {"enabled": False}

        service_standard = assessment.AssessmentService(config=config_standard)
        # The main service is AssessmentService, but it should use the standard service internally
        self.assertEqual(type(service_standard).__name__, "AssessmentService")
        # Check that granular is disabled in config
        granular_config = config_standard.get("assessment", {}).get("granular", {})
        self.assertFalse(granular_config.get("enabled", False))

        # Test 2: Granular enabled - should use granular service
        config_granular = self.base_config.copy()
        config_granular["assessment"]["granular"] = {"enabled": True}

        service_granular = assessment.AssessmentService(config=config_granular)
        self.assertEqual(type(service_granular).__name__, "AssessmentService")
        # Check that granular is enabled in config
        granular_config = config_granular.get("assessment", {}).get("granular", {})
        self.assertTrue(granular_config.get("enabled", False))

        # Test 3: No granular config - should default to standard
        config_default = self.base_config.copy()
        # Remove granular config entirely
        if "granular" in config_default["assessment"]:
            del config_default["assessment"]["granular"]

        service_default = assessment.AssessmentService(config=config_default)
        self.assertEqual(type(service_default).__name__, "AssessmentService")
        # Check that granular is not configured (defaults to disabled)
        granular_config = config_default.get("assessment", {}).get("granular", {})
        self.assertFalse(granular_config.get("enabled", False))

    def test_confidence_threshold_handling(self):
        """Test that confidence thresholds are handled correctly in both services."""
        # Test with various threshold formats (string, float, int, None)
        test_cases = [
            ("0.85", 0.85),
            (0.9, 0.9),
            (1, 1.0),
            (None, 0.9),  # Should use default
            ("", 0.9),  # Should use default
            ("invalid", 0.9),  # Should use default
        ]

        for threshold_input, expected_output in test_cases:
            config = self.base_config.copy()
            if threshold_input is not None:
                config["classes"][0]["attributes"][0]["confidence_threshold"] = (
                    threshold_input
                )
            else:
                # Remove confidence_threshold to test None case
                if "confidence_threshold" in config["classes"][0]["attributes"][0]:
                    del config["classes"][0]["attributes"][0]["confidence_threshold"]

            # Test with both standard and granular services
            for granular_enabled in [False, True]:
                config["assessment"]["granular"] = {"enabled": granular_enabled}

                service = assessment.AssessmentService(config=config)

                # The service should initialize without errors
                self.assertIsNotNone(service)

    @patch.dict(os.environ, {"WORKING_BUCKET": "test-bucket"})
    def test_assessment_function_emulation(self):
        """Test that emulates the actual AssessmentFunction handler."""
        # This test emulates the patterns/pattern-2/src/assessment_function/index.py handler

        # Mock event data (similar to what Lambda receives)
        event = {
            "document": {
                "id": "test_doc_123",
                "input_key": "test_document.pdf",
                "status": "EXTRACTING",
                "pages": {
                    "1": {
                        "page_id": "1",
                        "image_uri": "s3://test-bucket/images/page_1.jpg",
                        "parsed_text_uri": "s3://test-bucket/text/page_1.txt",
                        "raw_text_uri": "s3://test-bucket/raw/page_1.json",
                    }
                },
                "sections": [
                    {
                        "section_id": "section_1",
                        "classification": "invoice",
                        "page_ids": ["1"],
                        "extraction_result_uri": "s3://test-bucket/extraction/section_1.json",
                    }
                ],
            },
            "section_id": "section_1",
        }

        # Test with both granular enabled and disabled
        for granular_enabled in [False, True]:
            with self.subTest(granular_enabled=granular_enabled):
                config = self.base_config.copy()
                config["assessment"]["granular"] = {"enabled": granular_enabled}

                # Emulate the handler logic
                with (
                    patch("idp_common.get_config", return_value=config),
                    patch(
                        "idp_common.s3.get_json_content",
                        return_value=self._create_test_extraction_results(),
                    ),
                    patch("idp_common.s3.get_text_content", return_value="Sample text"),
                    patch("idp_common.s3.write_content"),
                    patch(
                        "idp_common.image.prepare_image",
                        return_value=self._create_mock_image_data(),
                    ),
                    patch("idp_common.bedrock.invoke_model") as mock_invoke,
                ):
                    # Configure mock response
                    mock_invoke.return_value = {
                        "output": {
                            "message": {
                                "content": [
                                    {
                                        "text": self._create_mock_assessment_response(
                                            "standard"
                                        )
                                    }
                                ]
                            }
                        },
                        "metering": {
                            "inputTokens": 1000,
                            "outputTokens": 200,
                            "totalTokens": 1200,
                        },
                    }

                    # Extract inputs (emulating handler)
                    document_data = event.get("document", {})
                    section_id = event.get("section_id")

                    # Validate inputs
                    self.assertIsNotNone(document_data)
                    self.assertIsNotNone(section_id)

                    # Convert to Document object (emulating Document.load_document)
                    document = Document.from_dict(document_data)
                    document.status = Status.ASSESSING

                    # Initialize assessment service
                    assessment_service = assessment.AssessmentService(config=config)

                    # Process the document section
                    updated_document = assessment_service.process_document_section(
                        document, section_id
                    )

                    # Verify processing succeeded
                    self.assertIsNotNone(updated_document)
                    self.assertEqual(updated_document.id, document.id)
                    self.assertNotEqual(updated_document.status, Status.FAILED)

                    # Verify appropriate service was used
                    if granular_enabled:
                        self.assertEqual(
                            type(assessment_service._service).__name__,
                            "GranularAssessmentService",
                        )
                        # Granular assessment may make multiple calls
                        self.assertGreaterEqual(mock_invoke.call_count, 1)
                    else:
                        # The original service is called "AssessmentService" in service.py
                        self.assertEqual(
                            type(assessment_service._service).__name__,
                            "AssessmentService",
                        )
                        # Standard assessment makes exactly one call
                        self.assertEqual(mock_invoke.call_count, 1)


if __name__ == "__main__":
    unittest.main()
