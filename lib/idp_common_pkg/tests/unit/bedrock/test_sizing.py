# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Model-aware auto-sizing (idp_common.bedrock.sizing.compute_sizing_plan)."""

from __future__ import annotations

import pytest
from idp_common.bedrock.sizing import compute_sizing_plan

NOVA_LITE = "us.amazon.nova-lite-v1:0"
SONNET5 = "us.anthropic.claude-sonnet-5"
SONNET5_1M = "us.anthropic.claude-sonnet-5:1m"


def test_larger_input_window_gives_larger_shard_budget():
    """A 1M-context model gets a much larger shard token budget than a 200K one."""
    base = compute_sizing_plan(model_id=SONNET5, context_buffer=0.3)
    big = compute_sizing_plan(model_id=SONNET5_1M, context_buffer=0.3)
    assert big.shard_token_budget > base.shard_token_budget
    assert big.max_input_tokens == 1_000_000
    assert base.max_input_tokens == 200_000


def test_context_buffer_reduces_budgets():
    """A larger context buffer leaves less usable window → smaller budgets."""
    low = compute_sizing_plan(model_id=SONNET5_1M, context_buffer=0.15)
    high = compute_sizing_plan(model_id=SONNET5_1M, context_buffer=0.6)
    assert high.shard_token_budget < low.shard_token_budget
    assert high.list_batch_size <= low.list_batch_size


def test_bbox_geometry_shrinks_list_batch():
    """Per-row output is larger with bbox geometry → smaller list batch.

    Use a high context buffer so the derived sizes land below the reliability
    cap (otherwise both clamp to the cap and the geometry effect is hidden)."""
    ocr = compute_sizing_plan(
        model_id=NOVA_LITE, geometry_mode="ocr_only", context_buffer=0.85
    )
    bbox = compute_sizing_plan(
        model_id=NOVA_LITE, geometry_mode="llm_grounded", context_buffer=0.85
    )
    assert bbox.list_batch_size < ocr.list_batch_size


def test_list_batch_capped_for_reliability():
    """Even a huge-output model does not batch more than the reliability cap."""
    plan = compute_sizing_plan(model_id=SONNET5_1M, geometry_mode="ocr_only")
    assert plan.list_batch_size <= 50


def test_unknown_model_falls_back_conservatively():
    """An unknown model still yields a sane (non-crashing) plan that shards."""
    plan = compute_sizing_plan(model_id="some.unknown.model-v9:0")
    assert plan.shard_token_budget >= 2000
    assert plan.list_batch_size >= 1


def test_none_model_uses_fallback():
    plan = compute_sizing_plan(model_id=None)
    assert plan.max_input_tokens > 0
    assert plan.list_batch_size >= 1


def test_overrides_short_circuit_derivation():
    """Explicit overrides win over auto-derivation and are recorded."""
    plan = compute_sizing_plan(
        model_id=SONNET5_1M,
        shard_token_budget_override=9999,
        max_pages_per_shard_override=3,
        list_batch_size_override=7,
    )
    assert plan.shard_token_budget == 9999
    assert plan.max_pages_per_shard == 3
    assert plan.list_batch_size == 7
    assert plan.overrides == {
        "shard_token_budget": 9999,
        "max_pages_per_shard": 3,
        "list_batch_size": 7,
    }


def test_image_reserve_scales_with_max_images():
    """More attached images reserve more input tokens (less for OCR text)."""
    few = compute_sizing_plan(model_id=SONNET5, max_images_per_agent=2)
    many = compute_sizing_plan(model_id=SONNET5, max_images_per_agent=20)
    assert many.image_reserve_tokens > few.image_reserve_tokens
    assert many.shard_token_budget < few.shard_token_budget


def test_plan_to_dict_round_trips_key_fields():
    plan = compute_sizing_plan(model_id=SONNET5, context_buffer=0.3)
    d = plan.to_dict()
    assert d["model_id"] == SONNET5
    assert d["context_buffer"] == pytest.approx(0.3)
    assert "shard_token_budget" in d and "list_batch_size" in d


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
