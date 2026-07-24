# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""PDF input validation to prevent malicious uploads"""

import os

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class PDFValidationError(Exception):
    """Raised when PDF validation fails"""

    pass


def validate_pdf(file_path, config=None):
    """
    Validate PDF before processing

    Args:
        file_path: Path to PDF file
        config: Configuration dict (uses defaults if None)

    Raises:
        PDFValidationError: If validation fails
    """
    # Get limits from config or use defaults
    if config:
        max_size_mb = (
            config.get("validation", {}).get("max_file_size_mb", {}).get("pdf", 50)
        )
        max_pages = config.get("validation", {}).get("max_pages", {}).get("pdf", 1000)
    else:
        max_size_mb = 50
        max_pages = 1000

    # Check file exists
    if not os.path.exists(file_path):
        raise PDFValidationError("File does not exist")

    # Check file size
    file_size = os.path.getsize(file_path)
    max_bytes = max_size_mb * 1024 * 1024
    if file_size > max_bytes:
        raise PDFValidationError(
            f"File size {file_size / 1024 / 1024:.1f}MB exceeds maximum {max_size_mb}MB"
        )

    if file_size == 0:
        raise PDFValidationError("File is empty")

    # Validate PDF structure
    try:
        reader = PdfReader(file_path)

        # Check if PDF is encrypted (before accessing pages)
        if reader.is_encrypted:
            raise PDFValidationError("Encrypted PDFs are not supported")

        num_pages = len(reader.pages)
        if num_pages == 0:
            raise PDFValidationError("PDF has no pages")

        if num_pages > max_pages:
            raise PDFValidationError(
                f"PDF has {num_pages} pages, exceeds maximum {max_pages}"
            )

    except PDFValidationError:
        raise
    except PdfReadError as e:
        raise PDFValidationError(f"Invalid PDF structure: {str(e)}")
    except Exception as e:
        raise PDFValidationError(f"PDF validation failed: {str(e)}")

    return True
