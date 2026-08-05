# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Tests for BDA mode schema-aware confidence threshold application.

The BDA processresults function uses ``enrich_assessment_with_thresholds`` from
batching.py to apply schema-aware thresholds. These tests verify the integration
pattern that the BDA function uses (resolving class schema from config, passing
explainability data through the enrichment function).
"""

from __future__ import annotations

from idp_common.assessment.batching import enrich_assessment_with_thresholds
from idp_common.assessment.threshold_resolver import resolve_threshold_for_path

W2_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "w2",
    "x-aws-idp-document-type": "w2",
    "type": "object",
    "properties": {
        "layout_type": {"type": "string"},
        "w2_copies": {
            "type": "array",
            "items": {"$ref": "#/$defs/W2CopyItem"},
        },
    },
    "$defs": {
        "W2CopyItem": {
            "type": "object",
            "properties": {
                "w2_form_year": {"type": "string"},
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

# 1099-R schema with state/local tax rows via $ref
F1099R_SCHEMA = {
    "x-aws-idp-document-type": "1099r",
    "type": "object",
    "properties": {
        "f1099r_form_year": {
            "type": "string",
            "x-aws-idp-confidence-threshold": "0.85",
        },
        "f1099r_state_local_tax_rows": {
            "type": "array",
            "items": {"$ref": "#/$defs/f1099r_state_local_tax_row"},
        },
    },
    "$defs": {
        "f1099r_state_local_tax_row": {
            "type": "object",
            "properties": {
                "state_tax_withheld": {
                    "type": ["number", "null"],
                    "x-aws-idp-confidence-threshold": "0.8",
                },
                "state_payer_state_no": {
                    "type": ["string", "null"],
                    "x-aws-idp-confidence-threshold": "0.8",
                },
                "state_distribution": {
                    "type": ["number", "null"],
                    "x-aws-idp-confidence-threshold": "0.8",
                },
                "local_tax_withheld": {
                    "type": ["number", "null"],
                    # No explicit threshold
                },
            },
        }
    },
}


def _resolve_class_schema(doc_class: str, config_classes: list) -> dict:
    """Mimics the BDA function's class schema lookup."""
    for schema in config_classes:
        if (
            schema.get("x-aws-idp-document-type", "") or ""
        ).lower() == doc_class.lower():
            return schema
    return {}


