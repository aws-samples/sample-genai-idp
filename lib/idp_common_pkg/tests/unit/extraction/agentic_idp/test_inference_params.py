# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for ``_get_inference_params`` in ``idp_common.extraction.agentic_idp``.

These tests specifically guard the fix for GitHub issue #304 where agentic
extraction with Claude Opus 4.7 failed at ConverseStream with:

    ValidationException: `top_p` is deprecated for this model.

The agentic code path must omit ``temperature``/``top_p``/``top_k`` entirely
for Claude 4.7+ models, matching the behaviour already implemented in the
traditional ``idp_common.bedrock.client`` path.

Like the sibling tests in ``tests/unit/extraction/agentic_idp/``, these run
only when the real ``strands`` package is importable (see the directory-level
``conftest.py`` which unmocks ``strands`` / ``pyarrow`` etc. when available
and instructs pytest to ignore collection otherwise).
"""

from __future__ import annotations

import pytest

# Guard the import: in environments where strands-agents isn't installed
# (e.g. CI with only the core deps), the directory conftest will already
# skip collection, but we mirror the try/except pattern used by
# ``test_agentic_idp_unit.py`` for defence in depth.
try:
    from idp_common.extraction.agentic_idp import _get_inference_params

    STRANDS_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    STRANDS_AVAILABLE = False

# Mark the whole module as `agentic` so it is only collected when the real
# strands package is available (see directory conftest.py). Also keep a
# defensive skipif in case the module gets imported through a different path.
pytestmark = [
    pytest.mark.agentic,
    pytest.mark.skipif(
        not STRANDS_AVAILABLE,
        reason="strands-agents package not installed",
    ),
]


# ---------------------------------------------------------------------------
# Claude 4.7+ models: MUST return an empty dict (no temperature/top_p).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_id",
    [
        "anthropic.claude-opus-4-7",
        "us.anthropic.claude-opus-4-7",
        "us.anthropic.claude-opus-4-7:1m",
        "eu.anthropic.claude-opus-4-7",
        "eu.anthropic.claude-opus-4-7:1m",
        "global.anthropic.claude-opus-4-7",
        "global.anthropic.claude-opus-4-7:1m",
        "anthropic.claude-opus-4-8",
        "us.anthropic.claude-opus-4-8",
        "us.anthropic.claude-opus-4-8:1m",
        "eu.anthropic.claude-opus-4-8",
        "eu.anthropic.claude-opus-4-8:1m",
        "global.anthropic.claude-opus-4-8",
        "global.anthropic.claude-opus-4-8:1m",
        "anthropic.claude-opus-5",
        "us.anthropic.claude-opus-5",
        "us.anthropic.claude-opus-5:1m",
        "eu.anthropic.claude-opus-5",
        "eu.anthropic.claude-opus-5:1m",
        "global.anthropic.claude-opus-5",
        "global.anthropic.claude-opus-5:1m",
    ],
)
def test_claude_4_7_models_return_no_inference_params(model_id: str) -> None:
    """Claude 4.7+ models must not receive temperature/top_p/top_k."""
    # Even with non-default config values, the helper must strip them out.
    params = _get_inference_params(
        model_id=model_id,
        temperature=0.5,
        top_p=0.3,
    )
    assert params == {}, (
        f"Claude 4.7+ model {model_id!r} must not receive inference params, "
        f"got {params!r}. See GitHub issue #304."
    )


def test_claude_4_7_empty_with_none_top_p() -> None:
    """Claude 4.7+ still returns {} even when top_p is None."""
    params = _get_inference_params(
        model_id="us.anthropic.claude-opus-4-7",
        temperature=0.0,
        top_p=None,
    )
    assert params == {}


# ---------------------------------------------------------------------------
# Non-Claude-4.7 models: existing mutually-exclusive temperature/top_p logic
# must be preserved (regression guard).
# ---------------------------------------------------------------------------


def test_sonnet_4_uses_top_p_when_positive() -> None:
    """For non-4.7 models, positive top_p wins over temperature."""
    params = _get_inference_params(
        model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
        temperature=0.0,
        top_p=0.1,
    )
    assert params == {"top_p": 0.1}


def test_sonnet_4_uses_temperature_when_top_p_zero() -> None:
    """For non-4.7 models, zero/None top_p falls back to temperature."""
    params = _get_inference_params(
        model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
        temperature=0.5,
        top_p=0.0,
    )
    assert params == {"temperature": 0.5}


def test_sonnet_4_uses_temperature_when_top_p_none() -> None:
    params = _get_inference_params(
        model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
        temperature=0.7,
        top_p=None,
    )
    assert params == {"temperature": 0.7}


def test_opus_4_6_still_receives_params() -> None:
    """Opus 4.6 (and earlier) are NOT in the Claude 4.7+ set and must still
    receive inference params. This guards against over-matching the version
    regex/suffix handling.
    """
    params = _get_inference_params(
        model_id="us.anthropic.claude-opus-4-6-v1",
        temperature=0.0,
        top_p=0.1,
    )
    assert params == {"top_p": 0.1}


def test_opus_4_6_1m_still_receives_params() -> None:
    """The :1m suffix handling must not accidentally match Opus 4.6."""
    params = _get_inference_params(
        model_id="us.anthropic.claude-opus-4-6-v1:1m",
        temperature=0.0,
        top_p=0.2,
    )
    assert params == {"top_p": 0.2}


def test_nova_models_still_receive_params() -> None:
    params = _get_inference_params(
        model_id="us.amazon.nova-pro-v1:0",
        temperature=0.0,
        top_p=0.1,
    )
    assert params == {"top_p": 0.1}
