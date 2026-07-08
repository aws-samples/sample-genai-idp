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
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$id": "invoice",
                    "x-aws-idp-document-type": "invoice",
                    "type": "object",
                    "description": "An invoice document",
                    "properties": {
                        "invoice_number": {
                            "type": "string",
                            "description": "The invoice number",
                        },
                        "invoice_date": {
                            "type": "string",
                            "description": "The invoice date",
                        },
                        "total_amount": {
                            "type": "number",
                            "description": "The total amount",
                        },
                    },
                },
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$id": "receipt",
                    "x-aws-idp-document-type": "receipt",
                    "type": "object",
                    "description": "A receipt document",
                    "properties": {
                        "receipt_number": {
                            "type": "string",
                            "description": "The receipt number",
                        },
                        "date": {"type": "string", "description": "The receipt date"},
                        "amount": {"type": "number", "description": "The total amount"},
                    },
                },
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$id": "bank_statement",
                    "x-aws-idp-document-type": "bank_statement",
                    "type": "object",
                    "description": "Monthly bank account statement",
                    "properties": {
                        "account_number": {
                            "type": "string",
                            "description": "Primary account identifier",
                        },
                        "account_holder_address": {
                            "type": "object",
                            "description": "Complete address information for the account holder",
                            "properties": {
                                "street_number": {
                                    "type": "string",
                                    "description": "House or building number",
                                },
                                "street_name": {
                                    "type": "string",
                                    "description": "Name of the street",
                                },
                                "city": {
                                    "type": "string",
                                    "description": "City name",
                                },
                            },
                        },
                        "transactions": {
                            "type": "array",
                            "description": "List of all transactions in the statement period",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "date": {
                                        "type": "string",
                                        "description": "Transaction date (MM/DD/YYYY)",
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": "Transaction description or merchant name",
                                    },
                                    "amount": {
                                        "type": "number",
                                        "description": "Transaction amount",
                                    },
                                },
                            },
                        },
                    },
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
                    
                    Document image:
                    {DOCUMENT_IMAGE}
                    
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
        # Config is converted to IDPConfig model, verify it has the expected structure
        assert hasattr(service.config, "extraction")
        assert service.config.extraction.model == mock_config["extraction"]["model"]

    def test_get_class_schema(self, service):
        """Test getting JSON Schema for a document class."""
        # Test with existing class
        invoice_schema = service._get_class_schema("invoice")
        assert "properties" in invoice_schema
        assert "invoice_number" in invoice_schema["properties"]
        assert "invoice_date" in invoice_schema["properties"]
        assert "total_amount" in invoice_schema["properties"]

        # Test with non-existent class
        unknown_schema = service._get_class_schema("unknown")
        assert unknown_schema == {}

        # Test case insensitivity
        invoice_schema_upper = service._get_class_schema("INVOICE")
        assert "properties" in invoice_schema_upper

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


