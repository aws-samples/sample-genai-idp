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

    def extract_manifest(self, pdf_bytes: bytes, s3_prefix: str) -> list[dict]:
        """
        Deconstructs a text-based PDF into a structured manifest of text and image blocks.

        This method processes a PDF and generates a list of dictionaries, where each
        dictionary represents a content block (text or image) in its correct order.
        For image blocks, it performs OCR and prepares the necessary data for persistence.

        Args:
            pdf_bytes: The byte content of the PDF file.
            s3_prefix: The S3 prefix for the document, used to generate image keys.

        Returns:
            A list of dictionaries, representing the structured manifest of the document.
            Returns an empty list if the PDF cannot be processed or if an ocr_service
            is not available.
        """
        if not self.ocr_service:
            logger.error("OcrService not available. Cannot process images.")
            return []

        manifest = []
        try:
            pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
            for page_num, page in enumerate(pdf_document):
                page_dict = page.get_text("dict", sort=True)
                for block in page_dict["blocks"]:
                    if block["type"] == 0:  # Text block
                        for line in block["lines"]:
                            for span in line["spans"]:
                                if span["text"].strip():
                                    manifest.append({
                                        "type": "text",
                                        "content": span["text"],
                                        "page": page_num + 1,
                                        "bbox": span["bbox"],
                                    })
                    elif block["type"] == 1:  # Image block
                        try:
                            if "image" in block:
                                img_bytes = block["image"]
                                # This is a simplified example; you might need to handle different image formats
                                img_ext = "png"
                            elif "xref" in block and block["xref"] > 0:
                                img_info = pdf_document.extract_image(block["xref"])
                                img_bytes = img_info["image"]
                                img_ext = img_info["ext"]
                            else:
                                logger.warning("Image block found without image data or xref.")
                                continue

                            ocr_text = self.ocr_service.get_text_from_image(img_bytes)
                            s3_key = f"{s3_prefix}/images/{page_num + 1}_{block['bbox']}.{img_ext}"
                            manifest.append({
                                "type": "image",
                                "content": ocr_text,
                                "image_bytes": img_bytes,
                                "s3_key": s3_key,
                                "page": page_num + 1,
                                "bbox": block["bbox"],
                            })
                        except Exception as e:
                            logger.warning(f"Could not extract or process image on page {page_num + 1}: {e}")
            pdf_document.close()
        except Exception as e:
            logger.error(f"Failed to process PDF for manifest extraction: {e}")
            return []

        return manifest