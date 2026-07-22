# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Text-based PII Processor Module — 3-step pipeline for PDF text extraction and PII redaction.

Step 1: Extract text from PDF → chunk → threaded PII detection
Step 2: Batch generate synthetic replacements via LLM
Step 3: Replace PII using longest-first ordering with exact + normalized matching
"""

import io
import os
import tempfile
import logging

import boto3
from pypdf import PdfReader

from helpers.text_chunker import chunk_text_by_lines
from helpers.threaded_detector import run_threaded_pii_detection
from core.synthetic_pii_generator import batch_generate_synthetic_pii
from core.text_replacer import replace_pii_in_text
from helpers.token_tracker import TokenTracker
from helpers.model_config_helper import (
    get_inference_config_from_yaml,
    get_concurrency_config,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def detect_pii_pdf_text(source_bucket, source_key, config, bedrock_runtime, s3_client):
    """Detect PII in a PDF using text extraction (Step 1 only)."""
    filename = os.path.splitext(os.path.basename(source_key))[0]
    model_id = config["model"]["id"]
    model_provider = config["model"]["provider"]
    inference_config = get_inference_config_from_yaml(config)
    cc = get_concurrency_config(config)
    tracker = TokenTracker(model_id)

    response = s3_client.get_object(Bucket=source_bucket, Key=source_key)
    pdf_bytes = response["Body"].read()

    temp_fd, temp_path = tempfile.mkstemp(
        suffix=f"_{filename}.pdf", dir=tempfile.gettempdir()
    )
    os.close(temp_fd)
    with open(temp_path, "wb") as f:
        f.write(pdf_bytes)

    from validation.pdf_validator import validate_pdf, PDFValidationError

    try:
        validate_pdf(temp_path, config)
    except PDFValidationError as e:
        raise ValueError(f"PDF validation failed: {e}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    text, page_count = _extract_text_from_pdf(pdf_bytes)
    if not text.strip():
        raise ValueError(
            f"PDF has {page_count} pages but no extractable text. "
            "Use image-based approach for this document."
        )

    text_chunks = chunk_text_by_lines(
        text, cc["max_txt_chunk_tokens"], cc["chars_per_token"]
    )
    chunks = {f"Chunk {i + 1}": c for i, c in enumerate(text_chunks)}

    all_detections, failed_chunks, _ = run_threaded_pii_detection(
        chunks,
        model_id,
        model_provider,
        bedrock_runtime,
        inference_config,
        cc["max_workers"],
        label="Chunk",
        token_tracker=tracker,
        config=config,
    )

    return {
        "source_key": source_key,
        "file_type": "pdf_text",
        "detections": [
            {
                "content": d["content"],
                "type": d["type"],
                "confidence": d.get("confidence", 0.0),
            }
            for d in all_detections
        ],
        "failed_chunks": failed_chunks,
        "token_usage": tracker.summary(),
    }


def _extract_text_from_pdf(pdf_bytes):
    """Extract text from PDF bytes using pypdf. Returns (text, page_count)."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    image_count = 0
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            pages.append(page_text)
        try:
            if hasattr(page, "images"):
                image_count += len(page.images)
        except Exception:
            image_count += 1  # Count page as having at least one image
    text = "\n".join(pages)
    logger.info(f"Extracted {len(text)} chars from {len(reader.pages)} PDF pages")
    if image_count:
        logger.warning(
            f"Found {image_count} embedded images — text-based approach cannot process images, PII in images will NOT be detected. Use image-based approach for full coverage."
        )
    return text, len(reader.pages)


def _store_pdf_text_pii_mapping(
    detections,
    pii_mapping,
    filename,
    dynamodb_manager,
    found_originals=None,
    token_tracker=None,
):
    """Store PDF text PII mappings in DynamoDB."""
    try:
        detailed_pii_data = []
        found_set = found_originals or set()
        for det in detections:
            original = det["content"]
            synthetic = pii_mapping.get(original, "")
            if original in found_set:
                status = "replaced"
            elif any(original in f for f in found_set):
                status = "replaced"
                if not synthetic:
                    for f in found_set:
                        if original in f and f in pii_mapping:
                            synthetic = f"(covered by: {pii_mapping[f]})"
                            break
            else:
                status = "not_found"
            detailed_pii_data.append(
                {
                    "original": original,
                    "synthetic": synthetic,
                    "type": det.get("type", "UNKNOWN"),
                    "confidence": det.get("confidence", 0),
                    "source": "text",
                    "replacement_status": status,
                }
            )
        dynamodb_manager.store_pii_mapping(
            detailed_pii_data,
            filename,
            status="SUCCESS",
            token_usage=token_tracker.summary() if token_tracker else {},
        )
        if token_tracker:
            token_tracker.log_summary()
        replaced = sum(
            1 for d in detailed_pii_data if d["replacement_status"] == "replaced"
        )
        logger.info(
            f"Stored {len(detailed_pii_data)} PDF text PII mappings in DynamoDB ({replaced} replaced, {len(detailed_pii_data) - replaced} not found)"
        )
    except Exception as e:
        logger.warning(f"Failed to store PDF text PII mapping in DynamoDB: {e}")


