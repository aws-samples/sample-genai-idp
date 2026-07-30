# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for Document compression and decompression methods.
"""

import json
from unittest.mock import Mock, patch

import boto3
import pytest
from moto import mock_aws

from idp_common.models import Document, Page, Section, Status


class TestDocumentCompression:
    """Test cases for Document compression functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        # Create a sample document with rich content
        self.document = Document(
            id="test-doc-123",
            input_bucket="input-bucket",
            input_key="test-document.pdf",
            output_bucket="output-bucket",
            status=Status.CLASSIFYING,
            num_pages=2,
            config_version="sample-health-insurance-review-v0.1.0",
        )

        # Add pages with large content
        self.document.pages = {
            "1": Page(
                page_id="1",
                classification="invoice",
                confidence=0.95,
                tables=[
                    {"rows": [["Item", "Price"], ["Widget", "$10.00"]]},
                    {"rows": [["Tax", "$1.00"], ["Total", "$11.00"]]},
                ],
                forms={"vendor": "ACME Corp", "amount": "$11.00"},
            ),
            "2": Page(
                page_id="2",
                classification="receipt",
                confidence=0.88,
                tables=[{"rows": [["Date", "2023-01-01"], ["Method", "Credit Card"]]}],
                forms={"signature": "John Doe"},
            ),
        }

        # Add sections
        self.document.sections = [
            Section(
                section_id="section_1",
                classification="invoice",
                page_ids=["1"],
                attributes={"vendor": "ACME Corp", "total": 11.00},
            ),
            Section(
                section_id="section_2",
                classification="receipt",
                page_ids=["2"],
                attributes={"payment_method": "Credit Card"},
            ),
        ]

        self.bucket = "test-working-bucket"

    @mock_aws
    def test_compress_method(self):
        """Test the compress method stores document in S3 and returns lightweight wrapper."""
        # Create S3 bucket
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket=self.bucket)

        # Compress document
        compressed_data = self.document.compress(self.bucket, "ocr")

        # Verify compressed data structure
        assert compressed_data["document_id"] == "test-doc-123"
        assert compressed_data["status"] == "CLASSIFYING"
        assert compressed_data["sections"] == ["section_1", "section_2"]
        assert compressed_data["compressed"] is True
        # config_version travels in the lightweight wrapper so consumers that
        # never decompress (e.g. the pipeline-hooks dispatcher) can honor it.
        assert (
            compressed_data["config_version"] == "sample-health-insurance-review-v0.1.0"
        )
        assert "s3_uri" in compressed_data
        assert "timestamp" in compressed_data

        # Verify S3 URI format
        expected_prefix = f"s3://{self.bucket}/compressed_documents/test-doc-123/"
        assert compressed_data["s3_uri"].startswith(expected_prefix)
        assert "_ocr_state.json" in compressed_data["s3_uri"]

        # Verify document was stored in S3
        s3_key = compressed_data["s3_uri"].replace(f"s3://{self.bucket}/", "")
        response = s3_client.get_object(Bucket=self.bucket, Key=s3_key)
        stored_document = json.loads(response["Body"].read().decode("utf-8"))

        # Verify stored document contains all original data
        assert stored_document["id"] == "test-doc-123"
        assert stored_document["num_pages"] == 2
        assert len(stored_document["pages"]) == 2
        assert len(stored_document["sections"]) == 2
        assert (
            stored_document["pages"]["1"]["tables"] == self.document.pages["1"].tables
        )

    @mock_aws
    def test_decompress_method(self):
        """Test the decompress method restores full document from S3."""
        # Create S3 bucket and compress document first
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket=self.bucket)

        compressed_data = self.document.compress(self.bucket, "classification")

        # Decompress document
        restored_document = Document.decompress(self.bucket, compressed_data)

        # Verify restored document matches original
        assert restored_document.id == self.document.id
        assert restored_document.status == self.document.status
        assert restored_document.num_pages == self.document.num_pages
        assert len(restored_document.pages) == len(self.document.pages)
        assert len(restored_document.sections) == len(self.document.sections)

        # Verify page content is preserved
        assert restored_document.pages["1"].tables == self.document.pages["1"].tables
        assert restored_document.pages["1"].forms == self.document.pages["1"].forms
        assert (
            restored_document.pages["2"].classification
            == self.document.pages["2"].classification
        )

        # Verify section content is preserved
        assert (
            restored_document.sections[0].attributes
            == self.document.sections[0].attributes
        )
        assert (
            restored_document.sections[1].page_ids == self.document.sections[1].page_ids
        )

    @mock_aws
    def test_round_trip_compression(self):
        """Test that compress -> decompress preserves all document data."""
        # Create S3 bucket
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket=self.bucket)

        # Add more complex data to test preservation
        self.document.metering = {"tokens": 1500, "pages": 2}
        self.document.errors = ["Warning: Low confidence on page 2"]

        # Compress and decompress
        compressed_data = self.document.compress(self.bucket, "extraction")
        restored_document = Document.decompress(self.bucket, compressed_data)

        # Verify all fields are preserved
        assert restored_document.metering == self.document.metering
        assert restored_document.errors == self.document.errors
        assert restored_document.input_bucket == self.document.input_bucket
        assert restored_document.input_key == self.document.input_key
        assert restored_document.output_bucket == self.document.output_bucket

    def test_section_ids_preserved_in_compressed_data(self):
        """Test that section IDs are preserved in compressed wrapper for Map step."""
        with patch("boto3.client") as mock_boto3:
            mock_s3 = Mock()
            mock_boto3.return_value = mock_s3

            compressed_data = self.document.compress(self.bucket, "test")

            # Verify section IDs are preserved
            assert "sections" in compressed_data
            assert compressed_data["sections"] == ["section_1", "section_2"]
            assert len(compressed_data["sections"]) == 2

    def test_unique_s3_keys_generated(self):
        """Test that each compression generates unique S3 keys."""
        with (
            patch("boto3.client") as mock_boto3,
            patch("time.time", side_effect=[1000.123, 1000.456]),
            # On Python <3.13, logging.LogRecord.__init__ calls time.time(),
            # which would consume our mocked side_effect values when the
            # idp_common logger is at INFO level (as it can be in the full
            # suite). Patch out the info() call so only compress()'s own
            # time.time() calls consume the mock, keeping this deterministic.
            patch("logging.Logger.info"),
        ):
            mock_s3 = Mock()
            mock_boto3.return_value = mock_s3

            # Compress twice
            compressed_1 = self.document.compress(self.bucket, "step1")
            compressed_2 = self.document.compress(self.bucket, "step2")

            # Verify different S3 URIs
            assert compressed_1["s3_uri"] != compressed_2["s3_uri"]
            assert "1000123_step1_state.json" in compressed_1["s3_uri"]
            assert "1000456_step2_state.json" in compressed_2["s3_uri"]

    def test_from_compressed_or_dict_with_compressed_data(self):
        """Test from_compressed_or_dict with compressed data."""
        compressed_data = {
            "document_id": "test-doc",
            "s3_uri": "s3://bucket/key.json",
            "compressed": True,
            "sections": ["s1", "s2"],
        }

        with patch.object(Document, "decompress") as mock_decompress:
            mock_decompress.return_value = self.document

            result = Document.from_compressed_or_dict(compressed_data, self.bucket)

            mock_decompress.assert_called_once_with(self.bucket, compressed_data)
            assert result == self.document

    def test_from_compressed_or_dict_with_regular_dict(self):
        """Test from_compressed_or_dict with regular document dict."""
        regular_data = {"id": "test-doc", "status": "QUEUED"}

        with patch.object(Document, "from_dict") as mock_from_dict:
            mock_from_dict.return_value = self.document

            result = Document.from_compressed_or_dict(regular_data)

            mock_from_dict.assert_called_once_with(regular_data)
            assert result == self.document

    def test_from_compressed_or_dict_missing_bucket_for_compressed(self):
        """Test from_compressed_or_dict raises error when bucket missing for compressed data."""
        compressed_data = {"compressed": True}

        with pytest.raises(
            ValueError, match="Bucket required for decompressing document"
        ):
            Document.from_compressed_or_dict(compressed_data)

    def test_compress_error_handling(self):
        """Test compress method handles S3 errors gracefully."""
        with patch("boto3.client") as mock_boto3:
            mock_s3 = Mock()
            mock_s3.put_object.side_effect = Exception("S3 Error")
            mock_boto3.return_value = mock_s3

            with pytest.raises(Exception, match="S3 Error"):
                self.document.compress(self.bucket, "test")

    def test_decompress_error_handling(self):
        """Test decompress method handles various error conditions."""
        # Test missing s3_uri
        with pytest.raises(ValueError, match="No s3_uri found in compressed data"):
            Document.decompress(self.bucket, {})

        # Test S3 error
        compressed_data = {"s3_uri": "s3://bucket/key.json"}
        with patch("boto3.client") as mock_boto3:
            mock_s3 = Mock()
            mock_s3.get_object.side_effect = Exception("S3 Error")
            mock_boto3.return_value = mock_s3

            with pytest.raises(Exception, match="S3 Error"):
                Document.decompress(self.bucket, compressed_data)

    def test_compress_with_empty_document(self):
        """Test compress works with minimal document data."""
        minimal_doc = Document(id="minimal", status=Status.QUEUED)

        with patch("boto3.client") as mock_boto3:
            mock_s3 = Mock()
            mock_boto3.return_value = mock_s3

            compressed_data = minimal_doc.compress(self.bucket, "test")

            assert compressed_data["document_id"] == "minimal"
            assert compressed_data["sections"] == []
            assert compressed_data["compressed"] is True

    def test_lightweight_wrapper_size(self):
        """Test that compressed wrapper is significantly smaller than full document."""
        with patch("boto3.client") as mock_boto3:
            mock_s3 = Mock()
            mock_boto3.return_value = mock_s3

            # Give the fixture realistic page content. The wrapper is a small,
            # near-fixed set of fields, so the "<20% of full document" check is
            # only meaningful against a representatively-sized document rather
            # than the tiny toy fixture shared by the other tests.
            self.document.pages["1"].forms = {
                f"field_{i}": f"value for field {i} on the invoice page"
                for i in range(40)
            }

            # Get sizes
            full_document_json = self.document.to_json()
            compressed_data = self.document.compress(self.bucket, "test")
            compressed_json = json.dumps(compressed_data)

            # Verify compressed wrapper is much smaller (less than 20% of original)
            assert len(compressed_json) < len(full_document_json) / 5

            # Verify essential data is preserved
            assert "sections" in compressed_data
            assert compressed_data["document_id"] == self.document.id

    @mock_aws
    def test_multiple_step_compression(self):
        """Test compressing document at different processing steps."""
        # Create S3 bucket
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket=self.bucket)

        # Compress at different steps
        ocr_compressed = self.document.compress(self.bucket, "ocr")

        # Modify document (simulate processing)
        self.document.status = Status.EXTRACTING
        extraction_compressed = self.document.compress(self.bucket, "extraction")

        # Verify different S3 keys
        assert ocr_compressed["s3_uri"] != extraction_compressed["s3_uri"]
        assert "_ocr_state.json" in ocr_compressed["s3_uri"]
        assert "_extraction_state.json" in extraction_compressed["s3_uri"]

        # Verify both can be decompressed
        ocr_doc = Document.decompress(self.bucket, ocr_compressed)
        extraction_doc = Document.decompress(self.bucket, extraction_compressed)

        assert ocr_doc.status == Status.CLASSIFYING  # Original status
        assert extraction_doc.status == Status.EXTRACTING  # Modified status

    @mock_aws
    def test_decompress_key_with_hash(self):
        """Compress→decompress round-trip must preserve S3 keys that contain '#'.

        urlparse treats '#' as a URL fragment delimiter and silently truncates
        the key at that character. parse_s3_uri uses str.split and is safe.
        """
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket=self.bucket)

        # id defaults to input_key in production (Document.from_s3_event), so a
        # '#' in the filename lands in the compressed-state S3 key itself —
        # that is the URI decompress() must parse without truncating.
        hash_doc = Document(
            id="incoming/invoices/invoice #123.pdf",
            input_bucket="input-bucket",
            input_key="incoming/invoices/invoice #123.pdf",
            output_bucket="output-bucket",
            status=Status.CLASSIFYING,
        )

        compressed_data = hash_doc.compress(self.bucket, "ocr")
        assert "#" in compressed_data["s3_uri"]  # guard: URI must exercise the bug
        restored = Document.decompress(self.bucket, compressed_data)

        assert restored.input_key == "incoming/invoices/invoice #123.pdf"
