"""Unit tests for _first_failure_reason — the deploy/pack failure surfacer.

Regression coverage for two bugs that caused a transform failure to be
misreported as a stale CopyObject/AccessDenied error:

  1. SAM/transform failures surface as a stack-level *_IN_PROGRESS event whose
     reason contains "failed with: ...", NOT a *_FAILED status. The old check
     only matched *_FAILED and missed them.
  2. The scan walked the ENTIRE event history, so a failure from a PRIOR
     operation was returned instead of the current one. It must stop at the
     current operation's "User Initiated" boundary.
"""

from __future__ import annotations

from idp_feature_sdk.pack import _first_failure_reason


class _FakeCfn:
    def __init__(self, events):
        self._events = events

    def describe_stack_events(self, StackName):  # noqa: N803 (boto3 casing)
        return {"StackEvents": self._events}


def _ev(logical, status, reason):
    return {
        "LogicalResourceId": logical,
        "ResourceStatus": status,
        "ResourceStatusReason": reason,
    }


def test_transform_failure_is_detected():
    """A transform failure (IN_PROGRESS + 'failed with' reason) is surfaced."""
    events = [  # newest-first, as boto3 returns them
        _ev(
            "my-stack",
            "UPDATE_IN_PROGRESS",
            "Transform AWS::Serverless-2016-10-31 failed with: Invalid ... "
            "[UiDeployerFunction] 'CodeUri' is not a valid S3 Uri",
        ),
        _ev("my-stack", "UPDATE_IN_PROGRESS", "User Initiated"),
    ]
    reason = _first_failure_reason(_FakeCfn(events), "arn")
    assert reason is not None
    assert "CodeUri" in reason


def test_stale_prior_failure_not_returned():
    """A *_FAILED from a PRIOR operation (before the current 'User Initiated')
    must NOT be returned — only the current operation is in scope."""
    events = [
        _ev("my-stack", "UPDATE_IN_PROGRESS", "User Initiated"),  # current op start
        # everything below is a previous operation
        _ev(
            "RegisterFeatureResource",
            "UPDATE_FAILED",
            "AccessDenied when calling CopyObject ... s3:ListBucket",
        ),
        _ev("my-stack", "UPDATE_IN_PROGRESS", "User Initiated"),
    ]
    # Current op has no failure event → None (not the stale CopyObject error).
    assert _first_failure_reason(_FakeCfn(events), "arn") is None


def test_current_failed_resource_is_returned():
    events = [
        _ev("BadResource", "CREATE_FAILED", "Resource creation cancelled"),
        _ev("my-stack", "CREATE_IN_PROGRESS", "User Initiated"),
    ]
    reason = _first_failure_reason(_FakeCfn(events), "arn")
    assert reason == "BadResource: Resource creation cancelled"


def test_api_error_returns_none():
    class _Boom:
        def describe_stack_events(self, StackName):  # noqa: N803
            raise RuntimeError("boom")

    assert _first_failure_reason(_Boom(), "arn") is None
