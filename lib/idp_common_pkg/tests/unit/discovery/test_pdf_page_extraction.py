# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for ClassesDiscovery PDF page extraction and page range parsing.
Tests the static methods that don't require AWS resources or Bedrock access.
"""

import io

import pytest

from idp_common.discovery.classes_discovery import ClassesDiscovery

# Import locally for test helpers only
pypdfium2 = pytest.importorskip("pypdfium2")
pdfium = pypdfium2

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_test_pdf(num_pages: int) -> bytes:
    """Create a minimal multi-page PDF for testing using pypdfium2."""
    pdf = pdfium.PdfDocument.new()
    for _ in range(num_pages):
        # Add a blank page (letter size: 612 x 792 points)
        pdf.new_page(612, 792)
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def _count_pages(pdf_bytes: bytes) -> int:
    """Count pages in a PDF byte stream."""
    doc = pdfium.PdfDocument(pdf_bytes)
    count = len(doc)
    doc.close()
    return count


# ---------------------------------------------------------------------------
# parse_page_range tests
# ---------------------------------------------------------------------------


class TestParsePageRange:
    """Tests for ClassesDiscovery.parse_page_range()"""

    def test_simple_range(self):
        start, end = ClassesDiscovery.parse_page_range("1-3")
        assert start == 1
        assert end == 3

    def test_single_page(self):
        start, end = ClassesDiscovery.parse_page_range("5-5")
        assert start == 5
        assert end == 5

    def test_whitespace_handling(self):
        start, end = ClassesDiscovery.parse_page_range("  2 - 7  ")
        assert start == 2
        assert end == 7

    def test_large_range(self):
        start, end = ClassesDiscovery.parse_page_range("1-100")
        assert start == 1
        assert end == 100

    def test_invalid_format_no_dash(self):
        with pytest.raises(ValueError, match="Invalid page range format"):
            ClassesDiscovery.parse_page_range("123")

    def test_invalid_format_text(self):
        with pytest.raises(ValueError, match="Invalid page range format"):
            ClassesDiscovery.parse_page_range("abc")

    def test_invalid_format_empty(self):
        with pytest.raises(ValueError, match="Invalid page range format"):
            ClassesDiscovery.parse_page_range("")

    def test_start_greater_than_end(self):
        with pytest.raises(ValueError, match="End page.*must be >= start page"):
            ClassesDiscovery.parse_page_range("5-3")

    def test_zero_start(self):
        with pytest.raises(ValueError, match="Page numbers must be >= 1"):
            ClassesDiscovery.parse_page_range("0-3")


# ---------------------------------------------------------------------------
# extract_pdf_pages tests
# ---------------------------------------------------------------------------


class TestExtractPdfPages:
    """Tests for ClassesDiscovery.extract_pdf_pages()"""

    def test_extract_first_page(self):
        """Extract just the first page from a 5-page PDF."""
        pdf_bytes = _create_test_pdf(5)
        result = ClassesDiscovery.extract_pdf_pages(pdf_bytes, 1, 1)
        assert _count_pages(result) == 1

    def test_extract_last_page(self):
        """Extract just the last page from a 5-page PDF."""
        pdf_bytes = _create_test_pdf(5)
        result = ClassesDiscovery.extract_pdf_pages(pdf_bytes, 5, 5)
        assert _count_pages(result) == 1

    def test_extract_middle_range(self):
        """Extract pages 2-4 from a 10-page PDF."""
        pdf_bytes = _create_test_pdf(10)
        result = ClassesDiscovery.extract_pdf_pages(pdf_bytes, 2, 4)
        assert _count_pages(result) == 3

    def test_extract_all_pages(self):
        """Extract all pages — should produce same page count."""
        pdf_bytes = _create_test_pdf(5)
        result = ClassesDiscovery.extract_pdf_pages(pdf_bytes, 1, 5)
        assert _count_pages(result) == 5

    def test_extract_single_page_from_large_pdf(self):
        """Extract page 7 from a 20-page PDF."""
        pdf_bytes = _create_test_pdf(20)
        result = ClassesDiscovery.extract_pdf_pages(pdf_bytes, 7, 7)
        assert _count_pages(result) == 1

    def test_result_is_valid_pdf(self):
        """Verify the result is a valid PDF that can be loaded."""
        pdf_bytes = _create_test_pdf(5)
        result = ClassesDiscovery.extract_pdf_pages(pdf_bytes, 2, 3)
        # Should not raise
        doc = pdfium.PdfDocument(result)
        assert len(doc) == 2
        doc.close()

    def test_out_of_bounds_end(self):
        """End page exceeds document page count."""
        pdf_bytes = _create_test_pdf(5)
        with pytest.raises(ValueError, match="out of bounds"):
            ClassesDiscovery.extract_pdf_pages(pdf_bytes, 1, 10)

    def test_out_of_bounds_start(self):
        """Start page is 0 (invalid)."""
        pdf_bytes = _create_test_pdf(5)
        with pytest.raises(ValueError, match="out of bounds"):
            ClassesDiscovery.extract_pdf_pages(pdf_bytes, 0, 3)

    def test_result_smaller_than_original(self):
        """Extracted subset should generally be smaller than the original."""
        pdf_bytes = _create_test_pdf(10)
        result = ClassesDiscovery.extract_pdf_pages(pdf_bytes, 1, 2)
        # A 2-page PDF should be smaller than a 10-page PDF
        assert len(result) < len(pdf_bytes)
