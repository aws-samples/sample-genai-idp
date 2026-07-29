# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Tests for the DockerBuildRun custom resource's build-retry behavior.

A failed container build is usually environmental (a PyPI/ECR connection drop
mid-wheel-download surfaces as a hard `pip ... exit 2`), and a single failure
used to cascade all the way to a failed stack deploy: CodeBuild FAILED → custom
resource FAILED → nested stack CREATE_FAILED → parent rollback. One rebuild
turns that into a couple of minutes of delay.

The retry must be scoped: a deliberate STOPPED build is not retried, and the
handler must always leave enough Lambda budget to actually answer
CloudFormation (an unanswered custom resource hangs the stack for a full hour).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import index  # noqa: E402


class _Context:
    """Lambda context with a shrinking, controllable time budget."""

    def __init__(self, remaining_secs=900):
        self.log_stream_name = "test-stream"
        self._remaining_ms = remaining_secs * 1000

    def get_remaining_time_in_millis(self):
        return self._remaining_ms

    def burn(self, secs):
        self._remaining_ms = max(0, self._remaining_ms - secs * 1000)


def _event(request_type="Create"):
    return {
        "RequestType": request_type,
        "ResourceProperties": {"ProjectName": "DockerBuildProject-abc"},
        "StackId": "arn:aws:cloudformation:us-east-1:1:stack/s/1",
        "RequestId": "req-1",
        "LogicalResourceId": "DockerBuildRun",
        "ResponseURL": "https://cfn-response.example/x",
    }


@pytest.fixture
def harness(monkeypatch):
    """Patch the module's AWS client, sleep, and CFN response sender."""
    sent = []
    monkeypatch.setattr(index, "send_response", lambda *a, **k: sent.append((a, k)))
    monkeypatch.setattr(index.time, "sleep", lambda s: None)
    cb = MagicMock()
    monkeypatch.setattr(index, "codebuild", cb)
    return cb, sent


def _statuses(cb, sequence):
    """Program start_build/batch_get_builds to walk a status sequence.

    `sequence` is a list of per-build status lists: one entry per start_build
    call, each a list of statuses returned by successive polls.
    """
    build_ids = [f"proj:{i}" for i in range(len(sequence))]
    cb.start_build.side_effect = [{"build": {"id": bid}} for bid in build_ids]
    polls = []
    for bid, statuses in zip(build_ids, sequence):
        for st in statuses:
            polls.append({"builds": [{"id": bid, "buildStatus": st}]})
    cb.batch_get_builds.side_effect = polls
    return build_ids


def _status_of(sent):
    (args, _kwargs) = sent[-1]
    return args[2]


def _reason_of(sent):
    (_args, kwargs) = sent[-1]
    return kwargs.get("reason", "")


# --------------------------------------------------------------------------- #
# the fix: retry a failed build once
# --------------------------------------------------------------------------- #


def test_failed_build_is_retried_and_success_reported(harness):
    """The 2026-07-27 case: build 1 dies on a pip network drop, build 2 passes."""
    cb, sent = harness
    _statuses(cb, [["IN_PROGRESS", "FAILED"], ["IN_PROGRESS", "SUCCEEDED"]])

    index.handler(_event(), _Context())

    assert cb.start_build.call_count == 2
    assert _status_of(sent) == "SUCCESS"


def test_retry_happens_at_most_once(harness):
    """A deterministic build error must surface, not loop forever."""
    cb, sent = harness
    _statuses(cb, [["FAILED"], ["FAILED"]])

    index.handler(_event(), _Context())

    assert cb.start_build.call_count == index.MAX_BUILD_ATTEMPTS == 2
    assert _status_of(sent) == "FAILED"


def test_first_attempt_success_does_not_retry(harness):
    cb, sent = harness
    _statuses(cb, [["SUCCEEDED"]])

    index.handler(_event(), _Context())

    assert cb.start_build.call_count == 1
    assert _status_of(sent) == "SUCCESS"


def test_fault_status_is_retried(harness):
    """FAULT is an infrastructure error on CodeBuild's side — retryable."""
    cb, sent = harness
    _statuses(cb, [["FAULT"], ["SUCCEEDED"]])

    index.handler(_event(), _Context())

    assert cb.start_build.call_count == 2
    assert _status_of(sent) == "SUCCESS"


