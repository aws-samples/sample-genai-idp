# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import logging
from io import BytesIO
from typing import List

from pypdf import PdfReader

logger = logging.getLogger(__name__)


def _reader(pdf_source) -> PdfReader:
    """Build a pypdf PdfReader from a path, bytes, or BytesIO."""
    if isinstance(pdf_source, str):
        return PdfReader(pdf_source)
    elif isinstance(pdf_source, (bytes, bytearray)):
        return PdfReader(BytesIO(pdf_source))
    elif isinstance(pdf_source, BytesIO):
        return PdfReader(pdf_source)
    return PdfReader(pdf_source)


def is_text_based_page(pdf_source, page_num: int, text_threshold: int = 50) -> bool:
    """
    Check if a page contains substantial text content.

    Args:
        pdf_source: PDF file path or bytes
        page_num: Page number (1-indexed)
        text_threshold: Minimum characters to consider text-based

    Returns:
        True if page has substantial text, False if image-only
    """
    try:
        reader = _reader(pdf_source)
        text = (reader.pages[page_num - 1].extract_text() or "").strip()
        return len(text) >= text_threshold
    except Exception as e:
        logger.error(f"Error checking page {page_num}: {str(e)}")
        return False


def get_text_based_pages(pdf_source, text_threshold: int = 50) -> List[int]:
    """
    Get list of page numbers that contain substantial text.

    Args:
        pdf_source: PDF file path or bytes
        text_threshold: Minimum characters to consider text-based

    Returns:
        List of page numbers (1-indexed) that have text content
    """
    try:
        reader = _reader(pdf_source)
        text_pages = []
        for page_num, page in enumerate(reader.pages):
            text = (page.extract_text() or "").strip()
            if len(text) >= text_threshold:
                text_pages.append(page_num + 1)  # 1-indexed
        return text_pages
    except Exception as e:
        logger.error(f"Error analyzing pages: {str(e)}")
        return []
