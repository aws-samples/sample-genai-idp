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

from types import SimpleNamespace
from unittest.mock import patch

from idp_common.assessment.batching import enrich_assessment_with_thresholds
from idp_common.assessment.service import AssessmentCoreResult
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


class _TruncateOverN:
    """Fake AssessmentService for the integrated missing-row retry: truncates any
    call carrying more than ``max_rows`` rows (mimicking Nova Lite overflowing its
    output cap on an llm-geometry batch), scores cleanly otherwise."""

    def __init__(self, *, region=None, config=None, max_rows=2):
        self.max_rows = max_rows
        self.calls: list[int] = []

    def _resolve_confidence_escalation_model(self, class_label):
        # No escalation model configured for this fake — the ladder stays at
        # token-aware shrink + same-model retry (what this test exercises).
        return None

    def assess_results(
        self,
        *,
        class_label,
        extraction_results,
        document_text,
        page_images,
        ocr_text_confidence="",
        model_id_override=None,
    ):
        (field,) = [k for k, v in extraction_results.items() if isinstance(v, list)]
        rows = extraction_results[field]
        self.calls.append(len(rows))
        if len(rows) > self.max_rows:
            return AssessmentCoreResult(
                enhanced_assessment={field: {"confidence": 0.5}},
                parsing_succeeded=False,
                truncated=True,
                duration_seconds=1.0,
            )
        return AssessmentCoreResult(
            enhanced_assessment={field: [{"rate": {"confidence": 0.9}} for _ in rows]},
            parsing_succeeded=True,
            truncated=False,
            duration_seconds=1.0,
        )


def test_integrated_retry_splits_on_truncation():
    """Simple + integrated: rows the inline pass left unscored are re-assessed,
    and a retry chunk the confidence model TRUNCATES is recursively split until it
    fits — so integrated mode gets the same recovery as the separate path."""
    svc = _svc()
    svc._document_text = "doc"
    svc._page_images = []
    section_info = SimpleNamespace(class_label="invoice")

    # 5 rows extracted; the inline pass scored none (all null placeholders).
    extracted = {"Items": [{"rate": str(i)} for i in range(5)]}
    merged = {
        "Items": [{"rate": {"confidence": None}} for _ in range(5)],
    }

    fake = _TruncateOverN(max_rows=2)
    with patch("idp_common.assessment.service.AssessmentService", return_value=fake):
        out, alerts, split_stats = svc._retry_missing_integrated_rows(
            merged_assessment=merged,
            extracted_fields=extracted,
            section_info=section_info,
        )

    # Every row recovered a real confidence via adaptive splitting.
    assert all(row["rate"]["confidence"] == 0.9 for row in out["Items"])
    assert split_stats is not None
    assert split_stats["truncated_calls"] >= 1
    assert split_stats["splits"] >= 1
    assert split_stats["unrecoverable_rows"] == 0
    # A too-large retry chunk was shrunk to <= max_rows.
    assert any(c <= 2 for c in fake.calls)


def test_integrated_retry_noop_when_nothing_missing():
    """No unscored rows -> no assessment calls, no split_stats."""
    svc = _svc()
    svc._document_text = "doc"
    svc._page_images = []
    section_info = SimpleNamespace(class_label="invoice")

    extracted = {"Items": [{"rate": "1"}]}
    merged = {"Items": [{"rate": {"confidence": 0.95}}]}

    fake = _TruncateOverN()
    with patch("idp_common.assessment.service.AssessmentService", return_value=fake):
        out, alerts, split_stats = svc._retry_missing_integrated_rows(
            merged_assessment=merged,
            extracted_fields=extracted,
            section_info=section_info,
        )

    assert fake.calls == []
    assert split_stats is None
    assert out["Items"][0]["rate"]["confidence"] == 0.95
