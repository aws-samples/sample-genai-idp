# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
This module provides a service for intelligent text extraction from documents.
"""

import logging
from typing import TYPE_CHECKING
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache

import fitz  # PyMuPDF
import json

from idp_common import utils

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
        max_workers: int = 4,
        enable_parallel_ocr: bool = True,
        enable_proximity_grouping: bool = True,
        max_drawings_per_page: int = 50,
        rendering_zoom: float = 1.5,
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
            max_workers: Maximum number of parallel OCR workers (default: 4)
            enable_parallel_ocr: Enable parallel processing for OCR operations (default: True)
            enable_proximity_grouping: Enable grouping of nearby images/drawings (default: True)
            max_drawings_per_page: Maximum drawings to process per page (default: 50)
            rendering_zoom: Zoom factor for rendering images/drawings (default: 1.5)
        """
        self.ocr_service = ocr_service
        self.text_length_threshold = text_length_threshold
        self.max_workers = max_workers
        self.enable_parallel_ocr = enable_parallel_ocr
        self.enable_proximity_grouping = enable_proximity_grouping
        self.max_drawings_per_page = max_drawings_per_page
        self.rendering_zoom = rendering_zoom

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

    def _table_to_markdown(self, table_data: list, headers: list = None) -> str:
        """
        Convert table data to Markdown format for LLM consumption.

        Args:
            table_data: List of lists representing table rows
            headers: Optional list of header names

        Returns:
            Markdown-formatted table string
        """
        if not table_data:
            return ""

        markdown_lines = []

        # Add headers if provided
        if headers:
            markdown_lines.append("| " + " | ".join(str(h) for h in headers) + " |")
            markdown_lines.append("|" + "|".join(["---"] * len(headers)) + "|")

        # Add data rows
        for row in table_data:
            markdown_lines.append("| " + " | ".join(str(cell) if cell else "" for cell in row) + " |")

        return "\n".join(markdown_lines)

    def _group_by_proximity(self, items: list[dict], proximity_threshold: float = 20.0, max_items: int = 100) -> list[list[dict]]:
        """
        Groups items by proximity of their bounding boxes using a fast greedy algorithm.

        Items whose bounding boxes are within proximity_threshold pixels of each other
        are grouped together. This helps combine fragmented elements (like multi-part
        formulas or split images) into single entities.

        Args:
            items: List of dicts, each containing a 'bbox' key with (x0, y0, x1, y1)
            proximity_threshold: Maximum distance in pixels between boxes to group them
            max_items: Maximum items to process; if exceeded, returns items ungrouped for speed

        Returns:
            List of groups, where each group is a list of items that should be combined
        """
        if not items:
            return []

        # Fast path: if too many items, skip grouping to avoid performance issues
        if len(items) > max_items:
            logger.warning(f"Skipping grouping for {len(items)} items (exceeds max_items={max_items}). Returning ungrouped.")
            return [[item] for item in items]

        if len(items) == 1:
            return [items]

        # Pre-convert all bboxes to Rect objects for faster access
        rects = [fitz.Rect(item['bbox']) for item in items]
        n = len(items)

        # Track which items have been assigned to groups
        assigned = [False] * n
        groups = []

        # Simple greedy grouping: process items in order
        for i in range(n):
            if assigned[i]:
                continue

            # Start new group with this item
            current_group = [items[i]]
            assigned[i] = True

            # Find all unassigned items close to this one (single pass, no transitive)
            for j in range(i + 1, n):
                if assigned[j]:
                    continue

                # Quick distance check to first item in group only (not transitive)
                rect_i = rects[i]
                rect_j = rects[j]

                # Fast intersection check
                if rect_i.intersects(rect_j):
                    distance = 0
                else:
                    # Simplified distance: max of horizontal and vertical gaps (faster than Euclidean)
                    h_gap = max(0, max(rect_i.x0 - rect_j.x1, rect_j.x0 - rect_i.x1))
                    v_gap = max(0, max(rect_i.y0 - rect_j.y1, rect_j.y0 - rect_i.y1))
                    distance = max(h_gap, v_gap)  # Chebyshev distance (faster)

                if distance <= proximity_threshold:
                    current_group.append(items[j])
                    assigned[j] = True

            groups.append(current_group)

        return groups

    def _merge_bboxes(self, bboxes: list) -> tuple:
        """
        Merges multiple bounding boxes into a single bounding box that encompasses all.

        Args:
            bboxes: List of bounding box tuples (x0, y0, x1, y1)

        Returns:
            Single merged bounding box tuple (x0, y0, x1, y1)
        """
        if not bboxes:
            return (0, 0, 0, 0)

        if len(bboxes) == 1:
            return tuple(bboxes[0]) if isinstance(bboxes[0], (list, fitz.Rect)) else bboxes[0]

        # Find the bounds that encompass all boxes
        rects = [fitz.Rect(bbox) for bbox in bboxes]
        x0 = min(r.x0 for r in rects)
        y0 = min(r.y0 for r in rects)
        x1 = max(r.x1 for r in rects)
        y1 = max(r.y1 for r in rects)

        return (x0, y0, x1, y1)

    def _extract_drawings_as_images(self, page, drawings: list, max_drawings: int = 50) -> list[dict]:
        """
        Extract drawing objects (like formulas) as images with their bounding boxes.

        Drawing objects in PDFs often represent mathematical formulas, equations,
        or vector graphics that don't have text representation. This method groups
        nearby drawings together before extraction to avoid fragmenting formulas.

        Args:
            page: PyMuPDF page object
            drawings: List of drawing objects from page.get_drawings()
            max_drawings: Maximum number of drawing objects to process (default: 50)

        Returns:
            List of dicts with 'image_bytes', 'bbox', and 'ext' keys
        """
        if not drawings:
            return []

        # Early termination for pages with too many drawings (likely complex graphics)
        if len(drawings) > max_drawings:
            logger.warning(f"Skipping {len(drawings)} drawings (exceeds max_drawings={max_drawings})")
            return []

        # First, collect all valid drawing bboxes
        drawing_items = []
        for drawing in drawings:
            try:
                rect = drawing.get("rect")
                if not rect:
                    continue

                # Expand rect slightly to capture surrounding context
                expanded_rect = fitz.Rect(rect)
                expanded_rect.x0 -= 2
                expanded_rect.y0 -= 2
                expanded_rect.x1 += 2
                expanded_rect.y1 += 2

                # Ensure rect is within page bounds
                expanded_rect.intersect(page.rect)

                # Skip very small drawings (likely decorative)
                if expanded_rect.width < 10 or expanded_rect.height < 10:
                    continue

                drawing_items.append({
                    "bbox": tuple(expanded_rect)
                })

            except Exception as e:
                logger.warning(f"Failed to process drawing bbox: {e}")
                continue

        if not drawing_items:
            return []

        # Group nearby drawings together (proximity threshold of 50 pixels, max 50 items)
        # Increased threshold to better capture complex diagrams with spaced elements
        grouped_drawings = self._group_by_proximity(drawing_items, proximity_threshold=50.0, max_items=50)

        logger.debug(f"Grouped {len(drawing_items)} drawings into {len(grouped_drawings)} groups")

        # Now extract each group as a single image
        drawing_images = []
        for group in grouped_drawings:
            try:
                # Merge all bboxes in the group
                merged_bbox = self._merge_bboxes([item['bbox'] for item in group])
                merged_rect = fitz.Rect(merged_bbox)

                # Ensure rect is within page bounds
                merged_rect.intersect(page.rect)

                # Render this merged region as a single image with lower resolution for speed
                mat = fitz.Matrix(1.5, 1.5)  # 1.5x zoom (reduced from 2x for speed)
                pix = page.get_pixmap(matrix=mat, clip=merged_rect)
                img_bytes = pix.tobytes("png")

                drawing_images.append({
                    "image_bytes": img_bytes,
                    "bbox": tuple(merged_rect),
                    "ext": "png"
                })

                logger.debug(f"Extracted merged drawing image from {len(group)} fragments")

            except Exception as e:
                logger.warning(f"Failed to extract merged drawing: {e}")
                continue

        return drawing_images

    def _batch_ocr_images(self, images_data: list[dict]) -> tuple[list[str], list[dict]]:
        """
        Perform OCR on multiple images in parallel.

        Args:
            images_data: List of dicts with 'image_bytes' key

        Returns:
            Tuple of (list of OCR text results, list of metering dicts) in the same order as input
        """
        logger.debug(f"_batch_ocr_images called with {len(images_data)} images")
        if not self.enable_parallel_ocr or len(images_data) <= 1:
            # Fallback to sequential processing
            results = []
            metering_list = []
            for idx, img in enumerate(images_data):
                text, metering = self.ocr_service.get_text_from_image(img['image_bytes'])
                logger.debug(f"Sequential OCR {idx + 1}/{len(images_data)}: text length={len(text)}, metering={metering}")
                results.append(text)
                metering_list.append(metering)
            logger.debug(f"Sequential processing complete. Returning {len(results)} texts and {len(metering_list)} metering dicts")
            return results, metering_list

        results = [None] * len(images_data)
        metering_results = [None] * len(images_data)

        def ocr_single(idx, img_data):
            try:
                text, metering = self.ocr_service.get_text_from_image(img_data['image_bytes'])
                logger.debug(f"Parallel OCR {idx + 1}/{len(images_data)}: text length={len(text)}, metering={metering}")
                return idx, text, metering
            except Exception as e:
                logger.warning(f"OCR failed for image {idx}: {e}")
                return idx, "", {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(ocr_single, idx, img_data)
                      for idx, img_data in enumerate(images_data)]

            for future in as_completed(futures):
                idx, text, metering = future.result()
                results[idx] = text
                metering_results[idx] = metering

        logger.debug(f"Parallel processing complete. Returning {len(results)} texts and {len(metering_results)} metering dicts")
        return results, metering_results

    def extract_manifest(
        self,
        pdf_bytes: bytes,
        s3_prefix: str,
        extract_config: dict = None
    ) -> tuple[list[dict], dict]:
        """
        Comprehensively extracts all content from a PDF into a structured manifest.

        This method performs deep extraction of PDF content using multiple PyMuPDF techniques
        to capture text, images, tables, forms, formulas, links, annotations, metadata, and
        embedded files. Each content type is represented as a dictionary in the manifest.

        Extraction Types:
        - metadata: Document-level metadata (title, author, dates, etc.)
        - text: Regular text blocks extracted from pages
        - table: Structured tables with headers, rows, columns (preserved structure)
        - image: Embedded images with OCR text extraction
        - formula: Mathematical formulas/equations from drawing objects (OCR)
        - form_field: Interactive PDF form fields with values
        - link: Hyperlinks and URI references
        - annotation: Comments, highlights, notes, and markup
        - embedded_file: Attached files within the PDF

        Args:
            pdf_bytes: The byte content of the PDF file.
            s3_prefix: The S3 prefix for the document, used to generate image keys.
            extract_config: Optional dict to control which extractions to perform. Default is all enabled.
                            Example: {"tables": True, "images": True, "formulas": False, "forms": True,
                                     "links": False, "annotations": False, "metadata": True, "embedded_files": False}

        Returns:
            Tuple of (manifest, metering_data):
            - manifest: A list of dictionaries representing the structured manifest. Each dict contains:
                - type: Content type (text, table, image, formula, form_field, link, annotation, metadata, embedded_file)
                - content: Human-readable text representation
                - page: Page number (0 for document-level items)
                - bbox: Bounding box coordinates (x0, y0, x1, y1) or None
                - Additional type-specific fields (structured_data, field_data, metadata, etc.)
            - metering_data: Dictionary containing aggregated metering data from OCR operations

            Returns ([], {}) if the PDF cannot be processed or if an ocr_service is not available.
        """
        if not self.ocr_service:
            logger.error("OcrService not available. Cannot process images.")
            return [], {}

        # Set default extraction configuration
        default_config = {
            "text": True,
            "tables": True,
            "images": True,
            "formulas": True,
            "forms": True,
            "links": False,  # Often not needed, disabled by default
            "annotations": False,  # Often not needed, disabled by default
            "metadata": True,
            "embedded_files": False,  # Rarely needed, disabled by default
        }

        if extract_config:
            default_config.update(extract_config)
        extract_config = default_config

        manifest = []
        image_counter = 0
        aggregated_metering = {}

        try:
            pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
            logger.info(f"Processing {len(pdf_document)} pages for text extraction manifest")
            logger.info(f"Extraction config: {extract_config}")

            for page_num, page in enumerate(pdf_document):
                # Collect all images/formulas on this page for batch OCR
                ocr_batch = []

                page_dict = page.get_text("dict", sort=True)

                # Extract tables with structure preservation
                if extract_config.get("tables", True):
                    try:
                        tables = page.find_tables()
                        if tables.tables:
                            logger.info(f"Page {page_num + 1}: Found {len(tables.tables)} tables")
                            for table_idx, table in enumerate(tables.tables):
                                try:
                                    # Extract table data
                                    table_data = table.extract()

                                    # Get table bbox
                                    table_bbox = table.bbox

                                    # Convert to structured format
                                    table_dict = {
                                        "headers": table.header.names if table.header else [],
                                        "rows": table_data,
                                        "col_count": len(table_data[0]) if table_data else 0,
                                        "row_count": len(table_data)
                                    }

                                    # Also generate markdown representation for LLM consumption
                                    markdown = self._table_to_markdown(table_data, table.header.names if table.header else None)

                                    manifest.append({
                                        "type": "table",
                                        "content": markdown,  # Human-readable format
                                        "structured_data": table_dict,  # Structured format
                                        "page": page_num + 1,
                                        "bbox": table_bbox,
                                    })

                                    logger.debug(f"Successfully extracted table {table_idx + 1} on page {page_num + 1}")

                                except Exception as e:
                                    logger.warning(f"Failed to extract table {table_idx + 1} on page {page_num + 1}: {e}")

                    except Exception as e:
                        logger.debug(f"No tables found on page {page_num + 1} or table extraction not supported: {e}")

                # Check for drawing objects (often formulas/equations) - collect for batch OCR
                drawings = []
                if extract_config.get("formulas", True):
                    drawings = page.get_drawings()
                    logger.debug(f"Page {page_num + 1}: Found {len(drawings)} drawing objects")

                # First pass: process text blocks and collect image blocks for grouping
                image_blocks = []
                for block in page_dict["blocks"]:
                    if block["type"] == 0 and extract_config.get("text", True):  # Text block
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

                    elif block["type"] == 1 and extract_config.get("images", True):  # Image block
                        # Collect image blocks for grouping instead of processing immediately
                        image_blocks.append(block)

                # Second pass: group nearby images and extract them as merged images
                if image_blocks and extract_config.get("images", True):
                    logger.debug(f"Page {page_num + 1}: Found {len(image_blocks)} image blocks")

                    # Create items for grouping (just bboxes)
                    image_items = []
                    for block in image_blocks:
                        image_items.append({
                            "bbox": block["bbox"],
                            "block": block  # Keep reference to original block
                        })

                    # Group nearby images together (proximity threshold of 30 pixels, max 100 items)
                    grouped_images = self._group_by_proximity(image_items, proximity_threshold=30.0, max_items=100)

                    logger.debug(f"Page {page_num + 1}: Grouped {len(image_blocks)} images into {len(grouped_images)} groups")

                    # Process each group
                    for group in grouped_images:
                        try:
                            # Merge all bboxes in the group
                            merged_bbox = self._merge_bboxes([item['bbox'] for item in group])
                            merged_rect = fitz.Rect(merged_bbox)
                            merged_rect.intersect(page.rect)

                            # Extract the merged image region from the page with lower resolution for speed
                            mat = fitz.Matrix(1.5, 1.5)  # 1.5x zoom (reduced from 2x for speed)
                            pix = page.get_pixmap(matrix=mat, clip=merged_rect)
                            img_bytes = pix.tobytes("png")

                            # Collect for batch OCR
                            ocr_batch.append({
                                "type": "image",
                                "image_bytes": img_bytes,
                                "ext": "png",
                                "bbox": tuple(merged_rect),
                                "page": page_num + 1,
                                "page_rect": page.rect,
                            })

                            logger.debug(f"Collected merged image from {len(group)} blocks on page {page_num + 1}")

                        except Exception as e:
                            logger.warning(
                                f"Could not extract merged image on page {page_num + 1}: {e}",
                                exc_info=True
                            )

                # Collect drawing objects (formulas, equations, etc.) for batch OCR
                if drawings:
                    logger.info(f"Collecting {len(drawings)} drawing objects on page {page_num + 1}")
                    drawing_imgs = self._extract_drawings_as_images(page, drawings)

                    for draw_img in drawing_imgs:
                        ocr_batch.append({
                            "type": "formula",
                            "image_bytes": draw_img["image_bytes"],
                            "ext": draw_img["ext"],
                            "bbox": draw_img["bbox"],
                            "page": page_num + 1,
                        })

                # Batch process all OCR operations for this page
                if ocr_batch:
                    logger.info(f"Batch processing {len(ocr_batch)} OCR operations for page {page_num + 1}")
                    ocr_results, metering_results = self._batch_ocr_images(ocr_batch)

                    # Aggregate metering data from this batch
                    for idx, metering_data in enumerate(metering_results):
                        if metering_data:
                            logger.debug(f"Merging metering data from OCR operation {idx + 1}: {metering_data}")
                            aggregated_metering = utils.merge_metering_data(aggregated_metering, metering_data)

                    logger.debug(f"Total aggregated metering after page {page_num + 1}: {aggregated_metering}")

                    for item, ocr_text in zip(ocr_batch, ocr_results):
                        try:
                            if item["type"] == "image":
                                # Apply filtering to determine if this is a content image
                                is_content = self._is_content_image(
                                    item["image_bytes"], item["bbox"], item["page_rect"], ocr_text
                                )

                                if not is_content:
                                    logger.debug(
                                        f"Skipping non-content image on page {item['page']} "
                                        f"(likely logo/decorative element)"
                                    )
                                    continue

                                image_counter += 1
                                s3_key = f"{s3_prefix}/images/image_{image_counter}.{item['ext']}"

                                manifest.append({
                                    "type": "image",
                                    "content": ocr_text,
                                    "image_bytes": item["image_bytes"],
                                    "s3_key": s3_key,
                                    "page": item["page"],
                                    "bbox": item["bbox"],
                                })

                                logger.debug(f"Successfully processed image {image_counter}")

                            elif item["type"] == "formula":
                                # Only include formulas if OCR found text
                                if ocr_text.strip():
                                    image_counter += 1
                                    s3_key = f"{s3_prefix}/images/formula_{image_counter}.{item['ext']}"

                                    manifest.append({
                                        "type": "formula",
                                        "content": ocr_text,
                                        "image_bytes": item["image_bytes"],
                                        "s3_key": s3_key,
                                        "page": item["page"],
                                        "bbox": item["bbox"],
                                    })

                                    logger.debug(f"Successfully processed formula {image_counter}")
                                else:
                                    logger.debug(f"Skipping formula on page {item['page']} - no text found")

                        except Exception as e:
                            logger.warning(f"Could not process OCR result: {e}", exc_info=True)

                # Extract form fields (interactive PDF forms)
                if extract_config.get("forms", True):
                    try:
                        widgets = page.widgets()
                        if widgets:
                            logger.info(f"Page {page_num + 1}: Found {len(widgets)} form fields")
                            for widget in widgets:
                                try:
                                    field_info = {
                                        "field_name": widget.field_name or "unnamed",
                                        "field_type": widget.field_type_string,
                                        "field_value": widget.field_value,
                                        "field_label": widget.field_label or "",
                                    }

                                    # Create readable content
                                    content = f"{field_info['field_name']}: {field_info['field_value']}"
                                    if field_info['field_label']:
                                        content = f"{field_info['field_label']} - {content}"

                                    manifest.append({
                                        "type": "form_field",
                                        "content": content,
                                        "field_data": field_info,
                                        "page": page_num + 1,
                                        "bbox": tuple(widget.rect) if widget.rect else None,
                                    })

                                    logger.debug(f"Extracted form field '{field_info['field_name']}' on page {page_num + 1}")

                                except Exception as e:
                                    logger.warning(f"Failed to extract form field on page {page_num + 1}: {e}")

                    except Exception as e:
                        logger.debug(f"No form fields on page {page_num + 1} or extraction not supported: {e}")

                # Extract links and hyperlinks
                if extract_config.get("links", False):
                    try:
                        links = page.get_links()
                        if links:
                            logger.debug(f"Page {page_num + 1}: Found {len(links)} links")
                            for link in links:
                                try:
                                    link_info = {
                                        "uri": link.get("uri", ""),
                                        "type": link.get("kind", ""),
                                        "page_dest": link.get("page", ""),
                                    }

                                    # Only include external links and named destinations
                                    if link_info["uri"]:
                                        manifest.append({
                                            "type": "link",
                                            "content": link_info["uri"],
                                            "link_data": link_info,
                                            "page": page_num + 1,
                                            "bbox": tuple(link.get("from", [])) if link.get("from") else None,
                                        })

                                        logger.debug(f"Extracted link to '{link_info['uri']}' on page {page_num + 1}")

                                except Exception as e:
                                    logger.warning(f"Failed to extract link on page {page_num + 1}: {e}")

                    except Exception as e:
                        logger.debug(f"No links found on page {page_num + 1}: {e}")

                # Extract annotations (comments, highlights, notes)
                if extract_config.get("annotations", False):
                    try:
                        annotations = page.annots()
                        if annotations:
                            logger.info(f"Page {page_num + 1}: Found annotations")
                            for annot in annotations:
                                try:
                                    annot_info = annot.info
                                    annot_type = annot.type[1] if annot.type else "Unknown"

                                    # Get annotation content
                                    content = annot_info.get("content", "")
                                    subject = annot_info.get("subject", "")

                                    if content or subject:
                                        manifest.append({
                                            "type": "annotation",
                                            "content": content,
                                            "annotation_data": {
                                                "subject": subject,
                                                "type": annot_type,
                                                "author": annot_info.get("author", ""),
                                                "created": annot_info.get("creationDate", ""),
                                            },
                                            "page": page_num + 1,
                                            "bbox": tuple(annot.rect) if annot.rect else None,
                                        })

                                        logger.debug(f"Extracted {annot_type} annotation on page {page_num + 1}")

                                except Exception as e:
                                    logger.warning(f"Failed to extract annotation on page {page_num + 1}: {e}")

                    except Exception as e:
                        logger.debug(f"No annotations on page {page_num + 1}: {e}")

            # Extract document-level metadata
            if extract_config.get("metadata", True):
                metadata = pdf_document.metadata
                if metadata:
                    logger.info("Extracting document metadata")
                    manifest.insert(0, {
                        "type": "metadata",
                        "content": json.dumps(metadata, indent=2),
                        "metadata": {
                            "title": metadata.get("title", ""),
                            "author": metadata.get("author", ""),
                            "subject": metadata.get("subject", ""),
                            "keywords": metadata.get("keywords", ""),
                            "creator": metadata.get("creator", ""),
                            "producer": metadata.get("producer", ""),
                            "created": metadata.get("creationDate", ""),
                            "modified": metadata.get("modDate", ""),
                        },
                        "page": 0,  # Document-level
                        "bbox": None,
                    })

            # Extract embedded files
            if extract_config.get("embedded_files", False):
                try:
                    embfile_count = pdf_document.embfile_count()
                    if embfile_count > 0:
                        logger.info(f"Found {embfile_count} embedded files")
                        for i in range(embfile_count):
                            try:
                                embfile_info = pdf_document.embfile_info(i)

                                manifest.append({
                                    "type": "embedded_file",
                                    "content": f"Embedded file: {embfile_info.get('name', 'unnamed')}",
                                    "file_data": {
                                        "name": embfile_info.get("name", ""),
                                        "filename": embfile_info.get("filename", ""),
                                        "description": embfile_info.get("desc", ""),
                                        "size": embfile_info.get("size", 0),
                                    },
                                    "page": 0,  # Document-level
                                    "bbox": None,
                                })

                                logger.debug(f"Extracted embedded file info: {embfile_info.get('name', 'unnamed')}")

                            except Exception as e:
                                logger.warning(f"Failed to extract embedded file {i}: {e}")

                except Exception as e:
                    logger.debug(f"No embedded files or extraction not supported: {e}")

            pdf_document.close()

            # Count all content types
            type_counts = {}
            for item in manifest:
                item_type = item.get('type', 'unknown')
                type_counts[item_type] = type_counts.get(item_type, 0) + 1

            # Build summary string
            summary_parts = [f"{count} {type_name}{'s' if count != 1 else ''}"
                           for type_name, count in sorted(type_counts.items())]
            summary = ", ".join(summary_parts)

            logger.info(
                f"Manifest extraction complete: {len(manifest)} total items ({summary})"
            )

            # Log complete manifest for debugging
            manifest_debug = []
            for item in manifest:
                debug_item = {k: v for k, v in item.items() if k != 'image_bytes'}
                if 'image_bytes' in item:
                    debug_item['image_bytes_size'] = len(item['image_bytes'])
                manifest_debug.append(debug_item)
            logger.info(f"Complete manifest structure: {json.dumps(manifest_debug, indent=2)}")

        except Exception as e:
            logger.error(f"Failed to process PDF for manifest extraction: {e}", exc_info=True)
            return [], {}

        logger.info(f"Manifest extraction complete. Returning {len(manifest)} items with metering: {aggregated_metering}")
        return manifest, aggregated_metering
