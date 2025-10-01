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

    def __init__(
        self,
        ocr_service: "OcrService" = None,
        text_length_threshold: int = 100,
        image_filter_config: dict = None,
    ):
        """
        Initializes the TextExtractionService.

        Args:
            ocr_service: An instance of the OcrService to use for image analysis.
            text_length_threshold: The minimum number of text characters to find
                                   in a PDF to classify it as "text-native". This
                                   helps filter out scanned PDFs that might have
                                   a few characters from a scanner's header or footer.
            image_filter_config: Configuration for filtering non-content images (logos, decorative elements).
                                 Default filters small images, header/footer images, and images with minimal OCR text.
                                 Set to None to disable filtering, or customize with:
                                 {
                                     "min_width": 150,  # Minimum width in pixels
                                     "min_height": 150,  # Minimum height in pixels
                                     "min_area": 22500,  # Minimum area in pixels (width * height)
                                     "max_aspect_ratio": 10.0,  # Max width/height or height/width ratio
                                     "header_footer_margin": 0.15,  # Top/bottom margin as % of page height
                                     "side_margin": 0.10,  # Left/right margin as % of page width
                                     "min_ocr_text_length": 10,  # Minimum OCR text characters
                                 }
        """
        self.ocr_service = ocr_service
        self.text_length_threshold = text_length_threshold

        # Set default image filter configuration
        if image_filter_config is None:
            self.image_filter_config = {
                "min_width": 150,
                "min_height": 150,
                "min_area": 22500,  # 150 * 150
                "max_aspect_ratio": 10.0,
                "header_footer_margin": 0.15,
                "side_margin": 0.10,
                "min_ocr_text_length": 10,
            }
        else:
            self.image_filter_config = image_filter_config

    def _is_content_image(
        self, img_bytes: bytes, bbox: tuple, page_rect: tuple, ocr_text: str
    ) -> bool:
        """
        Determines if an image is content-relevant or likely decorative (logo, watermark, etc.).

        Uses multiple heuristics:
        1. Size-based: Filters out very small images (likely icons/logos)
        2. Position-based: Filters images in typical header/footer/margin zones
        3. Aspect ratio: Filters images with extreme aspect ratios (banners)
        4. OCR content: Filters images with minimal text content

        Args:
            img_bytes: The raw image bytes
            bbox: Bounding box tuple (x0, y0, x1, y1) of the image on the page
            page_rect: Page rectangle (x0, y0, x1, y1) for positional analysis
            ocr_text: The OCR-extracted text from the image

        Returns:
            True if the image appears to be content-relevant, False if likely decorative
        """
        # If filtering is disabled, accept all images
        if self.image_filter_config is False:
            return True

        try:
            import io
            from PIL import Image

            # Get image dimensions
            img = Image.open(io.BytesIO(img_bytes))
            img_width, img_height = img.size

            # 1. SIZE-BASED FILTERING
            min_width = self.image_filter_config.get("min_width", 150)
            min_height = self.image_filter_config.get("min_height", 150)
            min_area = self.image_filter_config.get("min_area", 22500)

            if img_width < min_width or img_height < min_height:
                logger.debug(
                    f"Filtering image: too small ({img_width}x{img_height}, "
                    f"minimum {min_width}x{min_height})"
                )
                return False

            if (img_width * img_height) < min_area:
                logger.debug(
                    f"Filtering image: area too small ({img_width * img_height}, minimum {min_area})"
                )
                return False

            # 2. ASPECT RATIO FILTERING (extreme ratios indicate banners/dividers)
            max_aspect_ratio = self.image_filter_config.get("max_aspect_ratio", 10.0)
            aspect_ratio = max(img_width / img_height, img_height / img_width)

            if aspect_ratio > max_aspect_ratio:
                logger.debug(
                    f"Filtering image: extreme aspect ratio ({aspect_ratio:.2f}, max {max_aspect_ratio})"
                )
                return False

            # 3. POSITION-BASED FILTERING
            x0, y0, x1, y1 = bbox
            page_x0, page_y0, page_x1, page_y1 = page_rect

            page_width = page_x1 - page_x0
            page_height = page_y1 - page_y0

            # Calculate relative position on page
            rel_top = (y0 - page_y0) / page_height if page_height > 0 else 0
            rel_bottom = (y1 - page_y0) / page_height if page_height > 0 else 0
            rel_left = (x0 - page_x0) / page_width if page_width > 0 else 0
            rel_right = (x1 - page_x0) / page_width if page_width > 0 else 0

            header_footer_margin = self.image_filter_config.get("header_footer_margin", 0.15)
            side_margin = self.image_filter_config.get("side_margin", 0.10)

            # Filter images in header zone
            if rel_top < header_footer_margin:
                logger.debug(
                    f"Filtering image: in header zone (top at {rel_top:.2%} of page)"
                )
                return False

            # Filter images in footer zone
            if rel_bottom > (1.0 - header_footer_margin):
                logger.debug(
                    f"Filtering image: in footer zone (bottom at {rel_bottom:.2%} of page)"
                )
                return False

            # Filter images in side margins (often logos)
            if rel_left < side_margin or rel_right > (1.0 - side_margin):
                logger.debug(
                    f"Filtering image: in side margin (left={rel_left:.2%}, right={rel_right:.2%})"
                )
                return False

            # 4. OCR CONTENT-BASED FILTERING
            min_ocr_length = self.image_filter_config.get("min_ocr_text_length", 10)
            ocr_text_clean = ocr_text.strip()

            if len(ocr_text_clean) < min_ocr_length:
                logger.debug(
                    f"Filtering image: minimal OCR text ({len(ocr_text_clean)} chars, "
                    f"minimum {min_ocr_length})"
                )
                return False

            # Image passed all filters - likely content-relevant
            logger.debug(
                f"Image passed filters: {img_width}x{img_height}, "
                f"position ({rel_left:.2%}, {rel_top:.2%}), "
                f"OCR length {len(ocr_text_clean)}"
            )
            return True

        except Exception as e:
            # If filtering fails, err on the side of including the image
            logger.warning(f"Error during image filtering, including image: {e}")
            return True

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
            Each text block contains: type, content, page, bbox
            Each image block contains: type, content (OCR text), image_bytes, s3_key, page, bbox
            Returns an empty list if the PDF cannot be processed or if an ocr_service
            is not available.
        """
        if not self.ocr_service:
            logger.error("OcrService not available. Cannot process images.")
            return []

        manifest = []
        image_counter = 0

        try:
            pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
            logger.info(f"Processing {len(pdf_document)} pages for text extraction manifest")

            for page_num, page in enumerate(pdf_document):
                page_dict = page.get_text("dict", sort=True)

                for block in page_dict["blocks"]:
                    if block["type"] == 0:  # Text block
                        # Aggregate all text in the block into a single content string
                        block_text_parts = []
                        for line in block["lines"]:
                            line_text_parts = []
                            for span in line["spans"]:
                                if span["text"].strip():
                                    line_text_parts.append(span["text"])
                            if line_text_parts:
                                block_text_parts.append("".join(line_text_parts))

                        # Only add if there's actual text content
                        if block_text_parts:
                            block_text = "\n".join(block_text_parts)
                            manifest.append({
                                "type": "text",
                                "content": block_text,
                                "page": page_num + 1,
                                "bbox": block["bbox"],
                            })

                    elif block["type"] == 1:  # Image block
                        try:
                            img_bytes = None
                            img_ext = "png"

                            # Try to extract the image
                            if "xref" in block and block["xref"] > 0:
                                img_info = pdf_document.extract_image(block["xref"])
                                img_bytes = img_info["image"]
                                img_ext = img_info["ext"]
                            elif "image" in block:
                                img_bytes = block["image"]
                            else:
                                logger.warning(f"Image block found on page {page_num + 1} without extractable data.")
                                continue

                            if not img_bytes:
                                logger.warning(f"Failed to extract image bytes on page {page_num + 1}")
                                continue

                            # Perform OCR on the image
                            logger.debug(f"Performing OCR on image candidate from page {page_num + 1}")
                            ocr_text = self.ocr_service.get_text_from_image(img_bytes)

                            # Apply filtering to determine if this is a content image
                            page_rect = page.rect  # Get page dimensions for position analysis
                            is_content = self._is_content_image(
                                img_bytes, block["bbox"], page_rect, ocr_text
                            )

                            if not is_content:
                                logger.info(
                                    f"Skipping non-content image on page {page_num + 1} "
                                    f"(likely logo/decorative element)"
                                )
                                continue

                            # Generate a clean S3 key with sequential numbering
                            image_counter += 1
                            s3_key = f"{s3_prefix}/images/image_{image_counter}.{img_ext}"

                            manifest.append({
                                "type": "image",
                                "content": ocr_text,
                                "image_bytes": img_bytes,
                                "s3_key": s3_key,
                                "page": page_num + 1,
                                "bbox": block["bbox"],
                            })

                            logger.debug(f"Successfully processed content image {image_counter} on page {page_num + 1}")

                        except Exception as e:
                            logger.warning(
                                f"Could not extract or process image on page {page_num + 1}: {e}",
                                exc_info=True
                            )

            pdf_document.close()
            logger.info(
                f"Manifest extraction complete: {len(manifest)} items "
                f"({sum(1 for x in manifest if x['type'] == 'text')} text blocks, "
                f"{sum(1 for x in manifest if x['type'] == 'image')} images)"
            )

        except Exception as e:
            logger.error(f"Failed to process PDF for manifest extraction: {e}", exc_info=True)
            return []

        return manifest