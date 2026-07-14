# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for the Stickler-based evaluation service.

These tests focus on the public API and Stickler integration functionality.
"""

import warnings
from unittest.mock import MagicMock, patch

import pytest
from idp_common.evaluation.models import (
    AttributeEvaluationResult,
    SectionEvaluationResult,
)
from idp_common.evaluation.service import EvaluationService
from idp_common.models import Document, Section, Status


@pytest.fixture(autouse=True)
def suppress_datetime_warning():
    """Fixture to suppress the datetime.utcnow() deprecation warning from botocore."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="datetime.datetime.utcnow\\(\\) is deprecated",
            category=DeprecationWarning,
        )
        yield


@pytest.mark.unit
class TestSticklerEvaluationService:
    """Tests for the Stickler-based EvaluationService class."""

    @pytest.fixture
    def mock_config(self):
        """Fixture providing a mock configuration with evaluation extensions."""
        return {
            "classes": [
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$id": "invoice",
                    "x-aws-idp-document-type": "Invoice",
                    "x-aws-idp-evaluation-model-name": "Invoice",
                    "x-aws-idp-evaluation-match-threshold": 0.8,
                    "type": "object",
                    "description": "An invoice document",
                    "properties": {
                        "invoice_number": {
                            "type": "string",
                            "description": "The invoice number",
                            "x-aws-idp-evaluation-method": "EXACT",
                            "x-aws-idp-evaluation-weight": 3.0,
                        },
                        "invoice_date": {
                            "type": "string",
                            "description": "The invoice date",
                            "x-aws-idp-evaluation-method": "FUZZY",
                            "x-aws-idp-evaluation-threshold": 0.9,
                            "x-aws-idp-evaluation-weight": 1.5,
                        },
                        "total_amount": {
                            "type": "number",
                            "description": "The total amount",
                            "x-aws-idp-evaluation-method": "NUMERIC_EXACT",
                            "x-aws-idp-evaluation-threshold": 0.01,
                            "x-aws-idp-evaluation-weight": 2.0,
                        },
                    },
                }
            ],
            "evaluation": {
                "llm_method": {
                    "model": "anthropic.claude-3-sonnet-20240229-v1:0",
                    "temperature": 0.0,
                    "top_k": 5,
                }
            },
        }

    @pytest.fixture
    def service(self, mock_config):
        """Fixture providing an EvaluationService instance."""
        return EvaluationService(region="us-west-2", config=mock_config, max_workers=5)

    @pytest.fixture
    def sample_document(self):
        """Fixture providing a sample document with sections."""
        doc = Document(
            id="test-doc",
            input_key="test-document.pdf",
            input_bucket="input-bucket",
            output_bucket="output-bucket",
            status=Status.EXTRACTING,
        )

        # Add sections
        doc.sections.append(
            Section(
                section_id="1",
                classification="Invoice",
                page_ids=["1", "2"],
                extraction_result_uri="s3://input-bucket/test-document.pdf/sections/1/result.json",
            )
        )

        return doc

    def test_init(self, mock_config):
        """Test initialization with configuration."""
        service = EvaluationService(
            region="us-west-2", config=mock_config, max_workers=5
        )

        assert service.region == "us-west-2"
        assert service.max_workers == 5
        assert len(service.stickler_models) == 1
        assert "invoice" in service.stickler_models

    def test_stickler_model_creation(self, service):
        """Test that Stickler models are created correctly."""
        # Get Stickler model for invoice class
        model_class = service._get_stickler_model("Invoice")

        assert model_class is not None
        assert model_class.__name__ == "Invoice"

        # Test caching
        model_class_2 = service._get_stickler_model("Invoice")
        assert model_class is model_class_2  # Same instance from cache

    def test_stickler_model_not_found(self, service):
        """Test error when Stickler model not found for class."""
        with pytest.raises(ValueError, match="No schema configuration"):
            service._get_stickler_model("UnknownClass")

    @patch("idp_common.s3.get_json_content")
    def test_prepare_stickler_data(self, mock_get_json_content, service):
        """Test preparing data for Stickler."""
        # Test with inference_result wrapper
        mock_get_json_content.return_value = {
            "inference_result": {"invoice_number": "INV-123", "total_amount": 100.00},
            "explainability_info": [{"invoice_number": {"confidence": 0.95}}],
        }

        extraction_data, confidence_scores = service._prepare_stickler_data(
            "s3://bucket/path"
        )

        assert extraction_data == {"invoice_number": "INV-123", "total_amount": 100.00}
        assert "invoice_number" in confidence_scores

    def test_flatten_confidence_scores(self, service):
        """Test flattening confidence scores from assessment explainability format."""
        # Real-world confidence structure from assessment service with geometry and thresholds
        confidence_scores = {
            "Agency": {
                "confidence": 0.99,
                "geometry": [
                    {
                        "boundingBox": {
                            "top": 0.215,
                            "left": 0.15,
                            "width": 0.249,
                            "height": 0.014,
                        },
                        "page": 1,
                    }
                ],
                "confidence_threshold": 0.8,
            },
            "Advertiser": {
                "confidence": 1.0,
                "geometry": [
                    {
                        "boundingBox": {
                            "top": 0.183,
                            "left": 0.46,
                            "width": 0.158,
                            "height": 0.012,
                        },
                        "page": 1,
                    }
                ],
                "confidence_threshold": 0.8,
            },
            "GrossTotal": {
                "confidence": 0.99,
                "geometry": [
                    {
                        "boundingBox": {
                            "top": 0.725,
                            "left": 0.873,
                            "width": 0.07,
                            "height": 0.012,
                        },
                        "page": 2,
                    }
                ],
                "confidence_threshold": 0.8,
            },
            "LineItems": [
                {
                    "LineItemRate": {
                        "confidence": 1.0,
                        "geometry": [
                            {
                                "boundingBox": {
                                    "top": 0.47,
                                    "left": 0.754,
                                    "width": 0.052,
                                    "height": 0.013,
                                },
                                "page": 1,
                            }
                        ],
                        "confidence_threshold": 0.9,
                    },
                    "LineItemDays": {
                        "confidence": 0.8,
                        "geometry": [
                            {
                                "boundingBox": {
                                    "top": 0.47,
                                    "left": 0.5,
                                    "width": 0.05,
                                    "height": 0.013,
                                },
                                "page": 1,
                            }
                        ],
                        "confidence_threshold": 0.9,
                    },
                    "LineItemDescription": {
                        "confidence": 0.9,
                        "geometry": [
                            {
                                "boundingBox": {
                                    "top": 0.47,
                                    "left": 0.228,
                                    "width": 0.098,
                                    "height": 0.013,
                                },
                                "page": 1,
                            }
                        ],
                        "confidence_threshold": 0.9,
                    },
                },
                {
                    "LineItemRate": {
                        "confidence": 1.0,
                        "geometry": [
                            {
                                "boundingBox": {
                                    "top": 0.469,
                                    "left": 0.754,
                                    "width": 0.05,
                                    "height": 0.013,
                                },
                                "page": 1,
                            }
                        ],
                        "confidence_threshold": 0.9,
                    },
                    "LineItemDays": {
                        "confidence": 0.8,
                        "geometry": [
                            {
                                "boundingBox": {
                                    "top": 0.469,
                                    "left": 0.5,
                                    "width": 0.049,
                                    "height": 0.013,
                                },
                                "page": 1,
                            }
                        ],
                        "confidence_threshold": 0.9,
                    },
                },
            ],
        }

        # Test Rich Value conversion
        inference_result = {
            "Agency": "BUYING TIME, LLC",
            "Advertiser": "ACME CORP",
            "GrossTotal": 15185.0,
            "LineItems": [
                {
                    "LineItemRate": 600.0,
                    "LineItemDays": "MTWT---",
                    "LineItemDescription": "Ad spot",
                },
                {"LineItemRate": 500.0, "LineItemDays": "MTWT---"},
            ],
        }

        rich_values = service._convert_to_rich_values(
            inference_result, confidence_scores
        )

        # Verify top-level fields have rich values with confidence
        assert rich_values["Agency"] == {
            "_value": "BUYING TIME, LLC",
            "_confidence": 0.99,
        }
        assert rich_values["Advertiser"] == {"_value": "ACME CORP", "_confidence": 1.0}
        assert rich_values["GrossTotal"] == {"_value": 15185.0, "_confidence": 0.99}

        # Verify array items have rich values with confidence
        assert rich_values["LineItems"][0]["LineItemRate"] == {
            "_value": 600.0,
            "_confidence": 1.0,
        }
        assert rich_values["LineItems"][0]["LineItemDays"] == {
            "_value": "MTWT---",
            "_confidence": 0.8,
        }
        assert rich_values["LineItems"][0]["LineItemDescription"] == {
            "_value": "Ad spot",
            "_confidence": 0.9,
        }
        assert rich_values["LineItems"][1]["LineItemRate"] == {
            "_value": 500.0,
            "_confidence": 1.0,
        }
        assert rich_values["LineItems"][1]["LineItemDays"] == {
            "_value": "MTWT---",
            "_confidence": 0.8,
        }

    def test_flatten_confidence_scores_with_wrapper_keys(self, service):
        """Test flattening confidence scores when array elements have wrapper keys.

        This reproduces the production scenario where explainability_info contains
        wrapper keys like 'Item #6' that don't exist in the inference_result.
        """
        # Production data structure: LineItems[5] has a wrapper key 'Item #6'
        confidence_scores = {
            "Agency": {
                "confidence": 0.99,
                "geometry": [
                    {
                        "boundingBox": {
                            "top": 0.215,
                            "left": 0.15,
                            "width": 0.249,
                            "height": 0.014,
                        },
                        "page": 1,
                    }
                ],
                "confidence_threshold": 0.8,
            },
            "LineItems": [
                {
                    "LineItemRate": {
                        "confidence": 1.0,
                        "geometry": [],
                        "confidence_threshold": 0.9,
                    },
                    "LineItemDays": {
                        "confidence": 0.8,
                        "geometry": [],
                        "confidence_threshold": 0.9,
                    },
                },
                {
                    "LineItemRate": {
                        "confidence": 1.0,
                        "geometry": [],
                        "confidence_threshold": 0.9,
                    },
                    "LineItemDays": {
                        "confidence": 0.8,
                        "geometry": [],
                        "confidence_threshold": 0.9,
                    },
                },
                {
                    "LineItemRate": {
                        "confidence": 1.0,
                        "geometry": [],
                        "confidence_threshold": 0.9,
                    },
                    "LineItemDays": {
                        "confidence": 0.8,
                        "geometry": [],
                        "confidence_threshold": 0.9,
                    },
                },
                {
                    "LineItemRate": {
                        "confidence": 1.0,
                        "geometry": [],
                        "confidence_threshold": 0.9,
                    },
                    "LineItemDays": {
                        "confidence": 0.8,
                        "geometry": [],
                        "confidence_threshold": 0.9,
                    },
                },
                {
                    "LineItemRate": {
                        "confidence": 1.0,
                        "geometry": [],
                        "confidence_threshold": 0.9,
                    },
                    "LineItemDays": {
                        "confidence": 0.8,
                        "geometry": [],
                        "confidence_threshold": 0.9,
                    },
                },
                # Element 5: Has wrapper key 'Item #6'
                {
                    "Item #6": {
                        "LineItemRate": {
                            "confidence": 1.0,
                            "geometry": [],
                            "confidence_threshold": 0.9,
                        },
                        "LineItemDays": {
                            "confidence": 0.8,
                            "geometry": [],
                            "confidence_threshold": 0.9,
                        },
                    }
                },
            ],
        }

        # Inference result: Clean data without wrapper keys
        inference_result = {
            "Agency": "BUYING TIME, LLC",
            "LineItems": [
                {"LineItemRate": 1000.0, "LineItemDays": "MTWT---"},
                {"LineItemRate": 1000.0, "LineItemDays": "MTWT---"},
                {"LineItemRate": 1000.0, "LineItemDays": "MTWT---"},
                {"LineItemRate": 1000.0, "LineItemDays": "MTWT---"},
                {"LineItemRate": 1000.0, "LineItemDays": "MTWT---"},
                {"LineItemRate": 1000.0, "LineItemDays": "------S"},  # Element 5
            ],
        }

        # This should handle the wrapper key scenario without KeyError
        rich_values = service._convert_to_rich_values(
            inference_result, confidence_scores
        )

        # Verify top-level field
        assert rich_values["Agency"] == {
            "_value": "BUYING TIME, LLC",
            "_confidence": 0.99,
        }

        # Verify clean array elements (0-4)
        for i in range(5):
            assert rich_values["LineItems"][i]["LineItemRate"]["_value"] == 1000.0
            assert rich_values["LineItems"][i]["LineItemRate"]["_confidence"] == 1.0
            assert rich_values["LineItems"][i]["LineItemDays"]["_confidence"] == 0.8

        # Verify element 5 with wrapper key - should unwrap automatically
        assert rich_values["LineItems"][5]["LineItemRate"]["_value"] == 1000.0
        assert rich_values["LineItems"][5]["LineItemRate"]["_confidence"] == 1.0
        assert rich_values["LineItems"][5]["LineItemDays"]["_value"] == "------S"
        assert rich_values["LineItems"][5]["LineItemDays"]["_confidence"] == 0.8

    def test_production_scenario_exact_data(self, service):
        """Test with exact production data that caused KeyError: 0.

        Uses actual data structure from production S3 file where evaluation failed.
        """
        # Exact production confidence structure (explainability_info is a list with one element)
        explainability_info = [
            {
                "Agency": {
                    "confidence": 0.99,
                    "geometry": [
                        {
                            "boundingBox": {
                                "top": 0.215,
                                "left": 0.15,
                                "width": 0.249,
                                "height": 0.014,
                            },
                            "page": 1,
                        }
                    ],
                    "confidence_threshold": 0.8,
                },
                "Advertiser": {
                    "confidence": 1.0,
                    "geometry": [
                        {
                            "boundingBox": {
                                "top": 0.183,
                                "left": 0.46,
                                "width": 0.158,
                                "height": 0.012,
                            },
                            "page": 1,
                        }
                    ],
                    "confidence_threshold": 0.8,
                },
                "GrossTotal": {
                    "confidence": 0.99,
                    "geometry": [
                        {
                            "boundingBox": {
                                "top": 0.725,
                                "left": 0.873,
                                "width": 0.07,
                                "height": 0.012,
                            },
                            "page": 2,
                        }
                    ],
                    "confidence_threshold": 0.8,
                },
                "LineItems": [
                    {
                        "LineItemRate": {
                            "confidence": 1.0,
                            "geometry": [
                                {
                                    "boundingBox": {
                                        "top": 0.47,
                                        "left": 0.754,
                                        "width": 0.052,
                                        "height": 0.013,
                                    },
                                    "page": 1,
                                }
                            ],
                            "confidence_threshold": 0.9,
                        },
                        "LineItemDays": {
                            "confidence": 0.8,
                            "geometry": [
                                {
                                    "boundingBox": {
                                        "top": 0.47,
                                        "left": 0.5,
                                        "width": 0.05,
                                        "height": 0.013,
                                    },
                                    "page": 1,
                                }
                            ],
                            "confidence_threshold": 0.9,
                        },
                        "LineItemDescription": {
                            "confidence": 0.9,
                            "geometry": [
                                {
                                    "boundingBox": {
                                        "top": 0.47,
                                        "left": 0.228,
                                        "width": 0.098,
                                        "height": 0.013,
                                    },
                                    "page": 1,
                                }
                            ],
                            "confidence_threshold": 0.9,
                        },
                    },
                    {
                        "LineItemRate": {
                            "confidence": 1.0,
                            "geometry": [],
                            "confidence_threshold": 0.9,
                        },
                        "LineItemDays": {
                            "confidence": 0.8,
                            "geometry": [],
                            "confidence_threshold": 0.9,
                        },
                    },
                    {
                        "LineItemRate": {
                            "confidence": 1.0,
                            "geometry": [],
                            "confidence_threshold": 0.9,
                        },
                        "LineItemDays": {
                            "confidence": 0.8,
                            "geometry": [],
                            "confidence_threshold": 0.9,
                        },
                    },
                    {
                        "LineItemRate": {
                            "confidence": 1.0,
                            "geometry": [],
                            "confidence_threshold": 0.9,
                        },
                        "LineItemDays": {
                            "confidence": 0.8,
                            "geometry": [],
                            "confidence_threshold": 0.9,
                        },
                    },
                    {
                        "LineItemRate": {
                            "confidence": 1.0,
                            "geometry": [],
                            "confidence_threshold": 0.9,
                        },
                        "LineItemDays": {
                            "confidence": 0.8,
                            "geometry": [],
                            "confidence_threshold": 0.9,
                        },
                    },
                    {
                        "Item #6": {
                            "LineItemRate": {
                                "confidence": 1.0,
                                "geometry": [],
                                "confidence_threshold": 0.9,
                            },
                            "LineItemDays": {
                                "confidence": 0.8,
                                "geometry": [],
                                "confidence_threshold": 0.9,
                            },
                        }
                    },
                ],
            }
        ]

        # Exact production inference_result
        inference_result = {
            "Agency": "BUYING TIME, LLC",
            "Advertiser": "ACME CORP",
            "GrossTotal": 15185.0,
            "LineItems": [
                {
                    "LineItemRate": 1000.0,
                    "LineItemDays": "MTWT---",
                    "LineItemDescription": "Ad spot",
                },
                {"LineItemRate": 1000.0, "LineItemDays": "MTWT---"},
                {"LineItemRate": 1000.0, "LineItemDays": "MTWT---"},
                {"LineItemRate": 1000.0, "LineItemDays": "MTWT---"},
                {"LineItemRate": 1000.0, "LineItemDays": "MTWT---"},
                {"LineItemRate": 1000.0, "LineItemDays": "------S"},
            ],
        }

        # This should NOT raise KeyError: 0
        # Pass the unwrapped dict (mimicking what _prepare_stickler_data does)
        rich_values = service._convert_to_rich_values(
            inference_result, explainability_info[0]
        )

        # Verify structure is correct
        assert rich_values["Agency"]["_value"] == "BUYING TIME, LLC"
        assert rich_values["Agency"]["_confidence"] == 0.99
        assert len(rich_values["LineItems"]) == 6
        assert rich_values["LineItems"][5]["LineItemRate"]["_value"] == 1000.0

    def test_get_nested_value(self, service):
        """Test getting nested values from Stickler model instances."""
        # Create a mock object with nested attributes
        mock_obj = MagicMock()
        mock_obj.invoice_number = "INV-123"
        mock_obj.address = MagicMock()
        mock_obj.address.city = "Seattle"

        # Test simple attribute
        value = service._get_nested_value(mock_obj, "invoice_number")
        assert value == "INV-123"

        # Test nested attribute
        value = service._get_nested_value(mock_obj, "address.city")
        assert value == "Seattle"

        # Test with real dict (not MagicMock which always returns values)
        dict_obj = {"invoice_number": "INV-123", "address": {"city": "Seattle"}}

        # Test non-existent attribute with dict
        value = service._get_nested_value(dict_obj, "nonexistent")
        assert value is None

    def test_resolve_leaf_schema(self, service):
        """Leaf schema resolution follows array items and object properties."""
        field_schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "Amount": {"x-aws-stickler-comparator": "NumericComparator"},
                    "bankInfo": {
                        "type": "object",
                        "properties": {
                            "bank": {"x-aws-stickler-comparator": "FuzzyComparator"},
                        },
                    },
                },
            },
        }

        # Flat list-item field
        leaf = service._resolve_leaf_schema(field_schema, "LineItems[0].Amount")
        assert leaf is not None
        assert leaf["x-aws-stickler-comparator"] == "NumericComparator"

        # Deeply nested object field within a list item
        leaf = service._resolve_leaf_schema(field_schema, "LineItems[1].bankInfo.bank")
        assert leaf is not None
        assert leaf["x-aws-stickler-comparator"] == "FuzzyComparator"

        # Unknown field resolves to None
        assert (
            service._resolve_leaf_schema(field_schema, "LineItems[0].Missing") is None
        )

    def test_annotate_nested_comparison_methods(self, service):
        """Nested comparisons get per-field evaluation_method and weight."""
        field_schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "Description": {
                        "x-aws-stickler-comparator": "FuzzyComparator",
                        "x-aws-stickler-threshold": 0.9,
                        "x-aws-stickler-weight": 2.0,
                    },
                    "Rate": {
                        "x-aws-stickler-comparator": "NumericComparator",
                        # no weight configured -> defaults to 1.0
                    },
                },
            },
        }
        comparisons = [
            {
                "expected_key": "LineItems[0].Description",
                "expected_value": "Widget",
                "actual_value": "Widgets",
            },
            {
                "expected_key": "LineItems[0].Rate",
                "expected_value": 10.0,
                "actual_value": 10.0,
            },
        ]

        service._annotate_nested_comparison_methods(
            comparisons, field_schema=field_schema, match_threshold=0.8
        )

        assert comparisons[0]["evaluation_method"] == "Fuzzy (threshold: 0.90)"
        assert comparisons[0]["weight"] == 2.0
        assert comparisons[1]["evaluation_method"] == "NumericExact"
        assert comparisons[1]["weight"] == 1.0  # default

    def test_generate_reason(self, service):
        """Test reason generation."""
        # Test exact match
        reason = service._generate_reason("field", "val", "val", 1.0, True, "Exact")
        assert "Exact match" in reason

        # Test partial match
        reason = service._generate_reason("field", "val1", "val2", 0.85, True, "Fuzzy")
        assert "above threshold" in reason

        # Test no match
        reason = service._generate_reason("field", "val1", "val2", 0.5, False, "Exact")
        assert "do not match" in reason

        # Test both empty
        reason = service._generate_reason("field", None, None, 1.0, True, "Exact")
        assert "empty" in reason.lower()

    @patch("idp_common.s3.write_content")
    @patch("idp_common.evaluation.service.EvaluationService._process_section")
    def test_evaluate_document_api(
        self, mock_process_section, mock_write_content, service, sample_document
    ):
        """Test the public evaluate_document API."""
        # Create expected document
        expected_document = sample_document

        # Configure mock for _process_section
        section_result = SectionEvaluationResult(
            section_id="1",
            document_class="Invoice",
            attributes=[
                AttributeEvaluationResult(
                    name="invoice_number",
                    expected="INV-123",
                    actual="INV-123",
                    matched=True,
                    score=1.0,
                    evaluation_method="STICKLER",
                    weight=3.0,
                )
            ],
            metrics={"precision": 1.0, "recall": 1.0, "f1_score": 1.0},
        )

        mock_process_section.return_value = (
            section_result,
            {"tp": 1, "fp": 0, "fn": 0, "tn": 0, "fp1": 0, "fp2": 0},
        )

        # Patch calculate_metrics
        with patch("idp_common.evaluation.metrics.calculate_metrics") as mock_metrics:
            mock_metrics.return_value = {
                "precision": 1.0,
                "recall": 1.0,
                "f1_score": 1.0,
            }

            # Evaluate document
            result = service.evaluate_document(
                actual_document=sample_document,
                expected_document=expected_document,
                store_results=True,
            )

            # Verify API contract
            assert result.id == "test-doc"
            assert result.status == Status.COMPLETED
            assert result.evaluation_report_uri is not None
            assert result.evaluation_results_uri is not None
            assert result.evaluation_result is not None

            # Verify Stickler enhancements
            assert (
                result.evaluation_result.section_results[0].attributes[0].weight == 3.0
            )

    @patch("idp_common.s3.write_content")
    @patch("idp_common.evaluation.service.EvaluationService._process_section")
    def test_evaluate_document_error_handling(
        self, mock_process_section, mock_write_content, service, sample_document
    ):
        """Test error handling in evaluate_document."""
        expected_document = sample_document

        # Configure mock to raise exception
        mock_process_section.side_effect = Exception("Test error")

        # Evaluate document
        result = service.evaluate_document(
            actual_document=sample_document, expected_document=expected_document
        )

        # Check error was captured
        assert len(result.errors) > 0
        assert "Test error" in result.errors[0]

    def test_evaluate_section_with_stickler(self, service):
        """Test evaluate_section with Stickler comparison."""
        section = Section(section_id="1", classification="Invoice", page_ids=["1"])

        expected_results = {
            "invoice_number": "INV-123",
            "invoice_date": "2023-05-08",
            "total_amount": 100.00,
        }

        actual_results = {
            "invoice_number": "INV-123",
            "invoice_date": "2023-05-08",
            "total_amount": 100.00,
        }

        # Mock Stickler model and comparison
        with patch.object(service, "_get_stickler_model") as mock_get_model:
            # Create mock Stickler model
            mock_model_class = MagicMock()
            mock_instance = MagicMock()

            # Configure comparison result
            mock_instance.compare_with.return_value = {
                "overall_score": 1.0,
                "field_scores": {
                    "invoice_number": 1.0,
                    "invoice_date": 1.0,
                    "total_amount": 1.0,
                },
                "match": True,
            }

            mock_model_class.return_value = mock_instance
            mock_get_model.return_value = mock_model_class

            # Mock _get_nested_value to return the values
            with patch.object(service, "_get_nested_value") as mock_nested:

                def nested_side_effect(obj, field_name):
                    if "expected" in str(obj):
                        return expected_results.get(field_name)
                    return actual_results.get(field_name)

                mock_nested.side_effect = nested_side_effect

                # Evaluate section
                result = service.evaluate_section(
                    section=section,
                    expected_results=expected_results,
                    actual_results=actual_results,
                )

                # Verify result
                assert result.section_id == "1"
                assert result.document_class == "Invoice"
                assert len(result.attributes) == 3

                # Verify Stickler was used
                mock_get_model.assert_called_once()
                mock_instance.compare_with.assert_called_once()

    @pytest.fixture
    def nested_optional_config(self):
        """Config with a nested object whose fields have no 'required' array.

        Mirrors real auto/manual schemas (e.g. URLA) where every field is
        optional and may be None.
        """
        return {
            "classes": [
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$id": "form",
                    "x-aws-idp-document-type": "Form",
                    "type": "object",
                    "properties": {
                        "Contact": {"$ref": "#/$defs/Contact"},
                    },
                    "$defs": {
                        "Contact": {
                            "type": "object",
                            "properties": {
                                "HomePhone": {"type": "string"},
                                "WorkPhone": {"type": "string"},
                                "Email": {"type": "string"},
                            },
                        }
                    },
                }
            ]
        }

    def test_evaluate_section_none_in_nested_optional_with_confidence(
        self, nested_optional_config
    ):
        """Regression: None values in nested optional fields must not fail eval.

        Stickler's JsonSchemaFieldConverter builds optional fields with a None
        default but a non-nullable annotation (e.g. ``str``). The confidence
        path round-trips data through ``from_json``/``model_dump``, which
        materializes None for missing fields and re-validates, previously
        raising "Input should be a valid string [input_value=None]" and
        surfacing as a misleading "Schema configuration error". The service
        widens every field to Optional so this path succeeds.
        """
        service = EvaluationService(
            region="us-west-2", config=nested_optional_config, max_workers=1
        )
        section = Section(section_id="1", classification="Form", page_ids=["1"])

        # WorkPhone is None (not extracted) in both baseline and prediction
        expected = {
            "Contact": {"HomePhone": "555-1", "WorkPhone": None, "Email": "a@b.c"}
        }
        actual = {
            "Contact": {"HomePhone": "555-1", "WorkPhone": None, "Email": "a@b.c"}
        }
        confidence = {
            "Contact": {
                "HomePhone": {"confidence": 0.95},
                "Email": {"confidence": 0.95},
            }
        }

        result = service.evaluate_section(
            section=section,
            expected_results=expected,
            actual_results=actual,
            confidence_scores=confidence,
        )

        # Must not be flagged as a failed evaluation
        assert not result.metrics.get("evaluation_failed")
        assert result.document_class == "Form"

    def test_evaluate_section_blast_radius_limited_to_bad_field(self):
        """A single unparseable field must not zero out the whole section.

        The tolerant build drops only the offending field (from both sides) and
        still evaluates the rest, instead of raising and failing every attribute.
        """
        config = {
            "classes": [
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "$id": "t",
                    "x-aws-idp-document-type": "T",
                    "type": "object",
                    "properties": {
                        "Good": {"type": "string"},
                        # numeric field; a dict value can't be coerced and will
                        # fail Pydantic validation
                        "Amount": {"type": "number"},
                    },
                }
            ]
        }
        service = EvaluationService(region="us-west-2", config=config, max_workers=1)
        section = Section(section_id="1", classification="T", page_ids=["1"])

        expected = {"Good": "hello", "Amount": {"nested": "oops"}}
        actual = {"Good": "hello", "Amount": {"nested": "oops2"}}

        result = service.evaluate_section(section, expected, actual, None)

        # Section did NOT hard-fail; the good field was still scored
        assert not result.metrics.get("evaluation_failed")
        good = next((a for a in result.attributes if a.name == "Good"), None)
        assert good is not None and good.matched
        # The bad field is reported as skipped, not silently dropped
        assert result.metrics.get("skipped_field_count") == 1
        assert any(a.name.startswith("__SKIPPED__") for a in result.attributes)

    def test_drop_field_at_path_nested_and_list(self):
        """_drop_field_at_path removes the right leaf for dict and list paths."""
        service = EvaluationService(
            region="us-west-2", config={"classes": []}, max_workers=1
        )
        data = {
            "A": {"B": {"C": "x", "D": "y"}},
            "Items": [{"k": 1}, {"k": 2}],
        }

        # Nested dict path
        out = service._drop_field_at_path(data, ("A", "B", "C"))
        assert "C" not in out["A"]["B"]
        assert out["A"]["B"]["D"] == "y"
        assert data["A"]["B"]["C"] == "x"  # original untouched (deep copy)

        # List index path
        out2 = service._drop_field_at_path(data, ("Items", 0, "k"))
        assert "k" not in out2["Items"][0]
        assert out2["Items"][1]["k"] == 2

        # Non-existent path is a no-op
        out3 = service._drop_field_at_path(data, ("Nope", "Missing"))
        assert out3 == data


