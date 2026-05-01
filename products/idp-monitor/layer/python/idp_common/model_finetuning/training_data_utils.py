"""
Shared utility functions for fine-tuning training data generation.

These functions are used by both finetuning_data_generator and
finetuning_process_document Lambda functions to avoid code duplication.
"""

import base64
import io
import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


def get_extraction_fields(baseline: Dict[str, Any]) -> List[str]:
    """
    Extract field names from baseline extraction data.

    Parses various baseline formats to build a flat list of field names
    for training data generation.

    Supported formats:
        - Format 1: ``{"Sections": [{"Extraction": {"field": ...}}]}``
        - Format 2: ``{"Extraction": {"field": ...}}``
        - Format 3: ``{"fields": [{"name": "field"}, ...]}``

    Args:
        baseline: The baseline extraction result dictionary.

    Returns:
        List of field name strings (empty strings filtered out).
    """
    fields: List[str] = []

    # Format 1: Sections with Extraction
    sections = baseline.get("Sections", [])
    for section in sections:
        extraction = section.get("Extraction", {})
        fields.extend(extraction.keys())

    # Format 2: Direct extraction at top level
    extraction = baseline.get("Extraction", {})
    fields.extend(extraction.keys())

    # Format 3: Fields array
    for field in baseline.get("fields", []):
        if isinstance(field, dict):
            fields.append(field.get("name", ""))
        elif isinstance(field, str):
            fields.append(field)

    return [f for f in fields if f]  # Filter empty strings


def format_baseline_for_training(baseline: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format baseline extraction data into the structure expected for training.

    Maps baseline result fields to a clean ``field_name -> value`` dict.
    Handles nested value objects (``{"value": ...}`` or ``{"Value": ...}``).

    Supported formats:
        - Format 1: ``{"Sections": [{"Extraction": {"field": value}}]}``
        - Format 2: ``{"Extraction": {"field": value}}``
        - Format 3: ``{"fields": [{"name": "field", "value": "val"}]}``
        - Fallback: returns all non-metadata keys from baseline.

    Args:
        baseline: The baseline extraction result dictionary.

    Returns:
        Dictionary mapping field names to their extracted values.
    """
    result: Dict[str, Any] = {}

    # Format 1: Sections with Extraction
    sections = baseline.get("Sections", [])
    for section in sections:
        extraction = section.get("Extraction", {})
        for key, value in extraction.items():
            if isinstance(value, dict):
                result[key] = value.get("value", value.get("Value", str(value)))
            else:
                result[key] = value

    # Format 2: Direct extraction at top level
    extraction = baseline.get("Extraction", {})
    for key, value in extraction.items():
        if isinstance(value, dict):
            result[key] = value.get("value", value.get("Value", str(value)))
        else:
            result[key] = value

    # Format 3: Fields array with values
    for field in baseline.get("fields", []):
        if isinstance(field, dict):
            name = field.get("name", "")
            value = field.get("value", "")
            if name:
                result[name] = value

    # Fallback: return baseline as-is (cleaned up)
    if not result:
        for key, value in baseline.items():
            if key not in [
                "Sections",
                "metadata",
                "Metadata",
                "pageCount",
                "PageCount",
            ]:
                result[key] = value

    return result


def convert_pdf_to_images(
    pdf_bytes: bytes,
    max_pages: int = 20,
    dpi: int = 150,
) -> List[Tuple[bytes, str]]:
    """
    Convert PDF bytes to a list of PNG image byte tuples (one per page).

    Uses pypdfium2 for PDF rendering. Limits to *max_pages* to avoid
    excessive memory usage during training data generation.

    Args:
        pdf_bytes: Raw PDF file content.
        max_pages: Maximum number of pages to convert.
        dpi: Resolution for rendering (default 150).

    Returns:
        List of ``(png_bytes, "png")`` tuples, one per page.
        Returns an empty list if PDF conversion libraries are unavailable
        or an error occurs.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        logger.error("pypdfium2 is required for PDF to image conversion")
        return []

    images: List[Tuple[bytes, str]] = []
    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
        num_pages = min(len(pdf), max_pages)

        logger.info(f"Converting PDF with {len(pdf)} pages (processing {num_pages})")

        for page_idx in range(num_pages):
            page = pdf[page_idx]
            scale = dpi / 72.0
            bitmap = page.render(scale=scale)
            pil_image = bitmap.to_pil()

            buf = io.BytesIO()
            pil_image.save(buf, format="PNG", optimize=True)
            images.append((buf.getvalue(), "png"))

        pdf.close()
    except Exception as e:
        logger.error(f"Error converting PDF to images: {e}", exc_info=True)
        return []

    return images


def get_document_images(
    s3_client: Any,
    bucket: str,
    document_key: str,
) -> List[Tuple[str, str]]:
    """
    Get base64-encoded images for a document stored in S3.

    Supports PDF files (converted to images via :func:`convert_pdf_to_images`)
    and common image formats (PNG, JPG, JPEG, TIFF, BMP, GIF, WEBP).

    Args:
        s3_client: Boto3 S3 client.
        bucket: S3 bucket name.
        document_key: S3 object key for the document.

    Returns:
        List of ``(base64_string, format)`` tuples.
        Returns an empty list for unsupported file types.
    """
    response = s3_client.get_object(Bucket=bucket, Key=document_key)
    file_bytes = response["Body"].read()
    content_type = response.get("ContentType", "")

    lower_key = document_key.lower()

    if lower_key.endswith(".pdf") or "pdf" in content_type:
        page_images = convert_pdf_to_images(file_bytes)
        return [
            (base64.b64encode(img_bytes).decode("utf-8"), fmt)
            for img_bytes, fmt in page_images
        ]

    # Map extensions to format names
    extension_map = {
        ".png": "png",
        ".jpg": "jpeg",
        ".jpeg": "jpeg",
        ".gif": "gif",
        ".webp": "webp",
        ".tiff": "tiff",
        ".bmp": "bmp",
    }

    for ext, fmt in extension_map.items():
        if lower_key.endswith(ext):
            return [(base64.b64encode(file_bytes).decode("utf-8"), fmt)]

    logger.warning(f"Unsupported file type for {document_key}, treating as PNG")
    return [(base64.b64encode(file_bytes).decode("utf-8"), "png")]


def get_document_images_from_uri(
    s3_client: Any,
    s3_uri: str,
) -> List[Tuple[str, str]]:
    """
    Convenience wrapper around :func:`get_document_images` that accepts an S3 URI.

    Parses ``s3://bucket/key`` and delegates to :func:`get_document_images`.

    Args:
        s3_client: Boto3 S3 client.
        s3_uri: Full S3 URI (e.g. ``s3://my-bucket/path/to/doc.pdf``).

    Returns:
        List of ``(base64_string, format)`` tuples.

    Raises:
        ValueError: If *s3_uri* does not start with ``s3://``.
    """
    if not s3_uri.startswith("s3://"):
        raise ValueError(f"Invalid S3 URI: {s3_uri}")

    path = s3_uri[5:]
    parts = path.split("/", 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ""

    return get_document_images(s3_client, bucket, key)
