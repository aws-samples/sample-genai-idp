# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Stickler v0.4.0+ Confidence Integration Module.

This module integrates Stickler's ConfidenceCalculator (v0.4.0+) to provide
enhanced confidence metrics including calibration metrics (ECE, Brier score, AUROC)
and per-field confidence rollups.

Key Features:
- ECE (Expected Calibration Error): Measures how well confidence scores match actual accuracy
- Brier Score: Mean squared error between confidence and outcome (lower is better)
- AUROC: How well confidence discriminates correct from incorrect predictions
- Per-field confidence metrics with rollups to document and test-run levels
- Coverage tracking: fields with vs without confidence data

Rich Value Pattern Integration:
- Uses Stickler's native Rich Value format: {"_value": val, "_confidence": conf}
- Confidence automatically extracted to 'prediction_confidences' by Stickler
- Eliminates manual flattening and wrapper detection logic
- Simpler, more maintainable approach using Stickler as designed
"""

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ConfidenceMetricsCalculator:
    """
    Enhanced confidence metrics calculator using Stickler v0.4.0+ ConfidenceCalculator.

    This calculator extracts confidence pairs from Stickler comparison results and
    computes calibration metrics at both overall and per-field levels.
    """

    def __init__(self, enable_all_metrics: bool = True):
        """
        Initialize the confidence metrics calculator.

        Args:
            enable_all_metrics: If True, compute all metrics (ECE, Brier, AUROC).
                               If False, only compute AUROC (backward compatible).
        """
        try:
            from stickler.structured_object_evaluator.models.confidence import (
                AUROCMetric,
                BrierScoreMetric,
                ConfidenceCalculator,
                ECEMetric,
                default_metrics,
            )

            if enable_all_metrics:
                # Use all default metrics for comprehensive calibration analysis
                metrics = default_metrics() + [ECEMetric(n_bins=10), BrierScoreMetric()]
            else:
                # Minimal metrics for backward compatibility
                metrics = [AUROCMetric()]

            self.calculator = ConfidenceCalculator(metrics=metrics)
            self.enable_all_metrics = enable_all_metrics
            logger.info(
                f"Initialized ConfidenceMetricsCalculator with "
                f"{'all' if enable_all_metrics else 'AUROC-only'} metrics"
            )

        except ImportError as e:
            logger.error(
                f"Failed to import Stickler v0.4.0+ confidence module: {e}. "
                f"Please upgrade to stickler-eval>=0.4.0"
            )
            raise

    def compute_from_comparison_results(
        self,
        comparison_results: list[dict[str, Any]],
        confidence_data: dict[str, dict[str, float]] | None = None,
    ) -> dict[str, Any]:
        """
        Compute confidence metrics from a list of Stickler comparison results.

        This is the main entry point for bulk evaluation scenarios like test runs.

        Args:
            comparison_results: List of Stickler comparison_result dicts from section evaluations
            confidence_data: Optional dict mapping document_id -> field_name -> confidence score
                           (legacy format for backward compatibility)

        Returns:
            Dictionary with confidence metrics:
            {
                "overall": {
                    "auroc": {"value": float | None},
                    "ece": {"value": float, "bins": [...]},  # if enable_all_metrics
                    "brier": {"value": float}                 # if enable_all_metrics
                },
                "fields": {
                    "field_name": {"auroc": {...}, "ece": {...}, "brier": {...}}
                },
                "coverage": {
                    "fields_with_confidence": int,
                    "fields_total": int,
                    "ratio": float
                },
                "field_count": int,
                "total_pairs": int
            }
        """
        try:
            # Accumulate confidence pairs from all comparison results
            all_keyed_pairs: dict[str, list[Any]] = {}
            total_fields_with_confidence = 0
            total_fields = 0

            for comparison_result in comparison_results:
                # Extract confidence pairs using Stickler's built-in extractor
                try:
                    extraction_result = self.calculator.extract_from_dicts(
                        field_comparisons=comparison_result.get(
                            "field_comparisons", []
                        ),
                        confidences=comparison_result.get("prediction_confidences", {}),
                    )

                    # Merge keyed pairs from this document
                    for field_path, pairs in extraction_result.keyed_pairs.items():
                        if field_path not in all_keyed_pairs:
                            all_keyed_pairs[field_path] = []
                        all_keyed_pairs[field_path].extend(pairs)

                    # Track coverage
                    total_fields_with_confidence += (
                        extraction_result.fields_with_confidence
                    )
                    total_fields += extraction_result.fields_total

                except Exception as e:
                    logger.warning(
                        f"Failed to extract confidence pairs from comparison result: {e}. "
                        f"Skipping this result."
                    )
                    continue

            if not all_keyed_pairs:
                logger.warning("No confidence pairs extracted from comparison results")
                return self._empty_metrics()

            # Compute metrics across all accumulated pairs
            metrics = self.calculator.compute_metrics(
                keyed_pairs=all_keyed_pairs,
                fields_with_confidence=total_fields_with_confidence,
                fields_total=total_fields,
            )

            # Add summary stats
            metrics["field_count"] = len(all_keyed_pairs)
            metrics["total_pairs"] = sum(
                len(pairs) for pairs in all_keyed_pairs.values()
            )

            logger.info(
                f"Computed confidence metrics: {metrics['total_pairs']} pairs across "
                f"{metrics['field_count']} fields, coverage ratio: "
                f"{metrics.get('coverage', {}).get('ratio', 0):.2%}"
            )

            return metrics

        except Exception as e:
            logger.error(f"Error computing confidence metrics: {e}", exc_info=True)
            return self._empty_metrics()

    def compute_from_section_result(
        self,
        stickler_comparison_result: dict[str, Any],
        confidence_scores: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Compute confidence metrics from a single section evaluation result.

        This is used for per-document evaluation scenarios.

        Args:
            stickler_comparison_result: Stickler comparison_result dict from section evaluation
            confidence_scores: Optional confidence scores dict (legacy parameter, unused with Rich Value Pattern)

        Returns:
            Dictionary with confidence metrics (same format as compute_from_comparison_results)
        """
        try:
            # Extract confidence pairs from the comparison result
            # With Rich Value Pattern, prediction_confidences is auto-extracted by Stickler
            extraction_result = self.calculator.extract_from_dicts(
                field_comparisons=stickler_comparison_result.get(
                    "field_comparisons", []
                ),
                confidences=stickler_comparison_result.get(
                    "prediction_confidences", {}
                ),
            )

            # Compute metrics
            metrics = self.calculator.compute_metrics(
                keyed_pairs=extraction_result.keyed_pairs,
                fields_with_confidence=extraction_result.fields_with_confidence,
                fields_total=extraction_result.fields_total,
            )

            # Add summary stats
            metrics["field_count"] = len(extraction_result.keyed_pairs)
            metrics["total_pairs"] = sum(
                len(pairs) for pairs in extraction_result.keyed_pairs.values()
            )

            return metrics

        except Exception as e:
            logger.error(
                f"Error computing confidence metrics for section: {e}", exc_info=True
            )
            return self._empty_metrics()

    def _empty_metrics(self) -> dict[str, Any]:
        """Return empty metrics structure when computation fails or no data available."""
        if self.enable_all_metrics:
            overall_metrics: dict[str, Any] = {
                "auroc": {"value": None},
                "ece": {"value": None, "bins": []},
                "brier": {"value": None},
            }
        else:
            overall_metrics = {"auroc": {"value": None}}

        return {
            "overall": overall_metrics,
            "fields": {},
            "coverage": {
                "fields_with_confidence": 0,
                "fields_total": 0,
                "ratio": 0.0,
            },
            "field_count": 0,
            "total_pairs": 0,
        }


def get_average_confidence_from_metrics(
    confidence_metrics: dict[str, Any],
) -> float | None:
    """
    Extract average confidence from Stickler confidence metrics.

    This provides backward compatibility with the legacy average_confidence field
    that was previously computed from Athena queries.

    Args:
        confidence_metrics: Confidence metrics dict from ConfidenceMetricsCalculator

    Returns:
        Average confidence as float, or None if no confidence data available
    """
    try:
        # Check if we have ECE bins with mean_confidence data
        ece_data = confidence_metrics.get("overall", {}).get("ece", {})
        bins = ece_data.get("bins", [])

        if bins:
            # Compute weighted average confidence across all bins
            total_count = sum(bin_data.get("count", 0) for bin_data in bins)
            if total_count > 0:
                weighted_sum = sum(
                    bin_data.get("mean_confidence", 0) * bin_data.get("count", 0)
                    for bin_data in bins
                )
                return weighted_sum / total_count

        # Fallback: no ECE data available
        logger.debug("No ECE bin data available for average confidence calculation")
        return None

    except Exception as e:
        logger.warning(f"Error extracting average confidence from metrics: {e}")
        return None