@pytest.mark.unit
class TestPerClassExtractionModelOverride:
    """Tests for the per-class extraction model override feature (x-aws-idp-extraction-model)."""

    @pytest.fixture
    def config_with_override(self):
        """Config where one class has x-aws-idp-extraction-model and another does not."""
        return {
            "classes": [
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$id": "simple-receipt",
                    "x-aws-idp-document-type": "simple-receipt",
                    "type": "object",
                    "description": "A simple receipt",
                    "properties": {
                        "total": {
                            "type": "string",
                            "description": "Total amount",
                        },
                    },
                },
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$id": "complex-form",
                    "x-aws-idp-document-type": "complex-form",
                    "x-aws-idp-extraction-model": "us.anthropic.claude-sonnet-4-20250514-v1:0",
                    "type": "object",
                    "description": "A complex financial form",
                    "properties": {
                        "account_number": {
                            "type": "string",
                            "description": "Account number",
                        },
                    },
                },
            ],
            "extraction": {
                "model": "us.amazon.nova-pro-v1:0",
                "temperature": 0.0,
                "top_k": 5,
                "system_prompt": "You are a document extraction assistant.",
                "task_prompt": dedent("""
                    Extract fields from this {DOCUMENT_CLASS} document:
                    {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}
                    Document text: {DOCUMENT_TEXT}
                    {DOCUMENT_IMAGE}
                """),
            },
        }

    @pytest.fixture
    def service_with_override(self, config_with_override):
        """ExtractionService with per-class model override config."""
        return ExtractionService(region="us-west-2", config=config_with_override)

    @patch("idp_common.bedrock.invoke_model")
    def test_uses_global_model_when_no_override(
        self, mock_invoke_model, service_with_override
    ):
        """When the class schema has no x-aws-idp-extraction-model, use the global model."""
        from idp_common.extraction.service import SectionInfo

        # Set up context for a class WITHOUT override
        service_with_override._class_schema = service_with_override._get_class_schema(
            "simple-receipt"
        )
        service_with_override._class_label = "simple-receipt"
        service_with_override._page_images = []

        mock_invoke_model.return_value = {
            "response": {
                "output": {"message": {"content": [{"text": '{"total": "$42.00"}'}]}}
            },
            "metering": {"tokens": 100},
        }

        section_info = SectionInfo(
            class_label="simple-receipt",
            sorted_page_ids=["1"],
            page_indices=[0],
            output_bucket="bucket",
            output_key="key",
            output_uri="s3://bucket/key",
            start_page=1,
            end_page=1,
        )

        service_with_override._invoke_extraction_model(
            content=[{"text": "test"}],
            system_prompt="test",
            section_info=section_info,
        )

        # Verify the global model was used
        mock_invoke_model.assert_called_once()
        call_kwargs = mock_invoke_model.call_args
        assert call_kwargs.kwargs["model_id"] == "us.amazon.nova-pro-v1:0"

    @patch("idp_common.bedrock.invoke_model")
    def test_uses_override_model_when_specified(
        self, mock_invoke_model, service_with_override
    ):
        """When the class schema has x-aws-idp-extraction-model, use the override model."""
        from idp_common.extraction.service import SectionInfo

        # Set up context for a class WITH override
        service_with_override._class_schema = service_with_override._get_class_schema(
            "complex-form"
        )
        service_with_override._class_label = "complex-form"
        service_with_override._page_images = []

        mock_invoke_model.return_value = {
            "response": {
                "output": {
                    "message": {"content": [{"text": '{"account_number": "12345"}'}]}
                }
            },
            "metering": {"tokens": 100},
        }

        section_info = SectionInfo(
            class_label="complex-form",
            sorted_page_ids=["1"],
            page_indices=[0],
            output_bucket="bucket",
            output_key="key",
            output_uri="s3://bucket/key",
            start_page=1,
            end_page=1,
        )

        service_with_override._invoke_extraction_model(
            content=[{"text": "test"}],
            system_prompt="test",
            section_info=section_info,
        )

        # Verify the per-class override model was used
        mock_invoke_model.assert_called_once()
        call_kwargs = mock_invoke_model.call_args
        assert (
            call_kwargs.kwargs["model_id"]
            == "us.anthropic.claude-sonnet-4-20250514-v1:0"
        )

    @patch("idp_common.bedrock.invoke_model")
    def test_override_is_logged(self, mock_invoke_model, service_with_override, caplog):
        """Verify that using a per-class model override produces an info log message."""
        import logging

        from idp_common.extraction.service import SectionInfo

        service_with_override._class_schema = service_with_override._get_class_schema(
            "complex-form"
        )
        service_with_override._class_label = "complex-form"
        service_with_override._page_images = []

        mock_invoke_model.return_value = {
            "response": {
                "output": {
                    "message": {"content": [{"text": '{"account_number": "12345"}'}]}
                }
            },
            "metering": {"tokens": 100},
        }

        section_info = SectionInfo(
            class_label="complex-form",
            sorted_page_ids=["1"],
            page_indices=[0],
            output_bucket="bucket",
            output_key="key",
            output_uri="s3://bucket/key",
            start_page=1,
            end_page=1,
        )

        with caplog.at_level(logging.INFO, logger="idp_common.extraction.service"):
            service_with_override._invoke_extraction_model(
                content=[{"text": "test"}],
                system_prompt="test",
                section_info=section_info,
            )

        assert any(
            "per-class extraction model override" in record.message
            and "complex-form" in record.message
            for record in caplog.records
        )

    def test_schema_constant_exists(self):
        """Verify the X_AWS_IDP_EXTRACTION_MODEL constant is defined."""
        from idp_common.config.schema_constants import X_AWS_IDP_EXTRACTION_MODEL

        assert X_AWS_IDP_EXTRACTION_MODEL == "x-aws-idp-extraction-model"

    def test_clean_schema_removes_extraction_model(self, service_with_override):
        """Verify that x-aws-idp-extraction-model is stripped from prompts."""
        schema_with_override = service_with_override._get_class_schema("complex-form")
        assert "x-aws-idp-extraction-model" in schema_with_override

        cleaned = service_with_override._clean_schema_for_prompt(schema_with_override)
        assert "x-aws-idp-extraction-model" not in cleaned


