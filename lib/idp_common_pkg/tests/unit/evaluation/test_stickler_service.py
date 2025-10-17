# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for SticklerEvaluationService.
"""

import pytest
from unittest.mock import MagicMock, patch

from idp_common.evaluation.stickler_service import (
    SticklerEvaluationService,
    STICKLER_AVAILABLE,
)
from idp_common.evaluation.models import (
    AttributeEvaluationResult,
    SectionEvaluationResult,
)
from idp_common.models import Section


@pytest.mark.skipif(not STICKLER_AVAILABLE, reason="Stickler library not installed")
class TestSticklerEvaluationService:
    """Test cases for SticklerEvaluationService."""

    def test_initialization(self):
        """Test service initialization."""
        config = {
            "stickler_models": {
                "invoice": {
                    "model_name": "Invoice",
                    "fields": {
                        "invoice_number": {
                            "type": "str",
                            "comparator": "ExactComparator",
                        },
                        "total": {
                            "type": "float",
                            "comparator": "NumericComparator",
                        },
                    },
                }
            }
        }

        service = SticklerEvaluationService(config=config)
        assert service is not None
        assert "invoice" in service.stickler_models

    def test_flatten_comparison_result(self):
        """Test flattening of nested comparison results."""
        config = {}
        service = SticklerEvaluationService(config=config)

        comparison_result = {
            "overall_score": 0.95,
            "field_scores": {"name": 1.0, "age": 0.9},
            "nested_scores": {
                "address": {
                    "overall_score": 0.85,
                    "field_scores": {"street": 0.8, "city": 0.9},
                }
            },
        }

        flattened = service._flatten_comparison_result(comparison_result)

        # Should have 4 entries: name, age, address.street, address.city
        assert len(flattened) >= 2
        field_names = [f[0] for f in flattened]
        assert "name" in field_names
        assert "age" in field_names

    def test_get_nested_value(self):
        """Test getting nested values from dictionary."""
        config = {}
        service = SticklerEvaluationService(config=config)

        data = {"customer": {"name": "John Doe", "address": {"city": "New York"}}}

        # Test simple nested access
        assert service._get_nested_value(data, "customer.name") == "John Doe"

        # Test deeper nesting
        assert service._get_nested_value(data, "customer.address.city") == "New York"

        # Test non-existent path
        assert service._get_nested_value(data, "customer.phone") is None

    def test_create_attribute_result(self):
        """Test creation of AttributeEvaluationResult."""
        config = {}
        service = SticklerEvaluationService(config=config)

        # Test exact match
        result = service._create_attribute_result(
            "invoice_number", "INV-001", "INV-001", 1.0
        )

        assert isinstance(result, AttributeEvaluationResult)
        assert result.name == "invoice_number"
        assert result.matched is True
        assert result.score == 1.0
        assert result.evaluation_method == "STICKLER"

        # Test partial match
        result = service._create_attribute_result(
            "customer_name", "John Smith", "Jon Smith", 0.85
        )

        assert result.matched is True  # Above 0.8 threshold
        assert result.score == 0.85

        # Test no match
        result = service._create_attribute_result(
            "total", "100.00", "200.00", 0.5
        )

        assert result.matched is False  # Below 0.8 threshold
        assert result.score == 0.5

    def test_calculate_section_metrics(self):
        """Test calculation of section metrics."""
        config = {}
        service = SticklerEvaluationService(config=config)

        # Create sample attribute results
        attribute_results = [
            AttributeEvaluationResult(
                name="field1",
                expected="value1",
                actual="value1",
                matched=True,
                score=1.0,
                evaluation_method="STICKLER",
            ),
            AttributeEvaluationResult(
                name="field2",
                expected="value2",
                actual="value2_different",
                matched=False,
                score=0.5,
                evaluation_method="STICKLER",
            ),
            AttributeEvaluationResult(
                name="field3",
                expected=None,
                actual=None,
                matched=True,
                score=1.0,
                evaluation_method="STICKLER",
            ),
        ]

        metrics = service._calculate_section_metrics(attribute_results)

        # Check that metrics are returned (calculate_metrics returns precision, recall, etc.)
        assert "precision" in metrics
        assert "recall" in metrics
        assert "f1_score" in metrics
        assert "accuracy" in metrics
        assert "false_alarm_rate" in metrics
        assert "false_discovery_rate" in metrics

        # Verify metrics are reasonable
        assert 0.0 <= metrics["precision"] <= 1.0
        assert 0.0 <= metrics["recall"] <= 1.0
        assert 0.0 <= metrics["f1_score"] <= 1.0

    @patch("idp_common.evaluation.stickler_service.s3")
    def test_evaluate_section_no_model(self, mock_s3):
        """Test section evaluation when no Stickler model is configured."""
        config = {}
        service = SticklerEvaluationService(config=config)

        section = Section(
            section_id="section1",
            classification="unknown_class",
            page_ids=["page1"],
        )

        result = service.evaluate_section(
            section=section, expected_results={}, actual_results={}
        )

        assert isinstance(result, SectionEvaluationResult)
        assert result.section_id == "section1"
        assert len(result.attributes) == 0

    def test_calculate_overall_metrics(self):
        """Test calculation of overall metrics from section results."""
        config = {}
        service = SticklerEvaluationService(config=config)

        # Create sample section results with attributes
        section_results = [
            SectionEvaluationResult(
                section_id="section1",
                document_class="invoice",
                attributes=[
                    AttributeEvaluationResult(
                        name="field1",
                        expected="value1",
                        actual="value1",
                        matched=True,
                        score=1.0,
                        evaluation_method="STICKLER",
                    ),
                    AttributeEvaluationResult(
                        name="field2",
                        expected="value2",
                        actual="value2_diff",
                        matched=False,
                        score=0.5,
                        evaluation_method="STICKLER",
                    ),
                ],
                metrics={},
            ),
            SectionEvaluationResult(
                section_id="section2",
                document_class="invoice",
                attributes=[
                    AttributeEvaluationResult(
                        name="field3",
                        expected="value3",
                        actual="value3",
                        matched=True,
                        score=1.0,
                        evaluation_method="STICKLER",
                    ),
                ],
                metrics={},
            ),
        ]

        overall_metrics = service._calculate_overall_metrics(section_results)

        # Check that metrics are returned
        assert "precision" in overall_metrics
        assert "recall" in overall_metrics
        assert "f1_score" in overall_metrics
        assert "accuracy" in overall_metrics

        # Verify metrics are reasonable
        assert 0.0 <= overall_metrics["precision"] <= 1.0
        assert 0.0 <= overall_metrics["recall"] <= 1.0
        assert 0.0 <= overall_metrics["f1_score"] <= 1.0


def test_stickler_not_available():
    """Test that appropriate error is raised when Stickler is not available."""
    with patch(
        "idp_common.evaluation.stickler_service.STICKLER_AVAILABLE", False
    ):
        with pytest.raises(ImportError, match="Stickler library is not installed"):
            SticklerEvaluationService()
