# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
This module provides a service for intelligent text extraction from documents.
"""

import logging
from typing import TYPE_CHECKING

import fitz  # PyMuPDF

if TYPE_CHECKING:
    from idp_common.ocr.service import OcrService

logger = logging.getLogger(__name__)


class TextExtractionService:
    """
    A service to intelligently extract text from documents, particularly PDFs.

    This service can distinguish between "text-native" PDFs (those with
    selectable, machine-readable text) and "scanned" PDFs (image-based).
    It provides methods to check a PDF's type and extract text accordingly,
    allowing systems to avoid expensive OCR calls for documents where text
    can be extracted directly.
    """

    def __init__(self, ocr_service: "OcrService" = None, text_length_threshold: int = 100):
        """
        Initializes the TextExtractionService.

        Args:
            ocr_service: An instance of the OcrService to use for image analysis.
            text_length_threshold: The minimum number of text characters to find
                                   in a PDF to classify it as "text-native". This
                                   helps filter out scanned PDFs that might have
                                   a few characters from a scanner's header or footer.
        """
        self.ocr_service = ocr_service
        self.text_length_threshold = text_length_threshold

    def is_pdf_text_native(self, pdf_bytes: bytes) -> bool:
        """
        Inspects PDF bytes to determine if it contains significant extractable text.

        It opens the PDF in memory and iterates through its pages, summing the
        length of the text extracted from each. If the total text length exceeds
        the configured threshold, the PDF is considered text-native.

        Args:
            pdf_bytes: The byte content of the PDF file.

        Returns:
            True if the PDF is determined to be text-native, False otherwise.
            Returns False if the file is malformed, encrypted, or empty.
        """
        if not pdf_bytes:
            return False

        try:
            # Open PDF from memory using PyMuPDF
            pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
            total_text_length = 0

            # Iterate through pages and accumulate text length
            for page in pdf_document:
                # page.get_text("text") is used for efficient, raw text extraction
                total_text_length += len(page.get_text("text"))
                if total_text_length >= self.text_length_threshold:
                    logger.info(
                        f"PDF contains sufficient text ({total_text_length} chars), "
                        "classifying as text-native."
                    )
                    pdf_document.close()
                    return True

            logger.info(
                f"PDF contains only {total_text_length} text characters, "
                "classifying as scanned/image-based."
            )
            pdf_document.close()
            return False
        except Exception as e:
            # Handles exceptions from malformed, encrypted, or otherwise invalid PDFs
            logger.warning(
                f"Could not determine if PDF is text-native due to an error: {e}. "
                "Defaulting to scanned/image-based."
            )
            return False

    def extract_text_and_images_from_pdf(self, pdf_bytes: bytes) -> list[str]:
        """
        Extracts text from a PDF, performs OCR on embedded images, and returns the consolidated text for each page.
        This is the main entry point for processing PDFs with mixed content.
        """
        if not self.ocr_service:
            logger.warning("OcrService not available. Cannot process images. Returning only text.")
            pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
            page_texts = [page.get_text("text") for page in pdf_document]
            pdf_document.close()
            return page_texts

        pages_data = self._extract_text_and_images_from_pdf(pdf_bytes)

        final_page_texts = []
        for page_text_with_placeholders, images in pages_data:
            
            final_text = page_text_with_placeholders
            if images:
                replacements = {}
                for placeholder, image_bytes in images.items():
                    ocr_text = self.ocr_service.get_text_from_image(image_bytes)
                    replacements[placeholder] = f"[Image Content: {ocr_text}]"

                for placeholder, ocr_content in replacements.items():
                    final_text = final_text.replace(placeholder, ocr_content)
            
            final_page_texts.append(final_text)

        return final_page_texts

    def _extract_text_and_images_from_pdf(self, pdf_bytes: bytes) -> list[tuple[str, dict[str, bytes]]]:
        """
        Extracts text and images from each page of a PDF document.

        This method should be called for PDFs that are known to be text-native.
        It uses PyMuPDF to parse the text content and extract images from each page.

        Args:
            pdf_bytes: The byte content of the PDF file.

        Returns:
            A list of tuples, where each tuple contains:
            - The extracted text of a page with image placeholders.
            - A dictionary mapping image placeholders to image bytes.
        """
        import uuid
        pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
        results = []
        for page in pdf_document:
            page_text = ""
            images = {}
            page_dict = page.get_text("dict", sort=True)

            for block in page_dict["blocks"]:
                if block["type"] == 0:  # Text block
                    for line in block["lines"]:
                        line_text = ""
                        for span in line["spans"]:
                            line_text += span["text"]
                        page_text += line_text + "\n"
                elif block["type"] == 1:  # Image block
                    try:
                        if "image" in block:
                            img_bytes = block["image"]
                        elif "xref" in block and block["xref"] > 0:
                            img_bytes = pdf_document.extract_image(block["xref"])["image"]
                        else:
                            logger.warning("Image block found without image data or xref.")
                            continue
                            
                        placeholder = f"[IMAGE-PLACEHOLDER-{uuid.uuid4()}]"
                        page_text += f"\n{placeholder}\n"
                        images[placeholder] = img_bytes
                    except Exception as e:
                        logger.warning(f"Could not extract image from page: {e}")
            results.append((page_text.strip(), images))
        pdf_document.close()
        return results