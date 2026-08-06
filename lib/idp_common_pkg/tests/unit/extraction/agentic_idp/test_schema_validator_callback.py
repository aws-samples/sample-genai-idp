# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""In-loop schema-validator callback behavior in _invoke_agent_for_extraction.

Requires the real strands package (skipped in CI / when unavailable, per the
conftest in this directory). Run with: pytest -m agentic tests/unit/extraction/agentic_idp/
"""

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import BaseModel

from idp_common.extraction import agentic_idp


class _Doc(BaseModel):
    status: str


class _FakeState:
    def __init__(self, value: dict[str, Any]):
        self._value = value

    def get(self, key: str):
        return self._value if key == "current_extraction" else None


class _FakeAgent:
    def __init__(self, value: dict[str, Any]):
        self.state = _FakeState(value)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.mark.agentic
def test_validator_triggers_one_more_round_then_returns():
    """An invalid-then-fixed flow: validator fails first, agent re-prompted, passes."""
    agent = _FakeAgent({"status": "paid"})
    calls = {"n": 0}

    async def _fake_invoke(agent, input):  # noqa: ARG001
        calls["n"] += 1
        return "resp"

    # First validator call says invalid, second says valid.
    verdicts = iter([(False, "fix status"), (True, "ok")])

    def _validator(data):  # noqa: ARG001
        return next(verdicts)

    with patch.object(agentic_idp, "invoke_agent_with_retry", _fake_invoke):
        response, result = _run(
            agentic_idp._invoke_agent_for_extraction(
                agent=agent,
                prompt_content=[],
                data_format=_Doc,
                max_extraction_retries=3,
                schema_validator=_validator,
            )
        )

    assert result is not None and result.status == "paid"
    assert calls["n"] == 2  # re-prompted exactly once after the first failure


@pytest.mark.agentic
def test_validator_exhausts_retries_returns_best_effort():
    """Persistent schema failure returns the best-effort result (for escalation)."""
    agent = _FakeAgent({"status": "paid"})

    async def _fake_invoke(agent, input):  # noqa: ARG001
        return "resp"

    with patch.object(agentic_idp, "invoke_agent_with_retry", _fake_invoke):
        response, result = _run(
            agentic_idp._invoke_agent_for_extraction(
                agent=agent,
                prompt_content=[],
                data_format=_Doc,
                max_extraction_retries=2,
                schema_validator=lambda data: (False, "still bad"),
            )
        )

    # Pydantic-valid object is returned so the service can escalate/alert on it.
    assert result is not None and result.status == "paid"


@pytest.mark.agentic
def test_no_validator_returns_immediately():
    agent = _FakeAgent({"status": "paid"})
    calls = {"n": 0}

    async def _fake_invoke(agent, input):  # noqa: ARG001
        calls["n"] += 1
        return "resp"

    with patch.object(agentic_idp, "invoke_agent_with_retry", _fake_invoke):
        response, result = _run(
            agentic_idp._invoke_agent_for_extraction(
                agent=agent,
                prompt_content=[],
                data_format=_Doc,
                max_extraction_retries=3,
                schema_validator=None,
            )
        )

    assert result is not None
    assert calls["n"] == 1  # no extra round without a validator
