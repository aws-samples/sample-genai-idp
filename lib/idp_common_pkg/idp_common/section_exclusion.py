# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Helpers for the "excluded class" feature.

Some document types contain pages whose content is entirely static — e.g.,
instructions, legal warnings, cover sheets, federal tax notices on tax form
packages, etc. Those pages have no extractable fields and should not consume
compute, tokens, or LLM calls in the downstream stages of the pipeline
(extraction, assessment, summarization, rule validation, evaluation).

Authors mark a class as excluded in the configuration by setting the schema
extension ``x-aws-idp-exclude-from-processing: true`` on the class. The
classification service propagates that flag onto each ``Section`` it creates
(via ``Section.excluded`` and ``Section.exclusion_reason``). This module
provides the small shared functions that downstream services use to:

1. Decide whether to skip a section, and
2. Write a consistent "skipped" stub result so the reporting database and the
   UI can display a meaningful message to users instead of an empty result.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from idp_common.models import Document, Section

logger = logging.getLogger(__name__)

# Stable status string written into stub result files for excluded sections.
# Downstream code (UI, evaluation, reporting) can key off this value to
# render/annotate accordingly.
SKIPPED_STATUS = "skipped_excluded_class"


def is_section_excluded(section: Optional[Section]) -> bool:
    """Return True if the given section is marked as excluded.

    A missing / None section is treated as not excluded to keep call sites
    simple at the top of per-section handlers.
    """
    return bool(section is not None and getattr(section, "excluded", False))


def build_skipped_stub_result(
    document: Document,
    section: Section,
    stage: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a minimal result payload for a skipped section.

    The payload is intentionally small and uniform across stages so the UI
    and the reporting pipeline can render it without stage-specific logic.

    Args:
        document: The owning document (used only for context fields).
        section: The section being skipped.
        stage: Short stage name (e.g., "extraction", "assessment",
            "summarization", "rule_validation").
        extra: Optional additional fields to merge into the stub (e.g.,
            ``{"chunks_created": 0}``).

    Returns:
        A JSON-serializable dict suitable for writing to S3 as ``result.json``.
    """
    result: Dict[str, Any] = {
        "status": SKIPPED_STATUS,
        "stage": stage,
        "section_id": section.section_id,
        "classification": section.classification,
        "excluded": True,
        "exclusion_reason": section.exclusion_reason,
        "page_ids": list(section.page_ids or []),
        "message": (
            f"Section {section.section_id} classified as '{section.classification}' "
            f"which is marked x-aws-idp-exclude-from-processing=true; "
            f"{stage} was skipped."
        ),
    }
    if document.id:
        result["document_id"] = document.id
    if extra:
        result.update(extra)
    return result


def write_skipped_stub(
    document: Document,
    section: Section,
    stage: str,
    output_bucket: Optional[str] = None,
    output_key: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Write a skipped-stub result.json for a section to S3 (if possible).

    If ``output_bucket`` and ``output_key`` are both provided, the stub is
    uploaded and the resulting ``s3://`` URI is returned. Otherwise the stub
    is logged but not written (useful for unit tests and non-S3 contexts).

    Any exception during the S3 write is caught and logged as a warning —
    failing to write a stub must never surface as a section processing
    failure.
    """
    payload = build_skipped_stub_result(document, section, stage, extra=extra)
    body = json.dumps(payload, indent=2, default=str)

    if not (output_bucket and output_key):
        logger.info(
            "Skipped section stub for %s/%s (no S3 target provided):\n%s",
            stage,
            section.section_id,
            body,
        )
        return None

    try:
        # Import lazily so unit tests that don't need S3 don't pay the cost.
        import boto3

        s3_client = boto3.client("s3")
        s3_client.put_object(
            Bucket=output_bucket,
            Key=output_key,
            Body=body,
            ContentType="application/json",
        )
        uri = f"s3://{output_bucket}/{output_key}"
        logger.info(
            "Wrote skipped-section stub for %s stage to %s (class=%s, reason=%s)",
            stage,
            uri,
            section.classification,
            section.exclusion_reason or "excluded",
        )
        return uri
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(
            "Failed to write skipped-section stub for %s/%s to s3://%s/%s: %s",
            stage,
            section.section_id,
            output_bucket,
            output_key,
            e,
        )
        return None
