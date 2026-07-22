# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

#!/usr/bin/env python3
"""
PDF PII Detection and Redaction System

This script implements a sophisticated system for detecting and redacting
PII data in PDF documents using image-based
processing with a vision-capable Large Language Model (LLM).


"""

import os
import tempfile
import json
import logging
import traceback
import boto3

# Configure logging
logger = logging.getLogger(__name__)

# Import our modules
from helpers.pdf_processor import extract_all_pages_as_images
from core.pii_detector import detect_pii_in_image
from core.synthetic_pii_generator import batch_generate_synthetic_pii
from redaction.pdf_redactor import redact_pdf


def display_image(image, title=None, figsize=(10, 10)):
    """Display a PIL Image using matplotlib."""
    import matplotlib.pyplot as plt  # Lazy import - only loads when function is called

    plt.figure(figsize=figsize)
    plt.imshow(image)
    if title:
        plt.title(title)
    plt.axis("off")
    plt.show()


def process_pdf_for_pii_redaction(
    pdf_path,
    output_dir,
    model_id,
    model_provider,
    bedrock_runtime,
    process_embedded_images=True,
    debug=False,
    dynamodb_manager=None,
    config=None,
):
    """
    Process a PDF for PII detection and redaction.

    Args:
        pdf_path: Path to the PDF file
        output_dir: Directory to save output files
        model_id: ID of the model to use
        model_provider: Provider of the model
        bedrock_runtime: Bedrock runtime client
        process_embedded_images: Whether to process embedded images
        debug: Enable debug output
        dynamodb_manager: DynamoDBManager instance for storing PII mappings (optional)

    Returns:
        Dictionary with results
    """
    try:
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

        # Create evaluation directory
        eval_dir = os.path.join(output_dir, "evaluation")
        os.makedirs(eval_dir, exist_ok=True)

        # Create output paths
        pdf_name = os.path.basename(pdf_path)
        output_pdf_path = os.path.join(output_dir, f"redacted_{pdf_name}")
        summary_path = os.path.join(
            output_dir, f"redaction_summary_{pdf_name.replace('.pdf', '.json')}"
        )
        evaluation_path = os.path.join(eval_dir, pdf_name.replace(".pdf", ""))

        if debug:
            logger.info(f"Processing PDF: {pdf_path}")

        # Step 1: Extract page images from PDF
        if debug:
            logger.info("Extracting images from PDF...")
        page_images = extract_all_pages_as_images(pdf_path)

        if debug:
            logger.info(f"Extracted {len(page_images)} pages")

        # Step 2: Detect PII in pages (page-level only, no tiles)
        if debug:
            logger.info("Step 1 - PII Detection: Processing pages...")
        page_pii_detections = []
        for i, (img, metadata) in enumerate(page_images):
            if debug:
                logger.info(f"  Page {i + 1}/{len(page_images)}...")
            detections = detect_pii_in_image(
                img, metadata, model_id, model_provider, bedrock_runtime, config=config
            )
            page_pii_detections.extend(detections)

        all_pii_detections = page_pii_detections
        if debug:
            logger.info(f"Found {len(all_pii_detections)} PII instances")

        # Step 3: Generate synthetic PII
        if debug:
            logger.info("Generating synthetic PII...")
        pii_mapping = batch_generate_synthetic_pii(
            all_pii_detections, model_id, model_provider, bedrock_runtime
        )

        # Step 4: Redact PDF and generate evaluation data
        if debug:
            logger.info("Redacting PDF and generating evaluation data...")
        success = redact_pdf(
            pdf_path,
            output_pdf_path,
            all_pii_detections,
            pii_mapping,
            summary_path,
            evaluation_path,
            dynamodb_manager,
            bedrock_runtime=bedrock_runtime,
        )

        if success:
            if debug:
                logger.info(f"Successfully redacted PDF: {output_pdf_path}")
                logger.info(f"Redaction summary: {summary_path}")
                logger.info(f"Evaluation data: {evaluation_path}")
        else:
            if debug:
                logger.warning("Failed to redact PDF")

        # Return results
        return {
            "success": success,
            "input_pdf": pdf_path,
            "output_pdf": output_pdf_path,
            "summary_path": summary_path,
            "evaluation_path": evaluation_path,
            "pii_count": len(all_pii_detections),
            "pii_by_type": {
                pii_type: len([d for d in all_pii_detections if d["type"] == pii_type])
                for pii_type in set(d["type"] for d in all_pii_detections)
            },
        }

    except Exception as e:
        if debug:
            logger.error(f"Error processing PDF: {str(e)}")
            traceback.print_exc()
        return {"success": False, "error": str(e)}