def test_stopped_build_is_not_retried(harness):
    """STOPPED means someone cancelled it deliberately; respect that."""
    cb, sent = harness
    _statuses(cb, [["STOPPED"]])

    index.handler(_event(), _Context())

    assert cb.start_build.call_count == 1
    assert _status_of(sent) == "FAILED"


def test_timed_out_build_is_not_retried(harness):
    """A build that hit CodeBuild's own timeout will just time out again."""
    cb, sent = harness
    _statuses(cb, [["TIMED_OUT"]])

    index.handler(_event(), _Context())

    assert cb.start_build.call_count == 1
    assert _status_of(sent) == "FAILED"


# --------------------------------------------------------------------------- #
# budget safety — always answer CloudFormation
# --------------------------------------------------------------------------- #


def test_no_retry_when_lambda_budget_is_nearly_gone(harness):
    """Better to report the first failure than to be killed mid-second-build.

    A Lambda that dies without responding leaves the stack waiting an hour.
    """
    cb, sent = harness
    _statuses(cb, [["FAILED"]])
    ctx = _Context(remaining_secs=index.RESPONSE_RESERVE_SECS + 20)

    index.handler(_event(), ctx)

    assert cb.start_build.call_count == 1
    assert _status_of(sent) == "FAILED"


def test_polling_stops_before_the_response_reserve(harness, monkeypatch):
    """Polling must leave RESPONSE_RESERVE_SECS to send the CFN response."""
    cb, sent = harness
    cb.start_build.return_value = {"build": {"id": "proj:slow"}}
    cb.batch_get_builds.return_value = {
        "builds": [{"id": "proj:slow", "buildStatus": "IN_PROGRESS"}]
    }
    ctx = _Context(remaining_secs=200)
    # Each poll burns real budget so the loop can terminate.
    monkeypatch.setattr(index.time, "sleep", lambda s: ctx.burn(s))

    index.handler(_event(), ctx)

    assert _status_of(sent) == "FAILED"
    assert "did not complete within the Lambda budget" in _reason_of(sent)
    # Budget left for the response itself.
    assert ctx.get_remaining_time_in_millis() / 1000.0 >= 0


def test_timeout_reason_names_the_project(harness, monkeypatch):
    cb, sent = harness
    cb.start_build.return_value = {"build": {"id": "proj:slow"}}
    cb.batch_get_builds.return_value = {
        "builds": [{"id": "proj:slow", "buildStatus": "IN_PROGRESS"}]
    }
    ctx = _Context(remaining_secs=120)
    monkeypatch.setattr(index.time, "sleep", lambda s: ctx.burn(s))

    index.handler(_event(), ctx)

    assert "DockerBuildProject-abc" in _reason_of(sent)


# --------------------------------------------------------------------------- #
# failure reporting — point at where the real cause lives
# --------------------------------------------------------------------------- #


def test_failure_reason_points_to_codebuild_logs(harness):
    """The old reason was just "CodeBuild failed with status: FAILED".

    That dead-ends the investigation; the reason must name the build + project
    so a reader knows where to look.
    """
    cb, sent = harness
    _statuses(cb, [["FAILED"], ["FAILED"]])

    index.handler(_event(), _Context())

    reason = _reason_of(sent)
    assert "DockerBuildProject-abc" in reason
    assert "proj:1" in reason
    assert "log" in reason.lower()


# --------------------------------------------------------------------------- #
# unchanged behavior
# --------------------------------------------------------------------------- #


def test_delete_request_succeeds_without_building(harness):
    cb, sent = harness

    index.handler(_event("Delete"), _Context())

    cb.start_build.assert_not_called()
    assert _status_of(sent) == "SUCCESS"


def test_unexpected_exception_reports_failure(harness):
    cb, sent = harness
    cb.start_build.side_effect = RuntimeError("AccessDeniedException")

    index.handler(_event(), _Context())

    assert _status_of(sent) == "FAILED"
    assert "AccessDenied" in _reason_of(sent)


def test_update_request_builds_like_create(harness):
    cb, sent = harness
    _statuses(cb, [["SUCCEEDED"]])

    index.handler(_event("Update"), _Context())

    assert cb.start_build.call_count == 1
    assert _status_of(sent) == "SUCCESS"
