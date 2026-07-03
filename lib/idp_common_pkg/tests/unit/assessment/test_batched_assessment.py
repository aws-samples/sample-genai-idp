# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Shared large-list assessment batching (idp_common.assessment.batching).

These lock in the safety net that lets the STANDALONE (non-agentic) Assessment
step handle large lists on its own — the capability that previously lived only in
granular assessment. A single assessment inference over a 120-row table
under-enumerates or omits the list; ``assess_results_batched`` slices it into
``list_batch_size`` chunks, assesses each with the shared scalars/context, and
reconciles the concatenated per-row assessments to full per-cell coverage.
"""

from __future__ import annotations

import pytest
from idp_common.assessment.batching import (
    assess_results_batched,
    reconcile_assessment_to_data,
)
from idp_common.assessment.service import AssessmentCoreResult


class FakeAssessmentService:
    """Stand-in exposing the ``assess_results`` core the batcher calls.

    Records each call's row count for the batched list field and returns a
    per-row assessment covering only the rows it was handed — mimicking a model
    that DOES enumerate the rows it sees but is only ever shown a slice.
    """

    def __init__(self, list_field: str):
        self.list_field = list_field
        self.calls: list[int] = []

    def assess_results(
        self,
        *,
        class_label: str,
        extraction_results: dict,
        document_text: str,
        page_images: list,
        ocr_text_confidence: str = "",
    ) -> AssessmentCoreResult:
        rows = extraction_results.get(self.list_field, [])
        self.calls.append(len(rows))
        enhanced = {
            self.list_field: [
                {"confidence": 0.9, "confidence_reason": "clear"} for _ in rows
            ],
            "account_holder": {"confidence": 0.95, "confidence_reason": "header"},
        }
        return AssessmentCoreResult(
            enhanced_assessment=enhanced,
            confidence_threshold_alerts=[{"attribute_name": self.list_field}],
            metering={
                "Assessment/bedrock/model": {"inputTokens": 10, "outputTokens": 5}
            },
            parsing_succeeded=True,
            duration_seconds=1.0,
        )


def _rows(n: int) -> list[dict]:
    return [{"date": f"2020-01-{i:02d}", "amount": f"{i}.00"} for i in range(1, n + 1)]


def test_large_list_is_batched_and_fully_covered():
    """A 120-row list with batch_size 25 → 5 sequential calls, all 120 rows
    assessed with per-column confidence, and the scalar assessment preserved."""
    svc = FakeAssessmentService("transactions")
    data = {"transactions": _rows(120), "account_holder": "Jane Doe"}

    result = assess_results_batched(
        svc,
        class_label="bank-statement",
        extraction_results=data,
        document_text="...",
        page_images=[],
        batch_size=25,
    )

    # 120 rows / 25 = ceil -> 5 sequential batches (never a 20-way fan-out).
    assert svc.calls == [25, 25, 25, 25, 20]

    assessed = result["assessment"]["transactions"]
    assert len(assessed) == 120  # every row present
    # Every list cell got per-column confidence (fanned out from per-row score).
    assert all(set(row.keys()) == {"date", "amount"} for row in assessed), (
        "each row must carry a per-column leaf for date and amount"
    )
    assert all(row["date"]["confidence"] == 0.9 for row in assessed)

    # Scalar/group assessment from the first batch survives.
    assert result["assessment"]["account_holder"]["confidence"] == 0.95

    # Metering accumulated across all 5 calls; duration summed; parse ok.
    assert result["metering"]["Assessment/bedrock/model"]["inputTokens"] == 50
    assert result["metering"]["Assessment/bedrock/model"]["outputTokens"] == 25
    assert result["duration_seconds"] == pytest.approx(5.0)
    assert result["parsing_succeeded"] is True
    # One alert per batch accumulated.
    assert len(result["alerts"]) == 5


def test_small_list_single_call_still_reconciles():
    """A list at/under the batch size uses a single call — still reconciled to
    full per-cell coverage (no unassessed rows leak through)."""
    svc = FakeAssessmentService("transactions")
    data = {"transactions": _rows(10), "account_holder": "Jane Doe"}

    result = assess_results_batched(
        svc,
        class_label="bank-statement",
        extraction_results=data,
        document_text="...",
        page_images=[],
        batch_size=25,
    )

    assert svc.calls == [10]  # single call, no batching
    assessed = result["assessment"]["transactions"]
    assert len(assessed) == 10
    assert all(set(row.keys()) == {"date", "amount"} for row in assessed)


def test_batches_pad_when_model_underenumerates():
    """Even when a batch's model response omits rows, reconciliation pads to the
    batch's row count so the concatenated result covers every extracted row."""

    class UnderEnumeratingService(FakeAssessmentService):
        def assess_results(self, **kwargs):
            # Model returns only the FIRST row's assessment per batch.
            core = super().assess_results(**kwargs)
            core.enhanced_assessment[self.list_field] = core.enhanced_assessment[
                self.list_field
            ][:1]
            return core

    svc = UnderEnumeratingService("transactions")
    data = {"transactions": _rows(60)}

    result = assess_results_batched(
        svc,
        class_label="bank-statement",
        extraction_results=data,
        document_text="...",
        page_images=[],
        batch_size=25,
        max_retries=0,  # isolate reconcile/pad behavior from the retry pass
    )

    assessed = result["assessment"]["transactions"]
    assert len(assessed) == 60  # padded back to full extracted count
    # First row of each batch keeps real confidence; the rest are null placeholders.
    assert assessed[0]["date"]["confidence"] == 0.9
    assert assessed[1]["date"]["confidence"] is None