def process_pdf_text_based(
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
    """Process a PDF using text-based 3-step PII pipeline."""
    from validation.pdf_validator import validate_pdf, PDFValidationError

    try:
        if s3_client is None:
            s3_client = boto3.client("s3")

        model_id = config["model"]["id"]
        model_provider = config["model"]["provider"]
        inference_config = get_inference_config_from_yaml(config)
        cc = get_concurrency_config(config)
        tracker = TokenTracker(model_id)

        # Download PDF
        response = s3_client.get_object(Bucket=source_bucket, Key=source_key)
        pdf_bytes = response["Body"].read()

        # Validate
        temp_fd, temp_path = tempfile.mkstemp(
            suffix=f"_{filename_without_ext}.pdf", dir=tempfile.gettempdir()
        )
        os.close(temp_fd)
        with open(temp_path, "wb") as f:
            f.write(pdf_bytes)
        try:
            validate_pdf(temp_path, config)
            logger.info(f"PDF validation passed: {filename_without_ext}")
        except PDFValidationError as e:
            logger.error(f"PDF validation failed: {e}")
            if dynamodb_manager:
                dynamodb_manager.store_pii_mapping(
                    [],
                    filename_without_ext,
                    status="FAILED",
                    error_message=f"PDF validation failed: {e}",
                )
            raise ValueError(f"PDF validation failed: {e}")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        # Extract text
        text, page_count = _extract_text_from_pdf(pdf_bytes)
        if not text.strip():
            raise ValueError(
                f"PDF has {page_count} pages but no extractable text — likely a scanned/image-based PDF. "
                "Use image-based approach (approach: 'image' in config.yaml) for this document."
            )

        # Step 1: Chunk and detect PII concurrently
        text_chunks = chunk_text_by_lines(
            text, cc["max_txt_chunk_tokens"], cc["chars_per_token"]
        )
        chunks = {f"Chunk {i + 1}": c for i, c in enumerate(text_chunks)}

        all_detections, failed_chunks, raw_detections = run_threaded_pii_detection(
            chunks,
            model_id,
            model_provider,
            bedrock_runtime,
            inference_config,
            cc["max_workers"],
            label="Chunk",
            token_tracker=tracker,
            config=config,
        )
        logger.info(
            f"Total detections: {len(raw_detections)} raw, {len(all_detections)} after dedup"
        )

        if failed_chunks:
            logger.warning(f"Failed chunks: {[f['chunk_id'] for f in failed_chunks]}")
            if dynamodb_manager:
                for fc in failed_chunks:
                    dynamodb_manager.store_pii_mapping(
                        [],
                        filename_without_ext,
                        status="FAILED_DETECTION",
                        error_message=f"Chunk '{fc['chunk_id']}': {fc['error']}",
                    )

        # Step 2: Batch generate synthetic replacements
        pii_mapping = {}
        if all_detections:
            pii_mapping = batch_generate_synthetic_pii(
                all_detections,
                model_id,
                model_provider,
                bedrock_runtime,
                config=config,
                token_tracker=tracker,
            )
            logger.info(f"Generated {len(pii_mapping)} synthetic replacements")

        # Step 3: Replace using text_replacer
        redacted_text, found_originals, _, _, _ = replace_pii_in_text(text, pii_mapping)
        not_found = len(pii_mapping) - len(found_originals)
        if not_found:
            missing = [k for k in pii_mapping if k not in found_originals]
            covered = [m for m in missing if any(m in r for r in found_originals)]
            hallucinated = [m for m in missing if m not in covered and m not in text]
            truly_missing = len(missing) - len(covered) - len(hallucinated)
            if covered:
                logger.info(
                    f"{len(covered)} PII skipped (already covered by longer replacement)"
                )
            if hallucinated:
                logger.info(
                    f"{len(hallucinated)} PII skipped (LLM hallucinated, not in source text)"
                )
            if truly_missing:
                logger.warning(f"{truly_missing} PII not found in text")
        logger.info(
            f"Replacement: {len(found_originals)}/{len(pii_mapping)} unique PII replaced, {not_found} not found"
        )

        s3_output_key = f"{folder_path}redacted_{filename_without_ext}.txt"
        s3_client.put_object(
            Body=redacted_text, Bucket=output_bucket, Key=s3_output_key
        )
        logger.info(f"Uploaded redacted text file to: {s3_output_key}")

        # Create and upload summary JSON
        import json

        summary = {
            "input_file": f"s3://{source_bucket}/{source_key}",
            "output_file": f"s3://{output_bucket}/{s3_output_key}",
            "pii_count": len(raw_detections),
            "pii_replaced": len(found_originals),
            "pii_not_found": len(pii_mapping) - len(found_originals),
            "pages_processed": len(chunks),
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

        # Store in DynamoDB
        if dynamodb_manager and raw_detections:
            _store_pdf_text_pii_mapping(
                raw_detections,
                pii_mapping,
                filename_without_ext,
                dynamodb_manager,
                found_originals,
                token_tracker=tracker,
                config=config,
            )

        return {
            "success": True,
            "s3_output_file": s3_output_key,
            "pii_count": len(all_detections),
            "replacements": len(found_originals),
        }

    except Exception as e:
        logger.error(f"Error processing PDF text-based: {e}", exc_info=True)
        if dynamodb_manager:
            dynamodb_manager.store_pii_mapping(
                [], filename_without_ext, status="FAILED", error_message=str(e)
            )
        return {"success": False, "error": str(e)}
