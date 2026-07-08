# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for the DATE evaluation method (Stickler v0.5.0 DateComparator).

Covers the legacy comparator helpers (compare_date / compare_values) so the
format-insensitive date matching contract is locked in.
"""

import pytest
from idp_common.evaluation.comparator import compare_date, compare_values
from idp_common.evaluation.models import EvaluationMethod


@pytest.mark.unit
class TestCompareDate:
    """Direct tests of the compare_date helper."""

    def test_same_day_different_format_matches(self):
        matched, score = compare_date("2024-01-05", "January 5, 2024")
        assert matched is True
        assert score == 1.0

    def test_slash_vs_iso_matches(self):
        matched, score = compare_date("01/05/2024", "2024-01-05")
        assert matched is True
        assert score == 1.0

    def test_different_dates_do_not_match(self):
        matched, score = compare_date("2024-01-05", "2024-06-30")
        assert matched is False
        assert score == 0.0

    def test_both_none_matches(self):
        matched, score = compare_date(None, None)
        assert matched is True
        assert score == 1.0

    def test_one_none_does_not_match(self):
        matched, score = compare_date("2024-01-05", None)
        assert matched is False
        assert score == 0.0

    def test_datetime_ignores_time_component(self):
        # A value that carries a time still matches the same calendar day.
        matched, score = compare_date("2024-01-05 09:30 AM", "2024-01-05")
        assert matched is True
        assert score == 1.0


@pytest.mark.unit
class TestCompareValuesDate:
    """compare_values dispatch for EvaluationMethod.DATE."""

    def test_dispatch_matches_format_variants(self):
        matched, score, reason = compare_values(
            "2024-01-05", "01/05/2024", EvaluationMethod.DATE
        )
        assert matched is True
        assert score == 1.0
        assert reason is None

    def test_dispatch_mismatch(self):
        matched, score, _ = compare_values(
            "2024-01-05", "2024-06-30", EvaluationMethod.DATE
        )
        assert matched is False
        assert score == 0.0

    def test_dispatch_both_empty(self):
        # Shared empty-value shortcut in compare_values.
        matched, score, _ = compare_values(None, None, EvaluationMethod.DATE)
        assert matched is True
        assert score == 1.0

    def test_dispatch_uses_binary_match_not_generic_threshold(self):
        # DATE is binary: a "close but different" date must NOT match even
        # though the generic default threshold (0.8) would be permissive for a
        # similarity score.
        matched, score, _ = compare_values(
            "2024-01-05", "2024-01-06", EvaluationMethod.DATE
        )
        assert matched is False
        assert score < 1.0
