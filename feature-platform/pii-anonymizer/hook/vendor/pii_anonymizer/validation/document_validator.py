# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Document validators for Word, Excel, and Text files.
"""

import os
import logging

logger = logging.getLogger(__name__)


class DocumentValidationError(Exception):
    """Raised when document validation fails"""

    pass


def validate_word(file_path, config=None):
    """
    Validate Word document before processing.

    Args:
        file_path: Path to DOCX file
        config: Configuration dict (uses defaults if None)

    Raises:
        DocumentValidationError: If validation fails
    """
    from docx import Document

    # Get limits from config or use defaults
    if config:
        max_size_mb = (
            config.get("validation", {}).get("max_file_size_mb", {}).get("word", 50)
        )
    else:
        max_size_mb = 50

    # Check file exists
    if not os.path.exists(file_path):
        raise DocumentValidationError("File does not exist")

    # Check file size
    file_size = os.path.getsize(file_path)
    max_bytes = max_size_mb * 1024 * 1024
    if file_size > max_bytes:
        raise DocumentValidationError(
            f"File size {file_size / 1024 / 1024:.1f}MB exceeds maximum {max_size_mb}MB"
        )

    if file_size == 0:
        raise DocumentValidationError("File is empty")

    # Validate DOCX structure
    try:
        doc = Document(file_path)
        # Try to access paragraphs to verify document is valid
        _ = len(doc.paragraphs)
    except Exception as e:
        raise DocumentValidationError(f"Invalid DOCX file: {str(e)}")

    return True


def validate_excel(file_path, config=None):
    """
    Validate Excel document before processing.

    Args:
        file_path: Path to XLSX file
        config: Configuration dict (uses defaults if None)

    Raises:
        DocumentValidationError: If validation fails
    """
    import openpyxl

    # Get limits from config or use defaults
    if config:
        max_size_mb = (
            config.get("validation", {}).get("max_file_size_mb", {}).get("excel", 50)
        )
        max_sheets = (
            config.get("validation", {}).get("max_sheets", {}).get("excel", 100)
        )
    else:
        max_size_mb = 50
        max_sheets = 100

    # Check file exists
    if not os.path.exists(file_path):
        raise DocumentValidationError("File does not exist")

    # Check file size
    file_size = os.path.getsize(file_path)
    max_bytes = max_size_mb * 1024 * 1024
    if file_size > max_bytes:
        raise DocumentValidationError(
            f"File size {file_size / 1024 / 1024:.1f}MB exceeds maximum {max_size_mb}MB"
        )

    if file_size == 0:
        raise DocumentValidationError("File is empty")

    # Validate XLSX structure
    try:
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)

        # Check sheet count
        sheet_count = len(wb.sheetnames)
        if sheet_count > max_sheets:
            raise DocumentValidationError(
                f"Excel has {sheet_count} sheets, exceeds maximum {max_sheets}"
            )

        wb.close()
    except DocumentValidationError:
        raise
    except Exception as e:
        raise DocumentValidationError(f"Invalid XLSX file: {str(e)}")

    return True


def validate_txt(file_path, config=None):
    """
    Validate text file before processing.

    Args:
        file_path: Path to TXT file
        config: Configuration dict (uses defaults if None)

    Raises:
        DocumentValidationError: If validation fails
    """
    # Get limits from config or use defaults
    if config:
        max_size_mb = (
            config.get("validation", {}).get("max_file_size_mb", {}).get("txt", 10)
        )
    else:
        max_size_mb = 10

    # Check file exists
    if not os.path.exists(file_path):
        raise DocumentValidationError("File does not exist")

    # Check file size
    file_size = os.path.getsize(file_path)
    max_bytes = max_size_mb * 1024 * 1024
    if file_size > max_bytes:
        raise DocumentValidationError(
            f"File size {file_size / 1024 / 1024:.1f}MB exceeds maximum {max_size_mb}MB"
        )

    if file_size == 0:
        raise DocumentValidationError("File is empty")

    # Validate text encoding
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            # Read first 1KB to check encoding
            f.read(1024)
    except UnicodeDecodeError:
        raise DocumentValidationError("Invalid UTF-8 encoding")
    except Exception as e:
        raise DocumentValidationError(f"Cannot read text file: {str(e)}")

    return True
