# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Standalone image file processor for PII detection and redaction.
Supports: JPG, PNG, TIFF (multi-page), BMP, WEBP
"""

import io
import os
import logging
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}
MULTI_PAGE_FORMATS = {".tiff", ".tif"}


def detect_pii_image(source_bucket, source_key, config, bedrock_runtime, s3_client):
    """Detect PII in an image file (Step 1 only). Includes bounding boxes."""
    from core.pii_detector import detect_pii_in_image
    from helpers.textract_helper import (
        enhance_pii_detections_with_textract,
        get_textract_full,
    )
    from helpers.model_config_helper import get_concurrency_config
    from helpers.token_tracker import TokenTracker
    from concurrent.futures import ThreadPoolExecutor, as_completed

    model_id = config["model"]["id"]
    model_provider = config["model"]["provider"]
    cc = get_concurrency_config(config)
    tracker = TokenTracker(model_id)

    images = load_image_from_s3(s3_client, source_bucket, source_key, config)
    num_pages = len(images)
    max_workers = min(cc["max_workers"], num_pages)
    logger.info(f"Processing {num_pages} page(s) from {source_key}")

    def _detect_page(page_num, img):
        metadata = {
            "page_number": page_num,
            "width": img.width,
            "height": img.height,
            "page_width": img.width,
            "page_height": img.height,
            "scale_x": 1.0,
            "scale_y": 1.0,
        }
        textract_words, ocr_text, raw_textract = get_textract_full(img, bedrock_runtime)
        detections = detect_pii_in_image(
            img,
            metadata,
            model_id,
            model_provider,
            bedrock_runtime,
            token_tracker=tracker,
            ocr_text=ocr_text,
            config=config,
        )
        if detections:
            detections = enhance_pii_detections_with_textract(
                img, detections, bedrock_runtime, textract_words=textract_words
            )
        return (
            page_num,
            detections,
            {"page": page_num, "ocr_text": ocr_text, "raw": raw_textract},
        )

    all_detections = []
    textract_pages = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_detect_page, pn, img): pn
            for pn, img in enumerate(images, start=1)
        }
        for future in as_completed(futures):
            page_num, detections, tx_page = future.result()
            all_detections.extend(detections)
            textract_pages.append(tx_page)

    return {
        "source_key": source_key,
        "file_type": "image",
        "detections": [
            {
                "content": d.get("content", ""),
                "type": d.get("type", "unknown"),
                "confidence": d.get("confidence", 0.0),
                "bounding_box": d.get("bounding_box"),
                "page_num": d.get("page_num", 0),
                "bbox_source": d.get("bbox_source", ""),
                **(
                    {"bbox_segments": d["bbox_segments"]}
                    if "bbox_segments" in d
                    else {}
                ),
            }
            for d in all_detections
        ],
        "failed_chunks": [],
        "token_usage": tracker.summary(),
        "textract_pages": sorted(textract_pages, key=lambda x: x["page"]),
    }


def draw_synthetic_text_on_image(draw, text, x, y, width, height):
    """
    Draw synthetic text on image with proper font sizing.

    Args:
        draw: PIL ImageDraw object
        text: Text to draw
        x, y: Top-left coordinates
        width, height: Bounding box dimensions
    """
    from helpers.font_config import get_consistent_font

    # Start with 75% of box height
    font_size = max(8, int(height * 0.75))
    font = get_consistent_font(font_size)

    # Get text dimensions
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
    except Exception:
        # Fallback for older PIL versions
        text_width, text_height = draw.textsize(text, font=font)

    # Shrink font if text too wide (allow 10% overflow)
    while text_width > width * 1.1 and font_size > 6:
        font_size -= 1
        font = get_consistent_font(font_size)
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
        except Exception:
            text_width, _ = draw.textsize(text, font=font)

    # Center vertically
    text_y = y + max(0, (height - text_height) // 2)

    # Draw text
    draw.text((x + 1, text_y), text, fill=(0, 0, 0), font=font)


class ImageValidationError(Exception):
    """Raised when image validation fails"""

    pass


def validate_image(img_bytes, config=None):
    """
    Validate image before processing.

    Args:
        img_bytes: Image bytes
        config: Configuration dict (uses defaults if None)

    Raises:
        ImageValidationError: If validation fails
    """
    # Get limits from config or use defaults
    if config:
        max_size_mb = (
            config.get("validation", {}).get("max_file_size_mb", {}).get("image", 100)
        )
        max_pages = config.get("validation", {}).get("max_pages", {}).get("image", 50)
        min_dim = config.get("validation", {}).get("image_min_dimension", 10)
        max_dim = config.get("validation", {}).get("image_max_dimension", 10000)
    else:
        max_size_mb = 100
        max_pages = 50
        min_dim = 10
        max_dim = 10000

    # Check file size
    file_size = len(img_bytes)
    max_bytes = max_size_mb * 1024 * 1024
    if file_size > max_bytes:
        raise ImageValidationError(
            f"Image size {file_size / 1024 / 1024:.1f}MB exceeds maximum {max_size_mb}MB"
        )

    if file_size == 0:
        raise ImageValidationError("Image file is empty")

    # Validate image can be opened
    try:
        img = Image.open(io.BytesIO(img_bytes))
        img.verify()  # Verify image integrity

        # Reopen after verify (verify closes the file)
        img = Image.open(io.BytesIO(img_bytes))

        # Check dimensions
        if img.width < min_dim or img.height < min_dim:
            raise ImageValidationError(
                f"Image too small: {img.width}x{img.height} (min {min_dim}x{min_dim})"
            )
        if img.width > max_dim or img.height > max_dim:
            raise ImageValidationError(
                f"Image too large: {img.width}x{img.height} (max {max_dim}x{max_dim})"
            )

        # Check page count for multi-page formats
        try:
            n_frames = img.n_frames
            if n_frames > max_pages:
                raise ImageValidationError(
                    f"TIFF has {n_frames} pages, exceeds maximum {max_pages}"
                )
        except AttributeError:
            # Single page image
            pass

    except ImageValidationError:
        raise
    except Exception as e:
        raise ImageValidationError(f"Invalid image file: {str(e)}")

    return True


def load_image_from_s3(s3_client, bucket, key, config=None):
    """Load image from S3 -> PIL Image or list of PIL Images for multi-page."""
    response = s3_client.get_object(Bucket=bucket, Key=key)
    img_bytes = response["Body"].read()

    # Validate image
    validate_image(img_bytes, config)

    # Check if multi-page format
    ext = os.path.splitext(key)[1].lower()
    if ext in MULTI_PAGE_FORMATS:
        # Load all pages from TIFF
        images = []
        img = Image.open(io.BytesIO(img_bytes))
        try:
            for i in range(img.n_frames):
                img.seek(i)
                page = img.copy()
                if page.mode != "RGB":
                    page = page.convert("RGB")
                images.append(page)
            logger.info(f"Loaded {len(images)} pages from multi-page TIFF")
            return images
        except Exception as e:
            logger.warning(f"Multi-page load failed, treating as single page: {e}")
            if img.mode != "RGB":
                img = img.convert("RGB")
            return [img]
    else:
        # Single page image
        img = Image.open(io.BytesIO(img_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        return [img]


def process_image_file(
    source_bucket,
    source_key,
    output_bucket,
    filename_without_ext,
    config,
    bedrock_runtime,
    dynamodb_manager,
    s3_client,
    folder_path="",
):
    """
    Process standalone image file (TIFF/PNG/JPG/BMP/WEBP) for PII detection and redaction.
    Handles multi-page TIFF with multi-threading and OCR text context.
    """
    from core.pii_detector import detect_pii_in_image
    from helpers.textract_helper import (
        enhance_pii_detections_with_textract,
        get_textract_full,
    )
    from core.synthetic_pii_generator import batch_generate_synthetic_pii
    from helpers.model_config_helper import get_concurrency_config
    from helpers.token_tracker import TokenTracker
    from concurrent.futures import ThreadPoolExecutor, as_completed

    try:
        # Load image(s) - returns list of PIL Images
        images = load_image_from_s3(s3_client, source_bucket, source_key, config)
        num_pages = len(images)
        logger.info(f"Processing {num_pages} page(s) from {source_key}")

        model_id = config["model"]["id"]
        model_provider = config["model"]["provider"]
        cc = get_concurrency_config(config)
        max_workers = min(cc["max_workers"], num_pages)
        tracker = TokenTracker(model_id)

        all_pii_detections = []
        page_results = []  # Store (page_num, img, pii_detections, pii_mapping)

        # Step 1: Detect PII on all pages (multi-threaded with OCR text)
        logger.info(
            f"Step 1 - PII Detection: Processing {num_pages} pages with {max_workers} workers..."
        )

        def _detect_page(page_num, img):
            """Detect PII on single page with OCR text context."""
            metadata = {
                "page_number": page_num,
                "width": img.width,
                "height": img.height,
                "page_width": img.width,
                "page_height": img.height,
                "scale_x": 1.0,
                "scale_y": 1.0,
            }

            # Get Textract OCR text first
            textract_words, ocr_text, _raw = get_textract_full(img, bedrock_runtime)

            # Detect PII with image + OCR text
            pii_detections = detect_pii_in_image(
                img,
                metadata,
                model_id,
                model_provider,
                bedrock_runtime,
                token_tracker=tracker,
                ocr_text=ocr_text,
                config=config,
            )

            # Enhance with Textract bounding boxes
            if pii_detections:
                pii_detections = enhance_pii_detections_with_textract(
                    img, pii_detections, bedrock_runtime, textract_words=textract_words
                )

            logger.info(
                f"Page {page_num}/{num_pages}: Detected {len(pii_detections)} PII instances"
            )
            return page_num, img, pii_detections

        # Process pages in parallel
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_detect_page, page_num, img): page_num
                for page_num, img in enumerate(images, start=1)
            }

            for future in as_completed(futures):
                page_num, img, pii_detections = future.result()
                page_results.append((page_num, img, pii_detections))
                all_pii_detections.extend(pii_detections)

        # Sort by page number
        page_results.sort(key=lambda x: x[0])

        if not all_pii_detections:
            logger.info("No PII detected across all pages, skipping redaction")
            # Save original images
            ext = os.path.splitext(source_key)[1].lower()
            output_key = f"{folder_path}redacted_{filename_without_ext}{ext}"

            img_bytes = io.BytesIO()
            if ext in MULTI_PAGE_FORMATS and num_pages > 1:
                images[0].save(
                    img_bytes,
                    format="TIFF",
                    save_all=True,
                    append_images=images[1:],
                    compression="tiff_deflate",
                )
            elif ext in [".tiff", ".tif"]:
                images[0].save(img_bytes, format="TIFF", compression="tiff_deflate")
            else:
                img_format = "PNG" if ext == ".png" else "JPEG"
                images[0].save(img_bytes, format=img_format)
            img_bytes.seek(0)

            s3_client.put_object(
                Body=img_bytes.getvalue(), Bucket=output_bucket, Key=output_key
            )

            return {
                "success": True,
                "s3_output_file": output_key,
                "pii_count": 0,
                "pages": num_pages,
                "message": "No PII detected",
            }

        # Step 2: Generate synthetic replacements (batch all pages)
        logger.info(
            f"Step 2 - Generating synthetic data for {len(all_pii_detections)} PII instances..."
        )
        pii_mapping = batch_generate_synthetic_pii(
            all_pii_detections,
            model_id,
            model_provider,
            bedrock_runtime,
            config=config,
            token_tracker=tracker,
        )

        # Log token usage summary
        tracker.log_summary()

        # Step 3: Redact all pages
        logger.info(f"Step 3 - Redacting {num_pages} pages...")

        # Get redaction config
        from helpers.model_config_helper import get_show_bounding_boxes

        redaction_mode = config.get("redaction", {}).get("mode", "synthetic")
        show_boxes = get_show_bounding_boxes(config)
        box_color = tuple(
            config.get("validation", {}).get("bounding_box_color", [255, 0, 0])
        )

        logger.info(f"Redaction mode: {redaction_mode}, show_boxes: {show_boxes}")

        all_redacted_images = []
        total_redacted = 0

        for page_num, img, pii_detections in page_results:
            if not pii_detections:
                all_redacted_images.append(img)
                continue

            img_redacted = img.copy()
            draw = ImageDraw.Draw(img_redacted)

            redacted_count = 0
            for det in pii_detections:
                bbox = det.get("bounding_box")
                if not bbox:
                    continue

                original = det.get("content", "")
                synthetic = pii_mapping.get(original, original)

                left = max(0, int(bbox["left"]))
                top = max(0, int(bbox["top"]))
                right = min(img.width, int(bbox["left"] + bbox["width"]))
                bottom = min(img.height, int(bbox["top"] + bbox["height"]))

                if redaction_mode == "blackout":
                    # Black box only
                    draw.rectangle([left, top, right, bottom], fill=(0, 0, 0))
                else:
                    # White box + synthetic text
                    draw.rectangle([left, top, right, bottom], fill=(255, 255, 255))
                    draw_synthetic_text_on_image(
                        draw, synthetic, left, top, right - left, bottom - top
                    )

                # Optional bounding box border
                if show_boxes:
                    draw.rectangle(
                        [left, top, right, bottom], outline=box_color, width=3
                    )

                redacted_count += 1

            logger.info(
                f"Page {page_num}: Redacted {redacted_count}/{len(pii_detections)} PII instances"
            )
            total_redacted += redacted_count
            all_redacted_images.append(img_redacted)

        # Step 4: Save output
        ext = os.path.splitext(source_key)[1].lower()
        output_key = f"{folder_path}redacted_{filename_without_ext}{ext}"

        img_bytes = io.BytesIO()
        if ext in MULTI_PAGE_FORMATS and num_pages > 1:
            all_redacted_images[0].save(
                img_bytes,
                format="TIFF",
                save_all=True,
                append_images=all_redacted_images[1:],
                compression="tiff_deflate",
            )
            logger.info(f"Saved {num_pages}-page TIFF")
        elif ext in [".tiff", ".tif"]:
            all_redacted_images[0].save(
                img_bytes, format="TIFF", compression="tiff_deflate"
            )
            logger.info("Saved single-page TIFF")
        else:
            img_format = "PNG" if ext == ".png" else "JPEG"
            all_redacted_images[0].save(img_bytes, format=img_format)

        img_bytes.seek(0)

        content_type = (
            "image/tiff"
            if ext in [".tiff", ".tif"]
            else "image/jpeg" if ext in [".jpg", ".jpeg"] else "image/png"
        )
        s3_client.put_object(
            Body=img_bytes.getvalue(),
            Bucket=output_bucket,
            Key=output_key,
            ContentType=content_type,
        )
        logger.info(f"Uploaded redacted image to: {output_key}")

        # Create and upload summary JSON
        import json

        summary = {
            "input_file": f"s3://{source_bucket}/{source_key}",
            "output_file": f"s3://{output_bucket}/{output_key}",
            "pii_count": len(all_pii_detections),
            "pii_redacted": total_redacted,
            "pages_processed": num_pages,
            "token_usage": tracker.summary() if tracker else {},
        }
        summary_key = f"{folder_path}redaction_summary_{filename_without_ext}.json"
        s3_client.put_object(
            Body=json.dumps(summary, indent=2),
            Bucket=output_bucket,
            Key=summary_key,
            ContentType="application/json",
        )
        logger.info(f"Uploaded summary to: {summary_key}")

        # Step 5: Store in DynamoDB
        if dynamodb_manager:
            detailed_pii_data = []
            for det in all_pii_detections:
                original = det.get("content", "")
                has_bbox = bool(det.get("bounding_box"))
                detailed_pii_data.append(
                    {
                        "original": original,
                        "synthetic": (
                            pii_mapping.get(original, original)
                            if has_bbox
                            else "[NOT REDACTED - NO BBOX FOUND]"
                        ),
                        "type": det.get("type", "unknown"),
                        "page_num": int(det.get("page_num", 0)),
                        "confidence": float(det.get("confidence", 0.0)),
                        "replacement_status": (
                            "text_replaced" if has_bbox else "not_redacted"
                        ),
                        **(
                            {"not_redacted_reason": "no_bounding_box"}
                            if not has_bbox
                            else {}
                        ),
                        "bbox_source": det.get("bbox_source", "textract"),
                        "source": "image",
                    }
                )
            dynamodb_manager.store_pii_mapping(
                detailed_pii_data,
                filename_without_ext,
                status="SUCCESS",
                token_usage=tracker.summary() if tracker else None,
            )

        return {
            "success": True,
            "s3_output_file": output_key,
            "pii_count": len(all_pii_detections),
            "redacted_count": total_redacted,
            "pages": num_pages,
        }

    except Exception as e:
        logger.error(f"Image processing failed: {str(e)}", exc_info=True)
        if dynamodb_manager:
            try:
                dynamodb_manager.store_pii_mapping(
                    [], filename_without_ext, status="FAILED", error_message=str(e)
                )
            except Exception:
                pass
        return {"success": False, "error": str(e), "pii_count": 0}
