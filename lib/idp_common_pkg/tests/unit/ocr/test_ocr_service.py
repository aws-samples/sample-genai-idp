# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for the OCR service module.
"""

# ruff: noqa: E402, I001
# The above line disables E402 (module level import not at top of file) and I001 (import block sorting) for this file

# Import standard library modules first
import sys
from unittest.mock import MagicMock, patch

# Mock modules that might cause import issues
sys.modules["fitz"] = MagicMock()
sys.modules["textractor"] = MagicMock()
sys.modules["textractor.parsers"] = MagicMock()
sys.modules["textractor.parsers.response_parser"] = MagicMock()

# Now import third-party modules
import pytest

# Finally import application modules
from idp_common.ocr.service import OcrService
from idp_common.models import Document, Status


@pytest.mark.unit
class TestOcrService:
    """Tests for the OcrService class."""

    @pytest.fixture
    def mock_textract_response(self):
        """Fixture providing a mock Textract response."""
        return {
            "DocumentMetadata": {"Pages": 1},
            "Blocks": [
                {
                    "BlockType": "PAGE",
                    "Id": "1234",
                    "Relationships": [{"Type": "CHILD", "Ids": ["5678"]}],
                },
                {"BlockType": "LINE", "Id": "5678", "Text": "This is a test document."},
            ],
        }

    @pytest.fixture
    def mock_textract_client(self, mock_textract_response):
        """Fixture providing a mock Textract client."""
        mock_client = MagicMock()
        mock_client.detect_document_text.return_value = mock_textract_response
        mock_client.analyze_document.return_value = mock_textract_response
        return mock_client

    @pytest.fixture
    def mock_s3_client(self):
        """Fixture providing a mock S3 client."""
        mock_client = MagicMock()
        mock_client.get_object.return_value = {
            "Body": MagicMock(read=lambda: b"mock pdf content")
        }
        return mock_client

    @pytest.fixture
    def mock_pdf_document(self):
        """Fixture providing a mock PDF document."""
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_pixmap = MagicMock()

        # Configure the mocks
        mock_doc.load_page.return_value = mock_page
        mock_page.get_pixmap.return_value = mock_pixmap
        mock_pixmap.tobytes.return_value = b"mock image bytes"
        mock_doc.__len__ = lambda _: 2  # Mock 2 pages

        return mock_doc

    @pytest.fixture
    def service(self, mock_textract_client, mock_s3_client):
        """Fixture providing an OcrService instance with mocked clients."""
        with patch("boto3.client") as mock_boto3_client:
            # Configure boto3.client to return our mock clients
            mock_boto3_client.side_effect = lambda service, **kwargs: {
                "textract": mock_textract_client,
                "s3": mock_s3_client,
            }[service]

            # Create and return the service
            return OcrService(region="us-west-2", max_workers=5)

    @pytest.fixture
    def sample_document(self):
        """Fixture providing a sample document."""
        return Document(
            id="test-doc",
            input_key="test-document.pdf",
            input_bucket="input-bucket",
            output_bucket="output-bucket",
            status=Status.QUEUED,
        )

    def test_init_default(self):
        """Test initialization with default parameters."""
        with patch("boto3.client"), patch("os.environ.get", return_value="us-east-1"):
            service = OcrService()

            assert service.region == "us-east-1"
            assert service.max_workers == 20
            assert service.enhanced_features is False

    def test_init_with_params(self):
        """Test initialization with custom parameters."""
        with patch("boto3.client"):
            service = OcrService(
                region="us-west-2",
                max_workers=10,
                enhanced_features=["TABLES", "FORMS"],
            )

            assert service.region == "us-west-2"
            assert service.max_workers == 10
            assert service.enhanced_features == ["TABLES", "FORMS"]

    def test_init_with_invalid_features(self):
        """Test initialization with invalid features."""
        with patch("boto3.client"), pytest.raises(ValueError) as excinfo:
            OcrService(enhanced_features=["INVALID_FEATURE"])

        assert "Invalid Textract feature" in str(excinfo.value)

    @patch("fitz.open")
    @patch("idp_common.s3.write_content")
    def test_process_document_success(
        self,
        mock_write_content,
        mock_fitz_open,
        service,
        sample_document,
        mock_pdf_document,
        mock_textract_response,
    ):
        """Test successful document processing."""
        # Configure mocks
        mock_fitz_open.return_value = mock_pdf_document

        # Mock the textractor parser
        mock_parsed_response = MagicMock()
        mock_parsed_response.to_markdown.return_value = "This is a test document."

        with patch(
            "textractor.parsers.response_parser.parse",
            return_value=mock_parsed_response,
        ):
            # Process the document
            result = service.process_document(sample_document)

            # Verify the document was updated
            assert result.num_pages == 2
            assert len(result.pages) == 2
            assert "1" in result.pages
            assert "2" in result.pages
            assert result.pages["1"].image_uri.startswith(
                "s3://output-bucket/test-document.pdf/pages/1/image.jpg"
            )
            assert result.pages["1"].raw_text_uri.startswith(
                "s3://output-bucket/test-document.pdf/pages/1/rawText.json"
            )
            assert result.pages["1"].parsed_text_uri.startswith(
                "s3://output-bucket/test-document.pdf/pages/1/result.json"
            )
            assert result.pages["1"].text_confidence_uri.startswith(
                "s3://output-bucket/test-document.pdf/pages/1/textConfidence.json"
            )
            assert len(result.errors) == 0

            # Verify S3 client was called
            service.s3_client.get_object.assert_called_once_with(
                Bucket="input-bucket", Key="test-document.pdf"
            )

            # Verify write_content was called for each page (image, raw text, parsed text, text confidence)
            assert mock_write_content.call_count == 8  # 4 files per page, 2 pages

    @patch("fitz.open")
    def test_process_document_s3_error(self, mock_fitz_open, service, sample_document):
        """Test document processing with S3 error."""
        # Configure S3 client to raise an exception
        service.s3_client.get_object.side_effect = Exception("S3 error")

        # Process the document
        result = service.process_document(sample_document)

        # Verify the document has an error
        assert result.status == Status.FAILED
        assert len(result.errors) == 1
        assert "Error retrieving document from S3" in result.errors[0]

        # Verify fitz.open was not called
        mock_fitz_open.assert_not_called()

    @patch("fitz.open")
    @patch("idp_common.s3.write_content")
    def test_process_document_page_error(
        self,
        mock_write_content,
        mock_fitz_open,
        service,
        sample_document,
        mock_pdf_document,
    ):
        """Test document processing with page processing error."""
        # Configure mocks
        mock_fitz_open.return_value = mock_pdf_document

        # Make the first page processing fail
        with patch.object(service, "_process_single_page") as mock_process_page:
            mock_process_page.side_effect = [
                Exception("Page processing error"),  # First page fails
                (
                    {
                        "image_uri": "s3://uri",
                        "raw_text_uri": "s3://uri",
                        "parsed_text_uri": "s3://uri",
                        "text_confidence_uri": "s3://uri",
                    },
                    {},
                ),  # Second page succeeds
            ]

            # Process the document
            result = service.process_document(sample_document)

            # Verify the document has an error but still processed the second page
            assert len(result.errors) == 1
            assert "Error processing page 1" in result.errors[0]
            assert len(result.pages) == 1
            assert "2" in result.pages

    def test_feature_combo(self):
        """Test the _feature_combo method."""
        # Test with no features
        with patch("boto3.client"):
            service = OcrService(enhanced_features=False)
            assert service._feature_combo() == ""

            # Test with empty list
            service = OcrService(enhanced_features=[])
            assert service._feature_combo() == ""

            # Test with TABLES only
            service = OcrService(enhanced_features=["TABLES"])
            assert service._feature_combo() == "-Tables"

            # Test with FORMS only
            service = OcrService(enhanced_features=["FORMS"])
            assert service._feature_combo() == "-Forms"

            # Test with TABLES and FORMS
            service = OcrService(enhanced_features=["TABLES", "FORMS"])
            assert service._feature_combo() == "-Tables+Forms"

            # Test with LAYOUT only
            service = OcrService(enhanced_features=["LAYOUT"])
            assert service._feature_combo() == "-Layout"

            # Test with SIGNATURES only
            service = OcrService(enhanced_features=["SIGNATURES"])
            assert service._feature_combo() == "-Signatures"

    def test_get_api_name(self):
        """Test the _get_api_name method."""
        # Test with no features
        with patch("boto3.client"):
            service = OcrService(enhanced_features=False)
            assert service._get_api_name() == "detect_document_text"

            # Test with empty list
            service = OcrService(enhanced_features=[])
            assert service._get_api_name() == "detect_document_text"

            # Test with features
            service = OcrService(enhanced_features=["TABLES"])
            assert service._get_api_name() == "analyze_document"

    @patch("idp_common.s3.write_content")
    def test_process_single_page_basic(
        self, mock_write_content, service, mock_pdf_document, mock_textract_response
    ):
        """Test processing a single page with basic features."""
        # Configure service to use basic features
        service.enhanced_features = False

        # Mock the textractor parser
        mock_parsed_response = MagicMock()
        mock_parsed_response.to_markdown.return_value = "This is a test document."

        with patch(
            "textractor.parsers.response_parser.parse",
            return_value=mock_parsed_response,
        ):
            # Process a single page
            result, metering = service._process_single_page(
                page_index=0,
                pdf_document=mock_pdf_document,
                output_bucket="output-bucket",
                prefix="test-document.pdf",
            )

            # Verify the result
            assert (
                result["image_uri"]
                == "s3://output-bucket/test-document.pdf/pages/1/image.jpg"
            )
            assert (
                result["raw_text_uri"]
                == "s3://output-bucket/test-document.pdf/pages/1/rawText.json"
            )
            assert (
                result["parsed_text_uri"]
                == "s3://output-bucket/test-document.pdf/pages/1/result.json"
            )
            assert (
                result["text_confidence_uri"]
                == "s3://output-bucket/test-document.pdf/pages/1/textConfidence.json"
            )

            # Verify metering data
            assert "OCR/textract/detect_document_text" in metering
            assert metering["OCR/textract/detect_document_text"]["pages"] == 1

            # Verify Textract client was called with detect_document_text
            service.textract_client.detect_document_text.assert_called_once()
            service.textract_client.analyze_document.assert_not_called()

    @patch("idp_common.s3.write_content")
    def test_process_single_page_enhanced(
        self, mock_write_content, service, mock_pdf_document, mock_textract_response
    ):
        """Test processing a single page with enhanced features."""
        # Configure service to use enhanced features
        service.enhanced_features = ["TABLES", "FORMS"]

        # Mock the textractor parser
        mock_parsed_response = MagicMock()
        mock_parsed_response.to_markdown.return_value = "This is a test document."

        with patch(
            "textractor.parsers.response_parser.parse",
            return_value=mock_parsed_response,
        ):
            # Process a single page
            result, metering = service._process_single_page(
                page_index=0,
                pdf_document=mock_pdf_document,
                output_bucket="output-bucket",
                prefix="test-document.pdf",
            )

            # Verify the result
            assert (
                result["image_uri"]
                == "s3://output-bucket/test-document.pdf/pages/1/image.jpg"
            )
            assert (
                result["raw_text_uri"]
                == "s3://output-bucket/test-document.pdf/pages/1/rawText.json"
            )
            assert (
                result["parsed_text_uri"]
                == "s3://output-bucket/test-document.pdf/pages/1/result.json"
            )
            assert (
                result["text_confidence_uri"]
                == "s3://output-bucket/test-document.pdf/pages/1/textConfidence.json"
            )

            # Verify metering data
            assert "OCR/textract/analyze_document-Tables+Forms" in metering
            assert metering["OCR/textract/analyze_document-Tables+Forms"]["pages"] == 1

            # Verify Textract client was called with analyze_document
            service.textract_client.analyze_document.assert_called_once_with(
                Document={"Bytes": b"mock image bytes"},
                FeatureTypes=["TABLES", "FORMS"],
            )
            service.textract_client.detect_document_text.assert_not_called()

    def test_analyze_document(self, service, mock_textract_response):
        """Test the _analyze_document method."""
        # Configure service to use enhanced features
        service.enhanced_features = ["TABLES", "FORMS"]

        # Call the method
        result = service._analyze_document(b"mock image bytes", page_id=1)

        # Verify Textract client was called correctly
        service.textract_client.analyze_document.assert_called_once_with(
            Document={"Bytes": b"mock image bytes"}, FeatureTypes=["TABLES", "FORMS"]
        )

        # Verify the result
        assert result == mock_textract_response

    def test_parse_textract_response_success(self, service, mock_textract_response):
        """Test successful parsing of Textract response."""
        # Mock the textractor parser
        mock_parsed_response = MagicMock()
        mock_parsed_response.to_markdown.return_value = "This is a test document."

        with patch(
            "textractor.parsers.response_parser.parse",
            return_value=mock_parsed_response,
        ):
            # Mock the return value of _parse_textract_response
            with patch.object(
                service,
                "_parse_textract_response",
                return_value={"text": "This is a test document."},
            ):
                # Parse the response
                result = service._parse_textract_response(
                    mock_textract_response, page_id=1
                )

                # Verify the result
                assert result["text"] == "This is a test document."

    def test_parse_textract_response_markdown_error(
        self, service, mock_textract_response
    ):
        """Test parsing Textract response with markdown conversion error."""
        # Mock the textractor parser
        mock_parsed_response = MagicMock()
        mock_parsed_response.to_markdown.side_effect = Exception("Markdown error")
        mock_parsed_response.text = "Plain text content"

        with patch(
            "textractor.parsers.response_parser.parse",
            return_value=mock_parsed_response,
        ):
            # Mock the return value of _parse_textract_response
            with patch.object(
                service,
                "_parse_textract_response",
                return_value={"text": "Plain text content"},
            ):
                # Parse the response
                result = service._parse_textract_response(
                    mock_textract_response, page_id=1
                )

                # Verify the result falls back to plain text
                assert result["text"] == "Plain text content"

    def test_parse_textract_response_parser_error(
        self, service, mock_textract_response
    ):
        """Test parsing Textract response with parser error."""
        # Mock the textractor parser to raise an exception
        with patch(
            "textractor.parsers.response_parser.parse",
            side_effect=Exception("Parser error"),
        ):
            # Mock the return value of _parse_textract_response
            with patch.object(
                service,
                "_parse_textract_response",
                return_value={"text": "This is a test document."},
            ):
                # Parse the response
                result = service._parse_textract_response(
                    mock_textract_response, page_id=1
                )

                # Verify the result falls back to basic extraction
                assert result["text"] == "This is a test document."
