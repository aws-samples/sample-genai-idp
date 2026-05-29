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
            aggregate_from_comparisons,
            BulkStructuredModelEvaluator,
        )
        from stickler.structured_object_evaluator.models.confidence import (
            ErrorCaptureAtBudgetMetric,
        )

        process_eval = aggregate_from_comparisons(comparison_results)

        logger.info(
            f"Stickler aggregation complete: document_count={process_eval.document_count}, comparison_results={len(comparison_results)}, weighted_scores={len(doc_weighted_scores)}"
        )

        # Compute ECARB (Error Capture at Review Budget) metrics using BulkStructuredModelEvaluator
        # This is "the business metric" - answers: if you review X% of data (sorted by
        # confidence), how many errors do you catch vs random sampling?
        ecab_metrics = None
        try:
            evaluator = BulkStructuredModelEvaluator(
                confidence_metrics=[
                    ErrorCaptureAtBudgetMetric(budgets=[0.30]),
                ]
            )

            # Feed comparison results using JSONL round-trip pattern
            for comp_result in comparison_results:
                evaluator.update_from_comparison_result(comp_result)

            ecab_result = evaluator.compute()
            ecab_metrics = ecab_result.confidence_metrics

            if ecab_metrics and "overall" in ecab_metrics:
                ecab_30 = (
                    ecab_metrics.get("overall", {})
                    .get("error_capture_at_budget", {})
                    .get("budgets", {})
                    .get("0.30", {})
                )
                if ecab_30:
                    logger.info(
                        f"ECARB@30: catch {ecab_30.get('pct_errors_caught', 0)*100:.0f}% "
                        f"of errors with {ecab_30.get('gain', 0):.1f}x gain vs random"
                    )
        except Exception as e:
            logger.warning(f"Failed to compute ECAB metrics: {e}", exc_info=True)

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
                "success": True
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

        # Enhance confidence metrics with pattern-based nested field aggregation
        # Stickler only generates confidence metrics for top-level/scalar fields
        # This adds pattern-based metrics for nested array fields (e.g., LineItems.Rate)
        confidence_metrics = _enhance_confidence_metrics_with_patterns(
            confidence_metrics, comparison_results, process_eval.field_metrics
        )

        # Merge ECARB (Error Capture at Review Budget) metrics from separate evaluation
        # ECARB requires custom confidence_metrics in BulkStructuredModelEvaluator
        if ecab_metrics and confidence_metrics:
            # Merge ECAB into overall metrics
            if "overall" in ecab_metrics and "error_capture_at_budget" in ecab_metrics["overall"]:
                if "overall" not in confidence_metrics:
                    confidence_metrics["overall"] = {}
                confidence_metrics["overall"]["error_capture_at_budget"] = ecab_metrics["overall"]["error_capture_at_budget"]

            # Merge ECAB into per-field metrics
            if "fields" in ecab_metrics:
                if "fields" not in confidence_metrics:
                    confidence_metrics["fields"] = {}
                for field_name, field_ecab in ecab_metrics["fields"].items():
                    if "error_capture_at_budget" in field_ecab:
                        if field_name not in confidence_metrics["fields"]:
                            confidence_metrics["fields"][field_name] = {}
                        confidence_metrics["fields"][field_name]["error_capture_at_budget"] = field_ecab["error_capture_at_budget"]

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