@pytest.mark.unit
class TestPerClassExtractionPromptOverride:
    """Tests for per-class extraction prompt overrides.

    Covers x-aws-idp-extraction-system-prompt and
    x-aws-idp-extraction-task-prompt.
    """

    @pytest.fixture
    def config_with_prompt_override(self):
        """Config where one class overrides prompts and another does not."""
        return {
            "classes": [
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$id": "simple-receipt",
                    "x-aws-idp-document-type": "simple-receipt",
                    "type": "object",
                    "description": "A simple receipt",
                    "properties": {
                        "total": {
                            "type": "string",
                            "description": "Total amount",
                        },
                    },
                },
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$id": "w2",
                    "x-aws-idp-document-type": "w2",
                    "x-aws-idp-extraction-system-prompt": "You are an expert W2 extractor.",
                    "x-aws-idp-extraction-task-prompt": dedent("""
                        Extract these attributes from this {DOCUMENT_CLASS}:
                        {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}
                        Text: {DOCUMENT_TEXT}
                    """),
                    "type": "object",
                    "description": "A W2 tax form",
                    "properties": {
                        "employee_name": {
                            "type": "string",
                            "description": "Employee name",
                        },
                    },
                },
            ],
            "extraction": {
                "model": "us.amazon.nova-pro-v1:0",
                "temperature": 0.0,
                "top_k": 5,
                "system_prompt": "You are a generic document extraction assistant.",
                "task_prompt": dedent("""
                    Extract fields from this {DOCUMENT_CLASS} document:
                    {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}
                    Document text: {DOCUMENT_TEXT}
                """),
            },
        }

    @pytest.fixture
    def service_with_prompt_override(self, config_with_prompt_override):
        """ExtractionService with per-class prompt override config."""
        return ExtractionService(region="us-west-2", config=config_with_prompt_override)

    def _set_context(self, service, class_label):
        """Populate the instance prompt-context for a given class."""
        service._class_schema = service._get_class_schema(class_label)
        service._class_label = class_label
        service._document_text = "Some document text"
        service._attribute_descriptions = "field: description"
        service._page_images = []
        service._image_uris = []

    def test_uses_global_prompts_when_no_override(self, service_with_prompt_override):
        """A class without prompt overrides uses the global prompts."""
        self._set_context(service_with_prompt_override, "simple-receipt")

        content, system_prompt = service_with_prompt_override._build_extraction_content(
            document=Document(id="doc-1"),
            page_images=[],
        )

        assert system_prompt == "You are a generic document extraction assistant."
        combined = " ".join(item.get("text", "") for item in content)
        assert "Extract fields from this simple-receipt document" in combined

    def test_uses_override_system_prompt_when_specified(
        self, service_with_prompt_override
    ):
        """A class with a system prompt override uses it instead of the global."""
        self._set_context(service_with_prompt_override, "w2")

        _content, system_prompt = (
            service_with_prompt_override._build_extraction_content(
                document=Document(id="doc-1"),
                page_images=[],
            )
        )

        assert system_prompt == "You are an expert W2 extractor."

    def test_uses_override_task_prompt_with_substitution(
        self, service_with_prompt_override
    ):
        """The override task prompt is used and placeholders are substituted."""
        self._set_context(service_with_prompt_override, "w2")

        content, _system_prompt = (
            service_with_prompt_override._build_extraction_content(
                document=Document(id="doc-1"),
                page_images=[],
            )
        )

        combined = " ".join(item.get("text", "") for item in content)
        # Override-specific wording present, global wording absent
        assert "Extract these attributes from this w2" in combined
        assert "Extract fields from this" not in combined
        # Placeholders substituted, not left literal
        assert "{DOCUMENT_CLASS}" not in combined
        assert "{DOCUMENT_TEXT}" not in combined
        assert "Some document text" in combined
        assert "field: description" in combined

    def test_override_is_logged(self, service_with_prompt_override, caplog):
        """Using prompt overrides produces info log messages."""
        import logging

        self._set_context(service_with_prompt_override, "w2")

        with caplog.at_level(logging.INFO, logger="idp_common.extraction.service"):
            service_with_prompt_override._build_extraction_content(
                document=Document(id="doc-1"),
                page_images=[],
            )

        assert any(
            "per-class extraction system prompt override" in record.message
            and "w2" in record.message
            for record in caplog.records
        )
        assert any(
            "per-class extraction task prompt override" in record.message
            and "w2" in record.message
            for record in caplog.records
        )

    def test_schema_constants_exist(self):
        """Verify the prompt override constants are defined."""
        from idp_common.config.schema_constants import (
            X_AWS_IDP_EXTRACTION_SYSTEM_PROMPT,
            X_AWS_IDP_EXTRACTION_TASK_PROMPT,
        )

        assert (
            X_AWS_IDP_EXTRACTION_SYSTEM_PROMPT == "x-aws-idp-extraction-system-prompt"
        )
        assert X_AWS_IDP_EXTRACTION_TASK_PROMPT == "x-aws-idp-extraction-task-prompt"

    def test_clean_schema_removes_prompt_overrides(self, service_with_prompt_override):
        """Verify the prompt override keys are stripped from prompts."""
        schema = service_with_prompt_override._get_class_schema("w2")
        assert "x-aws-idp-extraction-system-prompt" in schema
        assert "x-aws-idp-extraction-task-prompt" in schema

        cleaned = service_with_prompt_override._clean_schema_for_prompt(schema)
        assert "x-aws-idp-extraction-system-prompt" not in cleaned
        assert "x-aws-idp-extraction-task-prompt" not in cleaned


