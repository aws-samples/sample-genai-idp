# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Shared large-list assessment batching + reconciliation.

A single assessment inference over a large list field (e.g. a 120-row
transaction table) is unreliable: the model under-enumerates or omits the list
entirely, leaving most rows unassessed. This module holds the two primitives
that make large-list assessment robust, factored out so BOTH the standalone
Assessment step (``AssessmentService.process_document_section``) and the agentic
in-shard path (``ExtractionService``) share exactly one implementation:

- :func:`reconcile_assessment_to_data` — force the per-field assessment to
  index-align with the extracted data (truncate over-long lists, pad short/omitted
  ones with per-sub-field placeholders, fan a per-row confidence out to per-column
  leaves) so ``explainability_info[0][field][i]`` lines up with
  ``inference_result[field][i]`` for every list cell.
- :func:`assess_results_batched` — slice the single largest oversized list field
  into ``list_batch_size`` chunks, assess each chunk with the SAME scalars/context,
  concatenate the per-row assessments in order, and reconcile against the full data.

The module is deliberately import-light (no strands / PIL / boto3 at top level)
so it is cheap to import from the assessment service and unit-testable without the
agentic stack. Metering is accumulated with ``utils.merge_metering_data`` — the
canonical token-count merge — so this module carries no dependency on the
extraction package.
"""

from __future__ import annotations

import logging
from typing import Any

from idp_common import utils

logger = logging.getLogger(__name__)


def reconcile_assessment_to_data(
    assessment: dict[str, Any], extraction_results: dict[str, Any]
) -> dict[str, Any]:
    """Force per-field assessment to index-align with the extracted data.

    The assessment LLM frequently emits a *different* number of list-item
    assessments than the data has rows (a 120-row table may come back with
    only 44 row assessments). Downstream consumers (HITL, UI) index
    ``explainability_info[0][field][i]`` against ``inference_result[field][i]``,
    so a length mismatch silently misattributes confidence to the wrong row —
    and in the sharded path the drift compounds across shards on merge.

    For every list-valued data field this truncates an over-long assessment
    list and pads a too-short one so ``len(assessment[field]) ==
    len(data[field])`` exactly — including the case where the model OMITTED
    the list field entirely (common for large tables: the shard extracted N
    rows but the assessment response left the field out, so without this every
    such row would be unassessed AND ungroundable).

    Crucially, each padded row is a **per-sub-field placeholder mirroring the
    data row's structure** — a ``{"confidence": null, ...}`` leaf for each
    sub-field the data row populated (e.g. ``date``, ``description``,
    ``amount``). This gives OCR geometry grounding a real value to match per
    sub-field, so an un-assessed row still gets a correct bounding box from its
    extracted values; only the LLM ``confidence`` is null. A scalar/non-dict
    row element falls back to a single neutral leaf.

    Scalar/group fields are left untouched. Mutates and returns ``assessment``.
    """
    if not isinstance(assessment, dict):
        return assessment

    def _row_placeholder(data_row: Any) -> dict[str, Any]:
        reason = (
            "Not individually assessed (assessment returned fewer items "
            "than were extracted)."
        )
        # Mirror the data row's sub-fields so grounding can attach a box per
        # populated sub-field from its actual value.
        if isinstance(data_row, dict):
            leaves = {
                sub: {"confidence": None, "confidence_reason": reason}
                for sub, sv in data_row.items()
                if sv is not None and not isinstance(sv, (dict, list))
            }
            if leaves:
                return leaves
        # Scalar row element (or all-null/nested row): single neutral leaf.
        return {"confidence": None, "confidence_reason": reason}

    def _expand_row_to_per_column(row_assess: Any, data_row: Any) -> Any:
        """Normalize a per-ROW confidence into per-COLUMN leaves.

        Some models (esp. integrated mode) emit ONE ``{"confidence", ...}`` object
        for an entire list row. Downstream (HITL, UI, grounding) index confidence
        per sub-field, so when the data row is a dict but the assessment row is a
        single confidence leaf, fan that one score out across the row's populated
        scalar columns (preserving the model's confidence/reason on each). Rows
        that already carry per-column leaves, or scalar row elements, pass through.
        """
        if (
            isinstance(row_assess, dict)
            and "confidence" in row_assess
            and isinstance(data_row, dict)
        ):
            leaf = {
                "confidence": row_assess.get("confidence"),
                "confidence_reason": row_assess.get("confidence_reason"),
            }
            cols = {
                sub: dict(leaf)
                for sub, sv in data_row.items()
                if sv is not None and not isinstance(sv, (dict, list))
            }
            if cols:
                return cols
        return row_assess

    for field, data_val in extraction_results.items():
        if not isinstance(data_val, list):
            continue
        target = len(data_val)
        assessed = assessment.get(field)
        assessed = assessed if isinstance(assessed, list) else []
        if len(assessed) > target:
            assessed = assessed[:target]
        elif len(assessed) < target:
            assessed = assessed + [
                _row_placeholder(data_val[i]) for i in range(len(assessed), target)
            ]
        # Normalize any per-row scalar confidence to per-column leaves so every
        # list-item field gets its own confidence + geometry downstream.
        assessment[field] = [
            _expand_row_to_per_column(assessed[i], data_val[i]) for i in range(target)
        ]
    return assessment


def assess_results_batched(
    assessment_service: Any,
    *,
    class_label: str,
    extraction_results: dict[str, Any],
    document_text: str,
    page_images: list[Any],
    batch_size: int,
    ocr_text_confidence: str = "",
) -> dict[str, Any]:
    """Assess one scope, batching large list fields across multiple inferences.

    A single assessment call over a large list (e.g. 120 transaction rows) is
    unreliable — the model under-enumerates or omits the list, leaving rows
    unassessed. When the largest list field exceeds ``batch_size``, the list is
    sliced into batches; each batch is assessed with the SAME scalars/context (so
    scalar assessments and the document context are preserved) but only that
    batch's rows, and the per-row assessments are concatenated in order.
    Scalar/group assessments come from the first batch.

    Concurrency is deliberately SEQUENTIAL: the cost win of retiring granular
    assessment came from avoiding a cacheWrite storm caused by fanning batches out
    across a large thread pool; do not reintroduce it. If prompt caching is added
    later, warm the cache with ONE call before any fan-out.

    ``assessment_service`` must expose the pure inference core
    ``assess_results(class_label, extraction_results, document_text, page_images,
    ocr_text_confidence) -> AssessmentCoreResult``.

    Returns ``{"assessment", "alerts", "metering", "parsing_succeeded",
    "duration_seconds"}``. Falls back to a single call (still reconciled) when no
    list field exceeds the batch size.
    """
    # Identify list fields large enough to warrant batching.
    list_fields = {
        k: v
        for k, v in extraction_results.items()
        if isinstance(v, list) and len(v) > batch_size
    }

    def _one_call(results: dict[str, Any]) -> Any:
        return assessment_service.assess_results(
            class_label=class_label,
            extraction_results=results,
            document_text=document_text,
            page_images=page_images,
            ocr_text_confidence=ocr_text_confidence,
        )

    if not list_fields:
        core = _one_call(extraction_results)
        return {
            "assessment": reconcile_assessment_to_data(
                core.enhanced_assessment, extraction_results
            ),
            "alerts": core.confidence_threshold_alerts,
            "metering": core.metering,
            "parsing_succeeded": core.parsing_succeeded,
            "duration_seconds": core.duration_seconds,
        }

    # Batch by the largest list field; other (smaller) list fields ride the
    # first batch and are reconciled afterward.
    big_field = max(list_fields, key=lambda k: len(list_fields[k]))
    rows = extraction_results[big_field]
    merged_assessment: dict[str, Any] = {}
    merged_alerts: list[dict[str, Any]] = []
    merged_metering: dict[str, Any] = {}
    big_field_acc: list[Any] = []
    parsing_succeeded = True
    duration_seconds = 0.0

    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        # Same scalars/context every batch; only the big list is sliced.
        batch_results = dict(extraction_results)
        batch_results[big_field] = chunk
        core = _one_call(batch_results)
        enhanced = reconcile_assessment_to_data(core.enhanced_assessment, batch_results)
        # Accumulate the big list's per-row assessments in order.
        big_field_acc.extend(
            enhanced.get(big_field, [])
            if isinstance(enhanced.get(big_field), list)
            else []
        )
        merged_metering = utils.merge_metering_data(
            merged_metering, core.metering or {}
        )
        merged_alerts.extend(core.confidence_threshold_alerts or [])
        parsing_succeeded = parsing_succeeded and core.parsing_succeeded
        duration_seconds += core.duration_seconds or 0.0
        # Scalars/other fields: keep the first batch's assessment.
        if not merged_assessment:
            merged_assessment = enhanced
    merged_assessment[big_field] = big_field_acc
    # Final alignment against the full extraction (pads any residual gap).
    merged_assessment = reconcile_assessment_to_data(
        merged_assessment, extraction_results
    )
    return {
        "assessment": merged_assessment,
        "alerts": merged_alerts,
        "metering": merged_metering,
        "parsing_succeeded": parsing_succeeded,
        "duration_seconds": duration_seconds,
    }