class TestBDASchemaAwareThresholdPattern:
    """Test the pattern that BDA processresults uses: look up class schema,
    then call enrich_assessment_with_thresholds on the explainability data."""

    def test_w2_array_with_ref_gets_per_field_thresholds(self):
        """Simulates BDA processing a W2 with $ref array items."""
        config_classes = [W2_SCHEMA]
        doc_class = "w2"
        default_threshold = 0.0  # Customer's hitl.confidence_threshold

        # BDA explainability_info[0] is the assessment dict
        assessment = {
            "w2_copies": [
                {
                    "w2_box_a_employee_ssn": {"confidence": 0.75},
                    "w2_box_1_wages": {"confidence": 0.95},
                    "w2_form_year": {"confidence": 0.6},
                }
            ],
            "layout_type": {"confidence": 0.99},
        }

        class_schema = _resolve_class_schema(doc_class, config_classes)
        enriched, alerts = enrich_assessment_with_thresholds(
            assessment, class_schema, default_threshold
        )

        # Per-sub-field thresholds from $defs/W2CopyItem
        assert (
            enriched["w2_copies"][0]["w2_box_a_employee_ssn"]["confidence_threshold"]
            == 0.8
        )
        assert enriched["w2_copies"][0]["w2_box_1_wages"]["confidence_threshold"] == 0.9
        # No explicit threshold on w2_form_year -> default 0.0
        assert enriched["w2_copies"][0]["w2_form_year"]["confidence_threshold"] == 0.0
        # Scalar field, no explicit threshold -> default 0.0
        assert enriched["layout_type"]["confidence_threshold"] == 0.0

        # SSN 0.75 < 0.8 -> alert
        ssn_alerts = [a for a in alerts if "employee_ssn" in a["attribute_name"]]
        assert len(ssn_alerts) == 1
        assert ssn_alerts[0]["confidence_threshold"] == 0.8

    def test_1099r_state_tax_rows_with_ref(self):
        """Simulates BDA processing 1099-R with state/local tax rows via $ref."""
        config_classes = [F1099R_SCHEMA]
        doc_class = "1099r"
        default_threshold = 0.0

        assessment = {
            "f1099r_form_year": {"confidence": 0.9},
            "f1099r_state_local_tax_rows": [
                {
                    "state_tax_withheld": {"confidence": 0.7},
                    "state_payer_state_no": {"confidence": 0.85},
                    "state_distribution": {"confidence": 0.6},
                    "local_tax_withheld": {"confidence": 0.5},
                },
                {
                    "state_tax_withheld": {"confidence": 0.95},
                    "state_payer_state_no": {"confidence": 0.4},
                    "state_distribution": {"confidence": 0.9},
                    "local_tax_withheld": {"confidence": 0.3},
                },
            ],
        }

        class_schema = _resolve_class_schema(doc_class, config_classes)
        enriched, alerts = enrich_assessment_with_thresholds(
            assessment, class_schema, default_threshold
        )

        # form_year has explicit threshold 0.85; confidence 0.9 >= 0.85 -> ok
        assert enriched["f1099r_form_year"]["confidence_threshold"] == 0.85

        # Row 0: state_tax_withheld 0.7 < 0.8, state_payer_state_no 0.85 >= 0.8 ok
        assert (
            enriched["f1099r_state_local_tax_rows"][0]["state_tax_withheld"][
                "confidence_threshold"
            ]
            == 0.8
        )
        assert (
            enriched["f1099r_state_local_tax_rows"][0]["state_payer_state_no"][
                "confidence_threshold"
            ]
            == 0.8
        )
        # local_tax_withheld has no explicit threshold -> default 0.0
        assert (
            enriched["f1099r_state_local_tax_rows"][0]["local_tax_withheld"][
                "confidence_threshold"
            ]
            == 0.0
        )

        # Row 1: state_payer_state_no 0.4 < 0.8 -> alert
        assert (
            enriched["f1099r_state_local_tax_rows"][1]["state_payer_state_no"][
                "confidence_threshold"
            ]
            == 0.8
        )

        # Count alerts:
        # Row 0: state_tax_withheld (0.7 < 0.8), state_distribution (0.6 < 0.8) = 2
        # Row 1: state_payer_state_no (0.4 < 0.8) = 1
        # form_year: 0.9 >= 0.85, no alert
        state_alerts = [a for a in alerts if "state_local" in a["attribute_name"]]
        assert len(state_alerts) == 3

    def test_class_not_found_uses_flat_threshold(self):
        """When class can't be found in config, flat threshold is applied."""
        config_classes = [W2_SCHEMA]
        doc_class = "unknown_class"
        default_threshold = 0.8

        assessment = {"field": {"confidence": 0.5}}

        class_schema = _resolve_class_schema(doc_class, config_classes)
        # class_schema is {} (empty), so properties is also {}
        enriched, alerts = enrich_assessment_with_thresholds(
            assessment, class_schema, default_threshold
        )

        # Falls back to default 0.8 for all fields
        assert enriched["field"]["confidence_threshold"] == 0.8
        assert len(alerts) == 1

    def test_customer_scenario_hitl_0_field_threshold_0_8(self):
        """End-to-end reproduction of the customer's exact scenario:
        hitl.confidence_threshold=0.0, but W2 SSN has threshold 0.8 in $defs."""
        config_classes = [W2_SCHEMA]
        doc_class = "w2"
        hitl_threshold = 0.0  # Customer's config

        # BDA returns confidence for the SSN field
        assessment = {
            "w2_copies": [
                {
                    "w2_box_a_employee_ssn": {"confidence": 0.75},
                }
            ]
        }

        class_schema = _resolve_class_schema(doc_class, config_classes)
        enriched, alerts = enrich_assessment_with_thresholds(
            assessment, class_schema, hitl_threshold
        )

        # THE FIX: SSN now shows 0.8 threshold (from schema), NOT 0.0%
        assert (
            enriched["w2_copies"][0]["w2_box_a_employee_ssn"]["confidence_threshold"]
            == 0.8
        )
        # And it triggers an alert (0.75 < 0.8)
        assert len(alerts) == 1
        assert alerts[0]["confidence_threshold"] == 0.8