def detect_pii_pdf_image(source_bucket, source_key, config, bedrock_runtime, s3_client):
    """Detect PII in a PDF using image-based approach (Step 1 only). Includes bounding boxes."""
    from core.pii_detector import detect_pii_in_image
    from helpers.pdf_processor import extract_all_pages_as_images
    from validation.pdf_validator import validate_pdf, PDFValidationError
    from helpers.token_tracker import TokenTracker
    from helpers.textract_helper import (
        enhance_pii_detections_with_textract,
        get_textract_full,
        find_text_bbox,
        _parse_textract_words,
    )
    from concurrent.futures import ThreadPoolExecutor, as_completed

    filename = os.path.splitext(os.path.basename(source_key))[0]
    model_id = config["model"]["id"]
    model_provider = config["model"]["provider"]
    dpi = config["performance"]["dpi"]
    tracker = TokenTracker(model_id)

    response = s3_client.get_object(Bucket=source_bucket, Key=source_key)
    pdf_content = response["Body"].read()

    temp_fd, temp_path = tempfile.mkstemp(
        suffix=f"_{filename}.pdf", dir=tempfile.gettempdir()
    )
    os.close(temp_fd)
    with open(temp_path, "wb") as f:
        f.write(pdf_content)
    try:
        validate_pdf(temp_path, config)
    except PDFValidationError as e:
        raise ValueError(f"PDF validation failed: {e}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    s3_uri = f"s3://{source_bucket}/{source_key}"
    page_images = extract_all_pages_as_images(s3_uri, dpi=dpi, s3_client=s3_client)
    logger.info(f"Extracted {len(page_images)} pages at {dpi} DPI")
    max_workers = config.get("performance", {}).get("max_workers", 5)

    completed = [0]

    def _detect_page(img, metadata, page_num):
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
        completed[0] += 1
        logger.info(
            f"  [{completed[0]}/{len(page_images)}] Page {page_num}: {len(detections)} detections"
        )
        return detections, {"page": page_num, "ocr_text": ocr_text, "raw": raw_textract}

    all_detections = []
    textract_pages = []
    failed_pages = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for i, (img, metadata) in enumerate(page_images):
            page_num = metadata.get("page_number", i)
            f = executor.submit(_detect_page, img, metadata, page_num)
            futures[f] = page_num
        for future in as_completed(futures):
            try:
                dets, tx_page = future.result()
                all_detections.extend(dets)
                textract_pages.append(tx_page)
            except Exception as e:
                # Track the failed page so the handler can fail the job. Do NOT
                # silently continue — a dropped page means undetected PII.
                logger.error(f"Error detecting PII in page {futures[future]}: {e}")
                failed_pages.append(
                    {"chunk_id": f"page_{futures[future]}", "error": str(e)}
                )

    # Cross-page sweep: search all unique PII values on every page via Textract
    unique_pii = {}
    SWEEP_EXCLUDE = {
        "Unknown",
        "unknown",
        "None",
        "none",
        "N/A",
        "n/a",
        "-",
        "Male",
        "Female",
    }
    for d in all_detections:
        c = d.get("content", "").strip()
        if c and c not in unique_pii and c not in SWEEP_EXCLUDE:
            unique_pii[c] = {
                "type": d.get("type", "unknown"),
                "confidence": d.get("confidence", 0.0),
            }

    page_pii = {}
    for d in all_detections:
        page_pii.setdefault(d.get("page_num", 0), set()).add(
            d.get("content", "").strip()
        )

    cross_extras = []
    for tp in textract_pages:
        pg = tp["page"]
        raw = tp.get("raw")
        if not raw:
            continue
        img_size = None
        for img, meta in page_images:
            if meta.get("page_number") == pg:
                img_size = img.size
                break
        if not img_size:
            continue
        words = _parse_textract_words(raw, img_size)
        if not words:
            continue
        used = set()
        # Claim indices only for the count LLM detected per PII on this page
        page_det_counts = {}
        for d in all_detections:
            if d.get("page_num") == pg and d.get("detection_source") != "textract":
                c = d.get("content", "").strip()
                page_det_counts[c] = page_det_counts.get(c, 0) + 1
        for pii_val, count in page_det_counts.items():
            for _ in range(count):
                bbox, indices, _ = find_text_bbox(pii_val, words, used)
                if not bbox:
                    break
                used.update(indices)
        # Search for extra occurrences of all PII values on this page
        for pii_val, meta in unique_pii.items():
            if len(pii_val) <= 3:
                continue
            while True:
                bbox, indices, mtype = find_text_bbox(pii_val, words, used)
                if not bbox:
                    break
                used.update(indices)
                cross_extras.append(
                    {
                        "content": pii_val,
                        "type": meta["type"],
                        "confidence": meta["confidence"],
                        "bounding_box": bbox,
                        "page_num": pg,
                        "bbox_source": f"textract_{mtype}" if mtype else "textract",
                        "detection_source": "textract",
                    }
                )
    if cross_extras:
        logger.info(
            f"Cross-page sweep: found {len(cross_extras)} extra PII occurrences"
        )
        all_detections.extend(cross_extras)

    return {
        "source_key": source_key,
        "file_type": "pdf_image",
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
                **(
                    {"detection_source": d["detection_source"]}
                    if "detection_source" in d
                    else {}
                ),
            }
            for d in all_detections
        ],
        "failed_chunks": failed_pages,
        "token_usage": tracker.summary(),
        "textract_pages": sorted(textract_pages, key=lambda x: x["page"]),
    }


