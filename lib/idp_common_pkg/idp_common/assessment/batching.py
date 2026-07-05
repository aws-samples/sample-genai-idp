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


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or (isinstance(v, str) and not v.strip()):
            return default
        return float(v)
    except (ValueError, TypeError):
        return default


def enrich_assessment_with_thresholds(
    assessment: dict[str, Any],
    class_schema: dict[str, Any],
    default_confidence_threshold: float = 0.9,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Attach ``confidence_threshold`` to every confidence leaf and build alerts.

    The *integrated* confidence paths (the extraction inference emits confidence
    inline, whether via the simple free-text prompt or the agentic tool call)
    produce raw ``{confidence, confidence_reason}`` leaves with NO threshold and
    NO ``confidence_threshold_alerts`` — unlike the standalone/separate path,
    which enriches them in ``AssessmentService.assess_results``. This helper adds
    the same enrichment so all confidence modes share one output contract:
    each leaf gains ``confidence_threshold`` (from the field's
    ``x-aws-idp-confidence-threshold`` or the default), and a flat list of
    threshold-violation alerts is returned.

    Pure/importable (no S3/Bedrock). Mutates a copy; returns
    ``(enriched_assessment, alerts)``. Scalars, groups, and list rows (per-column
    leaves) are all handled recursively.
    """
    from idp_common.config.schema_constants import (
        SCHEMA_PROPERTIES,
        X_AWS_IDP_CONFIDENCE_THRESHOLD,
    )

    if not isinstance(assessment, dict):
        return assessment, []
    properties = (class_schema or {}).get(SCHEMA_PROPERTIES, {}) or {}
    alerts: list[dict[str, Any]] = []

    def _enrich_leaf_container(node: Any, threshold: float, path: str) -> Any:
        """Recursively add threshold to every {confidence,...} leaf under node."""
        if isinstance(node, dict):
            if "confidence" in node:
                conf = (
                    _to_float(node.get("confidence"), None)
                    if node.get("confidence") is not None
                    else None
                )
                out = {**node, "confidence_threshold": threshold}
                if conf is not None and conf < threshold:
                    alerts.append(
                        {
                            "attribute_name": path,
                            "confidence": conf,
                            "confidence_threshold": threshold,
                        }
                    )
                return out
            return {
                k: _enrich_leaf_container(v, threshold, f"{path}.{k}" if path else k)
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [
                _enrich_leaf_container(v, threshold, f"{path}[{i}]")
                for i, v in enumerate(node)
            ]
        return node

    enriched: dict[str, Any] = {}
    for attr_name, attr_assessment in assessment.items():
        prop_schema = properties.get(attr_name, {}) or {}
        threshold = _to_float(
            prop_schema.get(
                X_AWS_IDP_CONFIDENCE_THRESHOLD, default_confidence_threshold
            ),
            default_confidence_threshold,
        )
        enriched[attr_name] = _enrich_leaf_container(
            attr_assessment, threshold, attr_name
        )
    return enriched, alerts


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


def _row_confidence_missing(row_assess: Any) -> bool:
    """True if a reconciled list-row assessment still lacks a real confidence.

    A row is 'missing' when it is the null placeholder or any of its per-column
    leaves has ``confidence is None`` — i.e. the model didn't actually score it.
    """
    if isinstance(row_assess, dict):
        if "confidence" in row_assess:
            return row_assess.get("confidence") is None
        leaves = [v for v in row_assess.values() if isinstance(v, dict)]
        if not leaves:
            return True
        return any(leaf.get("confidence") is None for leaf in leaves)
    return True


def _missing_row_indices(assessment_list: Any, data_list: Any) -> list[int]:
    if not isinstance(assessment_list, list) or not isinstance(data_list, list):
        return []
    n = min(len(assessment_list), len(data_list))
    return [i for i in range(n) if _row_confidence_missing(assessment_list[i])]


def _new_split_stats() -> dict[str, Any]:
    """Accumulator recording adaptive batch-split activity for visibility.

    Surfaced in extraction/assessment metadata + the processing report so a run
    that had to shrink its assessment batches (because the model truncated at its
    max-output-token ceiling) is observable rather than silent.
    """
    return {
        "truncated_calls": 0,  # assessment calls that hit max_tokens
        "splits": 0,  # times a slice was halved and re-assessed
        "min_batch_size_used": None,  # smallest row-slice actually assessed
        "rows_recovered_by_retry": 0,  # unscored rows rescued in the retry phase
        "unrecoverable_rows": 0,  # rows still unscored after all recovery
    }


def _record_min_batch(stats: dict[str, Any], size: int) -> None:
    cur = stats.get("min_batch_size_used")
    stats["min_batch_size_used"] = size if cur is None else min(cur, size)


def split_stats_are_notable(stats: dict[str, Any] | None) -> bool:
    """True when the run actually had to shrink batches (worth surfacing).

    A clean run (no truncation, no splits, no leftover unscored rows) is not
    notable — callers omit the metadata block entirely in that case to avoid
    noise.
    """
    if not stats:
        return False
    return bool(
        stats.get("truncated_calls")
        or stats.get("splits")
        or stats.get("unrecoverable_rows")
    )


def merge_split_stats(
    a: dict[str, Any] | None, b: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Additively merge two split-stats accumulators (for the sharded path, where
    each shard produces its own). Counters sum; ``min_batch_size_used`` takes the
    smaller non-null. Returns None only when both inputs are None."""
    if not a and not b:
        return None
    a = a or _new_split_stats()
    b = b or _new_split_stats()
    merged = _new_split_stats()
    for key in (
        "truncated_calls",
        "splits",
        "rows_recovered_by_retry",
        "unrecoverable_rows",
    ):
        merged[key] = a.get(key, 0) + b.get(key, 0)
    mins = [
        v
        for v in (a.get("min_batch_size_used"), b.get("min_batch_size_used"))
        if v is not None
    ]
    merged["min_batch_size_used"] = min(mins) if mins else None
    return merged


def format_split_stats_report(stats: dict[str, Any] | None) -> str:
    """Human-readable processing-report block for adaptive batch splitting.

    Returns an empty string when nothing notable happened.
    """
    if not split_stats_are_notable(stats):
        return ""
    assert stats is not None
    lines = [
        "Assessment Batch Splitting (model truncated output):",
        f"  - Truncated assessment calls: {stats.get('truncated_calls', 0)}",
        f"  - Batch splits performed: {stats.get('splits', 0)}",
        f"  - Smallest batch assessed: {stats.get('min_batch_size_used')}",
        f"  - Rows recovered on retry: {stats.get('rows_recovered_by_retry', 0)}",
        f"  - Rows still unscored: {stats.get('unrecoverable_rows', 0)}",
    ]
    return "\n".join(lines)


def _assess_slice_adaptive(
    one_call,
    *,
    base_results: dict[str, Any],
    big_field: str,
    rows: list[Any],
    reconcile,
    stats: dict[str, Any],
    min_slice: int = 1,
) -> dict[str, Any]:
    """Assess ``rows`` for ``big_field`` and, if the model TRUNCATES the response
    (``AssessmentCoreResult.truncated``), recursively halve the slice and retry
    until it parses or the slice reaches ``min_slice`` rows.

    A truncated call yields unparseable JSON → default/placeholder scores for the
    whole slice, so retrying the *same* size is futile; the output is too big for
    the model's cap (common with ``geometry.mode: llm``, which adds a bounding box
    per cell). Halving shrinks the output until it fits. Records activity in
    ``stats`` for downstream visibility. Sequential (no fan-out), consistent with
    the batcher's cost model.

    Returns ``{"rows": [per-row assessment...], "scalars": {enhanced non-big
    fields}, "alerts": [...], "metering": {...}, "duration": float}`` where
    ``rows`` is index-aligned to the input ``rows``.
    """
    slice_results = dict(base_results)
    slice_results[big_field] = rows
    core = one_call(slice_results)
    _record_min_batch(stats, len(rows))

    should_split = (
        getattr(core, "truncated", False) and len(rows) > min_slice and len(rows) > 1
    )
    if getattr(core, "truncated", False):
        stats["truncated_calls"] += 1

    if not should_split:
        enhanced = reconcile(core.enhanced_assessment, slice_results)
        enhanced_rows = (
            enhanced.get(big_field) if isinstance(enhanced.get(big_field), list) else []
        )
        # Pad/truncate to exactly len(rows) so indices stay aligned.
        enhanced_rows = list(enhanced_rows)[: len(rows)]
        scalars = {k: v for k, v in enhanced.items() if k != big_field}
        return {
            "rows": enhanced_rows,
            "scalars": scalars,
            "alerts": list(core.confidence_threshold_alerts or []),
            "metering": core.metering or {},
            "duration": core.duration_seconds or 0.0,
        }

    # Truncated with room to shrink: split in half and recurse.
    stats["splits"] += 1
    mid = len(rows) // 2
    logger.warning(
        "Assessment truncated for '%s' over %d rows; splitting into %d + %d "
        "and retrying with smaller batches.",
        big_field,
        len(rows),
        mid,
        len(rows) - mid,
    )
    left = _assess_slice_adaptive(
        one_call,
        base_results=base_results,
        big_field=big_field,
        rows=rows[:mid],
        reconcile=reconcile,
        stats=stats,
        min_slice=min_slice,
    )
    right = _assess_slice_adaptive(
        one_call,
        base_results=base_results,
        big_field=big_field,
        rows=rows[mid:],
        reconcile=reconcile,
        stats=stats,
        min_slice=min_slice,
    )
    # The truncated parent call still consumed real output tokens (and wall
    # time) before we decided to split — fold its metering/duration in so cost
    # dashboards reflect the TRUE spend, including the wasted truncated attempt.
    # (Discarding it would under-report cost by exactly the wasted work this
    # feature exists to make visible.)
    merged_metering = utils.merge_metering_data(left["metering"], right["metering"])
    merged_metering = utils.merge_metering_data(merged_metering, core.metering or {})
    # Scalars come from the first (left) sub-slice; both carry the same context.
    return {
        "rows": left["rows"] + right["rows"],
        "scalars": left["scalars"] or right["scalars"],
        "alerts": left["alerts"] + right["alerts"],
        "metering": merged_metering,
        "duration": left["duration"]
        + right["duration"]
        + (core.duration_seconds or 0.0),
    }


def assess_results_batched(
    assessment_service: Any,
    *,
    class_label: str,
    extraction_results: dict[str, Any],
    document_text: str,
    page_images: list[Any],
    batch_size: int,
    ocr_text_confidence: str = "",
    max_retries: int = 2,
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

    If a batch's response is TRUNCATED at the model's max-output-token ceiling
    (e.g. ``geometry.mode: llm`` makes per-row output too large for a small-cap
    model like Nova Lite), that slice is recursively halved and re-assessed until
    it fits — instead of accepting default 0.5 / null-placeholder scores. This
    activity is recorded and returned under ``split_stats`` for visibility.

    Returns ``{"assessment", "alerts", "metering", "parsing_succeeded",
    "duration_seconds", "split_stats"}``. Falls back to a single call (still
    reconciled) when no list field exceeds the batch size.
    """
    split_stats = _new_split_stats()

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

    # All list fields (any size) — used to target missing-row retries even when
    # no list is large enough to require batching.
    all_list_fields = {
        k: v for k, v in extraction_results.items() if isinstance(v, list) and v
    }

    if not list_fields:
        core = _one_call(extraction_results)
        merged_assessment = reconcile_assessment_to_data(
            core.enhanced_assessment, extraction_results
        )
        merged_alerts = list(core.confidence_threshold_alerts or [])
        merged_metering = core.metering or {}
        duration_seconds = core.duration_seconds or 0.0
        # Retry missing rows for the largest list (small lists can still drop
        # rows — esp. agentic single-shot cramming values+confidence in one call).
        if core.truncated:
            split_stats["truncated_calls"] += 1
        if all_list_fields:
            big = max(all_list_fields, key=lambda k: len(all_list_fields[k]))
            merged_assessment, merged_alerts, merged_metering, dur = (
                _retry_missing_rows(
                    _one_call,
                    extraction_results=extraction_results,
                    big_field=big,
                    merged_assessment=merged_assessment,
                    merged_alerts=merged_alerts,
                    merged_metering=merged_metering,
                    batch_size=batch_size,
                    max_retries=max_retries,
                    split_stats=split_stats,
                )
            )
            duration_seconds += dur
            split_stats["unrecoverable_rows"] = len(
                _missing_row_indices(
                    merged_assessment.get(big), extraction_results.get(big)
                )
            )
        return {
            "assessment": merged_assessment,
            "alerts": merged_alerts,
            "metering": merged_metering,
            "parsing_succeeded": core.parsing_succeeded,
            "duration_seconds": duration_seconds,
            "split_stats": split_stats,
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
        # Same scalars/context every batch; only the big list is sliced. If the
        # model truncates the chunk's response, _assess_slice_adaptive halves it
        # and retries until it fits (recording the activity in split_stats).
        sliced = _assess_slice_adaptive(
            _one_call,
            base_results=extraction_results,
            big_field=big_field,
            rows=chunk,
            reconcile=reconcile_assessment_to_data,
            stats=split_stats,
        )
        # Accumulate the big list's per-row assessments in order.
        big_field_acc.extend(sliced["rows"])
        merged_metering = utils.merge_metering_data(merged_metering, sliced["metering"])
        merged_alerts.extend(sliced["alerts"])
        duration_seconds += sliced["duration"]
        # Scalars/other fields: keep the first batch's assessment.
        if not merged_assessment and sliced["scalars"]:
            merged_assessment = dict(sliced["scalars"])
    merged_assessment[big_field] = big_field_acc
    # Final alignment against the full extraction (pads any residual gap).
    merged_assessment = reconcile_assessment_to_data(
        merged_assessment, extraction_results
    )
    merged_assessment, merged_alerts, merged_metering, dur = _retry_missing_rows(
        _one_call,
        extraction_results=extraction_results,
        big_field=big_field,
        merged_assessment=merged_assessment,
        merged_alerts=merged_alerts,
        merged_metering=merged_metering,
        batch_size=batch_size,
        max_retries=max_retries,
        split_stats=split_stats,
    )
    duration_seconds += dur

    # Count rows still unscored after all recovery, for visibility.
    split_stats["unrecoverable_rows"] = len(
        _missing_row_indices(merged_assessment.get(big_field), rows)
    )

    return {
        "assessment": merged_assessment,
        "alerts": merged_alerts,
        "metering": merged_metering,
        "parsing_succeeded": parsing_succeeded,
        "duration_seconds": duration_seconds,
        "split_stats": split_stats,
    }


def _retry_missing_rows(
    one_call,
    *,
    extraction_results: dict[str, Any],
    big_field: str,
    merged_assessment: dict[str, Any],
    merged_alerts: list[dict[str, Any]],
    merged_metering: dict[str, Any],
    batch_size: int,
    max_retries: int,
    split_stats: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], float]:
    """Re-assess ONLY the list rows the model left unscored, splicing real scores
    back by index so large-list confidence coverage reaches 100% (not just null
    placeholders). Bounded by ``max_retries`` rounds; sequential (no fan-out); a
    round that recovers nothing stops early. Best-effort — retry failures keep the
    placeholder. Each retry chunk goes through the adaptive splitter, so a chunk
    the model truncates is halved rather than left unscored. Returns updated
    (assessment, alerts, metering, added_duration)."""
    rows = extraction_results.get(big_field)
    if not isinstance(rows, list):
        return merged_assessment, merged_alerts, merged_metering, 0.0
    stats = split_stats if split_stats is not None else _new_split_stats()
    base_results = {k: v for k, v in extraction_results.items() if k != big_field}
    added_duration = 0.0
    for _round in range(max_retries):
        missing = _missing_row_indices(merged_assessment.get(big_field), rows)
        if not missing:
            break
        logger.info(
            "assess_results_batched: retrying %d unscored '%s' rows (round %d)",
            len(missing),
            big_field,
            _round + 1,
        )
        recovered_any = False
        for start in range(0, len(missing), batch_size):
            idx_chunk = missing[start : start + batch_size]
            try:
                sliced = _assess_slice_adaptive(
                    one_call,
                    base_results=base_results,
                    big_field=big_field,
                    rows=[rows[i] for i in idx_chunk],
                    reconcile=reconcile_assessment_to_data,
                    stats=stats,
                )
            except Exception as e:  # noqa: BLE001 - retry is best-effort
                logger.warning("Missing-row retry call failed: %s", e)
                continue
            retry_rows = sliced["rows"]
            merged_metering = utils.merge_metering_data(
                merged_metering, sliced["metering"]
            )
            merged_alerts.extend(sliced["alerts"])
            added_duration += sliced["duration"]
            for local_i, orig_i in enumerate(idx_chunk):
                if local_i < len(retry_rows) and not _row_confidence_missing(
                    retry_rows[local_i]
                ):
                    merged_assessment[big_field][orig_i] = retry_rows[local_i]
                    recovered_any = True
                    stats["rows_recovered_by_retry"] += 1
        if not recovered_any:
            logger.info("Missing-row retry made no progress; stopping retries.")
            break
    return merged_assessment, merged_alerts, merged_metering, added_duration
