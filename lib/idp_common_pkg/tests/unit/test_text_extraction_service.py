# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import unittest
import os
from idp_common.text_extraction.service import TextExtractionService

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

    def test_extract_text_from_pdf(self):
        """
        Tests that extract_text_from_pdf returns a list of strings, one for each page.
        """
        service = TextExtractionService()
        with open(self.text_native_pdf_path, "rb") as f:
            pdf_bytes = f.read()

        extracted_texts = service.extract_text_from_pdf(pdf_bytes)

        # The bank-statement-multipage.pdf has 5 pages
        self.assertIsInstance(extracted_texts, list)
        self.assertEqual(len(extracted_texts), 5)
        self.assertIsInstance(extracted_texts[0], str)
        # Check if some expected text is present on the first page
        self.assertIn("Example Inc. Credit Union", extracted_texts[0])

if __name__ == '__main__':
    unittest.main()