def process_pdf_image_based(
    source_bucket,
    source_key,
    output_bucket,
    filename_without_ext,
    config,
    bedrock_runtime,
    dynamodb_manager=None,
    s3_client=None,
    folder_path="",
):
    """
    Process a PDF using image-based PII detection directly from S3.

    Args:
        source_bucket: S3 bucket containing the PDF (input)
        source_key: S3 key of the PDF file
        output_bucket: S3 bucket for redacted PDF and temp images (output)
        filename_without_ext: Filename without extension
        config: Configuration dictionary
        bedrock_runtime: Bedrock runtime client
        dynamodb_manager: Optional DynamoDB manager
        s3_client: Optional S3 client
        folder_path: Folder path to preserve in output

    Returns:
        Dictionary with results
    """
    import time
    from core.pii_detector import detect_pii_in_image
    from helpers.pdf_processor import extract_all_pages_as_images
    from helpers.page_type_checker import get_text_based_pages
    from core.synthetic_pii_generator import batch_generate_synthetic_pii
    from redaction.pdf_redactor import redact_pdf
    from validation.pdf_validator import validate_pdf, PDFValidationError
    from helpers.token_tracker import TokenTracker

    try:
        start_time = time.time()

        if s3_client is None:
            s3_client = boto3.client("s3")

        output_pdf_key = f"{folder_path}redacted_{filename_without_ext}.pdf"
        summary_key = f"{folder_path}redaction_summary_{filename_without_ext}.json"

        model_id = config["model"]["id"]
        model_provider = config["model"]["provider"]
        dpi = config["performance"]["dpi"]
        _ = config["processing"]["process_embedded_images"]
        tracker = TokenTracker(model_id)

        # Step 1: Check page types
        logger.info("Analyzing page types...")
        s3_uri = f"s3://{source_bucket}/{source_key}"

        response = s3_client.get_object(Bucket=source_bucket, Key=source_key)
        pdf_content = response["Body"].read()

        temp_fd, temp_pdf_path = tempfile.mkstemp(
            suffix=f"_{filename_without_ext}.pdf", dir=tempfile.gettempdir()
        )
        os.close(temp_fd)
        with open(temp_pdf_path, "wb") as f:
            f.write(pdf_content)

        try:
            validate_pdf(temp_pdf_path, config)
            logger.info(f"PDF validation passed for: {filename_without_ext}")
        except PDFValidationError as e:
            logger.error(f"PDF validation failed: {str(e)}")
            if dynamodb_manager:
                dynamodb_manager.store_pii_mapping(
                    None,
                    filename_without_ext,
                    status="FAILED",
                    error_message=f"PDF validation failed: {str(e)}",
                )
            raise ValueError(f"PDF validation failed: {str(e)}")
        finally:
            if os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)

        text_pages = get_text_based_pages(pdf_content, text_threshold=50)
        logger.info(f"Found {len(text_pages)} text-based pages: {text_pages}")

        logger.info("Extracting images directly from S3...")
        page_images = extract_all_pages_as_images(s3_uri, dpi=dpi, s3_client=s3_client)
        logger.info(f"Successfully extracted {len(page_images)} pages from S3 PDF")

        # Step 2: Detect PII in pages (threaded)
        # Page-level only — no tile/embedded image LLM calls needed
        # Embedded image PII is detected from the page screenshot
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from helpers.textract_helper import enhance_pii_detections_with_textract

        max_workers = config.get("performance", {}).get("max_workers", 5)

        page_work = []
        for i, (img, metadata) in enumerate(page_images):
            page_num = metadata.get("page_number", i)
            page_work.append((img, metadata, page_num))

        logger.info(
            f"Step 1 - PII Detection: Processing {len(page_work)} pages with {max_workers} workers..."
        )

        completed = [0]

        def _detect_page(img, metadata, page_num):
            from helpers.textract_helper import get_textract_full

            textract_words, ocr_text, _raw = get_textract_full(img, bedrock_runtime)
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
            completed[0] += 1
            logger.info(
                f"  [{completed[0]}/{len(page_work)}] Page {page_num}: {len(detections)} detections"
            )
            return detections

        all_pii_detections = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for img, metadata, page_num in page_work:
                f = executor.submit(_detect_page, img, metadata, page_num)
                futures[f] = page_num

            for future in as_completed(futures):
                try:
                    all_pii_detections.extend(future.result())
                except Exception as e:
                    logger.error(f"Error detecting PII in page {futures[future]}: {e}")

        # Summary stats
        total = len(all_pii_detections)
        redactable_pii = [d for d in all_pii_detections if d.get("bounding_box")]
        skipped_pii = [d for d in all_pii_detections if not d.get("bounding_box")]
        exact = sum(1 for d in redactable_pii if d.get("bbox_source") == "textract")
        fuzzy = sum(
            1 for d in redactable_pii if d.get("bbox_source") == "textract_fuzzy"
        )
        spatial = sum(
            1 for d in redactable_pii if d.get("bbox_source") == "textract_spatial"
        )
        llm_vision = sum(
            1 for d in redactable_pii if d.get("bbox_source") == "llm_vision"
        )
        logger.info(
            f"Detection summary: {total} total, {len(redactable_pii)} with bbox ({exact} exact, {fuzzy} fuzzy, {spatial} spatial, {llm_vision} llm_vision), {len(skipped_pii)} skipped"
        )
        if skipped_pii:
            logger.warning(
                f"Skipping {len(skipped_pii)} PII items without bounding boxes"
            )
            if total > 0 and len(skipped_pii) / total > 0.5:
                logger.error(
                    f"WARNING: Over 50% of PII items ({len(skipped_pii)}/{total}) have no bounding box — redaction may be incomplete"
                )

        # Step 3: Generate synthetic PII (skip in blackout mode)
        redaction_mode = config.get("redaction", {}).get("mode", "synthetic")
        if redaction_mode == "blackout":
            logger.info("Blackout mode — skipping synthetic generation")
            pii_mapping = {d.get("content", ""): "[REDACTED]" for d in redactable_pii}
        else:
            logger.info(f"Generating synthetic PII for {len(redactable_pii)} items...")
            pii_mapping = batch_generate_synthetic_pii(
                redactable_pii,
                model_id,
                model_provider,
                bedrock_runtime,
                config=config,
                token_tracker=tracker,
            )

        # Step 4: Redact PDF
        logger.info("Step 3 - Redaction: Replacing PII with synthetic data...")
        response = s3_client.get_object(Bucket=source_bucket, Key=source_key)
        pdf_content = response["Body"].read()

        fd1, temp_input_path = tempfile.mkstemp(
            suffix=f"_in_{filename_without_ext}.pdf", dir=tempfile.gettempdir()
        )
        os.close(fd1)
        fd2, temp_output_path = tempfile.mkstemp(
            suffix=f"_out_{filename_without_ext}.pdf", dir=tempfile.gettempdir()
        )
        os.close(fd2)
        fd3, temp_summary_path = tempfile.mkstemp(
            suffix=f"_sum_{filename_without_ext}.json", dir=tempfile.gettempdir()
        )
        os.close(fd3)

        try:
            with open(temp_input_path, "wb") as f:
                f.write(pdf_content)

            from helpers.model_config_helper import get_show_bounding_boxes

            success = redact_pdf(
                temp_input_path,
                temp_output_path,
                all_pii_detections,
                pii_mapping,
                temp_summary_path,
                None,
                dynamodb_manager,
                token_usage=tracker.summary(),
                bedrock_runtime=bedrock_runtime,
                redaction_config={
                    **config.get("redaction", {}),
                    "show_bounding_boxes": get_show_bounding_boxes(config),
                    "bounding_box_color": config.get("validation", {}).get(
                        "bounding_box_color", [1, 0, 0]
                    ),
                    "dpi": config.get("performance", {}).get("dpi", 300),
                },
                s3_bucket=output_bucket,  # Store temp renders in output bucket
                s3_render_prefix=f"{folder_path}{filename_without_ext}/renders/",
            )

            if success:
                with open(temp_output_path, "rb") as f:
                    s3_client.put_object(
                        Body=f.read(), Bucket=output_bucket, Key=output_pdf_key
                    )

                summary = {
                    "input_pdf": f"s3://{source_bucket}/{source_key}",
                    "output_pdf": f"s3://{output_bucket}/redacted/{output_pdf_key}",
                    "pii_count": len(all_pii_detections),
                    "pii_redacted": len(redactable_pii),
                    "pii_skipped": len(skipped_pii),
                    "pii_by_type": {
                        pii_type: len(
                            [d for d in all_pii_detections if d["type"] == pii_type]
                        )
                        for pii_type in set(d["type"] for d in all_pii_detections)
                    },
                    "skipped_by_page": (
                        {
                            str(page): {
                                "count": len(
                                    [s for s in skipped_pii if s.get("page") == page]
                                ),
                                "types": list(
                                    set(
                                        s.get("type", "unknown")
                                        for s in skipped_pii
                                        if s.get("page") == page
                                    )
                                ),
                            }
                            for page in set(s.get("page") for s in skipped_pii)
                        }
                        if skipped_pii
                        else {}
                    ),
                    "processing_method": "image_based",
                    "processing_time": time.time() - start_time,
                }
                s3_client.put_object(
                    Body=json.dumps(summary, indent=2),
                    Bucket=output_bucket,
                    Key=summary_key,
                    ContentType="application/json",
                )
                logger.info(
                    f"Uploaded redacted PDF to s3://{output_bucket}/{output_pdf_key}"
                )
        finally:
            for temp_file in [temp_input_path, temp_output_path, temp_summary_path]:
                if os.path.exists(temp_file):
                    os.remove(temp_file)

        if success:
            tracker.log_summary()
            form_replaced = sum(
                1 for d in all_pii_detections if d.get("bbox_source") == "form_field"
            )
            final_redacted = len(redactable_pii) + form_replaced
            final_skipped = len(all_pii_detections) - final_redacted
            logger.info(
                f"Redaction: {final_redacted}/{len(all_pii_detections)} PII redacted, {final_skipped} skipped (no bounding box)"
            )
            logger.info("✅ PII ANONYMIZATION COMPLETED SUCCESSFULLY")
            return {
                "success": True,
                "s3_output_file": output_pdf_key,
                "s3_summary_file": summary_key,
                "pii_mapping": pii_mapping,
                "pii_count": len(all_pii_detections),
                "pii_by_type": {
                    pii_type: len(
                        [d for d in all_pii_detections if d["type"] == pii_type]
                    )
                    for pii_type in set(d["type"] for d in all_pii_detections)
                },
                "execution_time": time.time() - start_time,
                "token_usage": tracker.summary(),
            }
        else:
            logger.error("Failed to redact PDF")
            if dynamodb_manager:
                dynamodb_manager.store_pii_mapping(
                    [],
                    filename_without_ext,
                    status="FAILED",
                    error_message="Failed to redact PDF",
                )
            return {"success": False, "error": "Failed to redact PDF"}

    except Exception as e:
        logger.error(f"Error processing PDF image-based: {str(e)}", exc_info=True)
        if dynamodb_manager:
            dynamodb_manager.store_pii_mapping(
                [], filename_without_ext, status="FAILED", error_message=str(e)
            )
        return {"success": False, "error": str(e)}
