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
        os.environ, {"TRACKING_TABLE": "test-tracking-table", "LOG_LEVEL": "INFO"}
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
        """Test false alarm rate calculation."""
        index = import_test_module()

        # FP / (FP + TN)
        metrics = {"fp": 2, "tn": 8}
        rate = index._calculate_false_alarm_rate(metrics)
        assert rate == 0.2  # 2 / (2 + 8)

        # Zero denominator
        metrics = {"fp": 0, "tn": 0}
        rate = index._calculate_false_alarm_rate(metrics)
        assert rate is None

    def test_calculate_false_discovery_rate(self, mock_env):
        """Test false discovery rate calculation."""
        index = import_test_module()

        # FP / (FP + TP)
        metrics = {"fp": 3, "tp": 7}
        rate = index._calculate_false_discovery_rate(metrics)
        assert rate == 0.3  # 3 / (3 + 7)

        # Zero denominator
        metrics = {"fp": 0, "tp": 0}
        rate = index._calculate_false_discovery_rate(metrics)
        assert rate is None

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
        Test that pattern aggregation enhances Stickler's confidence metrics for nested fields.

        This validates:
        1. Path-based keys (LineItems[0].Rate, LineItems[1].Rate) are aggregated to patterns (LineItems.Rate)
        2. Confidence metrics match field_metrics key format
        3. AUROC/Brier scores are computed for pattern-based keys
        """
        index = import_test_module()

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
        ]

        # Aggregate with Stickler
        from stickler.structured_object_evaluator.bulk_structured_model_evaluator import (
            aggregate_from_comparisons,
        )

        process_eval = aggregate_from_comparisons(comparison_results)

        # Mock field_metrics with pattern-based keys (as Stickler would generate with schema)
        # In production, this comes from Stickler's bulk aggregator when schema is provided
        field_metrics = {
            "Agency": {"cm_accuracy": 1.0, "tp": 3, "fp": 0, "fn": 0, "tn": 0},
            "LineItems.Rate": {"cm_accuracy": 0.83, "tp": 5, "fp": 0, "fn": 1, "tn": 0},
        }

        # Enhance with pattern aggregation
        enhanced_confidence_metrics = index._enhance_confidence_metrics_with_patterns(
            process_eval.confidence_metrics, comparison_results, field_metrics
        )

        assert enhanced_confidence_metrics is not None, (
            "Should return enhanced confidence metrics"
        )

        fields = enhanced_confidence_metrics.get("fields", {})

        # Should have pattern-based key
        assert "LineItems.Rate" in fields, (
            "Should have pattern-based key LineItems.Rate"
        )

        # Check metrics for LineItems.Rate
        line_items_rate = fields["LineItems.Rate"]
        assert "auroc" in line_items_rate, "Should have AUROC"
        assert "brier" in line_items_rate, "Should have Brier score"
        assert "sample_count" in line_items_rate, "Should have sample count"
        assert "mean_confidence" in line_items_rate, "Should have mean confidence"

        # Validate sample count (6 total line items across 3 docs)
        assert line_items_rate["sample_count"] == 6, (
            f"Should have 6 samples, got {line_items_rate['sample_count']}"
        )

        # Validate mean confidence
        expected_mean = (0.95 + 0.92 + 0.88 + 0.94 + 0.91 + 0.97) / 6
        actual_mean = line_items_rate["mean_confidence"]
        assert abs(actual_mean - expected_mean) < 0.01, (
            f"Mean confidence should be ~{expected_mean}, got {actual_mean}"
        )

        # Validate AUROC (should be computable with mixed match results)
        auroc = line_items_rate["auroc"]["value"]
        assert auroc is not None, "AUROC should be computed"
        assert 0 <= auroc <= 1, f"AUROC should be in [0,1], got {auroc}"

        # Validate Brier score
        brier = line_items_rate["brier"]["value"]
        assert brier is not None, "Brier score should be computed"
        assert 0 <= brier <= 1, f"Brier score should be in [0,1], got {brier}"

        print("\n=== PATTERN AGGREGATION RESULTS ===")
        print("   LineItems.Rate:")
        print(f"     - AUROC: {auroc}")
        print(f"     - Brier: {brier}")
        print(f"     - Sample count: {line_items_rate['sample_count']}")
        print(f"     - Mean confidence: {actual_mean:.3f}")
        print("\n✅ Pattern aggregation successfully enhanced confidence metrics")
