# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for the summarization service module.
"""

# ruff: noqa: E402, I001
# The above line disables E402 (module level import not at top of file) and I001 (import block sorting) for this file

import pytest

# Mock dependencies before importing modules
import warnings
from unittest.mock import MagicMock, patch

# Import standard library modules
import json

# Import application modules
from idp_common.summarization.service import SummarizationService
from idp_common.summarization.models import DocumentSummary
from idp_common.models import Document, Page, Section, Status


@pytest.fixture(autouse=True)
def suppress_datetime_warning():
    """Fixture to suppress the datetime.utcnow() deprecation warning from botocore."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="datetime.datetime.utcnow\\(\\) is deprecated",
            category=DeprecationWarning,
        )
        yield


@pytest.mark.unit
class TestSummarizationService:
    """Tests for the SummarizationService class."""

    @pytest.fixture
    def mock_config(self):
        """Fixture providing a mock configuration."""
        return {
            "summarization": {
                "model": "anthropic.claude-3-sonnet-20240229-v1:0",
                "temperature": 0.0,
                "top_k": 5,
                "system_prompt": "You are a helpful assistant that summarizes documents.",
                "task_prompt": "Please summarize the following document: {DOCUMENT_TEXT}",
            }
        }

    @pytest.fixture
    def service(self, mock_config):
        """Fixture providing a SummarizationService instance."""
        return SummarizationService(region="us-west-2", config=mock_config)

    @pytest.fixture
    def sample_document(self):
        """Fixture providing a sample document with pages and sections."""
        doc = Document(
            id="test-doc",
            input_key="test-document.pdf",
            input_bucket="input-bucket",
            output_bucket="output-bucket",
            status=Status.EXTRACTING,
        )

        # Add pages
        doc.pages = {
            "1": Page(
                page_id="1",
                parsed_text_uri="s3://input-bucket/test-document.pdf/pages/1/text.txt",
            ),
            "2": Page(
                page_id="2",
                parsed_text_uri="s3://input-bucket/test-document.pdf/pages/2/text.txt",
            ),
            "3": Page(
                page_id="3",
                parsed_text_uri="s3://input-bucket/test-document.pdf/pages/3/text.txt",
            ),
        }

        # Add sections
        doc.sections = [
            Section(
                section_id="1",
                classification="invoice",
                page_ids=["1", "2"],
                extraction_result_uri="s3://input-bucket/test-document.pdf/sections/1/result.json",
            ),
            Section(
                section_id="2",
                classification="receipt",
                page_ids=["3"],
                extraction_result_uri="s3://input-bucket/test-document.pdf/sections/2/result.json",
            ),
        ]

        return doc

    def test_init(self, mock_config):
        """Test initialization with configuration."""
        service = SummarizationService(
            region="us-west-2", config=mock_config, backend="bedrock"
        )

        assert service.region == "us-west-2"
        assert service.backend == "bedrock"
        assert service.bedrock_model == "anthropic.claude-3-sonnet-20240229-v1:0"

    def test_init_invalid_backend(self, mock_config):
        """Test initialization with invalid backend."""
        service = SummarizationService(
            region="us-west-2", config=mock_config, backend="invalid"
        )

        assert service.backend == "bedrock"  # Should fall back to bedrock

    def test_init_missing_model(self):
        """Test initialization with missing model ID."""
        with pytest.raises(ValueError, match="No model ID specified"):
            SummarizationService(region="us-west-2", config={})

    def test_get_summarization_config(self, service):
        """Test getting and validating summarization configuration."""
        config = service._get_summarization_config()

        assert config["model_id"] == "anthropic.claude-3-sonnet-20240229-v1:0"
        assert config["temperature"] == 0.0
        assert config["top_k"] == 5
        assert "You are a helpful assistant" in config["system_prompt"]
        assert "Please summarize" in config["task_prompt"]

    def test_get_summarization_config_missing_prompts(self, mock_config):
        """Test getting configuration with missing prompts."""
        # Remove system_prompt
        config_no_system = mock_config.copy()
        config_no_system["summarization"] = mock_config["summarization"].copy()
        del config_no_system["summarization"]["system_prompt"]

        service = SummarizationService(region="us-west-2", config=config_no_system)
        with pytest.raises(ValueError, match="No system_prompt found"):
            service._get_summarization_config()

        # Remove task_prompt
        config_no_task = mock_config.copy()
        config_no_task["summarization"] = mock_config["summarization"].copy()
        del config_no_task["summarization"]["task_prompt"]

        service = SummarizationService(region="us-west-2", config=config_no_task)
        with pytest.raises(ValueError, match="No task_prompt found"):
            service._get_summarization_config()

    def test_extract_json_code_block(self):
        """Test extracting JSON from code block format."""
        text = 'Here is the summary:\n```json\n{"summary": "This is a summary", "key_points": ["Point 1", "Point 2"]}\n```\nI hope this helps!'
        service = SummarizationService(
            region="us-west-2",
            config={
                "summarization": {
                    "model": "test-model",
                    "system_prompt": "test",
                    "task_prompt": "test",
                }
            },
        )

        json_str = service._extract_json(text)
        parsed = json.loads(json_str)

        assert parsed["summary"] == "This is a summary"
        assert parsed["key_points"] == ["Point 1", "Point 2"]

    def test_extract_json_braces(self):
        """Test extracting JSON between braces."""
        text = 'Here is the summary: {"summary": "This is a summary", "key_points": ["Point 1", "Point 2"]} I hope this helps!'
        service = SummarizationService(
            region="us-west-2",
            config={
                "summarization": {
                    "model": "test-model",
                    "system_prompt": "test",
                    "task_prompt": "test",
                }
            },
        )

        json_str = service._extract_json(text)
        parsed = json.loads(json_str)

        assert parsed["summary"] == "This is a summary"
        assert parsed["key_points"] == ["Point 1", "Point 2"]

    def test_extract_json_normalized(self):
        """Test extracting JSON with normalization."""
        text = 'Here is the summary: {\n"summary": "This is a summary",\n"key_points": ["Point 1", "Point 2"]\n} I hope this helps!'
        service = SummarizationService(
            region="us-west-2",
            config={
                "summarization": {
                    "model": "test-model",
                    "system_prompt": "test",
                    "task_prompt": "test",
                }
            },
        )

        json_str = service._extract_json(text)
        parsed = json.loads(json_str)

        assert parsed["summary"] == "This is a summary"
        assert parsed["key_points"] == ["Point 1", "Point 2"]

    def test_extract_json_empty(self):
        """Test extracting JSON from empty text."""
        service = SummarizationService(
            region="us-west-2",
            config={
                "summarization": {
                    "model": "test-model",
                    "system_prompt": "test",
                    "task_prompt": "test",
                }
            },
        )

        json_str = service._extract_json("")
        assert json_str == ""

    def test_create_error_summary(self, service):
        """Test creating an error summary."""
        error_message = "Test error message"
        summary = service._create_error_summary(error_message)

        assert summary.content["error"] == "Error generating summary"
        assert summary.metadata["error"] == error_message

    @patch("idp_common.bedrock.invoke_model")
    def test_invoke_bedrock_model(self, mock_invoke_model, service):
        """Test invoking Bedrock model."""
        # Configure mock
        mock_invoke_model.return_value = {
            "response": {
                "output": {"message": {"content": [{"text": "Test response"}]}}
            },
            "metering": {"input_tokens": 100, "output_tokens": 50},
        }

        content = [{"text": "Test content"}]
        config = {
            "model_id": "test-model",
            "system_prompt": "Test system prompt",
            "temperature": 0.0,
            "top_k": 5,
            "top_p": 0.1,
            "max_tokens": 5000,
        }

        result = service._invoke_bedrock_model(content, config)

        # Verify invoke_model was called with correct parameters
        mock_invoke_model.assert_called_once_with(
            model_id=config["model_id"],
            system_prompt=config["system_prompt"],
            content=content,
            temperature=config["temperature"],
            top_k=config["top_k"],
            top_p=config["top_p"],
            max_tokens=config["max_tokens"],
        )

        # Verify result
        assert (
            result["response"]["output"]["message"]["content"][0]["text"]
            == "Test response"
        )
        assert result["metering"]["input_tokens"] == 100
        assert result["metering"]["output_tokens"] == 50

    @patch("idp_common.bedrock.invoke_model")
    def test_process_text_success(self, mock_invoke_model, service):
        """Test processing text successfully."""
        # Configure mock
        mock_invoke_model.return_value = {
            "response": {
                "output": {
                    "message": {
                        "content": [
                            {
                                "text": '{"summary": "This is a summary", "key_points": ["Point 1", "Point 2"]}'
                            }
                        ]
                    }
                }
            },
            "metering": {"input_tokens": 100, "output_tokens": 50},
        }

        result = service.process_text("Test document text")

        # Verify result
        assert result.content["summary"] == "This is a summary"
        assert result.content["key_points"] == ["Point 1", "Point 2"]
        assert result.metadata["metering"]["input_tokens"] == 100
        assert result.metadata["metering"]["output_tokens"] == 50

    @patch("idp_common.bedrock.invoke_model")
    def test_process_text_empty(self, mock_invoke_model, service):
        """Test processing empty text."""
        result = service.process_text("")

        # Verify result
        assert result.content["error"] == "Error generating summary"
        assert result.metadata["error"] == "Empty text provided"

        # Verify invoke_model was not called
        mock_invoke_model.assert_not_called()

    @pytest.mark.skip(reason="Temporarily disabled due to exception handling issues")
    @patch("idp_common.bedrock.invoke_model")
    def test_process_text_error(self, mock_invoke_model, service):
        """Test processing text with error."""
        # Configure mock to raise exception
        mock_invoke_model.side_effect = Exception("Test error")

        # Expect exception to be raised
        with pytest.raises(Exception, match="Test error"):
            service.process_text("Test document text")

    @patch("idp_common.s3.get_text_content")
    @patch("idp_common.s3.write_content")
    @patch("idp_common.summarization.service.SummarizationService.process_text")
    @patch("idp_common.utils.merge_metering_data")
    def test_process_document_section(
        self,
        mock_merge_metering,
        mock_process_text,
        mock_write_content,
        mock_get_text_content,
        service,
        sample_document,
    ):
        """Test processing a document section."""
        # Configure mocks
        mock_get_text_content.side_effect = ["Page 1 text", "Page 2 text"]

        summary = DocumentSummary(
            content={
                "summary": "This is a summary",
                "key_points": ["Point 1", "Point 2"],
            },
            metadata={"metering": {"input_tokens": 100, "output_tokens": 50}},
        )
        mock_process_text.return_value = summary

        # Configure merge_metering_data mock to return expected structure
        mock_merge_metering.return_value = {"input_tokens": 100, "output_tokens": 50}

        # Process section
        result, section_metering = service.process_document_section(
            sample_document, "1"
        )

        # Verify get_text_content was called for each page
        assert mock_get_text_content.call_count == 2

        # Verify process_text was called with combined text
        mock_process_text.assert_called_once()
        call_args = mock_process_text.call_args[0][0]
        assert "<page-number>1</page-number>" in call_args
        assert "<page-number>2</page-number>" in call_args
        assert "Page 1 text" in call_args
        assert "Page 2 text" in call_args

        # Verify write_content was called twice (JSON and Markdown)
        assert mock_write_content.call_count == 2

        # Verify section attributes were updated
        section = next(s for s in result.sections if s.section_id == "1")
        assert "summary_uri" in section.attributes
        assert "summary_md_uri" in section.attributes

        # Verify section metering data was returned
        assert section_metering == {"input_tokens": 100, "output_tokens": 50}

    @patch("idp_common.s3.get_text_content")
    def test_process_document_section_no_pages(
        self, mock_get_text_content, service, sample_document
    ):
        """Test processing a document section with no pages."""
        # Modify section to have no pages
        for section in sample_document.sections:
            if section.section_id == "1":
                section.page_ids = []

        # Process section
        result, section_metering = service.process_document_section(
            sample_document, "1"
        )

        # Verify get_text_content was not called
        mock_get_text_content.assert_not_called()

        # Verify error was added
        assert "Section 1 has no page IDs" in result.errors

        # Verify empty metering data was returned for error case
        assert section_metering == {}

    @patch("idp_common.s3.get_text_content")
    def test_process_document_section_invalid_section(
        self, mock_get_text_content, service, sample_document
    ):
        """Test processing an invalid document section."""
        # Process non-existent section
        result, section_metering = service.process_document_section(
            sample_document, "999"
        )

        # Verify get_text_content was not called
        mock_get_text_content.assert_not_called()

        # Verify error was added
        assert "Section 999 not found in document" in result.errors

        # Verify empty metering data was returned for error case
        assert section_metering == {}

    @patch("concurrent.futures.ThreadPoolExecutor")
    @patch("idp_common.s3.get_json_content")
    @patch("idp_common.s3.write_content")
    def test_process_document(
        self,
        mock_write_content,
        mock_get_json_content,
        mock_executor,
        service,
        sample_document,
    ):
        """Test processing a complete document."""
        # Configure mocks
        mock_executor_instance = MagicMock()
        mock_executor.return_value.__enter__.return_value = mock_executor_instance

        # Mock the future results
        future1 = MagicMock()
        future2 = MagicMock()

        # Configure the futures to return (document, metering) tuples
        doc1 = sample_document
        doc1.sections[0].attributes = {
            "summary_uri": "s3://output-bucket/test-document.pdf/sections/1/summary.json"
        }
        section1_metering = {"input_tokens": 100, "output_tokens": 50}
        future1.result.return_value = (doc1, section1_metering)

        doc2 = sample_document
        doc2.sections[1].attributes = {
            "summary_uri": "s3://output-bucket/test-document.pdf/sections/2/summary.json"
        }
        section2_metering = {"input_tokens": 150, "output_tokens": 75}
        future2.result.return_value = (doc2, section2_metering)

        # Configure the executor to return the futures
        mock_executor_instance.submit.side_effect = [future1, future2]

        # Mock as_completed to return our futures in order
        with patch("concurrent.futures.as_completed", return_value=[future1, future2]):
            # Mock get_json_content to return summary content
            mock_get_json_content.side_effect = [
                {"summary": "Section 1 summary"},
                {"summary": "Section 2 summary"},
            ]

            # Process document
            result = service.process_document(sample_document)

            # Verify executor was used to process sections in parallel
            assert mock_executor_instance.submit.call_count == 2

            # Verify write_content was called for combined results
            assert mock_write_content.call_count == 2

            # Verify document has summarization_result
            assert result.summarization_result is not None
            assert result.summary_report_uri is not None

    @patch("idp_common.s3.get_text_content")
    @patch("idp_common.s3.write_content")
    @patch("idp_common.summarization.service.SummarizationService.process_text")
    @patch("idp_common.utils.merge_metering_data")
    def test_process_document_as_whole(
        self,
        mock_merge_metering,
        mock_process_text,
        mock_write_content,
        mock_get_text_content,
        service,
        sample_document,
    ):
        """Test processing a document as a whole."""
        # Configure mocks
        mock_get_text_content.side_effect = [
            "Page 1 text",
            "Page 2 text",
            "Page 3 text",
        ]

        summary = DocumentSummary(
            content={
                "summary": "This is a summary",
                "key_points": ["Point 1", "Point 2"],
            },
            metadata={"metering": {"input_tokens": 100, "output_tokens": 50}},
        )
        mock_process_text.return_value = summary

        # Configure merge_metering_data mock to return expected structure
        mock_merge_metering.return_value = {"input_tokens": 100, "output_tokens": 50}

        # Remove sections to force processing as whole
        sample_document.sections = []

        # Process document
        result = service._process_document_as_whole(sample_document)

        # Verify get_text_content was called for each page
        assert mock_get_text_content.call_count == 3

        # Verify process_text was called with combined text
        mock_process_text.assert_called_once()
        call_args = mock_process_text.call_args[0][0]
        assert "<page-number>1</page-number>" in call_args
        assert "<page-number>2</page-number>" in call_args
        assert "<page-number>3</page-number>" in call_args

        # Verify write_content was called twice (JSON and Markdown)
        assert mock_write_content.call_count == 2

        # Verify document has summarization_result
        assert result.summarization_result is not None
        assert result.summary_report_uri is not None

        # Verify document metering was updated
        assert result.metering["input_tokens"] == 100
        assert result.metering["output_tokens"] == 50

    def test_update_document_status(self, service, sample_document):
        """Test updating document status."""
        # Test successful update
        result1 = service._update_document_status(sample_document)
        assert result1.status == Status.EXTRACTING  # Status unchanged

        # Test failed update
        result2 = service._update_document_status(
            sample_document, success=False, error_message="Test error"
        )
        assert result2.status == Status.FAILED
        assert "Test error" in result2.errors
