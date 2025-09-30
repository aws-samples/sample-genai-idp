import unittest
import os
from idp_common.text_extraction.service import TextExtractionService

import pytest

@pytest.mark.unit
class TestTextExtractionService(unittest.TestCase):

    def setUp(self):
        """Set up test resources with corrected file paths."""
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../.."))
        self.text_native_pdf_path = os.path.join(base_dir, "samples/bank-statement-multipage.pdf")
        self.scanned_pdf_path = os.path.join(base_dir, "samples/lending_package.pdf")

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

    def test_extract_manifest(self):
        """
        Tests that extract_manifest returns a structured manifest.
        """
        from unittest.mock import MagicMock
        from idp_common.ocr.service import OcrService

        mock_ocr_service = MagicMock(spec=OcrService)
        mock_ocr_service.get_text_from_image.return_value = "This is the image text."
        service = TextExtractionService(ocr_service=mock_ocr_service)

        with open(self.text_native_pdf_path, "rb") as f:
            pdf_bytes = f.read()

        manifest = service.extract_manifest(pdf_bytes, "test_prefix")

        self.assertIsInstance(manifest, list)
        self.assertGreater(len(manifest), 0)

        # Check structure of a text item
        text_item = next((item for item in manifest if item['type'] == 'text'), None)
        self.assertIsNotNone(text_item)
        self.assertIn("content", text_item)
        self.assertIn("page", text_item)
        self.assertIn("bbox", text_item)

        # Check structure of an image item
        image_item = next((item for item in manifest if item['type'] == 'image'), None)
        self.assertIsNotNone(image_item)
        self.assertEqual(image_item['content'], "This is the image text.")
        self.assertIn("image_bytes", image_item)
        self.assertIn("s3_key", image_item)
        self.assertIn("page", image_item)
        self.assertIn("bbox", image_item)

    @pytest.mark.skip(reason="This test is for manual inspection and prints to stdout.")
    def test_inspect_pdf_for_images(self):
        import fitz
        doc = fitz.open(self.text_native_pdf_path)
        for i, page in enumerate(doc):
            print(f"Page {i} images: {page.get_images(full=True)}")

if __name__ == '__main__':
    unittest.main()