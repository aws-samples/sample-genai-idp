# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for test_execution_aggregation_function Lambda.
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Add the function path to sys.path
FUNCTION_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "../../../../patterns/unified/src/test_execution_aggregation_function",
    )
)


def import_test_module():
    """Import the test_execution_aggregation index module."""
    if FUNCTION_PATH not in sys.path:
        sys.path.insert(0, FUNCTION_PATH)

    # Remove any cached index module
    if "index" in sys.modules:
        del sys.modules["index"]

    import index

    return index


@pytest.fixture
def mock_env():
    """Mock environment variables."""
    with patch.dict(
        os.environ,
        {
            "TRACKING_TABLE": "test-tracking-table",
            "LOG_LEVEL": "INFO",
            "OUTPUT_BUCKET": "test-output-bucket",
        },
    ):
        yield


@pytest.fixture
def lambda_context():
    """Mock Lambda context."""
    context = MagicMock()
    context.function_name = "test-function"
    context.invoked_function_arn = (
        "arn:aws:lambda:us-west-2:123456789012:function:test-function"
    )
    return context


@pytest.fixture
def mock_dynamodb_table():
    """Mock DynamoDB table."""
    table = MagicMock()
    table.scan.return_value = {
        "Items": [
            {
                "PK": "doc#test-run-123#doc1.pdf",
                "ObjectKey": "doc1.pdf",
                "EvaluationStatus": "COMPLETED",
                "EvaluationReportUri": "s3://bucket/doc1.pdf/evaluation/report.md",
            },
            {
                "PK": "doc#test-run-123#doc2.pdf",
                "ObjectKey": "doc2.pdf",
                "EvaluationStatus": "COMPLETED",
                "EvaluationReportUri": "s3://bucket/doc2.pdf/evaluation/report.md",
            },
        ]
    }
    return table


@pytest.fixture
def mock_s3_results():
    """Mock S3 evaluation results."""
    return {
        "overall_metrics": {"weighted_overall_score": 0.95},
        "section_results": [
            {
                "section_id": "1",
                "stickler_comparison_result": {
                    "tp": 10,
                    "fp": 1,
                    "tn": 5,
                    "fn": 2,
                },
            }
        ],
    }


@pytest.mark.unit
class TestHandler:
    """Tests for Lambda handler function."""

    def test_handler_success(self, mock_env, lambda_context):
        """Test successful handler execution."""
        index = import_test_module()

        event = {"test_run_id": "test-run-123"}

        with patch.object(index, "aggregate_test_run_with_stickler") as mock_aggregate:
            mock_aggregate.return_value = {
                "overall_accuracy": 0.85,
                "document_count": 2,
            }

            response = index.handler(event, lambda_context)

            assert response["statusCode"] == 200
            body = json.loads(response["body"])
            assert body["overall_accuracy"] == 0.85
            assert body["document_count"] == 2
            mock_aggregate.assert_called_once_with(
                "test-run-123", "test-tracking-table"
            )

    def test_handler_missing_test_run_id(self, mock_env, lambda_context):
        """Test handler with missing test_run_id."""
        index = import_test_module()

        event = {}

        response = index.handler(event, lambda_context)

        assert response["statusCode"] == 500
        body = json.loads(response["body"])
        assert "error" in body
        assert "test_run_id" in body["error"]

    def test_handler_aggregation_error(self, mock_env, lambda_context):
        """Test handler when aggregation fails."""
        index = import_test_module()

        event = {"test_run_id": "test-run-123"}

        with patch.object(index, "aggregate_test_run_with_stickler") as mock_aggregate:
            mock_aggregate.side_effect = Exception("DynamoDB error")

            response = index.handler(event, lambda_context)

            assert response["statusCode"] == 500
            body = json.loads(response["body"])
            assert "error" in body
            assert "DynamoDB error" in body["error"]


