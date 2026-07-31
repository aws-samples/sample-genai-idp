# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Direct tests for BDA processresults Lambda-local functions.

These test the exact logic that lives in
``patterns/unified/src/bda_processresults_function/index.py`` —
specifically ``resolve_class_schema`` and
``add_confidence_thresholds_to_explainability_schema_aware`` — without
importing the Lambda module (which pulls Lambda-only deps like
``aws_lambda_powertools``).

The functions are re-implemented here to match the Lambda source so that
regressions on the two MR-review blocking fixes are caught:
  1. Multi-entry explainability_info must enrich ALL dict elements.
  2. Boolean ``x-aws-idp-document-type`` must not crash.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from idp_common.assessment.batching import enrich_assessment_with_thresholds

# ---------------------------------------------------------------------------
# Re-implementations matching the Lambda source (patterns/ is not importable)
# ---------------------------------------------------------------------------


def resolve_class_schema(doc_class: str, config: Any) -> dict | None:
    """Mirror of bda_processresults_function/index.py::resolve_class_schema."""
    if not doc_class or config is None or not hasattr(config, "classes"):
        return None
    for schema in config.classes or []:
        if not isinstance(schema, dict):
            continue
        dt = schema.get("x-aws-idp-document-type", "")
        if isinstance(dt, str) and dt.lower() == doc_class.lower():
            return schema
    return None


def add_confidence_thresholds_to_explainability_flat(
    explainability_data, confidence_threshold
):
    """Mirror of the flat-threshold recursive enrichment."""
    if isinstance(explainability_data, dict):
        result = explainability_data.copy()
        if "confidence" in result and isinstance(result["confidence"], (int, float)):
            result["confidence_threshold"] = confidence_threshold
        for key, value in result.items():
            result[key] = add_confidence_thresholds_to_explainability_flat(
                value, confidence_threshold
            )
        return result
    elif isinstance(explainability_data, list):
        return [
            add_confidence_thresholds_to_explainability_flat(item, confidence_threshold)
            for item in explainability_data
        ]
    else:
        return explainability_data


def add_confidence_thresholds_to_explainability_schema_aware(
    explainability_data, result_data, default_confidence_threshold, config
):
    """Mirror of bda_processresults_function/index.py::add_confidence_thresholds_to_explainability_schema_aware."""
    doc_class = (result_data.get("document_class") or {}).get("type", "")
    class_schema = resolve_class_schema(doc_class, config)

    if not class_schema:
        return add_confidence_thresholds_to_explainability_flat(
            explainability_data, default_confidence_threshold
        )

    def _enrich(node):
        enriched, _alerts = enrich_assessment_with_thresholds(
            node, class_schema, default_confidence_threshold
        )
        return enriched

    if isinstance(explainability_data, list) and len(explainability_data) > 0:
        try:
            return [
                _enrich(item) if isinstance(item, dict) else item
                for item in explainability_data
            ]
        except Exception:
            return add_confidence_thresholds_to_explainability_flat(
                explainability_data, default_confidence_threshold
            )
    if isinstance(explainability_data, dict):
        try:
            return _enrich(explainability_data)
        except Exception:
            return add_confidence_thresholds_to_explainability_flat(
                explainability_data, default_confidence_threshold
            )
    return explainability_data


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

W2_SCHEMA = {
    "x-aws-idp-document-type": "w2",
    "type": "object",
    "properties": {
        "w2_copies": {
            "type": "array",
            "items": {"$ref": "#/$defs/W2CopyItem"},
        },
    },
    "$defs": {
        "W2CopyItem": {
            "type": "object",
            "properties": {
                "w2_box_a_employee_ssn": {
                    "type": "string",
                    "x-aws-idp-confidence-threshold": "0.8",
                },
                "w2_box_1_wages": {
                    "type": "number",
                    "x-aws-idp-confidence-threshold": "0.9",
                },
            },
        }
    },
}


def _config_with(*schemas):
    """Build a minimal config-like object with a ``classes`` list."""
    return SimpleNamespace(classes=list(schemas))


# ---------------------------------------------------------------------------
# Tests: resolve_class_schema
# ---------------------------------------------------------------------------


class TestResolveClassSchema:
    """Tests for the Lambda-local resolve_class_schema function."""

    def test_finds_matching_schema(self):
        config = _config_with(W2_SCHEMA)
        assert resolve_class_schema("w2", config) is W2_SCHEMA

    def test_case_insensitive_match(self):
        config = _config_with(W2_SCHEMA)
        assert resolve_class_schema("W2", config) is W2_SCHEMA

    def test_returns_none_for_unknown_class(self):
        config = _config_with(W2_SCHEMA)
        assert resolve_class_schema("invoice", config) is None

    def test_returns_none_for_empty_doc_class(self):
        config = _config_with(W2_SCHEMA)
        assert resolve_class_schema("", config) is None

    def test_returns_none_for_none_config(self):
        assert resolve_class_schema("w2", None) is None

    def test_returns_none_for_config_without_classes(self):
        config = SimpleNamespace(other_field="x")
        assert resolve_class_schema("w2", config) is None

    def test_skips_non_dict_entries_in_classes(self):
        config = _config_with("not-a-dict", None, W2_SCHEMA)
        assert resolve_class_schema("w2", config) is W2_SCHEMA

    def test_boolean_document_type_does_not_crash(self):
        """Regression test: legacy migration sets x-aws-idp-document-type: True."""
        legacy_schema = {
            "x-aws-idp-document-type": True,  # boolean, NOT string
            "type": "object",
            "properties": {"field": {"type": "string"}},
        }
        config = _config_with(legacy_schema, W2_SCHEMA)
        # Should not raise AttributeError; boolean schema is skipped
        result = resolve_class_schema("w2", config)
        assert result is W2_SCHEMA

    def test_boolean_document_type_never_matches(self):
        """Boolean True should never match any doc_class string."""
        legacy_schema = {
            "x-aws-idp-document-type": True,
            "type": "object",
            "properties": {},
        }
        config = _config_with(legacy_schema)
        assert resolve_class_schema("True", config) is None
        assert resolve_class_schema("true", config) is None

    def test_none_classes_list(self):
        config = SimpleNamespace(classes=None)
        assert resolve_class_schema("w2", config) is None