def _enhance_confidence_metrics_with_patterns(
    confidence_metrics: Optional[Dict[str, Any]],
    comparison_results: List[Dict[str, Any]],
    field_metrics: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Enhance Stickler's confidence_metrics with pattern-based nested field aggregation.

    Stickler's bulk aggregator only generates confidence metrics for scalar/top-level fields.
    This function aggregates path-based confidence keys (e.g., LineItems[0].Rate, LineItems[1].Rate)
    into pattern-based keys (e.g., LineItems.Rate) to match field_metrics format.

    Args:
        confidence_metrics: Stickler's confidence_metrics (may be None or missing nested fields)
        comparison_results: List of comparison results with prediction_confidences
        field_metrics: Stickler's field_metrics for reference (pattern-based keys)

    Returns:
        Enhanced confidence_metrics with pattern-based nested field metrics, or None if no data
    """
    if not comparison_results or not field_metrics:
        return confidence_metrics

    try:
        from collections import defaultdict

        # Initialize confidence_metrics if None
        if confidence_metrics is None:
            confidence_metrics = {
                "overall": {},
                "fields": {},
                "coverage": {
                    "fields_with_confidence": 0,
                    "fields_total": 0,
                    "ratio": 0.0,
                },
            }

        # Extract field_metrics keys to know what patterns we need
        field_pattern_keys = set(field_metrics.keys())

        # Collect confidence values and match results by pattern
        # Pattern: LineItems[0].Rate -> LineItems.Rate
        pattern_data = defaultdict(lambda: {"confidences": [], "matches": []})

        for comp_result in comparison_results:
            pred_confidences = comp_result.get("prediction_confidences", {})
            field_comparisons = comp_result.get("field_comparisons", [])

            # Build a map of field paths to match results
            match_map = {}
            for fc in field_comparisons:
                field_path = fc.get("field_path") or fc.get("expected_key", "")
                match_map[field_path] = fc.get("match", False)

            # Process each confidence value
            for path_key, conf_value in pred_confidences.items():
                # Convert path-based key to pattern-based key
                # LineItems[0].Rate -> LineItems.Rate
                # LineItems[1].Description -> LineItems.Description
                pattern_key = re.sub(r"\[\d+\]", "", path_key)

                # Only aggregate if this pattern exists in field_metrics
                if pattern_key in field_pattern_keys:
                    # Find match result for this path
                    # Try exact match first, then try parent object match
                    matched = match_map.get(path_key)
                    if matched is None:
                        # Try parent object (e.g., LineItems[0] for LineItems[0].Rate)
                        parent_path = (
                            path_key.rsplit(".", 1)[0] if "." in path_key else path_key
                        )
                        matched = match_map.get(parent_path, False)

                    pattern_data[pattern_key]["confidences"].append(conf_value)
                    pattern_data[pattern_key]["matches"].append(bool(matched))

        # Compute calibration metrics for each pattern
        # IMPORTANT: We re-compute metrics on the combined (confidence, match) pairs,
        # NOT by averaging pre-computed metrics. This is mathematically correct because
        # AUROC, ECE, and Brier are not linearly aggregable.
        fields = confidence_metrics.get("fields", {})

        for pattern_key, data in pattern_data.items():
            confidences = data["confidences"]
            matches = data["matches"]

            if len(confidences) < 2:
                # Need at least 2 samples for calibration metrics
                continue

            # Compute AUROC and Brier on combined raw data (mathematically correct)
            try:
                from sklearn.metrics import roc_auc_score, brier_score_loss

                # Check if we have both classes
                if len(set(matches)) > 1:
                    auroc = roc_auc_score(matches, confidences)
                else:
                    auroc = None  # Can't compute AUROC with single class

                # Brier score (lower is better, range 0-1)
                brier = brier_score_loss(matches, confidences)

                # Add to fields
                if pattern_key not in fields:
                    fields[pattern_key] = {}

                fields[pattern_key]["auroc"] = {"value": auroc}
                fields[pattern_key]["brier"] = {"value": brier}
                fields[pattern_key]["sample_count"] = len(confidences)
                fields[pattern_key]["mean_confidence"] = sum(confidences) / len(
                    confidences
                )

                logger.debug(
                    f"Pattern {pattern_key}: AUROC={auroc}, Brier={brier}, "
                    f"samples={len(confidences)}"
                )

            except Exception as e:
                logger.warning(
                    f"Failed to compute metrics for pattern {pattern_key}: {e}"
                )
                continue

        # Update coverage
        # Only count pattern-based keys (not index-based like LineItems[0].Rate)
        # Pattern-based keys don't have [digits] in them
        pattern_based_fields = {
            k: v
            for k, v in fields.items()
            if not re.search(r"\[\d+\]", k)  # Exclude index-based keys
        }

        total_patterns_with_conf = len(
            [f for f in pattern_based_fields.values() if f.get("auroc")]
        )
        total_patterns = len(field_pattern_keys)

        confidence_metrics["fields"] = fields
        confidence_metrics["coverage"] = {
            "fields_with_confidence": total_patterns_with_conf,
            "fields_total": total_patterns,
            "ratio": total_patterns_with_conf / total_patterns
            if total_patterns > 0
            else 0.0,
        }

        logger.info(
            f"Enhanced confidence metrics: {total_patterns_with_conf}/{total_patterns} "
            f"patterns with confidence"
        )

        return confidence_metrics

    except Exception as e:
        logger.error(f"Failed to enhance confidence metrics: {e}", exc_info=True)
        return confidence_metrics  # Return original if enhancement fails


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