@pytest.mark.unit
class TestAggregation:
    """Tests for aggregation logic."""

    def test_load_comparison_results(
        self, mock_env, mock_dynamodb_table, mock_s3_results
    ):
        """Test loading comparison results from DynamoDB and S3."""
        index = import_test_module()

        with patch.object(index, "dynamodb") as mock_dynamodb:
            mock_dynamodb.Table.return_value = mock_dynamodb_table
            with patch.object(index, "_load_s3_json") as mock_load_s3:
                mock_load_s3.return_value = mock_s3_results

                results, scores = index._load_comparison_results(
                    "test-run-123", "test-table"
                )

                assert len(results) == 2  # Two documents with stickler results
                assert len(scores) == 2  # Two weighted scores
                assert "doc1.pdf" in scores
                assert "doc2.pdf" in scores
                assert scores["doc1.pdf"] == 0.95

    def test_load_comparison_results_skips_incomplete(self, mock_env):
        """Test that incomplete evaluations are skipped."""
        index = import_test_module()

        incomplete_table = MagicMock()
        incomplete_table.scan.return_value = {
            "Items": [
                {
                    "PK": "doc#test-run-123#doc1.pdf",
                    "ObjectKey": "doc1.pdf",
                    "EvaluationStatus": "RUNNING",  # Not completed
                    "EvaluationReportUri": "s3://bucket/doc1.pdf/evaluation/report.md",
                }
            ]
        }

        with patch.object(index, "dynamodb") as mock_dynamodb:
            mock_dynamodb.Table.return_value = incomplete_table

            results, scores = index._load_comparison_results(
                "test-run-123", "test-table"
            )

            assert len(results) == 0
            assert len(scores) == 0

    def test_empty_metrics(self, mock_env):
        """Test empty metrics structure."""
        index = import_test_module()

        metrics = index._empty_metrics()

        assert metrics["overall_accuracy"] is None
        assert metrics["weighted_overall_scores"] == {}
        assert metrics["average_confidence"] is None
        assert metrics["document_count"] == 0
        assert "accuracy_breakdown" in metrics

    def test_calculate_false_alarm_rate(self, mock_env):
        """Test false alarm rate calculation.

        FAR = FA / (FA + TN), using Stickler's false-alarm count rather than the
        combined ``fp``. Since ``fp == fa + fd``, using ``fp`` here would fold
        false discoveries into the false-alarm rate.
        """
        index = import_test_module()

        # FA / (FA + TN) — fd present and must NOT contribute.
        metrics = {"fa": 2, "fd": 5, "fp": 7, "tn": 8}
        rate = index._calculate_false_alarm_rate(metrics)
        assert rate == 0.2  # 2 / (2 + 8), not 7 / (7 + 8)

        # Zero denominator
        metrics = {"fa": 0, "tn": 0}
        rate = index._calculate_false_alarm_rate(metrics)
        assert rate is None

    def test_calculate_false_discovery_rate(self, mock_env):
        """Test false discovery rate calculation.

        FDR = FD / (FD + TP), using Stickler's false-discovery count rather than
        the combined ``fp`` (see ``test_calculate_false_alarm_rate``).
        """
        index = import_test_module()

        # FD / (FD + TP) — fa present and must NOT contribute.
        metrics = {"fd": 3, "fa": 4, "fp": 7, "tp": 7}
        rate = index._calculate_false_discovery_rate(metrics)
        assert rate == 0.3  # 3 / (3 + 7), not 7 / (7 + 7)

        # Zero denominator
        metrics = {"fd": 0, "tp": 0}
        rate = index._calculate_false_discovery_rate(metrics)
        assert rate is None

    def test_far_fdr_match_per_doc_evaluation_service_formulas(self, mock_env):
        """Run-level FAR/FDR must equal the per-doc formulas on the same counts.

        The per-doc path
        (``idp_common.evaluation.stickler_backend.results.transform_stickler_result``)
        derives FAR from ``fa``/``tn`` and FDR from ``fd``/``tp``. This Lambda
        previously used the combined ``fp`` for both, so the per-document detail
        view and the run-level dashboard reported different error rates for the
        same document whenever both ``fa`` and ``fd`` were non-zero. Pin the
        agreement so the two paths can't drift apart again.
        """
        index = import_test_module()

        # Counts with BOTH error classes present — the case where fp-based and
        # fa/fd-based formulas diverge. Respects Stickler's fp == fa + fd.
        counts = {"tp": 5, "fa": 2, "fd": 3, "fp": 5, "tn": 4, "fn": 1}

        # Per-doc formulas, transcribed from stickler_backend/results.py.
        expected_far = counts["fa"] / (counts["fa"] + counts["tn"])
        expected_fdr = counts["fd"] / (counts["fd"] + counts["tp"])

        assert index._calculate_false_alarm_rate(counts) == pytest.approx(expected_far)
        assert index._calculate_false_discovery_rate(counts) == pytest.approx(
            expected_fdr
        )

        # And confirm the old fp-based formulas really would have disagreed,
        # so this test fails loudly if someone reverts to them.
        assert expected_far != pytest.approx(
            counts["fp"] / (counts["fp"] + counts["tn"])
        )
        assert expected_fdr != pytest.approx(
            counts["fp"] / (counts["fp"] + counts["tp"])
        )

    def test_load_s3_json(self, mock_env):
        """Test loading JSON from S3."""
        index = import_test_module()

        mock_response = {"Body": MagicMock()}
        mock_response["Body"].read.return_value = b'{"key": "value"}'

        with patch.object(index, "s3_client") as mock_s3:
            mock_s3.get_object.return_value = mock_response

            result = index._load_s3_json("s3://test-bucket/test-key.json")

            assert result == {"key": "value"}
            mock_s3.get_object.assert_called_once_with(
                Bucket="test-bucket", Key="test-key.json"
            )

    def test_load_s3_json_invalid_uri(self, mock_env):
        """Test loading JSON with invalid S3 URI."""
        index = import_test_module()

        with pytest.raises(ValueError, match="Invalid S3 URI"):
            index._load_s3_json("http://example.com/file.json")

    def test_stickler_bulk_confidence_aggregation(self, mock_env):
        """
        Test that Stickler bulk aggregator correctly processes prediction_confidences.

        This validates the complete flow:
        1. Multiple documents with prediction_confidences in comparison results
        2. Stickler's aggregate_from_comparisons() processes them
        3. process_eval.confidence_metrics contains pattern-based aggregated metrics
        """
        # Create comparison results matching our S3 format (with prediction_confidences from Rich Value Pattern)
        comparison_results = [
            # Document 1
            {
                "field_comparisons": [
                    {
                        "field_path": "Agency",
                        "expected_key": "Agency",
                        "actual_key": "Agency",
                        "match": True,
                        "score": 1.0,
                    },
                    {
                        "field_path": "LineItems[0].Rate",
                        "expected_key": "LineItems[0].Rate",
                        "actual_key": "LineItems[0].Rate",
                        "match": True,
                        "score": 1.0,
                    },
                    {
                        "field_path": "LineItems[1].Rate",
                        "expected_key": "LineItems[1].Rate",
                        "actual_key": "LineItems[1].Rate",
                        "match": False,
                        "score": 0.8,
                    },
                ],
                "prediction_confidences": {
                    "Agency": 0.99,
                    "LineItems[0].Rate": 0.95,
                    "LineItems[1].Rate": 0.92,
                },
                "confusion_matrix": {"tp": 2, "fp": 0, "tn": 0, "fn": 1},
                "overall_score": 0.85,
            },
            # Document 2
            {
                "field_comparisons": [
                    {
                        "field_path": "Agency",
                        "expected_key": "Agency",
                        "actual_key": "Agency",
                        "match": True,
                        "score": 1.0,
                    },
                    {
                        "field_path": "LineItems[0].Rate",
                        "expected_key": "LineItems[0].Rate",
                        "actual_key": "LineItems[0].Rate",
                        "match": False,
                        "score": 0.7,
                    },
                    {
                        "field_path": "LineItems[1].Rate",
                        "expected_key": "LineItems[1].Rate",
                        "actual_key": "LineItems[1].Rate",
                        "match": True,
                        "score": 1.0,
                    },
                ],
                "prediction_confidences": {
                    "Agency": 0.97,
                    "LineItems[0].Rate": 0.88,
                    "LineItems[1].Rate": 0.94,
                },
                "confusion_matrix": {"tp": 2, "fp": 0, "tn": 0, "fn": 1},
                "overall_score": 0.82,
            },
        ]

        # Import Stickler and test aggregation
        from stickler.structured_object_evaluator.bulk_structured_model_evaluator import (
            aggregate_from_comparisons,
        )

        process_eval = aggregate_from_comparisons(comparison_results)

        # Validate that confidence_metrics exists
        assert process_eval.confidence_metrics is not None, (
            "Stickler should return confidence_metrics"
        )

        # Validate structure
        confidence_metrics = process_eval.confidence_metrics
        assert "overall" in confidence_metrics
        assert "fields" in confidence_metrics
        assert "coverage" in confidence_metrics

        # Validate what Stickler actually returns
        fields = confidence_metrics.get("fields", {})

        # Stickler returns PATH-BASED keys (with array indices), not pattern-based
        # This is expected behavior - Stickler doesn't do pattern aggregation
        assert "Agency" in fields, "Should have Agency field"
        assert "LineItems[0].Rate" in fields, (
            "Should have LineItems[0].Rate (path-based)"
        )
        assert "LineItems[1].Rate" in fields, (
            "Should have LineItems[1].Rate (path-based)"
        )

        # Validate metrics structure (Stickler's default metrics may vary)
        agency_metrics = fields["Agency"]
        assert "auroc" in agency_metrics, "Should have AUROC metric"
        # Note: ECE/Brier may not be present unless explicitly configured

        # Validate LineItems metrics
        line_item_0_metrics = fields["LineItems[0].Rate"]
        assert "auroc" in line_item_0_metrics, "Should have AUROC metric"

        # Validate coverage tracking
        coverage = confidence_metrics.get("coverage", {})
        assert coverage.get("fields_with_confidence", 0) > 0, (
            "Should track fields with confidence"
        )
        assert coverage.get("fields_total", 0) > 0, "Should track total fields"

        # Check overall metrics exist
        overall = confidence_metrics.get("overall", {})
        assert overall is not None, "Should have overall metrics"

        # Check what field_metrics contains (for accuracy)
        field_metrics = process_eval.field_metrics
        if field_metrics:
            field_metrics_keys = list(field_metrics.keys())
            print("\n=== ACCURACY field_metrics ===")
            print(f"   - Keys: {field_metrics_keys[:5]}")
        else:
            print("\n=== ACCURACY field_metrics ===")
            print("   - ❌ Empty (may need schema/configuration)")

        print("\n=== CONFIDENCE confidence_metrics ===")
        print(f"   - Fields (path-based): {list(fields.keys())}")
        print(
            f"   - Coverage: {coverage.get('fields_with_confidence')}/{coverage.get('fields_total')}"
        )
        print(f"   - Overall AUROC: {overall.get('auroc', {}).get('value')}")

        # Compare key formats
        if field_metrics:
            fm_sample = (
                list(field_metrics.keys())[1]
                if len(field_metrics) > 1
                else list(field_metrics.keys())[0]
            )
            cm_sample = (
                list(fields.keys())[1] if len(fields) > 1 else list(fields.keys())[0]
            )
            print("\n=== KEY FORMAT ===")
            print(f"   field_metrics:      {fm_sample}")
            print(f"   confidence_metrics: {cm_sample}")
            print(f"   Same format: {fm_sample == cm_sample}")
        else:
            print("\n⚠️  NOTE: field_metrics is empty, can't compare formats")
            print(
                "   UI expects confidence_metrics.fields keys to match field_metrics keys"
            )
            print("   Both should use the SAME format (path-based or pattern-based)")

        print(
            f"\n✅ Test passed: Stickler returns confidence_metrics with {len(fields)} fields"
        )

    def test_pattern_aggregation_enhancement(self, mock_env):
        """
        Test that pattern aggregation collapses list-indexed confidence paths
        into pattern keys and computes standard Stickler calibration metrics
        on the pooled sample.

        R7 replaced the old sklearn-based ``_enhance_confidence_metrics_with_patterns``
        post-pass with ``_IndexCollapsingConfidenceAccumulator``. This test
        drives the new accumulator directly (which is what the aggregation
        Lambda's ``BulkStructuredModelEvaluator`` does internally).

        This validates:
        1. Path-based keys (``LineItems[0].Rate``, ``LineItems[1].Rate``) get
           aggregated to the pattern key (``LineItems.Rate``).
        2. AUROC / Brier / ECE are computed on the pooled per-pattern sample.
        3. Sample counts are correct (all indices across all docs land in one
           bucket).
        """
        index = import_test_module()
        from stickler.structured_object_evaluator.models.confidence import (
            AUROCMetric,
            BrierScoreMetric,
            ECEMetric,
        )

        # Create comparison results with nested array fields
        comparison_results = [
            # Document 1: 2 line items
            {
                "field_comparisons": [
                    {"field_path": "Agency", "expected_key": "Agency", "match": True},
                    {
                        "field_path": "LineItems[0]",
                        "expected_key": "LineItems[0]",
                        "match": True,
                    },
                    {
                        "field_path": "LineItems[1]",
                        "expected_key": "LineItems[1]",
                        "match": False,
                    },
                ],
                "prediction_confidences": {
                    "Agency": 0.99,
                    "LineItems[0].Rate": 0.95,  # Match=True (high confidence, correct)
                    "LineItems[1].Rate": 0.92,  # Match=False (high confidence, wrong)
                },
                "confusion_matrix": {"tp": 2, "fp": 0, "tn": 0, "fn": 1},
                "overall_score": 0.85,
            },
            # Document 2: 3 line items
            {
                "field_comparisons": [
                    {"field_path": "Agency", "expected_key": "Agency", "match": True},
                    {
                        "field_path": "LineItems[0]",
                        "expected_key": "LineItems[0]",
                        "match": False,
                    },
                    {
                        "field_path": "LineItems[1]",
                        "expected_key": "LineItems[1]",
                        "match": True,
                    },
                    {
                        "field_path": "LineItems[2]",
                        "expected_key": "LineItems[2]",
                        "match": True,
                    },
                ],
                "prediction_confidences": {
                    "Agency": 0.97,
                    "LineItems[0].Rate": 0.88,  # Match=False (lower confidence, wrong)
                    "LineItems[1].Rate": 0.94,  # Match=True (high confidence, correct)
                    "LineItems[2].Rate": 0.91,  # Match=True (high confidence, correct)
                },
                "confusion_matrix": {"tp": 3, "fp": 0, "tn": 0, "fn": 1},
                "overall_score": 0.82,
            },
            # Document 3: 1 line item
            {
                "field_comparisons": [
                    {"field_path": "Agency", "expected_key": "Agency", "match": True},
                    {
                        "field_path": "LineItems[0]",
                        "expected_key": "LineItems[0]",
                        "match": True,
                    },
                ],
                "prediction_confidences": {
                    "Agency": 0.98,
                    "LineItems[0].Rate": 0.97,  # Match=True (high confidence, correct)
                },
                "confusion_matrix": {"tp": 2, "fp": 0, "tn": 0, "fn": 0},
                "overall_score": 0.95,
            },
            # Document 4: 2 line items
            {
                "field_comparisons": [
                    {"field_path": "Agency", "expected_key": "Agency", "match": True},
                    {
                        "field_path": "LineItems[0]",
                        "expected_key": "LineItems[0]",
                        "match": True,
                    },
                    {
                        "field_path": "LineItems[1]",
                        "expected_key": "LineItems[1]",
                        "match": False,
                    },
                ],
                "prediction_confidences": {
                    "Agency": 0.96,
                    "LineItems[0].Rate": 0.89,
                    "LineItems[1].Rate": 0.65,  # Match=False (low confidence, wrong)
                },
                "confusion_matrix": {"tp": 2, "fp": 0, "tn": 0, "fn": 1},
                "overall_score": 0.75,
            },
            # Document 5: 2 line items
            {
                "field_comparisons": [
                    {"field_path": "Agency", "expected_key": "Agency", "match": True},
                    {
                        "field_path": "LineItems[0]",
                        "expected_key": "LineItems[0]",
                        "match": True,
                    },
                    {
                        "field_path": "LineItems[1]",
                        "expected_key": "LineItems[1]",
                        "match": True,
                    },
                ],
                "prediction_confidences": {
                    "Agency": 0.99,
                    "LineItems[0].Rate": 0.93,
                    "LineItems[1].Rate": 0.90,
                },
                "confusion_matrix": {"tp": 3, "fp": 0, "tn": 0, "fn": 0},
                "overall_score": 0.92,
            },
            # Document 6: 3 line items
            {
                "field_comparisons": [
                    {"field_path": "Agency", "expected_key": "Agency", "match": True},
                    {
                        "field_path": "LineItems[0]",
                        "expected_key": "LineItems[0]",
                        "match": False,
                    },
                    {
                        "field_path": "LineItems[1]",
                        "expected_key": "LineItems[1]",
                        "match": True,
                    },
                    {
                        "field_path": "LineItems[2]",
                        "expected_key": "LineItems[2]",
                        "match": True,
                    },
                ],
                "prediction_confidences": {
                    "Agency": 0.95,
                    "LineItems[0].Rate": 0.72,  # Match=False (medium confidence, wrong)
                    "LineItems[1].Rate": 0.96,
                    "LineItems[2].Rate": 0.88,
                },
                "confusion_matrix": {"tp": 3, "fp": 0, "tn": 0, "fn": 1},
                "overall_score": 0.80,
            },
            # Document 7: 2 line items
            {
                "field_comparisons": [
                    {"field_path": "Agency", "expected_key": "Agency", "match": True},
                    {
                        "field_path": "LineItems[0]",
                        "expected_key": "LineItems[0]",
                        "match": True,
                    },
                    {
                        "field_path": "LineItems[1]",
                        "expected_key": "LineItems[1]",
                        "match": False,
                    },
                ],
                "prediction_confidences": {
                    "Agency": 0.97,
                    "LineItems[0].Rate": 0.94,
                    "LineItems[1].Rate": 0.68,  # Match=False (low confidence, wrong)
                },
                "confusion_matrix": {"tp": 2, "fp": 0, "tn": 0, "fn": 1},
                "overall_score": 0.78,
            },
            # Document 8: 1 line item
            {
                "field_comparisons": [
                    {"field_path": "Agency", "expected_key": "Agency", "match": True},
                    {
                        "field_path": "LineItems[0]",
                        "expected_key": "LineItems[0]",
                        "match": True,
                    },
                ],
                "prediction_confidences": {
                    "Agency": 0.98,
                    "LineItems[0].Rate": 0.91,
                },
                "confusion_matrix": {"tp": 2, "fp": 0, "tn": 0, "fn": 0},
                "overall_score": 0.93,
            },
            # Document 9: 2 line items
            {
                "field_comparisons": [
                    {"field_path": "Agency", "expected_key": "Agency", "match": True},
                    {
                        "field_path": "LineItems[0]",
                        "expected_key": "LineItems[0]",
                        "match": True,
                    },
                    {
                        "field_path": "LineItems[1]",
                        "expected_key": "LineItems[1]",
                        "match": True,
                    },
                ],
                "prediction_confidences": {
                    "Agency": 0.96,
                    "LineItems[0].Rate": 0.87,
                    "LineItems[1].Rate": 0.92,
                },
                "confusion_matrix": {"tp": 3, "fp": 0, "tn": 0, "fn": 0},
                "overall_score": 0.89,
            },
            # Document 10: 2 line items
            {
                "field_comparisons": [
                    {"field_path": "Agency", "expected_key": "Agency", "match": True},
                    {
                        "field_path": "LineItems[0]",
                        "expected_key": "LineItems[0]",
                        "match": False,
                    },
                    {
                        "field_path": "LineItems[1]",
                        "expected_key": "LineItems[1]",
                        "match": True,
                    },
                ],
                "prediction_confidences": {
                    "Agency": 0.94,
                    "LineItems[0].Rate": 0.58,  # Match=False (very low confidence, wrong)
                    "LineItems[1].Rate": 0.95,
                },
                "confusion_matrix": {"tp": 2, "fp": 0, "tn": 0, "fn": 1},
                "overall_score": 0.73,
            },
        ]

        # Reshape the fixture so field_comparisons carry the leaf-level
        # ``actual_key`` that Stickler's extractor joins on (fixture originally
        # had entries at the LineItems[N] object level for the old sklearn
        # post-pass which walked its own match map).
        for cr in comparison_results:
            new_fcs = []
            for fc in cr["field_comparisons"]:
                key = fc.get("field_path") or fc.get("expected_key")
                if key == "Agency":
                    new_fcs.append(
                        {
                            **fc,
                            "actual_key": key,
                            "field_path": key,
                            "expected_key": key,
                            "score": 1.0 if fc["match"] else 0.0,
                        }
                    )
                elif key and key.startswith("LineItems["):
                    # Materialize as LineItems[N].Rate to match the confidence key.
                    leaf = f"{key}.Rate"
                    new_fcs.append(
                        {
                            **fc,
                            "actual_key": leaf,
                            "field_path": leaf,
                            "expected_key": leaf,
                            "score": 1.0 if fc["match"] else 0.0,
                        }
                    )
                else:
                    new_fcs.append(fc)
            cr["field_comparisons"] = new_fcs

        # Drive the new accumulator directly.
        acc = index._IndexCollapsingConfidenceAccumulator(
            metrics=[AUROCMetric(), ECEMetric(), BrierScoreMetric()]
        )
        for cr in comparison_results:
            acc.accumulate(cr, None)
        enhanced_confidence_metrics = acc.compute()

        assert enhanced_confidence_metrics is not None, (
            "Should return aggregated confidence metrics"
        )
        fields = enhanced_confidence_metrics.get("fields", {})

        # Pattern-based key present (indices collapsed to the pattern).
        assert "LineItems.Rate" in fields, (
            "Should have pattern-based key LineItems.Rate"
        )

        line_items_rate = fields["LineItems.Rate"]
        # Stickler emits AUROC / ECE / Brier under these keys.
        assert "auroc" in line_items_rate, "Should have AUROC"
        assert "brier_score" in line_items_rate, "Should have Brier score"
        assert "ece" in line_items_rate, "Should have ECE (with bins)"

        # AUROC / Brier in [0, 1] on a real sample.
        auroc = line_items_rate["auroc"]["value"]
        assert auroc is not None, "AUROC should be computed"
        assert 0 <= auroc <= 1, f"AUROC should be in [0,1], got {auroc}"
        brier = line_items_rate["brier_score"]["value"]
        assert brier is not None, "Brier score should be computed"
        assert 0 <= brier <= 1, f"Brier score should be in [0,1], got {brier}"

        # Sample count derives from ECE bins — 20 line items across 10 docs
        # (matches the fixture).
        total_from_bins = sum(b.get("count", 0) for b in line_items_rate["ece"]["bins"])
        assert total_from_bins == 20, (
            f"Should have 20 samples pooled across all LineItems indices, "
            f"got {total_from_bins}"
        )

        print("\n=== PATTERN AGGREGATION RESULTS ===")
        print("   LineItems.Rate:")
        print(f"     - AUROC: {auroc}")
        print(f"     - Brier: {brier}")
        print(f"     - Sample count: {total_from_bins}")
        print("\n✅ Pattern aggregation successfully enhanced confidence metrics")

        # ECARB computation test removed - Stickler v0.4.0 has specific requirements
        # for ECARB that are not satisfied by this test's mock data structure.
        # ECARB validation is covered by integration tests with real data.


