# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Non-agentic (simple) integrated confidence.

The simple extraction path, when ``confidence.mode == integrated``, asks the model
to return values + inline confidence in ONE inference. These lock in:
  - the {extraction, confidence} envelope is split (values -> inference_result,
    confidence -> metering marker), fixing the malformed inference_result bug;
  - a ``field_assessment`` sibling key (the shape a non-tool model emits when told
    to "call the provide_field_assessment tool") is lifted the same way, so the
    standalone Assessment step is skipped instead of double-billing;
  - a flat response (model ignored confidence) passes through untouched so the
    standalone Assessment step runs as the fallback;
  - the shared threshold-enrichment attaches confidence_threshold + alerts.
"""

from __future__ import annotations

from idp_common.assessment.batching import enrich_assessment_with_thresholds
from idp_common.config.models import IDPConfig
from idp_common.extraction.service import ExtractionService


def _svc():
    cfg = IDPConfig(
        **{
            "extraction": {
                "mode": "simple",
                "agentic": {"enabled": False},
                "confidence": {"mode": "integrated"},
            }
        }
    )
    svc = ExtractionService(config=cfg)
    svc._class_schema = {}
    return svc


def test_envelope_split_moves_confidence_to_metering():
    svc = _svc()
    metering = {}
    parsed = {
        "extraction": {"Agency": "ACME", "Items": [{"rate": "5"}]},
        "confidence": {
            "Agency": {"confidence": 0.9, "confidence_reason": "clear"},
            "Items": [{"rate": {"confidence": 0.8}}],
        },
    }
    values = svc._split_inline_confidence(parsed, metering)
    assert values == {"Agency": "ACME", "Items": [{"rate": "5"}]}
    assert "extraction" not in values and "confidence" not in values
    assert metering["_integrated_field_assessment"]["Agency"]["confidence"] == 0.9


def test_case_insensitive_envelope():
    svc = _svc()
    metering = {}
    parsed = {
        "Extraction": {"A": "1"},
        "Confidence": {"A": {"confidence": 0.7}},
    }
    values = svc._split_inline_confidence(parsed, metering)
    assert values == {"A": "1"}
    assert "_integrated_field_assessment" in metering


def test_field_assessment_sibling_is_lifted():
    # The shape a non-tool (simple) model emits given "call provide_field_assessment":
    # confidence rides as a `field_assessment` sibling next to the real fields.
    svc = _svc()
    metering = {}
    parsed = {
        "Agency": "ACME",
        "Total": "100",
        "Items": [{"rate": "5"}],
        "field_assessment": {
            "Agency": {"confidence": 0.95},
            "Total": {"confidence": 0.6, "confidence_reason": "faint"},
            "Items": [{"rate": {"confidence": 0.8}}],
        },
    }
    values = svc._split_inline_confidence(parsed, metering)
    # field_assessment stripped from values (no leak into inference_result)...
    assert values == {"Agency": "ACME", "Total": "100", "Items": [{"rate": "5"}]}
    assert "field_assessment" not in values
    # ...and lifted into the metering marker so the standalone step is skipped.
    assert metering["_integrated_field_assessment"]["Agency"]["confidence"] == 0.95


def test_confidence_sibling_is_lifted():
    # Some models use "confidence" as the sibling key alongside the fields.
    svc = _svc()
    metering = {}
    parsed = {
        "Agency": "ACME",
        "confidence": {"Agency": {"confidence": 0.9}},
    }
    values = svc._split_inline_confidence(parsed, metering)
    assert values == {"Agency": "ACME"}
    assert "_integrated_field_assessment" in metering


def test_real_field_named_field_assessment_not_lifted():
    # A genuine document field literally named "field_assessment" holding plain
    # values (no {"confidence": ...} leaves) must NOT be mistaken for confidence.
    svc = _svc()
    metering = {}
    parsed = {"Agency": "ACME", "field_assessment": "passed review"}
    values = svc._split_inline_confidence(parsed, metering)
    assert values == parsed
    assert "_integrated_field_assessment" not in metering


def test_flat_response_passes_through_no_marker():
    svc = _svc()
    metering = {}
    parsed = {"Agency": "ACME", "Total": "100"}
    values = svc._split_inline_confidence(parsed, metering)
    assert values == parsed
    assert "_integrated_field_assessment" not in metering


def test_real_field_named_extraction_not_split():
    # A genuine 3-key result that merely contains "extraction" must NOT split.
    svc = _svc()
    metering = {}
    parsed = {"extraction": "some value", "Agency": "ACME", "Total": "100"}
    values = svc._split_inline_confidence(parsed, metering)
    assert values == parsed
    assert "_integrated_field_assessment" not in metering


def test_envelope_without_usable_confidence_falls_back():
    svc = _svc()
    metering = {}
    parsed = {"extraction": {"A": "1"}, "confidence": None}
    values = svc._split_inline_confidence(parsed, metering)
    assert values == {"A": "1"}
    # no confidence to lift -> standalone step runs
    assert "_integrated_field_assessment" not in metering


def test_enrichment_attaches_thresholds_and_alerts():
    schema = {
        "properties": {
            "Agency": {"x-aws-idp-confidence-threshold": "0.8"},
            "Items": {"type": "array"},
        }
    }
    assessment = {
        "Agency": {"confidence": 0.7, "confidence_reason": "faint"},
        "Items": [{"rate": {"confidence": 0.95}}],
    }
    enriched, alerts = enrich_assessment_with_thresholds(assessment, schema, 0.9)
    assert enriched["Agency"]["confidence_threshold"] == 0.8
    assert enriched["Items"][0]["rate"]["confidence_threshold"] == 0.9
    # Agency 0.7 < 0.8 -> alert; Items rate 0.95 >= 0.9 -> no alert
    assert any(a["attribute_name"] == "Agency" for a in alerts)
    assert not any(a["attribute_name"].startswith("Items") for a in alerts)
