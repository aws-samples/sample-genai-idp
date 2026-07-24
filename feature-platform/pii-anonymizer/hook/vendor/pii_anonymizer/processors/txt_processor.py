# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Text file PII Processor Module

3-step pipeline: chunk text by lines, detect PII concurrently,
batch generate synthetic replacements, replace using text_replacer.
"""

import os
import tempfile
import logging

from helpers.model_config_helper import (
    get_inference_config_from_yaml,
    get_concurrency_config,
)
from core.synthetic_pii_generator import batch_generate_synthetic_pii
from helpers.threaded_detector import run_threaded_pii_detection
from helpers.text_chunker import chunk_text_by_lines
from core.text_replacer import replace_pii_in_text
from helpers.token_tracker import TokenTracker

logger = logging.getLogger(__name__)


def detect_pii_txt(source_bucket, source_key, config, bedrock_runtime, s3_client):
    """Detect PII in a text file (Step 1 only)."""
    filename = os.path.splitext(os.path.basename(source_key))[0]
    model_id = config["model"]["id"]
    model_provider = config["model"]["provider"]
    inference_config = get_inference_config_from_yaml(config)
    cc = get_concurrency_config(config)
    tracker = TokenTracker(model_id)

    temp_fd, temp_path = tempfile.mkstemp(
        suffix=f"_{filename}.txt", dir=tempfile.gettempdir()
    )
    os.close(temp_fd)
    s3_client.download_file(source_bucket, source_key, temp_path)
    logger.info(f"Downloaded text file: {source_key}")

    from validation.document_validator import validate_txt, DocumentValidationError

    try:
        validate_txt(temp_path, config)
    except DocumentValidationError as e:
        os.remove(temp_path)
        raise ValueError(f"Text validation failed: {e}")

    with open(temp_path, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    os.remove(temp_path)

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
    logger.info(f"Detections: {len(raw_detections)} raw, {len(all_detections)} deduped")

    return {
        "source_key": source_key,
        "file_type": "txt",
        "detections": [
            {
                "content": d["content"],
                "type": d["type"],
                "confidence": d.get("confidence", 0.0),
            }
            for d in all_detections
        ],
        "raw_detections": raw_detections,
        "failed_chunks": failed_chunks,
        "token_usage": tracker.summary(),
    }


def process_txt_file(
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
    """End-to-end text file processing: chunk, detect per chunk, batch synthetic, replace."""
    try:
        model_id = config["model"]["id"]
        model_provider = config["model"]["provider"]
        inference_config = get_inference_config_from_yaml(config)
        cc = get_concurrency_config(config)
        tracker = TokenTracker(model_id)

        # Download from S3
        temp_fd, temp_path = tempfile.mkstemp(
            suffix=f"_{filename_without_ext}.txt", dir=tempfile.gettempdir()
        )
        os.close(temp_fd)
        s3_client.download_file(source_bucket, source_key, temp_path)
        logger.info(f"Downloaded text file: {source_key}")

        # Validate text file
        from validation.document_validator import validate_txt, DocumentValidationError

        try:
            validate_txt(temp_path, config)
            logger.info(f"Text validation passed for: {filename_without_ext}")
        except DocumentValidationError as e:
            logger.error(f"Text validation failed: {str(e)}")
            return {"success": False, "error": str(e), "pii_count": 0}
        logger.info(f"Downloaded text file: {source_key}")

        with open(temp_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        logger.info(f"Text file: {len(text)} chars")

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

        # Write and upload
        fd, output_path = tempfile.mkstemp(
            suffix=f"_redacted_{filename_without_ext}.txt", dir=tempfile.gettempdir()
        )
        os.close(fd)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(redacted_text)

        s3_output_key = f"{folder_path}redacted_{filename_without_ext}.txt"
        s3_client.upload_file(output_path, output_bucket, s3_output_key)
        logger.info(f"Uploaded redacted text file to: {s3_output_key}")

        # Create and upload summary JSON
        import json

        summary = {
            "input_file": f"s3://{source_bucket}/{source_key}",
            "output_file": f"s3://{output_bucket}/{s3_output_key}",
            "pii_count": len(all_detections),
            "pii_replaced": len(found_originals),
            "pii_not_found": not_found,
            "chunks_processed": len(chunks),
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
        if dynamodb_manager and all_detections:
            _store_txt_pii_mapping(
                raw_detections,
                pii_mapping,
                filename_without_ext,
                dynamodb_manager,
                found_originals,
                tracker,
            )

        # Cleanup
        os.remove(temp_path)
        os.remove(output_path)

        return {
            "success": True,
            "s3_output_file": s3_output_key,
            "pii_count": len(all_detections),
            "replacements": len(found_originals),
        }
    except Exception as e:
        logger.error(f"Error processing text file: {e}", exc_info=True)
        if dynamodb_manager:
            dynamodb_manager.store_pii_mapping(
                [], filename_without_ext, status="FAILED", error_message=str(e)
            )
        return {"success": False, "error": str(e)}


def _store_txt_pii_mapping(
    detections,
    pii_mapping,
    filename,
    dynamodb_manager,
    found_originals=None,
    tracker=None,
):
    """Store text file PII mappings in DynamoDB."""
    try:
        detailed_pii_data = []
        found_set = found_originals or set()
        for det in detections:
            original = det["content"]
            synthetic = pii_mapping.get(original, "")
            if original in found_set:
                status = "text_replaced"
            elif any(original in f for f in found_set):
                status = "text_replaced"
                if not synthetic:
                    # Find synthetic from the longer form that covers this one
                    for f in found_set:
                        if original in f and f in pii_mapping:
                            synthetic = f"(covered by: {pii_mapping[f]})"
                            break
            else:
                status = "not_redacted"
            detailed_pii_data.append(
                {
                    "original": original,
                    "synthetic": synthetic,
                    "type": det.get("type", "UNKNOWN"),
                    "confidence": det.get("confidence", 0),
                    "source": "text",
                    "replacement_status": status,
                    **(
                        {"not_redacted_reason": "text_not_found_in_document"}
                        if status == "not_redacted"
                        else {}
                    ),
                }
            )

        token_usage = tracker.summary() if tracker else {}
        dynamodb_manager.store_pii_mapping(
            detailed_pii_data, filename, status="SUCCESS", token_usage=token_usage
        )
        if tracker:
            tracker.log_summary()
        replaced = sum(
            1 for d in detailed_pii_data if d["replacement_status"] == "text_replaced"
        )
        logger.info(
            f"Stored {len(detailed_pii_data)} text PII mappings in DynamoDB ({replaced} replaced, {len(detailed_pii_data) - replaced} not found)"
        )
    except Exception as e:
        logger.warning(f"Failed to store text PII mapping in DynamoDB: {e}")
