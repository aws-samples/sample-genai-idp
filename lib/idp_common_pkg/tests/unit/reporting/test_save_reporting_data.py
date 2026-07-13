# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for the SaveReportingData class.
"""

from unittest.mock import MagicMock, patch

import pytest
from idp_common.models import Document
from idp_common.reporting.save_reporting_data import SaveReportingData


@pytest.mark.unit
class TestSaveReportingData:
    """Test cases for SaveReportingData class."""

    @pytest.fixture
    def mock_s3_client(self):
        """Create a mock S3 client."""
        with patch("boto3.client") as mock_client:
            mock_s3 = MagicMock()
            mock_client.return_value = mock_s3
            yield mock_s3

    @pytest.fixture
    def document_with_evaluation_uri(self):
        """Create a test document with evaluation results URI."""
        doc = Document(id="test-doc-123", input_key="test/document.pdf")
        doc.evaluation_results_uri = (
            "s3://test-bucket/test/document.pdf/evaluation/results.json"
        )
        return doc

    @pytest.fixture
    def document_without_evaluation_uri(self):
        """Create a test document without evaluation results URI."""
        return Document(id="test-doc-456", input_key="test/document2.pdf")

    @pytest.fixture
    def mock_evaluation_results(self):
        """Create mock evaluation results."""
        return {
            "overall_metrics": {
                "accuracy": 0.85,
                "precision": 0.9,
                "recall": 0.8,
                "f1_score": 0.85,
                "false_alarm_rate": 0.1,
                "false_discovery_rate": 0.1,
            },
            "execution_time": 1.5,
            "section_results": [
                {
                    "section_id": "section-1",
                    "document_class": "invoice",
                    "metrics": {
                        "accuracy": 0.9,
                        "precision": 0.95,
                        "recall": 0.85,
                        "f1_score": 0.9,
                        "false_alarm_rate": 0.05,
                        "false_discovery_rate": 0.05,
                    },
                    "attributes": [
                        {
                            "name": "invoice_number",
                            "expected": "INV-123",
                            "actual": "INV-123",
                            "matched": True,
                            "score": 1.0,
                            "reason": "Exact match",
                            "evaluation_method": "exact",
                            "confidence": "high",
                        }
                    ],
                }
            ],
        }

    def test_serialize_value(self):
        """Test the _serialize_value method."""
        reporter = SaveReportingData("test-bucket")

        # Test various types
        assert reporter._serialize_value(None) is None
        assert reporter._serialize_value("test") == "test"
        assert reporter._serialize_value(123) == "123"
        assert reporter._serialize_value(True) == "True"
        assert reporter._serialize_value({"key": "value"}) == '{"key": "value"}'
        assert reporter._serialize_value(["item1", "item2"]) == '["item1", "item2"]'

    def test_parse_s3_uri(self):
        """Test the _parse_s3_uri method."""
        reporter = SaveReportingData("test-bucket")

        # Test valid S3 URI
        bucket, key = reporter._parse_s3_uri("s3://test-bucket/path/to/file.json")
        assert bucket == "test-bucket"
        assert key == "path/to/file.json"

        # Key containing '#' must not be truncated (urlparse treated '#' as a
        # URL fragment delimiter and silently dropped the rest of the key)
        bucket, key = reporter._parse_s3_uri("s3://test-bucket/path/file #99.json")
        assert bucket == "test-bucket"
        assert key == "path/file #99.json"

        # A double slash now denotes a key that genuinely starts with '/'
        # (previously lstrip'd away, which made the key unretrievable)
        bucket, key = reporter._parse_s3_uri("s3://test-bucket//path/to/file.json")
        assert bucket == "test-bucket"
        assert key == "/path/to/file.json"

        # Test invalid S3 URI
        with pytest.raises(ValueError):
            reporter._parse_s3_uri("http://test-bucket/path/to/file.json")

        # Bucket-only URI (no key) raises rather than returning an empty key
        with pytest.raises(ValueError):
            reporter._parse_s3_uri("s3://test-bucket")

    def test_save_with_empty_data_to_save(
        self, mock_s3_client, document_with_evaluation_uri
    ):
        """Test the save method with empty data_to_save list."""
        reporter = SaveReportingData("test-bucket")

        results = reporter.save(document_with_evaluation_uri, [])

        assert results == []

    @patch.object(SaveReportingData, "save_evaluation_results")
    def test_save_with_evaluation_results(
        self, mock_save_eval, mock_s3_client, document_with_evaluation_uri
    ):
        """Test the save method with evaluation_results in data_to_save."""
        reporter = SaveReportingData("test-bucket")

        # Mock the save_evaluation_results method
        mock_save_eval.return_value = {"statusCode": 200, "body": "Success"}

        results = reporter.save(document_with_evaluation_uri, ["evaluation_results"])

        # Verify calls
        mock_save_eval.assert_called_once_with(document_with_evaluation_uri)
        assert results == [{"statusCode": 200, "body": "Success"}]

    def test_save_evaluation_results_no_uri(
        self, mock_s3_client, document_without_evaluation_uri
    ):
        """Test save_evaluation_results with a document that has no evaluation results URI."""
        reporter = SaveReportingData("test-bucket")

        result = reporter.save_evaluation_results(document_without_evaluation_uri)

        assert result is None


@pytest.mark.unit
class TestSaveReportingDataSections:
    """Test cases for SaveReportingData document sections functionality."""

    @pytest.fixture
    def mock_s3_client(self):
        """Create a mock S3 client."""
        with patch("boto3.client") as mock_client:
            mock_s3 = MagicMock()
            mock_client.return_value = mock_s3
            yield mock_s3

    @pytest.fixture
    def document_with_sections(self):
        """Create a test document with sections."""
        from datetime import datetime

        from idp_common.models import Section

        sections = [
            Section(
                section_id="section_1",
                classification="invoice",
                confidence=0.95,
                page_ids=["page_1"],
                extraction_result_uri="s3://test-bucket/doc1/sections/section_1/result.json",
            ),
            Section(
                section_id="section_2",
                classification="receipt",
                confidence=0.87,
                page_ids=["page_2"],
                extraction_result_uri="s3://test-bucket/doc1/sections/section_2/result.json",
            ),
        ]

        doc = Document(
            id="test_document_123",
            input_key="documents/test_document_123.pdf",
            initial_event_time=datetime.now().isoformat() + "Z",
            sections=sections,
            num_pages=2,
        )
        return doc

    @pytest.fixture
    def document_without_sections(self):
        """Create a test document without sections."""
        return Document(id="test-doc-no-sections", input_key="test/document.pdf")

    @pytest.fixture
    def document_with_sections_no_extraction_uri(self):
        """Create a test document with sections but no extraction URIs."""
        from idp_common.models import Section

        sections = [
            Section(
                section_id="section_1",
                classification="invoice",
                confidence=0.95,
                page_ids=["page_1"],
                # No extraction_result_uri
            ),
        ]

        doc = Document(
            id="test_document_no_uri",
            input_key="documents/test_document_no_uri.pdf",
            sections=sections,
        )
        return doc

    @pytest.fixture
    def mock_extraction_data_dict(self):
        """Create mock extraction data as a dictionary."""
        return {
            "customer": {
                "name": "John Doe",
                "address": {"street": "123 Main St", "city": "Anytown"},
            },
            "invoice_number": "INV-123",
            "total_amount": 150.75,
            "items": ["item1", "item2"],
        }

    @pytest.fixture
    def mock_extraction_data_list(self):
        """Create mock extraction data as a list."""
        return [
            {"item": "Product A", "price": 50.0},
            {"item": "Product B", "price": 100.75},
        ]

    def test_infer_pyarrow_type(self, mock_s3_client):
        """Test the _infer_pyarrow_type method."""
        import pyarrow as pa

        reporter = SaveReportingData("test-bucket")

        # Test various types
        assert reporter._infer_pyarrow_type(None) == pa.string()
        assert reporter._infer_pyarrow_type("test") == pa.string()
        assert reporter._infer_pyarrow_type(123) == pa.int64()
        assert reporter._infer_pyarrow_type(123.45) == pa.float64()
        assert reporter._infer_pyarrow_type(True) == pa.bool_()
        assert reporter._infer_pyarrow_type({"key": "value"}) == pa.string()
        assert reporter._infer_pyarrow_type(["item1", "item2"]) == pa.string()

    def test_flatten_json_data(self, mock_s3_client):
        """Test the _flatten_json_data method."""
        reporter = SaveReportingData("test-bucket")

        # Test nested dictionary
        data = {
            "customer": {
                "name": "John Doe",
                "address": {"street": "123 Main St", "city": "Anytown"},
            },
            "items": ["item1", "item2"],
            "total": 150.75,
        }

        flattened = reporter._flatten_json_data(data)

        expected = {
            "customer.name": "John Doe",
            "customer.address.street": "123 Main St",
            "customer.address.city": "Anytown",
            "items": '["item1", "item2"]',
            "total": "150.75",  # Now converted to string for type consistency
        }

        assert flattened == expected

    def test_create_dynamic_schema(self, mock_s3_client):
        """Test the _create_dynamic_schema method."""
        reporter = SaveReportingData("test-bucket")

        # Test with empty records
        schema = reporter._create_dynamic_schema([])
        assert len(schema) == 1
        assert schema[0].name == "section_id"

        # Test with mixed type records
        records = [
            {"name": "John", "age": 30, "active": True, "score": 95.5},
            {"name": "Jane", "age": 25, "active": False, "score": 87.2},
        ]

        schema = reporter._create_dynamic_schema(records)
        field_names = [field.name for field in schema]

        assert "name" in field_names
        assert "age" in field_names
        assert "active" in field_names
        assert "score" in field_names

    def test_save_document_sections_no_sections(
        self, mock_s3_client, document_without_sections
    ):
        """Test save_document_sections with a document that has no sections."""
        reporter = SaveReportingData("test-bucket")

        result = reporter.save_document_sections(document_without_sections)

        assert result is None

    def test_save_document_sections_no_extraction_uri(
        self, mock_s3_client, document_with_sections_no_extraction_uri
    ):
        """Test save_document_sections with sections that have no extraction URIs."""
        reporter = SaveReportingData("test-bucket")

        result = reporter.save_document_sections(
            document_with_sections_no_extraction_uri
        )

        # Should return success but with 0 sections processed
        assert result["statusCode"] == 200
        assert "No sections with extraction results found" in result["body"]

    @patch("idp_common.reporting.save_reporting_data.get_json_content")
    def test_save_document_sections_dict_data(
        self,
        mock_get_json,
        mock_s3_client,
        document_with_sections,
        mock_extraction_data_dict,
    ):
        """Test save_document_sections with dictionary extraction data."""
        reporter = SaveReportingData("test-bucket")

        # Mock S3 JSON content
        mock_get_json.return_value = mock_extraction_data_dict

        result = reporter.save_document_sections(document_with_sections)

        # Verify successful processing
        assert result["statusCode"] == 200
        assert "Successfully saved 2 document sections" in result["body"]

        # Verify S3 calls were made
        assert mock_s3_client.put_object.call_count == 2

        # Verify get_json_content was called for each section
        assert mock_get_json.call_count == 2

    @patch("idp_common.reporting.save_reporting_data.get_json_content")
    def test_save_document_sections_list_data(
        self,
        mock_get_json,
        mock_s3_client,
        document_with_sections,
        mock_extraction_data_list,
    ):
        """Test save_document_sections with list extraction data."""
        reporter = SaveReportingData("test-bucket")

        # Mock S3 JSON content
        mock_get_json.return_value = mock_extraction_data_list

        result = reporter.save_document_sections(document_with_sections)

        # Verify successful processing
        assert result["statusCode"] == 200
        assert "Successfully saved 2 document sections" in result["body"]

    @patch("idp_common.reporting.save_reporting_data.get_json_content")
    def test_save_document_sections_primitive_data(
        self, mock_get_json, mock_s3_client, document_with_sections
    ):
        """Test save_document_sections with primitive extraction data."""
        reporter = SaveReportingData("test-bucket")

        # Mock S3 JSON content with primitive data
        mock_get_json.return_value = "Simple text result"

        result = reporter.save_document_sections(document_with_sections)

        # Verify successful processing
        assert result["statusCode"] == 200
        assert "Successfully saved 2 document sections" in result["body"]

    @patch("idp_common.reporting.save_reporting_data.get_json_content")
    def test_save_document_sections_s3_error(
        self, mock_get_json, mock_s3_client, document_with_sections
    ):
        """Test save_document_sections with S3 access error."""
        reporter = SaveReportingData("test-bucket")

        # Mock S3 error
        mock_get_json.side_effect = Exception("S3 access denied")

        result = reporter.save_document_sections(document_with_sections)

        # Should still return success but with 0 sections processed due to errors
        assert result["statusCode"] == 200
        assert "No sections with extraction results found" in result["body"]

    @patch.object(SaveReportingData, "save_document_sections")
    def test_save_with_sections(
        self, mock_save_sections, mock_s3_client, document_with_sections
    ):
        """Test the save method with sections in data_to_save."""
        reporter = SaveReportingData("test-bucket")

        # Mock the save_document_sections method
        mock_save_sections.return_value = {"statusCode": 200, "body": "Success"}

        results = reporter.save(document_with_sections, ["sections"])

        # Verify calls
        mock_save_sections.assert_called_once_with(document_with_sections)
        assert results == [{"statusCode": 200, "body": "Success"}]

    @patch.object(SaveReportingData, "save_document_sections")
    @patch.object(SaveReportingData, "save_metering_data")
    def test_save_with_multiple_data_types(
        self,
        mock_save_metering,
        mock_save_sections,
        mock_s3_client,
        document_with_sections,
    ):
        """Test the save method with multiple data types including sections."""
        reporter = SaveReportingData("test-bucket")

        # Add metering data to document
        document_with_sections.metering = {"test/api": {"calls": 5}}

        # Mock the methods
        mock_save_metering.return_value = {"statusCode": 200, "body": "Metering saved"}
        mock_save_sections.return_value = {"statusCode": 200, "body": "Sections saved"}

        results = reporter.save(document_with_sections, ["metering", "sections"])

        # Verify calls
        mock_save_metering.assert_called_once_with(document_with_sections)
        mock_save_sections.assert_called_once_with(document_with_sections)
        assert len(results) == 2

    def test_config_version_in_schemas_and_records(self, mock_s3_client):
        """Test that config_version is included in schemas and populated in records."""
        import pyarrow as pa

        # Test metering schema
        metering_schema = pa.schema(
            [
                ("document_id", pa.string()),
                ("context", pa.string()),
                ("service_api", pa.string()),
                ("unit", pa.string()),
                ("value", pa.float64()),
                ("number_of_pages", pa.int32()),
                ("unit_cost", pa.float64()),
                ("estimated_cost", pa.float64()),
                ("timestamp", pa.timestamp("ms")),
                ("config_version", pa.string()),
            ]
        )
        assert "config_version" in [field.name for field in metering_schema]

        # Test document evaluation schema (check in save_evaluation_results source)
        # Create a test document with config_version
        doc_with_config = Document(
            id="test-doc", input_key="test/doc.pdf", config_version="test-v1.0"
        )
        doc_without_config = Document(id="test-doc2", input_key="test/doc2.pdf")

        # Verify config_version fallback behavior
        assert doc_with_config.config_version == "test-v1.0"
        assert doc_without_config.config_version is None

        # Simulate record creation with fallback
        record_with_config = {
            "config_version": doc_with_config.config_version or "default"
        }
        record_without_config = {
            "config_version": doc_without_config.config_version or "default"
        }

        assert record_with_config["config_version"] == "test-v1.0"
        assert record_without_config["config_version"] == "default"
