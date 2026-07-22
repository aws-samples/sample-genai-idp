# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared PII detection with concurrent execution via ThreadPoolExecutor."""

import re
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.pii_detector import invoke_model_for_text
from core.prompts import SYSTEM_PROMPT, PII_DETECTION_PROMPT
from validation.model_schemas import (
    safe_get_response_content,
    extract_json_dict,
    is_truncated_response,
    TextBasedOutput,
)

logger = logging.getLogger(__name__)


def detect_pii_in_text(
    text_content,
    model_id,
    model_provider,
    bedrock_runtime,
    inference_config,
    token_tracker=None,
    additional_model_fields=None,
    config=None,
):
    """Detect PII in text using Bedrock. Returns list of {content, type, confidence}."""
    prompt = PII_DETECTION_PROMPT.format(dispute_document=text_content)
    response = invoke_model_for_text(
        prompt,
        SYSTEM_PROMPT,
        model_id,
        model_provider,
        bedrock_runtime,
        inference_config,
        token_tracker=token_tracker,
        additional_model_fields=additional_model_fields,
        config=config,
        step="detection",
    )
    # Fail loud if the model hit its output limit — a truncated detection drops
    # the tail of the PII list (silent leak). Raising here marks this chunk as
    # failed so the job fails rather than redacting an incomplete set.
    if is_truncated_response(response):
        raise RuntimeError(
            "Detection response truncated (model output-token limit hit) — PII "
            "would be incomplete. Use a model with a larger output limit "
            "(Claude/GPT) or reduce the input size."
        )
    content = safe_get_response_content(response)
    logger.info(f"Raw response length: {len(content)} chars")

    # Robustly extract JSON (handles control chars, code fences, <response>
    # wrappers/preamble, and truncation). One shared parser across all paths.
    json_data = extract_json_dict(content)
    if json_data is not None:
        return TextBasedOutput.from_dict(json_data).pii_detections

    logger.warning("No valid JSON found in response")
    return []


def run_threaded_pii_detection(
    chunks,
    model_id,
    model_provider,
    bedrock_runtime,
    inference_config,
    max_workers,
    label="Chunk",
    token_tracker=None,
    additional_model_fields=None,
    config=None,
):
    """Run detect_pii_in_text concurrently across chunks.

    Args:
        chunks: dict {chunk_id: text_content}
        max_workers: from config concurrency.max_workers
        label: display label for logging (e.g., "Sheet", "Page", "Chunk")
        additional_model_fields: Optional additionalModelRequestFields (e.g. topK)
        config: Optional config dict to auto-build additional_model_fields

    Returns:
        all_detections: list of {content, type, confidence}
        failed_chunks: list of {chunk_id, error}
    """
    # Auto-build additional_model_fields from config if not provided
    if additional_model_fields is None and config is not None:
        from helpers.model_config_helper import get_additional_model_fields

        additional_model_fields = get_additional_model_fields(config, model_id)
    # Per-model shaping (thinking/effort, sampling strip, maxTokens clamp) is
    # applied centrally in converse_or_responses via the capability registry,
    # driven by `config` + step="detection" — nothing to build here.
    all_detections = []
    failed_chunks = []
    lock = threading.Lock()

    logger.info(
        f"Starting detection: {len(chunks)} {label.lower()}(s) with max_workers={max_workers}"
    )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for chunk_id, text_content in chunks.items():
            future = executor.submit(
                detect_pii_in_text,
                text_content,
                model_id,
                model_provider,
                bedrock_runtime,
                inference_config,
                token_tracker,
                additional_model_fields,
                config,
            )
            futures[future] = chunk_id

        for future in as_completed(futures):
            chunk_id = futures[future]
            try:
                detections = future.result()
                with lock:
                    all_detections.extend(detections)
                logger.info(f"{label} '{chunk_id}': {len(detections)} detections")
            except Exception as e:
                logger.error(f"Error detecting PII in {label} '{chunk_id}': {e}")
                with lock:
                    failed_chunks.append({"chunk_id": chunk_id, "error": str(e)})

    logger.info(
        f"Detection complete: {len(all_detections)} detections, {len(failed_chunks)} failed"
    )
    raw_detections = list(all_detections)
    all_detections = _strip_labels(all_detections)
    all_detections = _split_multiline_detections(all_detections)
    full_text = "\n".join(chunks.values())
    all_detections = _remove_substring_detections(all_detections, full_text)
    return all_detections, failed_chunks, raw_detections


def _strip_labels(detections):
    """Strip field labels from detected PII content.

    LLM sometimes includes the label (e.g. 'DOB: July 22, 1990').
    If left side of ':' is a short label-like string, keep only the right side.
    """
    stripped = 0
    for d in detections:
        content = d["content"]
        if ":" in content:
            left, right = content.split(":", 1)
            left_clean = left.strip().lower()
            right_clean = right.strip()
            if (
                right_clean
                and len(left_clean) <= 25
                and re.fullmatch(r"[a-z /]+", left_clean)
            ):
                d["content"] = right_clean
                stripped += 1
    if stripped:
        logger.info(f"Stripped labels from {stripped} detection(s)")
    return detections


def _split_multiline_detections(detections):
    """Split detections that span multiple lines into separate items.

    LLM sometimes merges adjacent fields (e.g. name + phone across lines)
    into one detection. Each line should be a separate detection.
    """
    result = []
    split_count = 0
    for d in detections:
        if "\n" in d["content"]:
            parts = [p.strip() for p in d["content"].split("\n") if p.strip()]
            for part in parts:
                result.append(
                    {
                        "content": part,
                        "type": d["type"],
                        "confidence": d.get("confidence", 95),
                    }
                )
            split_count += 1
        else:
            result.append(d)
    if split_count:
        logger.info(f"Split {split_count} multiline detections into separate items")
    return result


def _remove_substring_detections(detections, source_text=""):
    """Remove detections whose content is a substring of another detection,
    BUT only if the short form doesn't appear standalone in the source text.

    'Houston, TX' inside '4100 Westheimer Rd, Houston, TX 77027' at the same
    location → drop it. But 'Sarah Johnson' appearing standalone in prose while
    'Sarah Elizabeth Johnson' appears in header → keep both.
    """
    unique_contents = set(d["content"] for d in detections)
    substrings = set()
    for short in unique_contents:
        longs = [
            long_str
            for long_str in unique_contents
            if long_str != short and short in long_str
        ]
        if not longs:
            continue
        if source_text:
            # Remove ALL longer forms, then check if short still exists standalone
            remaining = source_text
            for long_str in longs:
                remaining = remaining.replace(long_str, "")
            if short in remaining:
                continue  # short exists standalone — keep it
        substrings.add(short)

    if not substrings:
        return detections

    filtered = [d for d in detections if d["content"] not in substrings]
    logger.info(
        f"Removed {len(detections) - len(filtered)} substring detections, {len(filtered)} remaining"
    )
    return filtered
