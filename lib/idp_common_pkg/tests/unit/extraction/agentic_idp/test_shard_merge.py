# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Merge + context-overflow detection for sharded concurrent extraction.

Requires the real strands package (the helpers live in agentic_idp). Skipped in
CI / when unavailable per the conftest in this directory.
Run with: pytest -m agentic tests/unit/extraction/agentic_idp/
"""

import pytest
from idp_common.extraction.agentic_idp import (
    _is_context_overflow_error,
    _merge_shard_results,
)
from pydantic import BaseModel

pytestmark = pytest.mark.agentic


class _Model(BaseModel):
    account: str | None = None
    statement_period: str | None = None
    transactions: list | None = None


def _result(d: dict):
    """Build a (data, response) tuple like a shard agent returns."""
    return (_Model(**d), {"metering": {}})


class TestMergeShardResults:
    def test_lists_concatenate_in_order(self):
        results = [
            _result({"transactions": [{"r": 1}, {"r": 2}]}),
            _result({"transactions": [{"r": 3}]}),
            _result({"transactions": [{"r": 4}, {"r": 5}]}),
        ]
        merged, _metering, conflicts = _merge_shard_results(results, _Model)
        assert [t["r"] for t in merged["transactions"]] == [1, 2, 3, 4, 5]
        assert conflicts == []

    def test_scalar_first_non_null_wins(self):
        # Shard 1 has the account (page 1); later shards see it as null.
        results = [
            _result({"account": "12345", "transactions": [{"r": 1}]}),
            _result({"account": None, "transactions": [{"r": 2}]}),
        ]
        merged, _m, conflicts = _merge_shard_results(results, _Model)
        assert merged["account"] == "12345"
        assert conflicts == []

    def test_scalar_conflict_recorded_first_kept(self):
        results = [
            _result({"account": "12345"}),
            _result({"account": "99999"}),  # disagreement
        ]
        merged, _m, conflicts = _merge_shard_results(results, _Model)
        assert merged["account"] == "12345"  # first wins
        assert len(conflicts) == 1
        assert conflicts[0]["field"] == "account"
        assert conflicts[0]["kept"] == "12345"
        assert conflicts[0]["discarded"] == "99999"

    def test_all_null_scalar_stays_null(self):
        results = [
            _result({"transactions": [{"r": 1}]}),
            _result({"transactions": [{"r": 2}]}),
        ]
        merged, _m, conflicts = _merge_shard_results(results, _Model)
        assert merged.get("account") is None
        assert conflicts == []


class TestContextOverflowDetection:
    def test_detects_strands_summarizer_message(self):
        e = Exception("Cannot summarize: insufficient messages for summarization")
        assert _is_context_overflow_error(e) is True

    def test_detects_by_type_name(self):
        class ContextWindowOverflowException(Exception):
            pass

        assert (
            _is_context_overflow_error(ContextWindowOverflowException("boom")) is True
        )

    def test_detects_context_window_text(self):
        assert (
            _is_context_overflow_error(
                Exception("input is too long for the context window")
            )
            is True
        )

    def test_ignores_unrelated_errors(self):
        assert _is_context_overflow_error(ValueError("some random failure")) is False
        assert _is_context_overflow_error(KeyError("missing")) is False