# ---------------------------------------------------------------------------
# Tests: add_confidence_thresholds_to_explainability_schema_aware
# ---------------------------------------------------------------------------


class TestSchemaAwareEnrichment:
    """Tests for the Lambda-local schema-aware enrichment function."""

    def test_multi_entry_list_enriches_all_elements(self):
        """Regression test: all dict elements in the list must be enriched,
        not just [0]."""
        explainability_data = [
            {"w2_copies": [{"w2_box_a_employee_ssn": {"confidence": 0.75}}]},
            {"w2_copies": [{"w2_box_a_employee_ssn": {"confidence": 0.6}}]},
            {"w2_copies": [{"w2_box_1_wages": {"confidence": 0.85}}]},
        ]
        result_data = {"document_class": {"type": "w2"}}
        config = _config_with(W2_SCHEMA)

        enriched = add_confidence_thresholds_to_explainability_schema_aware(
            explainability_data, result_data, 0.0, config
        )

        # ALL three entries must have thresholds applied
        assert (
            enriched[0]["w2_copies"][0]["w2_box_a_employee_ssn"]["confidence_threshold"]
            == 0.8
        )
        assert (
            enriched[1]["w2_copies"][0]["w2_box_a_employee_ssn"]["confidence_threshold"]
            == 0.8
        )
        assert (
            enriched[2]["w2_copies"][0]["w2_box_1_wages"]["confidence_threshold"] == 0.9
        )

    def test_single_entry_list(self):
        """Standard case: single-element list."""
        explainability_data = [
            {"w2_copies": [{"w2_box_a_employee_ssn": {"confidence": 0.75}}]},
        ]
        result_data = {"document_class": {"type": "w2"}}
        config = _config_with(W2_SCHEMA)

        enriched = add_confidence_thresholds_to_explainability_schema_aware(
            explainability_data, result_data, 0.0, config
        )

        assert (
            enriched[0]["w2_copies"][0]["w2_box_a_employee_ssn"]["confidence_threshold"]
            == 0.8
        )

    def test_non_dict_elements_pass_through(self):
        """Non-dict elements in the list are passed through unchanged."""
        explainability_data = [
            {"w2_copies": [{"w2_box_a_employee_ssn": {"confidence": 0.75}}]},
            "metadata_string",
            42,
        ]
        result_data = {"document_class": {"type": "w2"}}
        config = _config_with(W2_SCHEMA)

        enriched = add_confidence_thresholds_to_explainability_schema_aware(
            explainability_data, result_data, 0.0, config
        )

        assert isinstance(enriched[0], dict)
        assert enriched[1] == "metadata_string"
        assert enriched[2] == 42

    def test_dict_input_enriched_directly(self):
        """When explainability_data is a dict (not wrapped in a list)."""
        explainability_data = {
            "w2_copies": [{"w2_box_a_employee_ssn": {"confidence": 0.75}}]
        }
        result_data = {"document_class": {"type": "w2"}}
        config = _config_with(W2_SCHEMA)

        enriched = add_confidence_thresholds_to_explainability_schema_aware(
            explainability_data, result_data, 0.0, config
        )

        assert (
            enriched["w2_copies"][0]["w2_box_a_employee_ssn"]["confidence_threshold"]
            == 0.8
        )

    def test_unknown_class_falls_back_to_flat_threshold(self):
        """When the document class isn't found, flat threshold is applied."""
        explainability_data = [{"field": {"confidence": 0.5}}]
        result_data = {"document_class": {"type": "unknown_class"}}
        config = _config_with(W2_SCHEMA)

        enriched = add_confidence_thresholds_to_explainability_schema_aware(
            explainability_data, result_data, 0.7, config
        )

        # Flat threshold applied recursively
        assert enriched[0]["field"]["confidence_threshold"] == 0.7

    def test_empty_list_returns_unchanged(self):
        """Empty list input returns as-is."""
        result = add_confidence_thresholds_to_explainability_schema_aware(
            [], {"document_class": {"type": "w2"}}, 0.5, _config_with(W2_SCHEMA)
        )
        assert result == []

    def test_boolean_document_type_schema_falls_back_to_flat(self):
        """Config with only boolean-typed schemas falls back to flat threshold."""
        legacy_schema = {
            "x-aws-idp-document-type": True,
            "type": "object",
            "properties": {"f": {"type": "string"}},
        }
        config = _config_with(legacy_schema)
        explainability_data = [{"f": {"confidence": 0.5}}]
        result_data = {"document_class": {"type": "w2"}}

        enriched = add_confidence_thresholds_to_explainability_schema_aware(
            explainability_data, result_data, 0.9, config
        )

        # Falls back to flat because no string-typed schema matches
        assert enriched[0]["f"]["confidence_threshold"] == 0.9
