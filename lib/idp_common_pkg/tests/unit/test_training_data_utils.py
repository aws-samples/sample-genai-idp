# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Unit tests for training_data_utils shared utility module.
"""

import base64
from unittest.mock import MagicMock, patch

import pytest

from idp_common.model_finetuning.training_data_utils import (
    convert_pdf_to_images,
    format_baseline_for_training,
    get_document_images,
    get_document_images_from_uri,
    get_extraction_fields,
)


class TestGetExtractionFields:
    """Tests for get_extraction_fields."""

    @pytest.mark.unit
    def test_sections_with_extraction(self):
        """Test extracting fields from Sections/Extraction format."""
        baseline = {
            "Sections": [
                {"Extraction": {"name": "John", "age": "30"}},
                {"Extraction": {"address": "123 Main St"}},
            ]
        }
        fields = get_extraction_fields(baseline)
        assert sorted(fields) == ["address", "age", "name"]

    @pytest.mark.unit
    def test_direct_extraction(self):
        """Test extracting fields from top-level Extraction format."""
        baseline = {"Extraction": {"invoice_number": "INV-001", "total": "$100"}}
        fields = get_extraction_fields(baseline)
        assert sorted(fields) == ["invoice_number", "total"]

    @pytest.mark.unit
    def test_fields_array_with_dicts(self):
        """Test extracting fields from fields array with dict entries."""
        baseline = {
            "fields": [
                {"name": "first_name", "value": "Jane"},
                {"name": "last_name", "value": "Doe"},
            ]
        }
        fields = get_extraction_fields(baseline)
        assert sorted(fields) == ["first_name", "last_name"]

    @pytest.mark.unit
    def test_fields_array_with_strings(self):
        """Test extracting fields from fields array with string entries."""
        baseline = {"fields": ["field_a", "field_b", "field_c"]}
        fields = get_extraction_fields(baseline)
        assert fields == ["field_a", "field_b", "field_c"]

    @pytest.mark.unit
    def test_empty_baseline(self):
        """Test with empty baseline returns empty list."""
        assert get_extraction_fields({}) == []

    @pytest.mark.unit
    def test_filters_empty_strings(self):
        """Test that empty field names are filtered out."""
        baseline = {
            "fields": [
                {"name": "valid_field"},
                {"name": ""},
                {"name": "another_field"},
            ]
        }
        fields = get_extraction_fields(baseline)
        assert fields == ["valid_field", "another_field"]

    @pytest.mark.unit
    def test_combined_formats(self):
        """Test baseline with multiple formats combined."""
        baseline = {
            "Sections": [{"Extraction": {"section_field": "val"}}],
            "Extraction": {"top_field": "val"},
            "fields": [{"name": "array_field"}],
        }
        fields = get_extraction_fields(baseline)
        assert sorted(fields) == ["array_field", "section_field", "top_field"]


class TestFormatBaselineForTraining:
    """Tests for format_baseline_for_training."""

    @pytest.mark.unit
    def test_sections_with_extraction_simple_values(self):
        """Test formatting Sections/Extraction with simple values."""
        baseline = {
            "Sections": [
                {"Extraction": {"name": "John", "age": "30"}},
            ]
        }
        result = format_baseline_for_training(baseline)
        assert result == {"name": "John", "age": "30"}

    @pytest.mark.unit
    def test_sections_with_extraction_dict_values(self):
        """Test formatting Sections/Extraction with nested dict values."""
        baseline = {
            "Sections": [
                {
                    "Extraction": {
                        "name": {"value": "John"},
                        "age": {"Value": "30"},
                    }
                },
            ]
        }
        result = format_baseline_for_training(baseline)
        assert result == {"name": "John", "age": "30"}

    @pytest.mark.unit
    def test_direct_extraction(self):
        """Test formatting top-level Extraction."""
        baseline = {"Extraction": {"invoice_number": "INV-001", "total": "$100"}}
        result = format_baseline_for_training(baseline)
        assert result == {"invoice_number": "INV-001", "total": "$100"}

    @pytest.mark.unit
    def test_fields_array(self):
        """Test formatting fields array."""
        baseline = {
            "fields": [
                {"name": "first_name", "value": "Jane"},
                {"name": "last_name", "value": "Doe"},
            ]
        }
        result = format_baseline_for_training(baseline)
        assert result == {"first_name": "Jane", "last_name": "Doe"}

    @pytest.mark.unit
    def test_fields_array_skips_empty_names(self):
        """Test that fields with empty names are skipped."""
        baseline = {
            "fields": [
                {"name": "valid", "value": "yes"},
                {"name": "", "value": "skip"},
            ]
        }
        result = format_baseline_for_training(baseline)
        assert result == {"valid": "yes"}

    @pytest.mark.unit
    def test_fallback_to_baseline_keys(self):
        """Test fallback when no standard format matches."""
        baseline = {
            "documentClass": "invoice",
            "confidence": 0.95,
        }
        result = format_baseline_for_training(baseline)
        assert result == {"documentClass": "invoice", "confidence": 0.95}

    @pytest.mark.unit
    def test_fallback_excludes_metadata_keys(self):
        """Test that fallback excludes known metadata keys."""
        baseline = {
            "documentClass": "invoice",
            "Sections": [],
            "metadata": {"source": "test"},
            "Metadata": {"version": 1},
            "pageCount": 3,
            "PageCount": 3,
        }
        result = format_baseline_for_training(baseline)
        assert result == {"documentClass": "invoice"}

    @pytest.mark.unit
    def test_empty_baseline(self):
        """Test with empty baseline returns empty dict."""
        assert format_baseline_for_training({}) == {}

    @pytest.mark.unit
    def test_dict_value_without_value_key(self):
        """Test dict value that has neither 'value' nor 'Value' key."""
        baseline = {
            "Extraction": {
                "field": {"confidence": 0.9, "source": "ocr"},
            }
        }
        result = format_baseline_for_training(baseline)
        # Should fall back to str(value)
        assert "field" in result


class TestConvertPdfToImages:
    """Tests for convert_pdf_to_images."""

    @pytest.mark.unit
    def test_returns_empty_when_pypdfium2_unavailable(self):
        """Test graceful handling when pypdfium2 is not installed."""
        with patch.dict("sys.modules", {"pypdfium2": None}):
            # Force re-import to trigger ImportError
            with patch(
                "idp_common.model_finetuning.training_data_utils.convert_pdf_to_images"
            ) as mock_fn:
                mock_fn.return_value = []
                result = mock_fn(b"fake pdf bytes")
                assert result == []

    @pytest.mark.unit
    def test_returns_tuples_with_format(self):
        """Test that results are (bytes, format) tuples."""
        # Create a mock PDF document
        mock_pil_image = MagicMock()
        # Create a small valid PNG
        import struct
        import zlib

        def _make_minimal_png():
            """Create a minimal 1x1 white PNG."""
            signature = b"\x89PNG\r\n\x1a\n"
            # IHDR chunk
            ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
            ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
            ihdr = (
                struct.pack(">I", 13)
                + b"IHDR"
                + ihdr_data
                + struct.pack(">I", ihdr_crc)
            )
            # IDAT chunk
            raw_data = zlib.compress(b"\x00\xff\xff\xff")
            idat_crc = zlib.crc32(b"IDAT" + raw_data) & 0xFFFFFFFF
            idat = (
                struct.pack(">I", len(raw_data))
                + b"IDAT"
                + raw_data
                + struct.pack(">I", idat_crc)
            )
            # IEND chunk
            iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
            iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
            return signature + ihdr + idat + iend

        png_bytes = _make_minimal_png()
        mock_pil_image.save = MagicMock(side_effect=lambda b, **kw: b.write(png_bytes))

        mock_bitmap = MagicMock()
        mock_bitmap.to_pil.return_value = mock_pil_image

        mock_page = MagicMock()
        mock_page.render.return_value = mock_bitmap

        mock_pdf = MagicMock()
        mock_pdf.__len__ = MagicMock(return_value=2)
        mock_pdf.__getitem__ = MagicMock(return_value=mock_page)

        with patch("builtins.__import__") as mock_import:
            mock_pdfium = MagicMock()
            mock_pdfium.PdfDocument.return_value = mock_pdf

            original_import = (
                __builtins__.__import__
                if hasattr(__builtins__, "__import__")
                else __import__
            )

            def side_effect(name, *args, **kwargs):
                if name == "pypdfium2":
                    return mock_pdfium
                return original_import(name, *args, **kwargs)

            mock_import.side_effect = side_effect

            result = convert_pdf_to_images(b"fake pdf", max_pages=2, dpi=150)
            # Each result should be a tuple of (bytes, str)
            for item in result:
                assert isinstance(item, tuple)
                assert len(item) == 2
                assert isinstance(item[0], bytes)
                assert item[1] == "png"

    @pytest.mark.unit
    def test_max_pages_limit(self):
        """Test that max_pages parameter limits conversion."""
        mock_pil_image = MagicMock()
        mock_pil_image.save = MagicMock(
            side_effect=lambda b, **kw: b.write(b"fake_png")
        )

        mock_bitmap = MagicMock()
        mock_bitmap.to_pil.return_value = mock_pil_image

        mock_page = MagicMock()
        mock_page.render.return_value = mock_bitmap

        mock_pdf = MagicMock()
        mock_pdf.__len__ = MagicMock(return_value=10)
        mock_pdf.__getitem__ = MagicMock(return_value=mock_page)

        with patch("builtins.__import__") as mock_import:
            mock_pdfium = MagicMock()
            mock_pdfium.PdfDocument.return_value = mock_pdf

            original_import = (
                __builtins__.__import__
                if hasattr(__builtins__, "__import__")
                else __import__
            )

            def side_effect(name, *args, **kwargs):
                if name == "pypdfium2":
                    return mock_pdfium
                return original_import(name, *args, **kwargs)

            mock_import.side_effect = side_effect

            result = convert_pdf_to_images(b"fake pdf", max_pages=3)
            assert len(result) == 3

    @pytest.mark.unit
    def test_dpi_parameter_used(self):
        """Test that dpi parameter affects the scale factor."""
        mock_pil_image = MagicMock()
        mock_pil_image.save = MagicMock(
            side_effect=lambda b, **kw: b.write(b"fake_png")
        )

        mock_bitmap = MagicMock()
        mock_bitmap.to_pil.return_value = mock_pil_image

        mock_page = MagicMock()
        mock_page.render.return_value = mock_bitmap

        mock_pdf = MagicMock()
        mock_pdf.__len__ = MagicMock(return_value=1)
        mock_pdf.__getitem__ = MagicMock(return_value=mock_page)

        with patch("builtins.__import__") as mock_import:
            mock_pdfium = MagicMock()
            mock_pdfium.PdfDocument.return_value = mock_pdf

            original_import = (
                __builtins__.__import__
                if hasattr(__builtins__, "__import__")
                else __import__
            )

            def side_effect(name, *args, **kwargs):
                if name == "pypdfium2":
                    return mock_pdfium
                return original_import(name, *args, **kwargs)

            mock_import.side_effect = side_effect

            convert_pdf_to_images(b"fake pdf", dpi=300)
            # Verify render was called with scale=300/72
            mock_page.render.assert_called_once_with(scale=300 / 72.0)

    @pytest.mark.unit
    def test_returns_empty_on_error(self):
        """Test that errors during conversion return empty list."""
        mock_pdfium = MagicMock()
        mock_pdfium.PdfDocument.side_effect = RuntimeError("corrupt PDF")

        with patch.dict("sys.modules", {"pypdfium2": mock_pdfium}):
            result = convert_pdf_to_images(b"corrupt pdf")
            assert result == []


class TestGetDocumentImages:
    """Tests for get_document_images."""

    @pytest.mark.unit
    def test_png_image(self):
        """Test handling of PNG image files."""
        png_bytes = b"fake png content"
        mock_s3 = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = png_bytes
        mock_s3.get_object.return_value = {
            "Body": mock_body,
            "ContentType": "image/png",
        }

        result = get_document_images(mock_s3, "my-bucket", "docs/image.png")

        assert len(result) == 1
        b64_data, fmt = result[0]
        assert fmt == "png"
        assert base64.b64decode(b64_data) == png_bytes

    @pytest.mark.unit
    def test_jpeg_image(self):
        """Test handling of JPEG image files."""
        jpeg_bytes = b"fake jpeg content"
        mock_s3 = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = jpeg_bytes
        mock_s3.get_object.return_value = {
            "Body": mock_body,
            "ContentType": "image/jpeg",
        }

        result = get_document_images(mock_s3, "my-bucket", "docs/photo.jpg")

        assert len(result) == 1
        b64_data, fmt = result[0]
        assert fmt == "jpeg"
        assert base64.b64decode(b64_data) == jpeg_bytes

    @pytest.mark.unit
    def test_jpeg_extension(self):
        """Test handling of .jpeg extension."""
        mock_s3 = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = b"jpeg data"
        mock_s3.get_object.return_value = {
            "Body": mock_body,
            "ContentType": "image/jpeg",
        }

        result = get_document_images(mock_s3, "bucket", "file.jpeg")
        assert result[0][1] == "jpeg"

    @pytest.mark.unit
    def test_gif_image(self):
        """Test handling of GIF image files."""
        mock_s3 = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = b"gif data"
        mock_s3.get_object.return_value = {
            "Body": mock_body,
            "ContentType": "image/gif",
        }

        result = get_document_images(mock_s3, "bucket", "anim.gif")
        assert result[0][1] == "gif"

    @pytest.mark.unit
    def test_webp_image(self):
        """Test handling of WebP image files."""
        mock_s3 = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = b"webp data"
        mock_s3.get_object.return_value = {
            "Body": mock_body,
            "ContentType": "image/webp",
        }

        result = get_document_images(mock_s3, "bucket", "photo.webp")
        assert result[0][1] == "webp"

    @pytest.mark.unit
    def test_unsupported_extension_defaults_to_png(self):
        """Test that unsupported file types default to PNG."""
        mock_s3 = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = b"unknown data"
        mock_s3.get_object.return_value = {
            "Body": mock_body,
            "ContentType": "application/octet-stream",
        }

        result = get_document_images(mock_s3, "bucket", "file.xyz")
        assert len(result) == 1
        assert result[0][1] == "png"

    @pytest.mark.unit
    def test_pdf_delegates_to_convert(self):
        """Test that PDF files are converted via convert_pdf_to_images."""
        mock_s3 = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = b"pdf bytes"
        mock_s3.get_object.return_value = {
            "Body": mock_body,
            "ContentType": "application/pdf",
        }

        with patch(
            "idp_common.model_finetuning.training_data_utils.convert_pdf_to_images"
        ) as mock_convert:
            mock_convert.return_value = [(b"page1_png", "png"), (b"page2_png", "png")]

            result = get_document_images(mock_s3, "bucket", "doc.pdf")

            mock_convert.assert_called_once_with(b"pdf bytes")
            assert len(result) == 2
            assert result[0][1] == "png"
            assert result[1][1] == "png"
            # Verify base64 encoding
            assert base64.b64decode(result[0][0]) == b"page1_png"

    @pytest.mark.unit
    def test_pdf_detected_by_content_type(self):
        """Test that PDF is detected by content type even without .pdf extension."""
        mock_s3 = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = b"pdf bytes"
        mock_s3.get_object.return_value = {
            "Body": mock_body,
            "ContentType": "application/pdf",
        }

        with patch(
            "idp_common.model_finetuning.training_data_utils.convert_pdf_to_images"
        ) as mock_convert:
            mock_convert.return_value = [(b"page_png", "png")]

            result = get_document_images(mock_s3, "bucket", "document_no_ext")

            mock_convert.assert_called_once()
            assert len(result) == 1


class TestGetDocumentImagesFromUri:
    """Tests for get_document_images_from_uri."""

    @pytest.mark.unit
    def test_parses_s3_uri_correctly(self):
        """Test that S3 URI is parsed into bucket and key."""
        mock_s3 = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = b"image data"
        mock_s3.get_object.return_value = {
            "Body": mock_body,
            "ContentType": "image/png",
        }

        get_document_images_from_uri(mock_s3, "s3://my-bucket/path/to/image.png")

        mock_s3.get_object.assert_called_once_with(
            Bucket="my-bucket", Key="path/to/image.png"
        )

    @pytest.mark.unit
    def test_invalid_uri_raises_error(self):
        """Test that non-S3 URIs raise ValueError."""
        mock_s3 = MagicMock()

        with pytest.raises(ValueError, match="Invalid S3 URI"):
            get_document_images_from_uri(mock_s3, "https://example.com/file.png")

    @pytest.mark.unit
    def test_bucket_only_uri(self):
        """Test S3 URI with bucket only (no key)."""
        mock_s3 = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = b"data"
        mock_s3.get_object.return_value = {
            "Body": mock_body,
            "ContentType": "image/png",
        }

        # s3://my-bucket -> bucket="my-bucket", key=""
        get_document_images_from_uri(mock_s3, "s3://my-bucket")

        mock_s3.get_object.assert_called_once_with(Bucket="my-bucket", Key="")

    @pytest.mark.unit
    def test_returns_same_as_get_document_images(self):
        """Test that result matches get_document_images for same input."""
        png_bytes = b"test png"
        mock_s3 = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = png_bytes
        mock_s3.get_object.return_value = {
            "Body": mock_body,
            "ContentType": "image/png",
        }

        result = get_document_images_from_uri(mock_s3, "s3://bucket/key/image.png")

        assert len(result) == 1
        assert result[0][1] == "png"
        assert base64.b64decode(result[0][0]) == png_bytes
