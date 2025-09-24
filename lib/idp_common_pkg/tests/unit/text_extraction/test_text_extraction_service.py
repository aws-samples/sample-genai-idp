# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import unittest
import os
from idp_common.text_extraction.service import TextExtractionService

import pytest

@pytest.mark.unit
class TestTextExtractionService(unittest.TestCase):

    def setUp(self):
        """Set up test resources with corrected file paths."""
        self.text_native_pdf_path = "samples/bank-statement-multipage.pdf"
        self.scanned_pdf_path = "samples/lending_package.pdf"

    def test_is_pdf_text_native_returns_true_for_text_document(self):
        """
        Tests that is_pdf_text_native returns True for a PDF with ample text.
        """
        service = TextExtractionService(text_length_threshold=100)
        with open(self.text_native_pdf_path, "rb") as f:
            pdf_bytes = f.read()

        self.assertTrue(service.is_pdf_text_native(pdf_bytes))

    def test_is_pdf_text_native_returns_false_for_scanned_document(self):
        """
        Tests that is_pdf_text_native returns False for a PDF with negligible text,
        simulating a scanned document.
        """
        # This file has only 14 characters of text, so the default threshold of 100 will work.
        service = TextExtractionService(text_length_threshold=100)
        with open(self.scanned_pdf_path, "rb") as f:
            pdf_bytes = f.read()

        self.assertFalse(service.is_pdf_text_native(pdf_bytes))

    def test_is_pdf_text_native_handles_empty_bytes(self):
        """
        Tests that the service handles empty byte input gracefully.
        """
        service = TextExtractionService()
        self.assertFalse(service.is_pdf_text_native(b''))

    def test_is_pdf_text_native_handles_malformed_pdf(self):
        """
        Tests that the service handles malformed PDF content gracefully.
        """
        service = TextExtractionService()
        malformed_bytes = b'this is not a pdf'
        self.assertFalse(service.is_pdf_text_native(malformed_bytes))

    def test_extract_text_and_images_from_pdf(self):
        """
        Tests that _extract_text_and_images_from_pdf returns a list of tuples, one for each page.
        """
        service = TextExtractionService()
        with open(self.text_native_pdf_path, "rb") as f:
            pdf_bytes = f.read()

        extracted_data = service._extract_text_and_images_from_pdf(pdf_bytes)

        # The bank-statement-multipage.pdf has 5 pages
        self.assertIsInstance(extracted_data, list)
        self.assertEqual(len(extracted_data), 5)
        
        # Check the structure of the first page data
        first_page_data = extracted_data[0]
        self.assertIsInstance(first_page_data, tuple)
        self.assertEqual(len(first_page_data), 2)
        
        # Check text and images
        text, images = first_page_data
        self.assertIsInstance(text, str)
        self.assertIsInstance(images, dict)
        
        # This document has 1 image
        self.assertEqual(len(images), 1)
        # Check if some expected text is present on the first page
        self.assertIn("Example Inc. Credit Union", text)

    def test_inspect_pdf_for_images(self):
        import fitz
        doc = fitz.open(self.text_native_pdf_path)
        for i, page in enumerate(doc):
            print(f"Page {i} images: {page.get_images(full=True)}")

if __name__ == '__main__':
    unittest.main()
