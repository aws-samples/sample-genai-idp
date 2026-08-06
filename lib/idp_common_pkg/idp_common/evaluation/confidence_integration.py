# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Confidence-metric helpers.

R12 removed the ``ConfidenceMetricsCalculator`` class from this module — it
had no production caller (only doc references) and its purpose was subsumed by
the aggregation Lambda's use of Stickler's ``BulkStructuredModelEvaluator``
(with confidence metrics installed as bulk-level accumulators). The one helper
retained here, ``get_average_confidence_from_metrics``, is still used to derive
the legacy ``average_confidence`` field from Stickler's ECE bins so the field
survives on old-format queries.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_average_confidence_from_metrics(
    confidence_metrics: dict[str, Any],
) -> float | None:
    """Extract average confidence from Stickler's confidence-metrics dict.

    Backward-compatible with the legacy ``average_confidence`` field
    (previously computed from Athena queries) — reads mean-confidence values
    out of the ECE bins reported by Stickler's overall aggregator and returns
    the count-weighted mean.

    Args:
        confidence_metrics: The ``confidence_metrics`` sub-dict Stickler emits
            (see ``stickler.structured_object_evaluator.models.confidence``).

    Returns:
        Average confidence in ``[0.0, 1.0]``, or ``None`` if no ECE data.
    """
    try:
        ece_data = confidence_metrics.get("overall", {}).get("ece", {})
        bins = ece_data.get("bins", [])
        if bins:
            total_count = sum(bin_data.get("count", 0) for bin_data in bins)
            if total_count > 0:
                weighted_sum = sum(
                    bin_data.get("mean_confidence", 0) * bin_data.get("count", 0)
                    for bin_data in bins
                )
                return weighted_sum / total_count
        logger.debug("No ECE bin data available for average confidence calculation")
        return None
    except Exception as e:  # noqa: BLE001 — helper is non-fatal
        logger.warning(f"Error extracting average confidence from metrics: {e}")
        return None