class TestResolveThresholdForPath:
    """The BDA HITL path (``process_keyvalue_details``) resolves thresholds by
    key path, e.g. ``["w2_copies", "_0", "w2_box_a_employee_ssn"]``. These lock
    in that walk, including $ref dereferencing and index markers."""

    def test_array_item_field_via_index_marker(self):
        path = ["w2_copies", "_0", "w2_box_a_employee_ssn"]
        assert resolve_threshold_for_path(path, W2_SCHEMA, 0.0) == 0.8

    def test_array_item_field_second_row(self):
        path = ["w2_copies", "_3", "w2_box_1_wages"]
        assert resolve_threshold_for_path(path, W2_SCHEMA, 0.0) == 0.9

    def test_array_item_field_without_explicit_threshold(self):
        path = ["w2_copies", "_0", "w2_form_year"]
        assert resolve_threshold_for_path(path, W2_SCHEMA, 0.42) == 0.42

    def test_integer_index_marker(self):
        """Integer indices are also accepted as index markers."""
        path = ["w2_copies", 0, "w2_box_a_employee_ssn"]
        assert resolve_threshold_for_path(path, W2_SCHEMA, 0.0) == 0.8

    def test_scalar_top_level_field(self):
        path = ["f1099r_form_year"]
        assert resolve_threshold_for_path(path, F1099R_SCHEMA, 0.0) == 0.85

    def test_unknown_field_returns_default(self):
        path = ["does_not_exist"]
        assert resolve_threshold_for_path(path, W2_SCHEMA, 0.55) == 0.55

    def test_unknown_nested_field_returns_default(self):
        path = ["w2_copies", "_0", "nope"]
        assert resolve_threshold_for_path(path, W2_SCHEMA, 0.55) == 0.55

    def test_empty_path_returns_default(self):
        assert resolve_threshold_for_path([], W2_SCHEMA, 0.31) == 0.31

    def test_empty_schema_returns_default(self):
        path = ["w2_copies", "_0", "w2_box_a_employee_ssn"]
        assert resolve_threshold_for_path(path, {}, 0.77) == 0.77

    def test_broken_ref_returns_default(self):
        schema = {
            "properties": {
                "items": {"type": "array", "items": {"$ref": "#/$defs/Missing"}}
            },
            "$defs": {},
        }
        assert resolve_threshold_for_path(["items", "_0", "f"], schema, 0.66) == 0.66

    def test_field_omitting_index_still_resolves(self):
        """BDA sometimes omits the index for single-element lists; the resolver
        falls through the array container into its item properties."""
        path = ["w2_copies", "w2_box_a_employee_ssn"]
        assert resolve_threshold_for_path(path, W2_SCHEMA, 0.0) == 0.8

    def test_1099r_state_row_field(self):
        path = ["f1099r_state_local_tax_rows", "_1", "state_payer_state_no"]
        assert resolve_threshold_for_path(path, F1099R_SCHEMA, 0.0) == 0.8

    def test_1099r_state_row_field_without_threshold(self):
        path = ["f1099r_state_local_tax_rows", "_0", "local_tax_withheld"]
        assert resolve_threshold_for_path(path, F1099R_SCHEMA, 0.0) == 0.0

    def test_inherits_array_level_threshold(self):
        """A column with no threshold of its own inherits the array attribute's."""
        schema = {
            "properties": {
                "rows": {
                    "type": "array",
                    "x-aws-idp-confidence-threshold": "0.7",
                    "items": {"$ref": "#/$defs/Row"},
                }
            },
            "$defs": {
                "Row": {
                    "type": "object",
                    "properties": {
                        "a": {"x-aws-idp-confidence-threshold": "0.95"},
                        "b": {},
                    },
                }
            },
        }
        # Column with its own threshold wins
        assert resolve_threshold_for_path(["rows", "_0", "a"], schema, 0.0) == 0.95
        # Column without one inherits the array's 0.7, not the 0.0 default
        assert resolve_threshold_for_path(["rows", "_0", "b"], schema, 0.0) == 0.7

    def test_path_resolver_agrees_with_enrichment(self):
        """The BDA HITL path and the enrichment path must agree field-for-field."""
        schema = {
            "properties": {
                "rows": {
                    "type": "array",
                    "x-aws-idp-confidence-threshold": "0.7",
                    "items": {"$ref": "#/$defs/Row"},
                }
            },
            "$defs": {
                "Row": {
                    "type": "object",
                    "properties": {
                        "a": {"x-aws-idp-confidence-threshold": "0.95"},
                        "b": {},
                    },
                }
            },
        }
        default = 0.0
        assessment = {"rows": [{"a": {"confidence": 0.9}, "b": {"confidence": 0.9}}]}
        enriched, _ = enrich_assessment_with_thresholds(assessment, schema, default)

        for col in ("a", "b"):
            via_enrichment = enriched["rows"][0][col]["confidence_threshold"]
            via_path = resolve_threshold_for_path(["rows", "_0", col], schema, default)
            assert via_enrichment == via_path, (
                f"mismatch for column {col}: "
                f"enrichment={via_enrichment} path={via_path}"
            )

    def test_resolvers_diverge_on_nesting_below_array_items(self):
        """Pin the DOCUMENTED divergence between the two resolvers.

        ``resolve_threshold_for_path`` (BDA HITL alert path) walks arbitrary
        nesting; ``enrich_assessment_with_thresholds`` (pipeline assessment and
        BDA result.json paths) resolves only ONE level of array-item sub-fields,
        so a threshold on a field nested *below* an array item — or inside an
        array nested in an object group — falls back to the default there.

        This is a deliberate, documented limitation (see the note in
        docs/extraction-and-confidence.md, "Thresholds inside lists"). This test
        exists so that changing either resolver is a visible decision rather than
        a silent behavior change: if a future change unifies the two paths, this
        test fails and should be updated to assert agreement.
        """
        schema = {
            "properties": {
                # threshold two levels down: array item -> object -> field
                "w2_copies": {"type": "array", "items": {"$ref": "#/$defs/Item"}},
                # array nested inside an object group
                "employer": {
                    "type": "object",
                    "properties": {
                        "contacts": {
                            "type": "array",
                            "items": {
                                "properties": {
                                    "email": {"x-aws-idp-confidence-threshold": "0.99"}
                                }
                            },
                        }
                    },
                },
            },
            "$defs": {
                "Item": {
                    "type": "object",
                    "properties": {
                        "address": {
                            "type": "object",
                            "properties": {
                                "zip": {"x-aws-idp-confidence-threshold": "0.99"}
                            },
                        }
                    },
                }
            },
        }
        default = 0.5
        assessment = {
            "w2_copies": [{"address": {"zip": {"confidence": 0.4}}}],
            "employer": {"contacts": [{"email": {"confidence": 0.4}}]},
        }
        enriched, _alerts = enrich_assessment_with_thresholds(
            assessment, schema, default
        )

        # Path resolver reaches the nested declaration...
        assert (
            resolve_threshold_for_path(
                ["w2_copies", "_0", "address", "zip"], schema, default
            )
            == 0.99
        )
        assert (
            resolve_threshold_for_path(
                ["employer", "contacts", "_0", "email"], schema, default
            )
            == 0.99
        )
        # ...while enrichment falls back to the default at that depth.
        assert (
            enriched["w2_copies"][0]["address"]["zip"]["confidence_threshold"]
            == default
        )
        assert (
            enriched["employer"]["contacts"][0]["email"]["confidence_threshold"]
            == default
        )