@pytest.mark.unit
class TestBrierScoreKeyRename:
    """Regression: Stickler's BrierScoreMetric emits under ``brier_score`` but
    the Test Studio UI (TestResults.tsx, TestComparison.tsx) + awsjson-types
    still read ``brier`` (matching the deleted sklearn post-pass's key).
    ``_rename_brier_score_key`` maps the accumulator output to the UI-expected
    key at the aggregation boundary.
    """

    def test_renames_overall_brier_score_to_brier(self, mock_env):
        index = import_test_module()
        cm = {
            "overall": {
                "auroc": {"value": 0.9},
                "brier_score": {"value": 0.2},
                "ece": {"value": 0.05},
            },
        }
        out = index._rename_brier_score_key(cm)
        assert "brier" in out["overall"]
        assert out["overall"]["brier"] == {"value": 0.2}
        assert "brier_score" not in out["overall"]

    def test_renames_per_field_brier_score_to_brier(self, mock_env):
        index = import_test_module()
        cm = {
            "fields": {
                "LineItems.Rate": {
                    "auroc": {"value": 0.8},
                    "brier_score": {"value": 0.3},
                },
                "Agency": {
                    "auroc": {"value": 0.95},
                    "brier_score": {"value": 0.1},
                },
            },
        }
        out = index._rename_brier_score_key(cm)
        for field_name in ("LineItems.Rate", "Agency"):
            assert "brier" in out["fields"][field_name]
            assert "brier_score" not in out["fields"][field_name]

    def test_passthrough_on_none_or_empty(self, mock_env):
        index = import_test_module()
        assert index._rename_brier_score_key(None) is None
        assert index._rename_brier_score_key({}) == {}

    def test_preserves_existing_brier_key(self, mock_env):
        """If the payload already has ``brier`` (e.g. from an older codepath),
        don't clobber it with the (possibly stale) ``brier_score`` value."""
        index = import_test_module()
        cm = {
            "overall": {
                "brier": {"value": 0.5},
                "brier_score": {"value": 0.9},  # would clobber if we didn't guard
            },
        }
        out = index._rename_brier_score_key(cm)
        assert out["overall"]["brier"] == {"value": 0.5}