@pytest.mark.unit
def test_section_evaluation_result_includes_stickler_comparison():
    """Test that SectionEvaluationResult can store stickler_comparison_result."""
    stickler_result = {
        "overall_score": 0.85,
        "confusion_matrix": {
            "overall": {"tp": 5, "fp": 1, "tn": 2, "fn": 1},
            "fields": {"field1": {"tp": 3, "fp": 0, "tn": 1, "fn": 0}},
        },
    }

    section_result = SectionEvaluationResult(
        section_id="1",
        document_class="Invoice",
        attributes=[],
        metrics={"accuracy": 0.85},
        stickler_comparison_result=stickler_result,
    )

    assert section_result.stickler_comparison_result is not None
    assert section_result.stickler_comparison_result["overall_score"] == 0.85
    assert "confusion_matrix" in section_result.stickler_comparison_result


@pytest.mark.unit
def test_section_evaluation_result_optional_stickler_comparison():
    """Test that stickler_comparison_result is optional."""
    section_result = SectionEvaluationResult(
        section_id="1",
        document_class="Invoice",
        attributes=[],
        metrics={"accuracy": 0.85},
    )

    assert section_result.stickler_comparison_result is None


@pytest.mark.unit
def test_document_evaluation_serializes_stickler_comparison():
    """Test that DocumentEvaluationResult.to_dict() includes stickler_comparison_result."""
    from idp_common.evaluation.models import DocumentEvaluationResult

    stickler_result = {
        "overall_score": 0.85,
        "confusion_matrix": {"overall": {"tp": 5, "fp": 1}},
    }

    attr_result = AttributeEvaluationResult(
        name="field1",
        expected="value1",
        actual="value1",
        matched=True,
        score=1.0,
        reason="Exact match",
    )

    section_result = SectionEvaluationResult(
        section_id="1",
        document_class="Invoice",
        attributes=[attr_result],
        metrics={"accuracy": 0.85},
        stickler_comparison_result=stickler_result,
    )

    doc_result = DocumentEvaluationResult(
        document_id="test-doc",
        section_results=[section_result],
        overall_metrics={"accuracy": 0.85},
    )

    result_dict = doc_result.to_dict()

    assert "section_results" in result_dict
    assert len(result_dict["section_results"]) == 1
    assert "stickler_comparison_result" in result_dict["section_results"][0]
    assert (
        result_dict["section_results"][0]["stickler_comparison_result"]
        == stickler_result
    )
