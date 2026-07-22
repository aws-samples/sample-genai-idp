# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
PDF Redactor Module

Redacts PII in PDF documents using a **flatten-to-image** approach:

  render page (pypdfium2) -> draw redaction/synthetic text (Pillow)
  -> assemble redacted page images into an image-based PDF (Pillow)

Because every page is flattened to a raster, the output PDF has **no text
layer**, which guarantees the original PII cannot leak through an
invisible/searchable text layer — a known failure mode of annotation-based
redaction. Rendering uses pypdfium2; drawing uses Pillow.

Provides:
1. Redact text + image PII using Textract-derived bounding boxes
2. Create redaction summaries
"""

import os
import io
import json
import math
import shutil
import logging
import traceback
import tempfile
import re

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFilter
from core.synthetic_pii_generator import generate_synthetic_pii_fallback

# Set up logger
logger = logging.getLogger(__name__)


def _get_synthetic(pii_mapping, original, pii_type="PII"):
    """Lookup synthetic value with normalized fallback, then Faker."""
    val = pii_mapping.get(original)
    if val:
        return val
    # Try stripped
    stripped = original.strip()
    val = pii_mapping.get(stripped)
    if val:
        return val
    # Try normalized whitespace
    normed = re.sub(r"\s+", " ", stripped)
    for k, v in pii_mapping.items():
        if re.sub(r"\s+", " ", k.strip()) == normed:
            return v
    # Faker fallback
    return generate_synthetic_pii_fallback(pii_type, original)


def _bbox_to_pixels_safe(bbox, img_w, img_h):
    """Convert normalized or absolute bbox to pixel coordinates."""
    left = float(bbox.get("left", 0))
    top = float(bbox.get("top", 0))
    width = float(bbox.get("width", 0))
    height = float(bbox.get("height", 0))

    # Check if normalized (0-1 range)
    vals = [left, top, width, height]
    is_norm = all(0 <= v <= 1.5 for v in vals)

    if is_norm:
        x0 = math.floor(left * img_w)
        y0 = math.floor(top * img_h)
        x1 = math.ceil((left + width) * img_w)
        y1 = math.ceil((top + height) * img_h)
    else:
        x0 = math.floor(left)
        y0 = math.floor(top)
        x1 = math.ceil(left + width)
        y1 = math.ceil(top + height)

    x0 = max(0, min(img_w - 1, x0))
    y0 = max(0, min(img_h - 1, y0))
    x1 = max(x0 + 1, min(img_w, x1))
    y1 = max(y0 + 1, min(img_h, y1))
    return x0, y0, x1, y1


def _apply_raster_redaction(
    img,
    pii_detections,
    pii_mapping,
    bedrock_runtime=None,
    fill_color=(1, 1, 1),
    insert_text=True,
    show_boxes=False,
    box_color=(1, 0, 0),
):
    """Draw pixel redaction (and optional synthetic text) onto a page image.

    Args:
        img: PIL Image of the page (already rendered at the target DPI)
        pii_detections: PII detections for this page (with bounding boxes)
        pii_mapping: original -> synthetic mapping
        bedrock_runtime: boto3 client for Textract (used to size synthetic text)
        fill_color: (0,0,0) blackout or (1,1,1) synthetic (white) base
        insert_text: draw synthetic replacement text (False for blackout)
        show_boxes: draw bounding-box overlay
        box_color: RGB 0-1 overlay color

    Returns:
        The redacted PIL Image (a copy; the input is not mutated).
    """
    from helpers.font_config import get_consistent_font

    # Work on a copy so the caller's render is untouched
    img = img.copy().convert("RGB")

    # Collect redaction items
    redaction_items = []

    for detection in pii_detections:
        bbox = detection.get("bounding_box")
        if not bbox:
            detection["_raster_applied"] = False
            reason = (
                "signature"
                if "signature" in (detection.get("content") or "").lower()
                or detection.get("type") == "biometric"
                else "no_bounding_box"
            )
            detection["_not_redacted_reason"] = reason
            continue
        original = (detection.get("content") or "").strip()
        if not original:
            detection["_raster_applied"] = False
            detection["_not_redacted_reason"] = "empty_content"
            continue

        synthetic = _get_synthetic(pii_mapping, original, detection.get("type", "PII"))
        num_lines = max(original.count("\n") + 1, synthetic.count("\n") + 1)
        ptype = detection.get("type", "unknown")

        # Use per-segment bboxes when available (form columns)
        segments = detection.get("bbox_segments")
        added = False
        if segments:
            for idx, seg in enumerate(segments):
                try:
                    seg_px = _bbox_to_pixels_safe(seg, img.width, img.height)
                except Exception:
                    continue
                # First segment gets synthetic text, rest just white-out
                redaction_items.append(
                    (
                        seg_px,
                        synthetic if idx == 0 else "",
                        ptype,
                        num_lines if idx == 0 else 1,
                    )
                )
                added = True
        else:
            try:
                box_px = _bbox_to_pixels_safe(bbox, img.width, img.height)
            except Exception:
                pass
            else:
                redaction_items.append((box_px, synthetic, ptype, num_lines))
                added = True
        detection["_raster_applied"] = added
        if not added:
            detection["_not_redacted_reason"] = "bbox_conversion_failed"

    # Deduplicate overlapping boxes
    if redaction_items:
        deduped = []
        for item in redaction_items:
            x0, y0, x1, y1 = item[0]
            is_dup = False
            for existing in deduped:
                ex0, ey0, ex1, ey1 = existing[0]
                overlap_x = max(0, min(x1, ex1) - max(x0, ex0))
                overlap_y = max(0, min(y1, ey1) - max(y0, ey0))
                overlap_area = overlap_x * overlap_y
                item_area = (x1 - x0) * (y1 - y0)
                existing_area = (ex1 - ex0) * (ey1 - ey0)
                # If 80%+ overlap with either box, consider duplicate
                if overlap_area > 0.8 * min(item_area, existing_area):
                    is_dup = True
                    break
            if not is_dup:
                deduped.append(item)
        redaction_items = deduped

    if redaction_items:
        W, H = img.size

        # Get Textract word heights for scaling tiny PII bboxes
        page_line_h = None
        if insert_text and bedrock_runtime:
            try:
                from helpers.textract_helper import get_textract_bounding_boxes

                all_words = get_textract_bounding_boxes(img, bedrock_runtime)
                if all_words:
                    wh = sorted(
                        w["bbox"]["height"]
                        for w in all_words
                        if w.get("bbox", {}).get("height", 0) > 3
                    )
                    if wh:
                        page_line_h = wh[int(len(wh) * 0.75)]
            except Exception:
                pass

        # Scale up tiny bboxes to match page text height (pre-pass)
        if page_line_h:
            scaled = []
            for (x0, y0, x1, y1), synthetic, ptype, num_lines in redaction_items:
                box_h = y1 - y0
                line_h = box_h / num_lines
                if line_h < page_line_h * 0.5:
                    new_h = int(page_line_h * num_lines)
                    dy = (new_h - box_h) // 2
                    y0 = max(0, y0 - dy)
                    y1 = min(H, y0 + new_h)
                scaled.append(((x0, y0, x1, y1), synthetic, ptype, num_lines))
            redaction_items = scaled

        # Mask + dilate
        mask = Image.new("L", (W, H), 0)
        md = ImageDraw.Draw(mask)
        for (x0, y0, x1, y1), _, _, _ in redaction_items:
            box_h = max(1, y1 - y0)
            px = min(8, max(4, int(box_h * 0.10)))
            pt = min(6, max(3, int(box_h * 0.06)))
            pb = min(8, max(4, int(box_h * 0.10)))
            md.rectangle(
                [max(0, x0 - px), max(0, y0 - pt), min(W, x1 + px), min(H, y1 + pb)],
                fill=255,
            )

        avg_h = sum((y1 - y0) for (x0, y0, x1, y1), _, _, _ in redaction_items) / len(
            redaction_items
        )
        r = min(3, max(2, int(avg_h * 0.05)))
        mask = mask.filter(ImageFilter.MaxFilter(size=r * 2 + 1))
        pixel_fill = (0, 0, 0) if fill_color == (0, 0, 0) else (255, 255, 255)
        img.paste(pixel_fill, mask=mask)

        # Draw synthetic text (skip in blackout mode)
        if insert_text:
            line_heights = [y1 - y0 for (x0, y0, x1, y1), _, _, _ in redaction_items]
            typical_line_h = (
                sorted(line_heights)[len(line_heights) // 2] if line_heights else 30
            )
            draw = ImageDraw.Draw(img)
            # Two-pass: compute sizes/wrapping first, then draw, so an extended
            # white rect can't erase already-drawn text on the same line.
            text_items = []
            for (x0, y0, x1, y1), synthetic, _, num_lines in redaction_items:
                box_w, box_h = x1 - x0, y1 - y0
                est_lines = (
                    max(1, round(box_h / typical_line_h))
                    if box_h > typical_line_h * 1.5
                    else 1
                )
                line_h = box_h / est_lines
                max_fs = int(page_line_h * 0.95) if page_line_h else 24
                font_size = min(max(8, int(line_h * 0.95)), max_fs)
                min_fs = max(8, int(font_size * 0.3))
                font = get_consistent_font(font_size)
                bb = draw.textbbox((0, 0), synthetic, font=font)
                tw = bb[2] - bb[0]
                # Shrink to fit box width
                while tw > (box_w - 4) and font_size > min_fs:
                    font_size -= 1
                    font = get_consistent_font(font_size)
                    bb = draw.textbbox((0, 0), synthetic, font=font)
                    tw = bb[2] - bb[0]
                # If still too wide, wrap text instead of extending
                if tw > (box_w - 4):
                    avg_cw = tw / max(1, len(synthetic))
                    cpl = max(1, int((box_w - 4) / avg_cw))
                    words = synthetic.split()
                    lines, cur, cur_len = [], [], 0
                    for w in words:
                        if cur_len + len(w) + (1 if cur else 0) <= cpl:
                            cur.append(w)
                            cur_len += len(w) + (1 if len(cur) > 1 else 0)
                        else:
                            if cur:
                                lines.append(" ".join(cur))
                            cur, cur_len = [w], len(w)
                    if cur:
                        lines.append(" ".join(cur))
                    synthetic = "\n".join(lines)
                    bb = draw.textbbox((0, 0), synthetic, font=font)
                    tw = bb[2] - bb[0]
                th = bb[3] - bb[1]
                text_items.append((x0, y0, box_h, th, synthetic, font))

            # Pass 2: draw all synthetic text
            for x0, y0, box_h, th, synthetic, font in text_items:
                draw.text(
                    (x0 + 3, y0 + max(0, (box_h - th) // 2)),
                    synthetic,
                    fill=(0, 0, 0),
                    font=font,
                )

    # Draw bounding boxes if requested
    if show_boxes and redaction_items:
        draw_b = ImageDraw.Draw(img)
        r, g, b = (
            int(box_color[0] * 255),
            int(box_color[1] * 255),
            int(box_color[2] * 255),
        )
        for (x0, y0, x1, y1), _, _, _ in redaction_items:
            draw_b.rectangle([x0, y0, x1, y1], outline=(r, g, b), width=3)

    return img


def create_redaction_summary(pdf_path, output_path, pii_detections, pii_mapping):
    """
    Create a summary of redactions performed on a PDF.

    Args:
        pdf_path: Path to the input PDF
        output_path: Path for the summary file
        pii_detections: List of all PII detections
        pii_mapping: Dictionary mapping original PII to synthetic replacements

    Returns:
        True if successful, False otherwise
    """
    try:
        # Group detections by page and type
        detections_by_page = {}
        for detection in pii_detections:
            if "page_num" in detection:
                page_num = detection["page_num"]
                if page_num not in detections_by_page:
                    detections_by_page[page_num] = {}

                pii_type = detection["type"]
                if pii_type not in detections_by_page[page_num]:
                    detections_by_page[page_num][pii_type] = []

                detections_by_page[page_num][pii_type].append(detection)

        # Create summary
        summary = {
            "input_pdf": pdf_path,
            "output_pdf": output_path,
            "total_redactions": len(pii_detections),
            "redactions_by_type": {},
            "redactions_by_page": {},
            "pii_mapping": pii_mapping,
        }

        # Count redactions by type
        for detection in pii_detections:
            pii_type = detection["type"]
            if pii_type not in summary["redactions_by_type"]:
                summary["redactions_by_type"][pii_type] = 0
            summary["redactions_by_type"][pii_type] += 1

        # Count redactions by page
        for page_num, types in detections_by_page.items():
            summary["redactions_by_page"][str(page_num)] = {
                "total": sum(len(detections) for detections in types.values()),
                "by_type": {
                    pii_type: len(detections) for pii_type, detections in types.items()
                },
            }

        # Save summary as JSON
        with open(output_path, "w") as f:
            json.dump(summary, f, indent=2)

        return True

    except Exception as e:
        logger.info(f"Error creating redaction summary: {str(e)}")
        traceback.print_exc()
        return False


def _open_pdf(pdf_source):
    """Open a PDF from a file path or bytes using pypdfium2."""
    if isinstance(pdf_source, (bytes, bytearray)):
        return pdfium.PdfDocument(bytes(pdf_source))
    return pdfium.PdfDocument(pdf_source)


def redact_pdf(
    pdf_path,
    output_path,
    pii_detections,
    pii_mapping,
    summary_path=None,
    evaluation_path=None,
    dynamodb_manager=None,
    original_filename=None,
    token_usage=None,
    bedrock_runtime=None,
    redaction_config=None,
    s3_bucket=None,
    s3_render_prefix=None,
):
    """
    Redact PII in a PDF by flattening every page to a redacted raster image.

    Each page is rendered with pypdfium2, redacted with Pillow (pixel fill +
    optional synthetic text, Textract-driven bounding boxes), and the pages are
    re-assembled into an image-based PDF. The output has no text layer, so the
    original PII cannot leak via a hidden/searchable text layer.
    """
    try:
        logger.info("\n" + "=" * 60)
        logger.info("Step 3 - Applying flatten-to-image redaction")
        logger.info("=" * 60)
        logger.info(f"Total PII detections: {len(pii_detections)}")

        # Parse redaction config
        rc = redaction_config or {}
        redaction_mode = rc.get("mode", "synthetic")  # "synthetic" or "blackout"
        show_boxes = rc.get("show_bounding_boxes", False)
        box_color = tuple(rc.get("bounding_box_color", [1, 0, 0]))  # RGB 0-1
        dpi = rc.get("dpi", 300)
        # Fill color: black for blackout, white for synthetic
        fill_color = (0, 0, 0) if redaction_mode == "blackout" else (1, 1, 1)
        insert_text = redaction_mode == "synthetic"

        logger.info(f"Redaction mode: {redaction_mode}, show_boxes: {show_boxes}")

        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        # Detection page_num is 1-indexed; group by 0-indexed page
        page_detections = {}
        for d in pii_detections:
            pg = max(0, int(d.get("page_num", 1)) - 1)
            page_detections.setdefault(pg, []).append(d)

        # Page-image store: S3 (if configured) or local /tmp, to bound memory
        _use_s3 = bool(s3_bucket and s3_render_prefix)
        if _use_s3:
            import boto3 as _boto3

            _s3 = _boto3.client("s3")
        _render_dir = tempfile.mkdtemp(prefix="pii_redact_", dir=tempfile.gettempdir())

        def _store_page(page_num, image):
            if _use_s3:
                buf = io.BytesIO()
                image.save(buf, format="PNG")
                _s3.put_object(
                    Bucket=s3_bucket,
                    Key=f"{s3_render_prefix}redacted_p{page_num}.png",
                    Body=buf.getvalue(),
                )
            else:
                image.save(
                    os.path.join(_render_dir, f"p{page_num:05d}.png"), format="PNG"
                )

        def _load_page(page_num):
            if _use_s3:
                resp = _s3.get_object(
                    Bucket=s3_bucket,
                    Key=f"{s3_render_prefix}redacted_p{page_num}.png",
                )
                return Image.open(io.BytesIO(resp["Body"].read())).convert("RGB")
            return Image.open(
                os.path.join(_render_dir, f"p{page_num:05d}.png")
            ).convert("RGB")

        def _cleanup():
            if _use_s3:
                try:
                    resp = _s3.list_objects_v2(
                        Bucket=s3_bucket, Prefix=s3_render_prefix
                    )
                    if "Contents" in resp:
                        _s3.delete_objects(
                            Bucket=s3_bucket,
                            Delete={
                                "Objects": [
                                    {"Key": o["Key"]} for o in resp["Contents"]
                                ]
                            },
                        )
                except Exception:
                    pass
            shutil.rmtree(_render_dir, ignore_errors=True)

        # Render + redact each page, store the redacted raster
        pdf = _open_pdf(pdf_path)
        num_pages = len(pdf)
        stats = {"redacted": 0, "passthrough": 0}

        for page_num in range(num_pages):
            page = pdf[page_num]
            img = page.render(scale=dpi / 72).to_pil().convert("RGB")

            dets = page_detections.get(page_num)
            if dets:
                img = _apply_raster_redaction(
                    img,
                    dets,
                    pii_mapping,
                    bedrock_runtime=bedrock_runtime,
                    fill_color=fill_color,
                    insert_text=insert_text,
                    show_boxes=show_boxes,
                    box_color=box_color,
                )
                stats["redacted"] += 1
                for d in dets:
                    d["_redact_method"] = (
                        "rasterized" if d.get("_raster_applied") else "not_redacted"
                    )
            else:
                stats["passthrough"] += 1

            _store_page(page_num, img)
            del img

        pdf.close()

        logger.info("=" * 60)
        logger.info(
            f"REDACTION SUMMARY: {stats['redacted']} pages redacted, "
            f"{stats['passthrough']} pages flattened unchanged "
            f"({num_pages} total, image-based output)"
        )
        logger.info("=" * 60)

        # Assemble redacted page images into a single image-based PDF.
        # A generator keeps peak memory to ~one page at a time.
        if num_pages == 0:
            raise ValueError("PDF has no pages to redact")

        first_page = _load_page(0)

        def _remaining_pages():
            for pn in range(1, num_pages):
                yield _load_page(pn)

        first_page.save(
            output_path,
            format="PDF",
            save_all=True,
            append_images=_remaining_pages(),
            resolution=float(dpi),
        )
        first_page.close()
        _cleanup()

        # Create summary if requested
        if summary_path:
            create_redaction_summary(
                pdf_path, summary_path, pii_detections, pii_mapping
            )

        # Create evaluation data if requested
        if evaluation_path:
            try:
                from .redaction_evaluator import create_comprehensive_evaluation

                eval_output = create_comprehensive_evaluation(
                    pdf_path=pdf_path,
                    output_pdf_path=output_path,
                    pii_detections=pii_detections,
                    pii_mapping=pii_mapping,
                    output_dir=evaluation_path,
                    capture_images=True,
                )
                if eval_output:
                    logger.info(f"Evaluation data saved to: {eval_output}")
            except Exception as eval_error:
                logger.info(f"Error creating evaluation data: {str(eval_error)}")

        # Store PII mapping in DynamoDB
        if dynamodb_manager is not None:
            filename = os.path.basename(pdf_path)
            filename = filename.replace("temp_input_", "").replace("temp_output_", "")
            filename_without_ext = os.path.splitext(filename)[0]
            try:
                detailed_pii_data = []
                for detection in pii_detections:
                    original = detection.get("content", "")
                    method = detection.get("_redact_method", "")
                    if method == "rasterized":
                        synthetic = _get_synthetic(
                            pii_mapping, original, detection.get("type", "PII")
                        )
                        replacement_status = method
                    else:
                        synthetic = "[NOT REDACTED - NO BBOX FOUND]"
                        replacement_status = "not_redacted"
                    pii_record = {
                        "original": original,
                        "synthetic": synthetic,
                        "type": detection.get("type", "unknown"),
                        "page_num": int(detection.get("page_num", 0)),
                        "confidence": float(detection.get("confidence", 0.0)),
                        "replacement_status": replacement_status,
                    }
                    if replacement_status == "not_redacted" and detection.get(
                        "_not_redacted_reason"
                    ):
                        pii_record["not_redacted_reason"] = detection[
                            "_not_redacted_reason"
                        ]
                    if "xref" in detection:
                        pii_record["source"] = "embedded_image"
                        pii_record["xref"] = detection["xref"]
                    else:
                        pii_record["source"] = "text"
                    if "bbox_source" in detection:
                        pii_record["bbox_source"] = detection["bbox_source"]
                    detailed_pii_data.append(pii_record)

                dynamodb_manager.store_pii_mapping(
                    detailed_pii_data,
                    filename_without_ext,
                    status="SUCCESS",
                    token_usage=token_usage,
                )
                logger.info("Successfully stored PII mapping in DynamoDB")
            except Exception as db_error:
                logger.error(
                    f"Failed to store PII mapping in DynamoDB: {str(db_error)}"
                )

        return True

    except Exception as e:
        logger.info(f"Error redacting PDF: {str(e)}")
        traceback.print_exc()
        if dynamodb_manager is not None:
            try:
                filename = os.path.basename(pdf_path)
                filename = filename.replace("temp_input_", "").replace(
                    "temp_output_", ""
                )
                filename_without_ext = os.path.splitext(filename)[0]
                dynamodb_manager.store_pii_mapping(
                    None, filename_without_ext, status="FAILED", error_message=str(e)
                )
            except Exception:
                pass
        return False
