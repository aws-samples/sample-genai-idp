# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for token-budgeted page sharding (idp_common.extraction.sharding)."""

import pytest

from idp_common.extraction.sharding import (
    DEFAULT_MAX_PAGES_PER_SHARD,
    DEFAULT_SHARD_TOKEN_BUDGET,
    Shard,
    estimate_tokens,
    plan_shards,
)

pytestmark = pytest.mark.unit


def _covers_all(shards: list[Shard], n: int) -> bool:
    """Shards must tile [0, n) contiguously with no gaps/overlaps."""
    prev = 0
    for s in shards:
        if s.start != prev:
            return False
        prev = s.end
    return prev == n


class TestPlanShards:
    def test_single_page_is_one_shard(self):
        shards = plan_shards(["x" * 100000], token_budget=40000)
        assert len(shards) == 1
        assert (shards[0].start, shards[0].end) == (0, 1)

    def test_light_pages_fit_in_one_shard(self):
        # 3 pages ~1k tokens each, budget 40k -> single shard
        shards = plan_shards(["y" * 4000] * 3, token_budget=40000, max_shards=10)
        assert len(shards) == 1
        assert _covers_all(shards, 3)

    def test_dense_pages_split_by_budget(self):
        # 17 pages ~12k tokens each, budget 40k -> ~3 pages/shard
        pages = ["x" * 48000] * 17
        shards = plan_shards(pages, token_budget=40000, max_shards=10)
        assert _covers_all(shards, 17)
        # every shard within budget unless it is a single page
        for s in shards:
            toks = sum(estimate_tokens(pages[i]) for i in range(s.start, s.end))
            assert toks <= 40000 or s.page_count == 1

    def test_max_shards_cap_binds(self):
        # 17 pages each individually over budget -> would be 17 shards, capped to 10
        pages = ["z" * 200000] * 17
        shards = plan_shards(pages, token_budget=40000, max_shards=10)
        assert len(shards) == 10
        assert _covers_all(shards, 17)
        # no empty shards
        assert all(s.page_count >= 1 for s in shards)

    def test_no_cap_allows_many_shards(self):
        pages = ["z" * 200000] * 8  # each over budget
        shards = plan_shards(pages, token_budget=40000, max_shards=None)
        assert len(shards) == 8  # one per page
        assert _covers_all(shards, 8)

    def test_table_boundary_preference_splits_between_tables(self):
        # 6 medium pages (~15k tokens each); budget fits ~2 pages. Tables start
        # at pages 2 and 4 -> splits should land at those boundaries.
        pages = ["m" * 60000] * 6
        shards = plan_shards(
            pages,
            token_budget=40000,
            max_shards=10,
            table_boundary_pages=frozenset({2, 4}),
        )
        assert _covers_all(shards, 6)
        starts = {s.start for s in shards}
        # A new shard begins at each table boundary.
        assert 2 in starts and 4 in starts

    def test_empty_input(self):
        shards = plan_shards([], token_budget=40000)
        assert len(shards) == 1
        assert (shards[0].start, shards[0].end) == (0, 0)

    def test_estimate_tokens(self):
        assert estimate_tokens("") == 0
        assert estimate_tokens("a" * 400) == 100


class TestDefaults:
    def test_default_budget_is_lowered(self):
        # Regression guard: the 40K foot-gun default is gone; 8000 is proven to
        # shard large dense tables so a single agent never emits a giant table.
        assert DEFAULT_SHARD_TOKEN_BUDGET == 8_000

    def test_default_page_ceiling(self):
        assert DEFAULT_MAX_PAGES_PER_SHARD == 5


class TestPageCeiling:
    def test_compact_pages_still_shard_on_page_count(self):
        # 20 tiny pages whose total text fits ONE token budget would historically
        # NOT shard (the foot-gun). With the page ceiling they still shard.
        pages = ["tiny"] * 20  # ~1 token each, well under any budget
        shards = plan_shards(pages, token_budget=DEFAULT_SHARD_TOKEN_BUDGET)
        assert _covers_all(shards, 20)
        # default ceiling 5 -> 4 shards of 5 pages each
        assert len(shards) == 4
        assert all(s.page_count <= DEFAULT_MAX_PAGES_PER_SHARD for s in shards)

    def test_explicit_page_cap_binds_before_budget(self):
        pages = ["small"] * 12
        shards = plan_shards(pages, token_budget=1_000_000, max_pages_per_shard=3)
        assert _covers_all(shards, 12)
        assert len(shards) == 4
        assert all(s.page_count <= 3 for s in shards)

    def test_page_cap_disabled_with_zero(self):
        # Compact pages, page ceiling disabled -> a single shard (budget only).
        pages = ["tiny"] * 30
        shards = plan_shards(
            pages, token_budget=DEFAULT_SHARD_TOKEN_BUDGET, max_pages_per_shard=0
        )
        assert len(shards) == 1
        assert _covers_all(shards, 30)

    def test_page_cap_disabled_with_none(self):
        pages = ["tiny"] * 30
        shards = plan_shards(
            pages, token_budget=DEFAULT_SHARD_TOKEN_BUDGET, max_pages_per_shard=None
        )
        assert len(shards) == 1
        assert _covers_all(shards, 30)

    def test_token_budget_can_split_below_page_cap(self):
        # Dense pages (~12k tokens) with a small budget split on tokens before
        # reaching the page ceiling -> 1 page/shard even though ceiling is 5.
        pages = ["x" * 48000] * 6
        shards = plan_shards(
            pages, token_budget=DEFAULT_SHARD_TOKEN_BUDGET, max_pages_per_shard=5
        )
        assert _covers_all(shards, 6)
        assert all(s.page_count == 1 for s in shards)

    def test_both_bounds_whichever_first(self):
        # 100 compact pages, ceiling 5 -> exactly 20 shards (page-bound).
        pages = ["row data"] * 100
        shards = plan_shards(
            pages, token_budget=DEFAULT_SHARD_TOKEN_BUDGET, max_pages_per_shard=5
        )
        assert _covers_all(shards, 100)
        assert len(shards) == 20
