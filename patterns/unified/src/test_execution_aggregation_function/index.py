# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Test Execution Aggregation Lambda Function.

Aggregates evaluation metrics for test runs using Stickler's bulk evaluator.
This function is invoked by the TestResultsResolver to offload heavy Stickler processing.
"""

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for test execution aggregation.

    Args:
        event: Lambda event containing test_run_id
        context: Lambda context

    Returns:
        Dictionary with aggregated metrics
    """
    try:
        test_run_id = event.get("test_run_id")
        tracking_table_name = os.environ.get("TRACKING_TABLE")

        if not test_run_id:
            raise ValueError("Missing required parameter: test_run_id")

        if not tracking_table_name:
            raise ValueError("TRACKING_TABLE environment variable not set")

        logger.info(f"Aggregating test run: {test_run_id}")

        result = aggregate_test_run_with_stickler(test_run_id, tracking_table_name)

        # Calculate average weighted score from document-level scores
        weighted_scores = result.get("weighted_overall_scores", {})
        avg_weighted_score = None
        if weighted_scores:
            scores = [score for score in weighted_scores.values() if score is not None]
            if scores:
                avg_weighted_score = sum(scores) / len(scores)

        # Format avg_weighted_score
        avg_weighted_score_str = (
            f"{avg_weighted_score:.4f}" if avg_weighted_score is not None else "N/A"
        )

        logger.info(
            f"Aggregation completed for test run: {test_run_id}, "
            f"document_count={result.get('document_count', 0)}, "
            f"overall_accuracy={result.get('overall_accuracy')}, "
            f"avg_weighted_score={avg_weighted_score_str}"
        )

        return {"statusCode": 200, "body": json.dumps(result)}

    except Exception as e:
        logger.error(f"Error in test execution aggregation: {e}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e), "metrics": _empty_metrics()}),
        }


def aggregate_test_run_with_stickler(
    test_run_id: str, tracking_table_name: str
) -> Dict[str, Any]:
    """
    Aggregate evaluation metrics for a test run using Stickler's bulk evaluator.

    Args:
        test_run_id: Test run identifier (batch ID prefix)
        tracking_table_name: DynamoDB tracking table name

    Returns:
        Dictionary with aggregated metrics matching the existing format
    """
    # Load Stickler comparison results from S3
    comparison_results, doc_weighted_scores = _load_comparison_results(
        test_run_id, tracking_table_name
    )

    if not comparison_results:
        logger.warning(f"No comparison results found for test run: {test_run_id}")
        return _empty_metrics()

    # Use Stickler's bulk aggregator
    try:
        from stickler.structured_object_evaluator.bulk_structured_model_evaluator import (
            BulkStructuredModelEvaluator,
            aggregate_from_comparisons,
        )
        from stickler.structured_object_evaluator.models.confidence import (
            AUROCMetric,
            BrierScoreMetric,
            ECEMetric,
            ErrorCaptureAtBudgetMetric,
        )

        process_eval = aggregate_from_comparisons(comparison_results)

        logger.info(
            f"Stickler aggregation complete: document_count={process_eval.document_count}, comparison_results={len(comparison_results)}, weighted_scores={len(doc_weighted_scores)}"
        )

        # R7: replace the sklearn confidence post-pass with a Stickler
        # accumulator subclass that collapses list-index paths
        # (LineItems[0].Rate → LineItems.Rate) BEFORE Stickler's
        # ConfidenceCalculator sees them. Two accumulators can't share
        # the built-in ``confidence_metrics`` name, so ECARB and the
        # pattern-collapsed confidence metrics run in two evaluators —
        # both cheap: each is a single pass over the same
        # ``update_from_comparison_result`` stream.
        confidence_metrics = None
        try:
            evaluator = BulkStructuredModelEvaluator(
                accumulators=[
                    _IndexCollapsingConfidenceAccumulator(
                        metrics=[AUROCMetric(), ECEMetric(), BrierScoreMetric()]
                    )
                ]
            )
            for comp_result in comparison_results:
                evaluator.update_from_comparison_result(comp_result)
            confidence_metrics = evaluator.compute().confidence_metrics
        except Exception as e:
            logger.warning(
                f"Failed to compute pattern-collapsed confidence metrics: {e}",
                exc_info=True,
            )

        ecab_metrics = None
        try:
            ecab_evaluator = BulkStructuredModelEvaluator(
                confidence_metrics=[ErrorCaptureAtBudgetMetric(budgets=[0.30])]
            )
            for comp_result in comparison_results:
                ecab_evaluator.update_from_comparison_result(comp_result)
            ecab_metrics = ecab_evaluator.compute().confidence_metrics

            if ecab_metrics and "overall" in ecab_metrics:
                ecab_30 = (
                    ecab_metrics.get("overall", {})
                    .get("error_capture_at_budget", {})
                    .get("budgets", {})
                    .get("0.30", {})
                )
                if ecab_30:
                    logger.info(
                        f"ECARB@30: catch {ecab_30.get('pct_errors_caught', 0) * 100:.0f}% "
                        f"of errors with {ecab_30.get('gain', 0):.1f}x gain vs random"
                    )
        except Exception as e:
            logger.warning(f"Failed to compute ECAB metrics: {e}", exc_info=True)

        # Replace process_eval.confidence_metrics with the pattern-collapsed
        # version — process_eval only has per-doc metrics for scalar
        # top-level fields.
        if confidence_metrics is not None:
            process_eval.confidence_metrics = confidence_metrics

        # Transform to IDP format (split metrics will be added by caller from Athena)
        return _transform_stickler_metrics(
            process_eval, doc_weighted_scores, comparison_results, ecab_metrics
        )

    except Exception as e:
        logger.error(
            f"Stickler aggregation failed for {test_run_id}: {e}", exc_info=True
        )
        return _empty_metrics()


