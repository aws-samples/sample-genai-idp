# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Thin adapters over ``stickler.doc_split.*``.

Two things live here:

- ``load_sections_for_doc_split(sections, calculator)`` — the S3 adapter
  that bridges IDP's ``Section`` objects (with ``extraction_result_uri``
  pointing at S3-stored per-section JSON) to the plain-dict shape upstream's
  ``DocSplitClassificationMetrics.load_sections`` accepts.

- ``compute_graded_packet_metrics(gt_sections, pred_sections)`` — R14. Builds
  page-level rows from loaded section dicts and calls
  ``stickler.doc_split.packet_evaluation_metrics.evaluate_packet``. Returns
  ``None`` on failure (metrics are supplemental — the exact-match counters
  above them stand on their own and the pipeline must not fail because these
  couldn't be computed).
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from idp_common import s3

logger = logging.getLogger(__name__)


def load_sections_for_doc_split(
    sections: List[Any],
    calculator: Any,
) -> List[Dict[str, Any]]:
    """Load section JSON from S3 and shape it for upstream's
    ``DocSplitClassificationMetrics.load_sections``.

    The IDP fork previously subclassed ``load_sections`` to accept ``Section``
    objects directly; upstream 0.5.0 accepts plain dicts (specifically the
    nested ``{section_id, document_class, split_document}`` shape IDP already
    uses natively). This adapter — the S3 dependency and the Section-object
    contract — sits inside ``stickler_backend`` because it's a Stickler-facing
    adapter, not orchestration.

    Failures loading a section's JSON append to ``calculator.errors``, which
    flows into ``calculate_all_metrics()["errors"]`` and out to the markdown
    report; the section is skipped from metrics.

    Args:
        sections: IDP ``Section`` objects (typed via duck-typing to avoid a
            hard dependency loop on ``idp_common.models``).
        calculator: A ``stickler.doc_split.DocSplitClassificationMetrics``
            instance whose ``.errors`` list will accumulate load failures.
    """
    loaded: List[Dict[str, Any]] = []
    for section in sections:
        if not getattr(section, "extraction_result_uri", None):
            logger.warning(f"Section {section.section_id} has no extraction_result_uri")
            continue
        try:
            data = s3.get_json_content(section.extraction_result_uri)
        except Exception as e:  # noqa: BLE001 — surface all load failures
            calculator.errors.append(
                f"Error loading section data from {section.extraction_result_uri}: {e}"
            )
            logger.error(
                f"Error loading section data from {section.extraction_result_uri}: {e}"
            )
            continue
        if not isinstance(data, dict):
            continue
        # Preserve IDP's section_id (upstream defaults to gt_N/pred_N when
        # missing, which would break the section_details tables the UI
        # renders).
        loaded.append({"section_id": section.section_id, **data})
    return loaded


def compute_graded_packet_metrics(
    sections_gt: List[Dict[str, Any]],
    sections_pred: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """R14: build page-level rows from loaded gt/pred section dicts and call
    ``stickler.doc_split.packet_evaluation_metrics.evaluate_packet``.

    Returns ``None`` (rather than raising) on any failure — graded metrics are
    a supplemental enrichment layered on top of the existing exact-match
    counters.

    Rows are keyed by page index; a page present on only one side is skipped
    (``evaluate_packet`` requires both group and predicted-group columns for
    every row).
    """
    try:
        from stickler.doc_split.packet_evaluation_metrics import evaluate_packet
    except ImportError:
        return None

    gt_page_info: Dict[int, Tuple[int, int, str]] = {}
    for group_idx, section in enumerate(sections_gt):
        for page_order, page_idx in enumerate(section.get("page_indices") or []):
            gt_page_info[int(page_idx)] = (
                group_idx,
                page_order,
                section.get("document_class") or "Unknown",
            )

    pred_page_info: Dict[int, Tuple[int, int, str]] = {}
    for group_idx, section in enumerate(sections_pred):
        for page_order, page_idx in enumerate(section.get("page_indices") or []):
            pred_page_info[int(page_idx)] = (
                group_idx,
                page_order,
                section.get("document_class") or "Unknown",
            )

    rows: List[Dict[str, Any]] = []
    for page_idx in sorted(set(gt_page_info) & set(pred_page_info)):
        g_gt, po_gt, cl_gt = gt_page_info[page_idx]
        g_pr, po_pr, cl_pr = pred_page_info[page_idx]
        rows.append(
            {
                "group_id": g_gt,
                "group_id_predicted": g_pr,
                "page_number": po_gt,
                "page_number_predicted": po_pr,
                "class_label": cl_gt,
                "class_label_predicted": cl_pr,
            }
        )

    if not rows:
        return None

    try:
        return evaluate_packet(rows)
    except Exception as e:  # noqa: BLE001 — supplemental metric, never fatal
        logger.warning(f"Graded packet metrics failed: {e}")
        return None