@pytest.mark.unit
class TestNormalizeTableParsingStats:
    """The display-time guard that clamps merged table-parsing stats."""

    def test_drops_internal_rate_weight(self):
        out = ExtractionService._normalize_table_parsing_stats(
            {"rows_parsed": 100, "_rate_weight": 100, "parse_success_rate": 0.9}
        )
        assert "_rate_weight" not in out
        assert out["rows_parsed"] == 100

    def test_clamps_out_of_range_rate_and_confidence(self):
        # Defense in depth: even if a merge regression slips through, the report
        # can never show a 500% rate / 496% confidence again.
        out = ExtractionService._normalize_table_parsing_stats(
            {"parse_success_rate": 5.0, "avg_confidence": 496.1}
        )
        assert out["parse_success_rate"] == 1.0
        assert out["avg_confidence"] == 100.0

    def test_leaves_valid_values_untouched(self):
        out = ExtractionService._normalize_table_parsing_stats(
            {"parse_success_rate": 0.98, "avg_confidence": 98.4}
        )
        assert out["parse_success_rate"] == pytest.approx(0.98)
        assert out["avg_confidence"] == pytest.approx(98.4)


@pytest.mark.unit
class TestGroundShardAssessment:
    """Per-shard OCR grounding: a shard grounds its OWN rows against ONLY its own
    pages, so grounding scales per-shard instead of a full-section merge sweep."""

    def _service(self):
        config = {
            "classes": [
                {
                    "$id": "stmt",
                    "type": "object",
                    "properties": {
                        "Transactions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"Amount": {"type": "string"}},
                            },
                        }
                    },
                }
            ],
            "extraction": {
                "model": "anthropic.claude-3-sonnet-20240229-v1:0",
                "temperature": 0.0,
                "top_k": 5,
                "system_prompt": "sys",
                "task_prompt": "task {DOCUMENT_TEXT}",
            },
        }
        return ExtractionService(region="us-west-2", config=config)

    def _section_info(self, page_ids):
        from idp_common.extraction.service import SectionInfo

        return SectionInfo(
            class_label="stmt",
            sorted_page_ids=page_ids,
            page_indices=[int(p) - 1 for p in page_ids],
            output_bucket="out",
            output_key="k",
            output_uri="s3://out/k",
            start_page=int(page_ids[0]),
            end_page=int(page_ids[-1]),
        )

    def test_grounds_only_shard_pages(self):
        """The shard for pages 3-4 loads OCR for exactly those page_ids and grounds
        its rows against them — NOT the whole section's pages."""
        service = self._service()
        service._class_schema = service._get_class_schema("stmt")

        # 6-page section; this shard covers global pages 3-4 (0-based slice 2:4).
        section_info = self._section_info(["1", "2", "3", "4", "5", "6"])
        payload = {"page_start": 2, "page_end": 4}

        assessment = {
            "Transactions": [
                {"Amount": {"confidence": 0.9}},
                {"Amount": {"confidence": 0.9}},
            ]
        }
        extracted = {"Transactions": [{"Amount": "10.00"}, {"Amount": "20.00"}]}

        captured = {}

        def fake_load(pages, page_ids):
            captured["page_ids"] = list(page_ids)
            return {3: {"lines": []}}  # non-empty so grounding proceeds

        def fake_ground(assess, extraction, pd, mode, schema, skip_grounded=False):
            captured["mode"] = mode
            captured["schema"] = schema
            captured["skip_grounded"] = skip_grounded
            # tag a leaf so we can assert it ran in place
            assess["Transactions"][0]["Amount"]["geometry_source"] = "ocr"
            return assess

        with (
            patch(
                "idp_common.assessment.ocr_grounding.load_page_ocr_data",
                side_effect=fake_load,
            ),
            patch(
                "idp_common.assessment.ocr_grounding.ground_assessment_geometry",
                side_effect=fake_ground,
            ),
        ):
            service._ground_shard_assessment(
                assessment=assessment,
                extracted_fields=extracted,
                payload=payload,
                document=Document(id="d", input_key="k"),
                section_info=section_info,
                geometry_mode="ocr_only",
            )

        # Scoped to exactly the shard's global page_ids (3, 4) — not all six.
        assert captured["page_ids"] == ["3", "4"]
        assert captured["mode"] == "ocr_only"
        # Grounded in place on the passed assessment object.
        assert assessment["Transactions"][0]["Amount"]["geometry_source"] == "ocr"

    def test_noop_on_empty_assessment(self):
        service = self._service()
        # Should not raise or call load when assessment is empty.
        with patch(
            "idp_common.assessment.ocr_grounding.load_page_ocr_data"
        ) as mock_load:
            service._ground_shard_assessment(
                assessment={},
                extracted_fields={"Transactions": []},
                payload={"page_start": 0, "page_end": 1},
                document=Document(id="d", input_key="k"),
                section_info=self._section_info(["1"]),
                geometry_mode="ocr_only",
            )
        mock_load.assert_not_called()

    def test_grounding_failure_is_swallowed(self):
        """A grounding exception must never propagate out of the shard."""
        service = self._service()
        service._class_schema = service._get_class_schema("stmt")
        with patch(
            "idp_common.assessment.ocr_grounding.load_page_ocr_data",
            side_effect=RuntimeError("boom"),
        ):
            # No exception should escape.
            service._ground_shard_assessment(
                assessment={"Transactions": [{"Amount": {"confidence": 0.9}}]},
                extracted_fields={"Transactions": [{"Amount": "10.00"}]},
                payload={"page_start": 0, "page_end": 1},
                document=Document(id="d", input_key="k"),
                section_info=self._section_info(["1"]),
                geometry_mode="ocr_only",
            )