def test_reconcile_aligns_list_length():
    """reconcile_assessment_to_data truncates over-long and pads short lists."""
    data = {"txns": _rows(3)}
    out = reconcile_assessment_to_data({"txns": [{"confidence": 0.9}]}, data)
    assert len(out["txns"]) == 3
    assert out["txns"][0]["date"]["confidence"] == 0.9  # fanned to per-column
    assert out["txns"][2]["date"]["confidence"] is None  # padded placeholder


class DropLastFirstPass(FakeAssessmentService):
    """Drops the last row on the FIRST full-list pass, scores everything it's
    handed on any later (retry) call — a model that under-counts once but scores
    a focused re-ask of just the missing rows."""

    def __init__(self, list_field, full_len):
        super().__init__(list_field)
        self.full_len = full_len

    def assess_results(self, **kw):
        core = super().assess_results(**kw)
        rows = kw["extraction_results"].get(self.list_field, [])
        if len(rows) == self.full_len and len(self.calls) == 1:
            core.enhanced_assessment[self.list_field] = core.enhanced_assessment[
                self.list_field
            ][:-1]
        return core


def test_missing_rows_are_retried_to_full_coverage():
    """A row dropped on the first pass is recovered by the bounded retry → every
    list cell ends with a real (non-null) confidence, no null placeholders."""
    svc = DropLastFirstPass("transactions", full_len=10)
    data = {"transactions": _rows(10)}
    result = assess_results_batched(
        svc,
        class_label="bank-statement",
        extraction_results=data,
        document_text="...",
        page_images=[],
        batch_size=25,  # single-call path, then retry
    )
    assessed = result["assessment"]["transactions"]
    assert len(assessed) == 10
    for row in assessed:
        for leaf in row.values():
            assert leaf["confidence"] is not None
    assert len(svc.calls) >= 2  # retry happened


def test_retry_stops_when_no_progress():
    """If the model can never score a row, retry stops after bounded rounds and
    leaves the null placeholder (no infinite loop)."""

    class NeverScoresLastRow(FakeAssessmentService):
        def assess_results(self, **kw):
            core = super().assess_results(**kw)
            rows = kw["extraction_results"].get(self.list_field, [])
            if len(rows) > 1:
                core.enhanced_assessment[self.list_field] = core.enhanced_assessment[
                    self.list_field
                ][:-1]
            else:
                core.enhanced_assessment[self.list_field] = []
            return core

    svc = NeverScoresLastRow("transactions")
    data = {"transactions": _rows(5)}
    result = assess_results_batched(
        svc,
        class_label="bank-statement",
        extraction_results=data,
        document_text="...",
        page_images=[],
        batch_size=25,
        max_retries=2,
    )
    assessed = result["assessment"]["transactions"]
    assert len(assessed) == 5
    assert assessed[-1]["date"]["confidence"] is None
