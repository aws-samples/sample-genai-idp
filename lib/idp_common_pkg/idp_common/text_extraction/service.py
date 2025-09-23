# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
This module provides a service for intelligent text extraction from documents.
"""

import logging

import fitz  # PyMuPDF

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

    def __init__(self, text_length_threshold: int = 100):
        """
        Initializes the TextExtractionService.

        Args:
            text_length_threshold: The minimum number of text characters to find
                                   in a PDF to classify it as "text-native". This
                                   helps filter out scanned PDFs that might have
                                   a few characters from a scanner's header or footer.
        """
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

    def extract_text_from_pdf(self, pdf_bytes: bytes) -> list[str]:
        """
        Extracts text from each page of a PDF document.

        This method should be called for PDFs that are known to be text-native.
        It uses PyMuPDF to efficiently parse the text content from each page.

        Args:
            pdf_bytes: The byte content of the PDF file.

        Returns:
            A list of strings, where each string corresponds to the
            extracted text of a page in the document.
        """
        pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_texts = [page.get_text("text") for page in pdf_document]
        pdf_document.close()
        return page_texts
