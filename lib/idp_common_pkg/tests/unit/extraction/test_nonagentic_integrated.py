# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Non-agentic (simple) integrated confidence — 1S-TopK.

The simple extraction path, when ``confidence.mode == integrated``, uses the
1S-TopK prompt: the model returns, per field, its top-K guesses with
probabilities (``G1/P1`` … ``GK/PK``) in ONE inference. These lock in:
  - a TopK candidate response is split (``G1`` -> inference_result, ``P1`` ->
    the ``_integrated_field_assessment`` metering marker) so the standalone
    Assessment step is skipped instead of double-billing, with the full
    candidate set stashed in ``_topk_candidates`` for audit;
  - list/array fields resolve per-row/per-column;
  - a flat response (no G1/P1 candidates) passes through untouched so the
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


def test_topk_scalar_split_moves_confidence_to_metering():
    # Each field is a {G1, P1, ...} candidate object. G1 -> value, P1 -> confidence.
    svc = _svc()
    svc._class_schema = {"properties": {"Agency": {}, "Total": {"type": "number"}}}
    metering = {}
    parsed = {
        "Agency": {"G1": "ACME", "P1": 0.9, "G2": "ACMY", "P2": 0.1},
        "Total": {"G1": "100", "P1": 0.7},
    }
    values = svc._split_inline_confidence(parsed, metering)
    assert values == {"Agency": "ACME", "Total": 100.0}  # number coerced
    assert metering["_integrated_field_assessment"]["Agency"]["confidence"] == 0.9
    assert metering["_integrated_field_assessment"]["Total"]["confidence"] == 0.7
    # Raw candidates preserved for audit.
    assert metering["_topk_candidates"]["Agency"]["G2"] == "ACMY"


def test_topk_list_split_resolves_per_row():
    # Direct-array TopK: each row's sub-attributes are {G1, P1, ...} candidates.
    svc = _svc()
    svc._class_schema = {
        "properties": {
            "Items": {"type": "array", "items": {"properties": {"rate": {}}}}
        }
    }
    metering = {}
    parsed = {
        "Items": [
            {"rate": {"G1": "5", "P1": 0.8}},
            {"rate": {"G1": "6", "P1": 0.6}},
        ]
    }
    values = svc._split_inline_confidence(parsed, metering)
    assert values == {"Items": [{"rate": "5"}, {"rate": "6"}]}
    assess = metering["_integrated_field_assessment"]["Items"]
    assert assess[0]["rate"]["confidence"] == 0.8
    assert assess[1]["rate"]["confidence"] == 0.6


def test_topk_confidence_leaves_have_no_threshold():
    # The resolver emits confidence-only leaves; thresholds are attached later by
    # the shared enricher (single source of truth for thresholds).
    svc = _svc()
    svc._class_schema = {"properties": {"Agency": {}}}
    metering = {}
    svc._split_inline_confidence({"Agency": {"G1": "ACME", "P1": 0.9}}, metering)
    leaf = metering["_integrated_field_assessment"]["Agency"]
    assert leaf == {"confidence": 0.9}
    assert "confidence_threshold" not in leaf


def test_flat_response_passes_through_no_marker():
    # No G1/P1 candidates -> not TopK; pass through and let the standalone
    # Assessment step run as the fallback.
    svc = _svc()
    metering = {}
    parsed = {"Agency": "ACME", "Total": "100"}
    values = svc._split_inline_confidence(parsed, metering)
    assert values == parsed
    assert "_integrated_field_assessment" not in metering
    assert "_topk_candidates" not in metering


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
