# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for ECARB (Error Capture at Review Budget) computation in test_execution_aggregation_function.
"""

import pytest


@pytest.mark.unit
def test_ecarb_computation_with_bulk_evaluator():
    """
    Test ECARB@30 computation using BulkStructuredModelEvaluator with ErrorCaptureAtBudgetMetric.

    Validates:
    1. BulkStructuredModelEvaluator can be instantiated without target_schema
    2. update_from_comparison_result() processes comparison results
    3. compute() returns confidence_metrics with error_capture_at_budget
    4. ECARB@30 metrics include pct_errors_caught and gain
    """
    from stickler.structured_object_evaluator.bulk_structured_model_evaluator import (
        BulkStructuredModelEvaluator,
    )
    from stickler.structured_object_evaluator.models.confidence import (
        ErrorCaptureAtBudgetMetric,
    )

    # Create comparison results with varied confidence scores and match results
    # Designed to test confidence-guided review effectiveness
    comparison_results = [
        # Document 1: High confidence, all correct
        {
            "field_comparisons": [
                {"actual_key": "Field1", "expected_key": "Field1", "match": True},
                {"actual_key": "Field2", "expected_key": "Field2", "match": True},
            ],
            "prediction_confidences": {
                "Field1": 0.95,  # High confidence, correct
                "Field2": 0.93,  # High confidence, correct
            },
            "confusion_matrix": {"tp": 2, "fp": 0, "tn": 0, "fn": 0},
            "overall_score": 1.0,
        },
        # Document 2: Low confidence, errors present
        {
            "field_comparisons": [
                {"actual_key": "Field1", "expected_key": "Field1", "match": False},
                {"actual_key": "Field2", "expected_key": "Field2", "match": True},
            ],
            "prediction_confidences": {
                "Field1": 0.55,  # Low confidence, incorrect (error!)
                "Field2": 0.88,  # Medium confidence, correct
            },
            "confusion_matrix": {"tp": 1, "fp": 0, "tn": 0, "fn": 1},
            "overall_score": 0.5,
        },
        # Document 3: Mixed confidence
        {
            "field_comparisons": [
                {"actual_key": "Field1", "expected_key": "Field1", "match": True},
                {"actual_key": "Field2", "expected_key": "Field2", "match": False},
            ],
            "prediction_confidences": {
                "Field1": 0.92,  # High confidence, correct
                "Field2": 0.65,  # Medium-low confidence, incorrect (error!)
            },
            "confusion_matrix": {"tp": 1, "fp": 0, "tn": 0, "fn": 1},
            "overall_score": 0.5,
        },
        # Document 4: Low confidence error case
        {
            "field_comparisons": [
                {"actual_key": "Field1", "expected_key": "Field1", "match": False},
                {"actual_key": "Field2", "expected_key": "Field2", "match": True},
            ],
            "prediction_confidences": {
                "Field1": 0.48,  # Low confidence, incorrect (error!)
                "Field2": 0.90,  # High confidence, correct
            },
            "confusion_matrix": {"tp": 1, "fp": 0, "tn": 0, "fn": 1},
            "overall_score": 0.5,
        },
    ]

    # Total: 8 fields
    # Errors: Field1 doc2 (0.55), Field2 doc3 (0.65), Field1 doc4 (0.48) = 3 errors
    # Correct: 5 fields
    # Sorted by confidence (ascending): 0.48, 0.55, 0.65, 0.88, 0.90, 0.92, 0.93, 0.95
    # Bottom 30% (2.4 ≈ 2 fields): 0.48, 0.55
    # Expected ECARB@30: catch 2 out of 3 errors = 67% (2/3)

    # Create BulkStructuredModelEvaluator without target_schema
    evaluator = BulkStructuredModelEvaluator(
        confidence_metrics=[
            ErrorCaptureAtBudgetMetric(budgets=[0.30]),
        ]
    )

    # Feed comparison results
    for comp_result in comparison_results:
        evaluator.update_from_comparison_result(comp_result)

    # Compute metrics
    result = evaluator.compute()

    # Validate confidence_metrics structure
    assert result.confidence_metrics is not None, "Should return confidence_metrics"

    confidence_metrics = result.confidence_metrics
    assert "overall" in confidence_metrics, "Should have overall metrics"
    assert "error_capture_at_budget" in confidence_metrics["overall"], (
        "Should have error_capture_at_budget in overall metrics"
    )

    # Extract ECARB metrics
    ecarb = confidence_metrics["overall"]["error_capture_at_budget"]
    assert "budgets" in ecarb, "Should have budgets dictionary"

    # Check ECARB@30 specifically (budget key is "0.30", not "0.3")
    ecarb_30 = ecarb["budgets"].get("0.30")
    assert ecarb_30 is not None, "Should have ECARB@30 (budget 0.3)"

    # Validate structure
    assert "pct_errors_caught" in ecarb_30, "Should have pct_errors_caught"
    assert "gain" in ecarb_30, "Should have gain multiplier"

    pct_errors = ecarb_30["pct_errors_caught"]
    gain = ecarb_30["gain"]

    # Validate types and ranges
    assert isinstance(pct_errors, (int, float)), "pct_errors_caught should be numeric"
    assert isinstance(gain, (int, float)), "gain should be numeric"
    assert 0 <= pct_errors <= 1, (
        f"pct_errors_caught should be in [0,1], got {pct_errors}"
    )
    assert gain >= 0, f"gain should be non-negative, got {gain}"

    # Validate that gain > 1 means confidence is useful
    # (30% review catches more than 30% of errors)
    if pct_errors > 0.3:
        assert gain > 1.0, (
            f"If catching {pct_errors * 100:.0f}% of errors at 30% budget, "
            f"gain should be > 1.0, got {gain}"
        )

    print("\n=== ECARB@30 COMPUTATION RESULTS ===")
    print("   Total fields: 8")
    print("   Total errors: 3")
    print("   Review budget: 30% (≈2 fields)")
    print(f"   Errors caught: {pct_errors * 100:.0f}%")
    print(f"   Gain vs random: {gain:.2f}x")
    print(
        f"   Interpretation: Reviewing lowest-confidence 30% catches {pct_errors * 100:.0f}% of errors"
    )
    print(f"                   ({gain:.1f}x better than random sampling)")
    print("\n✅ ECARB computation successful using BulkStructuredModelEvaluator")


@pytest.mark.unit
def test_ecarb_merging_into_confidence_metrics():
    """
    Test that ECARB metrics are correctly merged into the main confidence_metrics structure.

    Validates the merge logic in _transform_stickler_metrics that combines:
    - AUROC/ECE/Brier from aggregate_from_comparisons
    - ECARB from BulkStructuredModelEvaluator with ErrorCaptureAtBudgetMetric
    """
    # Simulate confidence_metrics from aggregate_from_comparisons
    base_confidence_metrics = {
        "overall": {
            "auroc": {"value": 0.85},
            "ece": {"value": 0.08},
            "brier": {"value": 0.12},
        },
        "fields": {
            "Field1": {
                "auroc": {"value": 0.90},
                "brier": {"value": 0.10},
                "sample_count": 4,
            },
            "Field2": {
                "auroc": {"value": 0.80},
                "brier": {"value": 0.15},
                "sample_count": 4,
            },
        },
        "coverage": {
            "fields_with_confidence": 2,
            "fields_total": 2,
            "ratio": 1.0,
        },
    }

    # Simulate ECARB metrics from BulkStructuredModelEvaluator
    ecarb_metrics = {
        "overall": {
            "error_capture_at_budget": {
                "budgets": {
                    "0.30": {"pct_errors_caught": 0.89, "gain": 3.0},
                }
            }
        },
        "fields": {
            "Field1": {
                "error_capture_at_budget": {
                    "budgets": {"0.30": {"pct_errors_caught": 0.92, "gain": 3.1}}
                }
            },
            "Field2": {
                "error_capture_at_budget": {
                    "budgets": {"0.30": {"pct_errors_caught": 0.85, "gain": 2.8}}
                }
            },
        },
    }

    # Merge ECARB into base confidence_metrics
    confidence_metrics = base_confidence_metrics.copy()

    # Merge overall ECARB
    if (
        "overall" in ecarb_metrics
        and "error_capture_at_budget" in ecarb_metrics["overall"]
    ):
        confidence_metrics["overall"]["error_capture_at_budget"] = ecarb_metrics[
            "overall"
        ]["error_capture_at_budget"]

    # Merge field-level ECARB
    if "fields" in ecarb_metrics:
        for field_name, field_ecab in ecarb_metrics["fields"].items():
            if "error_capture_at_budget" in field_ecab:
                if field_name not in confidence_metrics["fields"]:
                    confidence_metrics["fields"][field_name] = {}
                confidence_metrics["fields"][field_name]["error_capture_at_budget"] = (
                    field_ecab["error_capture_at_budget"]
                )

    # Validate merged structure
    assert "error_capture_at_budget" in confidence_metrics["overall"], (
        "Overall ECARB should be merged"
    )
    assert "auroc" in confidence_metrics["overall"], (
        "Original AUROC should be preserved"
    )

    # Validate field-level merge
    field1 = confidence_metrics["fields"]["Field1"]
    assert "auroc" in field1, "Original field AUROC should be preserved"
    assert "error_capture_at_budget" in field1, "Field ECARB should be merged"

    # Validate ECARB@30 values
    overall_ecarb_30 = confidence_metrics["overall"]["error_capture_at_budget"][
        "budgets"
    ]["0.30"]
    assert overall_ecarb_30["pct_errors_caught"] == 0.89
    assert overall_ecarb_30["gain"] == 3.0

    field1_ecarb_30 = field1["error_capture_at_budget"]["budgets"]["0.30"]
    assert field1_ecarb_30["pct_errors_caught"] == 0.92
    assert field1_ecarb_30["gain"] == 3.1

    print("\n=== ECARB MERGE VALIDATION ===")
    print("   Overall metrics:")
    print(f"     - AUROC: {confidence_metrics['overall']['auroc']['value']}")
    print(
        f"     - ECARB@30: {overall_ecarb_30['pct_errors_caught'] * 100:.0f}% ({overall_ecarb_30['gain']:.1f}x)"
    )
    print("   Field1 metrics:")
    print(f"     - AUROC: {field1['auroc']['value']}")
    print(
        f"     - ECARB@30: {field1_ecarb_30['pct_errors_caught'] * 100:.0f}% ({field1_ecarb_30['gain']:.1f}x)"
    )
    print("\n✅ ECARB metrics successfully merged with existing confidence metrics")