def _load_comparison_results(
    test_run_id: str, tracking_table_name: str
) -> tuple[List[Dict[str, Any]], Dict[str, float]]:
    """
    Load all Stickler comparison results for documents in a test run.

    Args:
        test_run_id: Test run identifier (batch ID prefix)
        tracking_table_name: DynamoDB tracking table name

    Returns:
        Tuple of (comparison_results, doc_weighted_scores)
    """
    table = dynamodb.Table(tracking_table_name)
    output_bucket = os.environ.get("OUTPUT_BUCKET")

    if not output_bucket:
        logger.error("OUTPUT_BUCKET environment variable not set")
        return [], {}

    # Scan for all documents matching the test run prefix
    comparison_results = []
    doc_weighted_scores = {}

    # Use scan with filter on PK to select only document records for this test run
    response = table.scan(
        FilterExpression="begins_with(PK, :pk_prefix)",
        ExpressionAttributeValues={":pk_prefix": f"doc#{test_run_id}"},
    )

    items = response.get("Items", [])

    # Handle pagination
    while "LastEvaluatedKey" in response:
        response = table.scan(
            FilterExpression="begins_with(PK, :pk_prefix)",
            ExpressionAttributeValues={":pk_prefix": f"doc#{test_run_id}"},
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))

    logger.info(f"Found {len(items)} documents for test run {test_run_id}")

    # Filter for completed documents
    docs_to_load = []
    for item in items:
        doc_key = item.get("ObjectKey")
        if not doc_key:
            continue

        eval_status = item.get("EvaluationStatus")
        if eval_status != "COMPLETED":
            logger.debug(f"Skipping document {doc_key} with status {eval_status}")
            continue

        docs_to_load.append(doc_key)

    logger.info(f"Loading {len(docs_to_load)} completed documents in parallel")

    # Load S3 results in parallel using ThreadPoolExecutor
    # Use max 20 workers to balance parallelism with Lambda memory/network limits
    max_workers = min(20, len(docs_to_load)) if docs_to_load else 1

    def load_document_results(doc_key):
        """Load and parse a single document's evaluation results.

        NOTE: Uses hardcoded /evaluation/results.json path. This must stay in sync
        with EvaluationService path format (service.py:2077). If evaluation layout
        changes, update this path accordingly.
        """
        eval_results_uri = f"s3://{output_bucket}/{doc_key}/evaluation/results.json"
        try:
            eval_data = _load_s3_json(eval_results_uri)
            section_results = eval_data.get("section_results", [])

            # Extract comparison results from sections
            doc_comparisons = []
            for section in section_results:
                stickler_result = section.get("stickler_comparison_result")
                if stickler_result:
                    doc_comparisons.append(stickler_result)

            # Extract weighted score
            weighted_score = None
            if section_results:
                weighted_score = eval_data.get("overall_metrics", {}).get(
                    "weighted_overall_score"
                )

            return {
                "doc_key": doc_key,
                "comparisons": doc_comparisons,
                "weighted_score": weighted_score,
                "success": True,
            }
        except Exception as e:
            logger.warning(
                f"Failed to load evaluation results from {eval_results_uri}: {e}"
            )
            return {"doc_key": doc_key, "success": False}

    # Execute parallel S3 loads
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(load_document_results, doc_key): doc_key
            for doc_key in docs_to_load
        }

        for future in as_completed(futures):
            result = future.result()
            if result["success"]:
                comparison_results.extend(result["comparisons"])
                if result["weighted_score"] is not None:
                    doc_weighted_scores[result["doc_key"]] = result["weighted_score"]

    logger.info(
        f"Loaded {len(comparison_results)} comparison results for test run {test_run_id}"
    )
    logger.info(
        f"Loaded {len(doc_weighted_scores)} weighted scores for test run {test_run_id}"
    )
    return comparison_results, doc_weighted_scores