class TestBDAAlertBuildingUsesPerEntryThreshold:
    """``create_confidence_threshold_alerts`` must compare each entry against its
    OWN resolved threshold, not one flat value. Replicated here without importing
    the Lambda module (which pulls Lambda-only deps)."""

    @staticmethod
    def _build_alerts(pagespecific_details, fallback):
        alerts = []
        for _page, kv_details in pagespecific_details.get(
            "key_value_details", {}
        ).items():
            for kv_entry in kv_details:
                confidence = kv_entry.get("confidence", 0.0)
                entry_threshold = kv_entry.get("confidence_threshold", fallback)
                if entry_threshold is None:
                    entry_threshold = fallback
                if confidence < entry_threshold:
                    alerts.append(
                        {
                            "attribute_name": kv_entry.get("key", ""),
                            "confidence": confidence,
                            "confidence_threshold": entry_threshold,
                        }
                    )
        return alerts

    def test_per_entry_threshold_drives_alert(self):
        """With hitl default 0.0, a 0.75-confidence SSN carrying a 0.8 per-field
        threshold must still alert — the old flat-0.0 comparison never would."""
        details = {
            "key_value_details": {
                "1": [
                    {
                        "key": "w2_copies[0].w2_box_a_employee_ssn",
                        "confidence": 0.75,
                        "confidence_threshold": 0.8,
                    },
                    {
                        "key": "w2_copies[0].w2_form_year",
                        "confidence": 0.6,
                        "confidence_threshold": 0.0,
                    },
                ]
            }
        }
        alerts = self._build_alerts(details, 0.0)
        assert len(alerts) == 1
        assert alerts[0]["attribute_name"] == "w2_copies[0].w2_box_a_employee_ssn"
        assert alerts[0]["confidence_threshold"] == 0.8

    def test_missing_entry_threshold_uses_fallback(self):
        details = {"key_value_details": {"1": [{"key": "f", "confidence": 0.5}]}}
        alerts = self._build_alerts(details, 0.9)
        assert len(alerts) == 1
        assert alerts[0]["confidence_threshold"] == 0.9

    def test_none_entry_threshold_uses_fallback(self):
        details = {
            "key_value_details": {
                "1": [{"key": "f", "confidence": 0.5, "confidence_threshold": None}]
            }
        }
        alerts = self._build_alerts(details, 0.9)
        assert len(alerts) == 1
        assert alerts[0]["confidence_threshold"] == 0.9
