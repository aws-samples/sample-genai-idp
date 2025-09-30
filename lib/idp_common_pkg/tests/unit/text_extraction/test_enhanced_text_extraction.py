import unittest
import os
import fitz  # PyMuPDF
from PIL import Image
from unittest.mock import MagicMock
import io
import pytest

from idp_common.text_extraction.service import TextExtractionService
from idp_common.ocr.service import OcrService

@pytest.mark.unit
class TestEnhancedTextExtraction(unittest.TestCase):

    def setUp(self):
        """Set up test resources."""
        self.test_dir = os.path.join(os.path.dirname(__file__), "test_data")
        os.makedirs(self.test_dir, exist_ok=True)

        # Create a dummy image in memory
        img = Image.new('RGB', (100, 100), color = 'red')
        img_bytes_io = io.BytesIO()
        img.save(img_bytes_io, format='PNG')
        img_bytes = img_bytes_io.getvalue()
        pix = fitz.Pixmap(img_bytes)

        # Create a dummy PDF with text and an image
        self.pdf_path = os.path.join(self.test_dir, "test_doc.pdf")
        doc = fitz.open()
        page = doc.new_page()
        
        # Add text
        page.insert_text((50, 72), "This is the first line of text.")
        
        # Add image from memory
        page.insert_image(fitz.Rect(50, 100, 150, 200), pixmap=pix)
        
        # Add more text
        page.insert_text((50, 250), "This is the second line of text.")
        
        doc.save(self.pdf_path)
        doc.close()

        # Mock OcrService
        self.mock_ocr_service = MagicMock(spec=OcrService)
        self.mock_ocr_service.get_text_from_image.return_value = "This is the image text."

        # Instantiate TextExtractionService with the mock
        self.text_extraction_service = TextExtractionService(ocr_service=self.mock_ocr_service)

    def tearDown(self):
        """Clean up test resources."""
        import shutil
        shutil.rmtree(self.test_dir)

    def test_extract_manifest(self):
        """
        Tests that the service correctly extracts text, identifies images,
        calls the OCR service, and composes the final manifest.
        """
        with open(self.pdf_path, "rb") as f:
            pdf_bytes = f.read()

        # Process the PDF
        manifest = self.text_extraction_service.extract_manifest(pdf_bytes, "test_prefix")
        
        self.assertGreaterEqual(len(manifest), 2)

        text_items = [item for item in manifest if item['type'] == 'text']
        image_items = [item for item in manifest if item['type'] == 'image']

        self.assertEqual(len(text_items), 2)
        self.assertEqual(len(image_items), 1)

        self.assertIn("This is the first line of text", text_items[0]['content'])
        self.assertIn("This is the second line of text", text_items[1]['content'])

        self.assertEqual(image_items[0]['content'], "This is the image text.")
        
        # Check that the OCR service was called
        self.mock_ocr_service.get_text_from_image.assert_called_once()

if __name__ == '__main__':
    unittest.main()