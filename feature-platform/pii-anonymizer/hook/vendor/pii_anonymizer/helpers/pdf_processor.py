# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
PDF Processor Module

Handles extraction of images from PDF documents using **pypdfium2** (Google
PDFium; Apache-2.0/BSD-3-Clause) — a permissively licensed renderer. Provides:
1. Convert PDF pages to high-resolution images (page rendering)
2. Extract embedded images from PDF documents
"""

import os
import logging
import traceback
from typing import Dict, List, Tuple, Optional
import boto3
from io import BytesIO

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from PIL import Image

# Configure logging
logger = logging.getLogger(__name__)


def _open_pdf(pdf_source):
    """Open a PDF from a file path, bytes, or BytesIO using pypdfium2."""
    if isinstance(pdf_source, str):
        return pdfium.PdfDocument(pdf_source)
    elif isinstance(pdf_source, bytes):
        return pdfium.PdfDocument(pdf_source)
    elif isinstance(pdf_source, BytesIO):
        return pdfium.PdfDocument(pdf_source.getvalue())
    raise ValueError("pdf_source must be file path, bytes, or BytesIO")


def extract_page_as_image(
    pdf_source, page_num: int, dpi: int = 300, source_info: str = ""
) -> Tuple[Optional[Image.Image], Dict]:
    """
    Extract a specific page from a PDF as a high-resolution image.

    Args:
        pdf_source: Either a file path (str) or BytesIO/bytes object
        page_num: Page number to extract (0-indexed)
        dpi: Resolution for the extracted image
        source_info: Optional source info for metadata (e.g., S3 URI)

    Returns:
        Tuple containing:
        - PIL Image of the page (or None if extraction fails)
        - Metadata dictionary with page dimensions and scale factors
    """
    try:
        pdf = _open_pdf(pdf_source)

        if page_num >= len(pdf):
            raise ValueError(
                f"Page number {page_num} out of range (document has {len(pdf)} pages)"
            )

        page = pdf[page_num]

        # Page size in PDF points (72 DPI standard)
        page_width, page_height = page.get_size()

        # Render at the requested DPI (scale = dpi / 72) → RGB PIL image
        scale = dpi / 72
        img = page.render(scale=scale).to_pil().convert("RGB")

        # Store metadata for coordinate mapping (same keys as before)
        metadata = {
            "page_number": page_num + 1,
            "page_width": page_width,
            "page_height": page_height,
            "width": img.width,
            "height": img.height,
            "dpi": dpi,
            "scale_x": img.width / page_width if page_width else scale,
            "scale_y": img.height / page_height if page_height else scale,
            "source": source_info if source_info else str(pdf_source),
        }

        pdf.close()
        return img, metadata

    except Exception as e:
        logger.error(f"Error extracting page as image: {str(e)}")
        traceback.print_exc()
        return None, {}


def extract_all_pages_as_images(
    pdf_source, dpi: int = 300, s3_client=None
) -> List[Tuple[Image.Image, Dict]]:
    """
    Extract all pages from a PDF as high-resolution images.
    Supports both local files and S3 URIs.

    Args:
        pdf_source: Either a local file path OR S3 URI (s3://bucket/key)
        dpi: Resolution for the extracted images
        s3_client: S3 client (required if pdf_source is S3 URI)

    Returns:
        List of tuples, each containing:
        - PIL Image of a page
        - Metadata dictionary with page dimensions and scale factors
    """
    try:
        source_info = str(pdf_source)

        # Resolve S3 URI to bytes
        if isinstance(pdf_source, str) and pdf_source.startswith("s3://"):
            if s3_client is None:
                s3_client = boto3.client("s3")
            s3_path = pdf_source.replace("s3://", "")
            bucket, key = s3_path.split("/", 1)
            response = s3_client.get_object(Bucket=bucket, Key=key)
            pdf_source = response["Body"].read()

        # Determine page count
        pdf = _open_pdf(pdf_source)
        num_pages = len(pdf)
        pdf.close()

        results = []
        for page_num in range(num_pages):
            img, metadata = extract_page_as_image(
                pdf_source, page_num, dpi, source_info
            )
            if img is not None:
                results.append((img, metadata))

        return results

    except Exception as e:
        logger.error(f"Error extracting all pages as images: {str(e)}")
        traceback.print_exc()
        return []


def extract_embedded_images(
    pdf_source, page_num: int, source_info: str = ""
) -> List[Tuple[Image.Image, Dict]]:
    """
    Extract embedded images from a specific page of a PDF (via pypdfium2 page
    objects of type IMAGE).

    Args:
        pdf_source: Either a file path (str) or BytesIO/bytes object
        page_num: Page number to extract images from (0-indexed)
        source_info: Optional source info for metadata (e.g., S3 URI)

    Returns:
        List of tuples, each containing:
        - PIL Image of an embedded image
        - Metadata dictionary with image information
    """
    try:
        pdf = _open_pdf(pdf_source)

        if page_num >= len(pdf):
            raise ValueError(
                f"Page number {page_num} out of range (document has {len(pdf)} pages)"
            )

        page = pdf[page_num]

        images = []
        img_index = 0
        for obj in page.get_objects():
            if getattr(obj, "type", None) != pdfium_c.FPDF_PAGEOBJ_IMAGE:
                continue
            try:
                # render=True applies any soft-mask/transform so the extracted
                # raster matches what is shown on the page.
                pil_img = obj.get_bitmap(render=True).to_pil().convert("RGB")
            except Exception as obj_err:  # noqa: BLE001
                logger.warning(f"Skipping unreadable embedded image: {obj_err}")
                continue

            metadata = {
                "page_number": page_num + 1,
                "image_index": img_index,
                "width": pil_img.width,
                "height": pil_img.height,
                "format": "png",
                "source": source_info if source_info else str(pdf_source),
            }
            images.append((pil_img, metadata))
            img_index += 1

        pdf.close()
        return images

    except Exception as e:
        logger.error(f"Error extracting embedded images: {str(e)}")
        traceback.print_exc()
        return []


def extract_all_embedded_images(
    pdf_source, s3_client=None
) -> List[Tuple[Image.Image, Dict]]:
    """
    Extract all embedded images from a PDF.
    Supports both local files and S3 URIs.

    Args:
        pdf_source: Either a local file path OR S3 URI (s3://bucket/key)
        s3_client: S3 client (required if pdf_source is S3 URI)

    Returns:
        List of tuples of (PIL Image, metadata dict)
    """
    try:
        source_info = str(pdf_source)

        if isinstance(pdf_source, str) and pdf_source.startswith("s3://"):
            if s3_client is None:
                s3_client = boto3.client("s3")
            s3_path = pdf_source.replace("s3://", "")
            bucket, key = s3_path.split("/", 1)
            response = s3_client.get_object(Bucket=bucket, Key=key)
            pdf_source = response["Body"].read()

        pdf = _open_pdf(pdf_source)
        num_pages = len(pdf)
        pdf.close()

        all_images = []
        for page_num in range(num_pages):
            all_images.extend(
                extract_embedded_images(pdf_source, page_num, source_info)
            )
        return all_images

    except Exception as e:
        logger.error(f"Error extracting all embedded images: {str(e)}")
        traceback.print_exc()
        return []


def save_image(image: Image.Image, output_dir: str, filename: str) -> str:
    """
    Save a PIL Image to a file.

    Args:
        image: PIL Image to save
        output_dir: Directory to save the image in
        filename: Name for the image file

    Returns:
        Path to the saved image
    """
    try:
        os.makedirs(output_dir, exist_ok=True)

        ext = image.format.lower() if image.format else "png"
        if not filename.lower().endswith(f".{ext}"):
            filename = f"{filename}.{ext}"

        output_path = os.path.join(output_dir, filename)
        image.save(output_path)
        return output_path

    except Exception as e:
        logger.error(f"Error saving image: {str(e)}")
        traceback.print_exc()
        return ""