def _load_s3_json(s3_uri: str) -> Dict[str, Any]:
    """Load JSON content from S3 URI."""
    if not s3_uri.startswith("s3://"):
        raise ValueError(f"Invalid S3 URI: {s3_uri}")

    parts = s3_uri[5:].split("/", 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ""

    response = s3_client.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")
    return json.loads(content)


def _transform_stickler_metrics(
    process_eval,
    doc_weighted_scores: Dict[str, float],
    comparison_results: List[Dict[str, Any]],
    ecab_metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Transform Stickler ProcessEvaluation to IDP metrics format.

    Args:
        process_eval: ProcessEvaluation from Stickler
        doc_weighted_scores: Per-document weighted scores
        comparison_results: List of comparison results for confidence calculation
        ecab_metrics: ECARB confidence metrics from BulkStructuredModelEvaluator (optional)

    Returns:
        Dictionary matching existing IDP metrics format (without split metrics)
    """
    metrics = process_eval.metrics

    # Use Stickler's bulk confidence metrics (computed by aggregate_from_comparisons)
    # Stickler automatically aggregates prediction_confidences from comparison results
    confidence_metrics = process_eval.confidence_metrics
    average_confidence = None

    try:
        from idp_common.evaluation.confidence_integration import (
            get_average_confidence_from_metrics,
        )

        # R7: pattern-collapsed confidence metrics already computed by
        # ``_IndexCollapsingConfidenceAccumulator`` upstream — the caller
        # replaced ``process_eval.confidence_metrics`` before invoking us.
        # No post-pass enhancement required.

        # Merge ECARB (Error Capture at Review Budget) metrics from separate evaluation
        # ECARB requires custom confidence_metrics in BulkStructuredModelEvaluator
        if ecab_metrics and confidence_metrics:
            # Merge ECAB into overall metrics
            if (
                "overall" in ecab_metrics
                and "error_capture_at_budget" in ecab_metrics["overall"]
            ):
                if "overall" not in confidence_metrics:
                    confidence_metrics["overall"] = {}
                confidence_metrics["overall"]["error_capture_at_budget"] = ecab_metrics[
                    "overall"
                ]["error_capture_at_budget"]

            # Merge ECAB into per-field metrics
            if "fields" in ecab_metrics:
                if "fields" not in confidence_metrics:
                    confidence_metrics["fields"] = {}
                for field_name, field_ecab in ecab_metrics["fields"].items():
                    if "error_capture_at_budget" in field_ecab:
                        if field_name not in confidence_metrics["fields"]:
                            confidence_metrics["fields"][field_name] = {}
                        confidence_metrics["fields"][field_name][
                            "error_capture_at_budget"
                        ] = field_ecab["error_capture_at_budget"]

        if confidence_metrics and confidence_metrics.get("fields"):
            # Extract average confidence for backward compatibility
            average_confidence = get_average_confidence_from_metrics(confidence_metrics)

            # Log confidence metrics for debugging
            logger.info(
                f"Enhanced confidence metrics: "
                f"AUROC={confidence_metrics.get('overall', {}).get('auroc', {}).get('value')}, "
                f"ECE={confidence_metrics.get('overall', {}).get('ece', {}).get('value')}, "
                f"Brier={confidence_metrics.get('overall', {}).get('brier', {}).get('value')}, "
                f"avg_confidence={average_confidence}, "
                f"field_count={len(confidence_metrics.get('fields', {}))}"
            )

            # Log sample field names to verify structure
            sample_fields = list(confidence_metrics.get("fields", {}).keys())[:5]
            logger.info(f"Sample confidence field patterns: {sample_fields}")
        else:
            logger.warning("No confidence metrics returned by Stickler bulk aggregator")
            confidence_metrics = None

    except Exception as e:
        logger.warning(f"Error processing confidence metrics: {e}")
        confidence_metrics = None

    return {
        "overall_accuracy": metrics.get("cm_accuracy"),
        "weighted_overall_scores": doc_weighted_scores,
        "average_confidence": average_confidence,  # Now computed from Stickler if available
        "confidence_metrics": confidence_metrics,  # NEW: Full calibration metrics (v0.4.0+)
        "accuracy_breakdown": {
            "precision": metrics.get("cm_precision"),
            "recall": metrics.get("cm_recall"),
            "f1_score": metrics.get("cm_f1"),
            "false_alarm_rate": _calculate_false_alarm_rate(metrics),
            "false_discovery_rate": _calculate_false_discovery_rate(metrics),
        },
        "confusion_matrix": {
            "tp": metrics.get("tp", 0),
            "fp": metrics.get("fp", 0),
            "tn": metrics.get("tn", 0),
            "fn": metrics.get("fn", 0),
            "fa": metrics.get("fa", 0),
            "fd": metrics.get("fd", 0),
        },
        "field_metrics": process_eval.field_metrics,
        "document_count": process_eval.document_count,
        "total_time": process_eval.total_time,
    }


def _calculate_false_alarm_rate(metrics: Dict[str, Any]) -> Optional[float]:
    """Calculate false alarm rate (FP / (FP + TN))."""
    fp = metrics.get("fp", 0)
    tn = metrics.get("tn", 0)
    return fp / (fp + tn) if (fp + tn) > 0 else None


def _calculate_false_discovery_rate(metrics: Dict[str, Any]) -> Optional[float]:
    """Calculate false discovery rate (FP / (FP + TP))."""
    fp = metrics.get("fp", 0)
    tp = metrics.get("tp", 0)
    return fp / (fp + tp) if (fp + tp) > 0 else None


class _IndexCollapsingConfidenceAccumulator:
    """R7: ``ConfidenceAccumulator`` subclass that collapses list-index paths
    before Stickler's ``ConfidenceCalculator`` sees them.

    Stickler's ``ConfidenceAccumulator`` keys pairs by the raw field path —
    which means for a Hungarian-matched array, ``LineItems[0].Rate``,
    ``LineItems[1].Rate``, ``LineItems[2].Rate`` are three separate entries
    with sample-sizes of 1 each. Downstream metrics (AUROC, ECE, Brier) can't
    be computed on N=1 series and the report either omits the field or fills
    it with nulls.

    This subclass rewrites every occurrence of ``[digits]`` to nothing before
    feeding the extractor, aggregating all indices at a single pattern-based
    key (``LineItems.Rate``). One pass over ``comparison_results``, all
    Stickler-native math. Replaces the previous scikit-learn-based post-pass
    (``_enhance_confidence_metrics_with_patterns``) that ran outside the
    accumulator pipeline entirely.
    """

    _INDEX_RE = re.compile(r"\[\d+\]")
    name = "confidence_metrics"

    def __init__(self, metrics=None):
        # Lazy-import Stickler so the module still parses when stickler-eval
        # isn't installed (defensive — Lambda always has it).
        from stickler.structured_object_evaluator.models.confidence.calculator import (
            ConfidenceCalculator,
        )

        self._calculator = ConfidenceCalculator(metrics=metrics)
        self.reset()

    def reset(self):
        self._keyed_pairs: Dict[str, list] = {}
        self._fields_with = 0
        self._fields_total = 0

    @classmethod
    def _collapse(cls, key: str) -> str:
        """LineItems[0].Rate -> LineItems.Rate — strip every ``[digits]``."""
        return cls._INDEX_RE.sub("", key)

    def accumulate(self, comparison_result, prediction_raw):
        """Rewrite indexed paths to pattern keys, then delegate to Stickler.

        Mirrors the built-in ``ConfidenceAccumulator.accumulate`` layout so any
        upstream refactor of the base class is a merge-conflict signal rather
        than silent drift.
        """
        field_comparisons = comparison_result.get("field_comparisons", []) or []
        if not field_comparisons:
            return

        # Feed raw indexed keys through extract_from_dicts (which joins each
        # comparison's actual_key against the confidences dict — 1:1 match).
        # Then collapse the resulting ``keyed_pairs`` into pattern buckets
        # afterwards so all indices at ``LineItems[N].Rate`` land under a
        # single ``LineItems.Rate`` pattern for AUROC/ECE/Brier computation
        # over the full sample.
        confidences = comparison_result.get("prediction_confidences") or {}
        extraction = self._calculator.extract_from_dicts(field_comparisons, confidences)

        if confidences:
            for field_path, pairs in extraction.keyed_pairs.items():
                pattern_key = (
                    self._collapse(field_path)
                    if isinstance(field_path, str)
                    else field_path
                )
                self._keyed_pairs.setdefault(pattern_key, []).extend(pairs)

        self._fields_with += extraction.fields_with_confidence
        self._fields_total += extraction.fields_total

    def compute(self):
        if self._fields_total == 0:
            return None
        return self._calculator.compute_metrics(
            self._keyed_pairs,
            fields_with_confidence=self._fields_with,
            fields_total=self._fields_total,
        )

    def get_state(self) -> Dict[str, Any]:
        return {
            "keyed_confidence_pairs": {
                field_path: [p.model_dump() for p in pairs]
                for field_path, pairs in self._keyed_pairs.items()
            },
            "confidence_fields_with": self._fields_with,
            "confidence_fields_total": self._fields_total,
        }

    def load_state(self, state: Dict[str, Any]) -> None:
        from stickler.structured_object_evaluator.models.confidence.metrics import (
            ConfidencePair,
        )

        self._keyed_pairs = {
            field_path: [ConfidencePair(**p) for p in pairs]
            for field_path, pairs in state.get("keyed_confidence_pairs", {}).items()
        }
        self._fields_with = state.get("confidence_fields_with", 0)
        self._fields_total = state.get("confidence_fields_total", 0)

    def merge_state(self, other_state: Dict[str, Any]) -> None:
        from stickler.structured_object_evaluator.models.confidence.metrics import (
            ConfidencePair,
        )

        for field_path, pairs in other_state.get("keyed_confidence_pairs", {}).items():
            self._keyed_pairs.setdefault(field_path, []).extend(
                [ConfidencePair(**p) for p in pairs]
            )
        self._fields_with += other_state.get("confidence_fields_with", 0)
        self._fields_total += other_state.get("confidence_fields_total", 0)


def _empty_metrics() -> Dict[str, Any]:
    """Return empty metrics structure."""
    return {
        "overall_accuracy": None,
        "weighted_overall_scores": {},
        "average_confidence": None,
        "accuracy_breakdown": {
            "precision": None,
            "recall": None,
            "f1_score": None,
            "false_alarm_rate": None,
            "false_discovery_rate": None,
        },
        "split_classification_metrics": {},
        "document_count": 0,
        "total_time": 0,
    }
