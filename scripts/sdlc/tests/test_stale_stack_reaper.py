"""Unit tests for cleanup_stale_idp_stacks — the IAM-role-leak startup reaper.

The reaper is the durability guarantee that leaked `-iam` stacks (and their
per-run roles) can't accumulate and exhaust the account RolesPerAccount quota
when a run's own cleanup is interrupted. These tests mock boto3 so they need no
AWS: they verify the age gate (never delete an in-flight concurrent run), the
nested-stack skip (only top-level stacks are deleted; parents cascade), the
apigw-vpc skip (owned by the other reaper), and the main-before-iam delete
ordering.
"""

from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.unit


class _FakePaginator:
    def __init__(self, summaries):
        self._summaries = summaries

    def paginate(self, **kwargs):
        return [{"StackSummaries": self._summaries}]


class _FakeCfn:
    def __init__(self, summaries):
        self._summaries = summaries
        self.deleted = []

    def get_paginator(self, name):
        return _FakePaginator(self._summaries)

    def delete_stack(self, StackName):
        self.deleted.append(StackName)


def _summary(name, age_seconds, root=None, parent=None):
    now = datetime.now(tz=timezone.utc)
    s = {
        "StackName": name,
        "CreationTime": now - timedelta(seconds=age_seconds),
    }
    if root:
        s["RootId"] = root
    if parent:
        s["ParentId"] = parent
    return s


def _install(cbd, monkeypatch, summaries):
    fake = _FakeCfn(summaries)
    monkeypatch.setattr(cbd.boto3, "client", lambda name, *a, **k: fake)
    return fake


def test_reaper_deletes_old_stacks(cbd, monkeypatch):
    old = cbd.IDP_STACK_STALE_AGE_SECONDS + 3600
    fake = _install(
        cbd,
        monkeypatch,
        [
            _summary("idp-0709-211927", old),
            _summary("idp-0709-211927-iam", old),
        ],
    )
    cbd.cleanup_stale_idp_stacks()
    assert set(fake.deleted) == {"idp-0709-211927", "idp-0709-211927-iam"}


def test_reaper_skips_young_stacks(cbd, monkeypatch):
    # A stack younger than the age gate could be a concurrent pipeline's
    # in-flight run — must NOT be deleted.
    young = cbd.IDP_STACK_STALE_AGE_SECONDS - 600
    fake = _install(
        cbd,
        monkeypatch,
        [
            _summary("idp-0716-150000", young),
            _summary("idp-0716-150000-iam", young),
        ],
    )
    cbd.cleanup_stale_idp_stacks()
    assert fake.deleted == []


def test_reaper_skips_nested_stacks(cbd, monkeypatch):
    # Nested stacks (RootId/ParentId set) are deleted by their parent cascade,
    # never directly.
    old = cbd.IDP_STACK_STALE_AGE_SECONDS + 3600
    fake = _install(
        cbd,
        monkeypatch,
        [
            _summary("idp-0709-211927", old),
            _summary(
                "idp-0709-211927-PATTERNSTACK-ABC",
                old,
                root="arn:...:stack/idp-0709-211927/x",
                parent="arn:...:stack/idp-0709-211927/x",
            ),
        ],
    )
    cbd.cleanup_stale_idp_stacks()
    assert fake.deleted == ["idp-0709-211927"]


def test_reaper_skips_apigw_vpc(cbd, monkeypatch):
    # *-apigw-vpc is owned by cleanup_stale_apigw_test_vpcs (ENI-aware delete);
    # this reaper must leave it alone.
    old = cbd.IDP_STACK_STALE_AGE_SECONDS + 3600
    fake = _install(
        cbd,
        monkeypatch,
        [
            _summary("idp-0715-200655-apigw-vpc", old),
            _summary("idp-0709-211927", old),
        ],
    )
    cbd.cleanup_stale_idp_stacks()
    assert fake.deleted == ["idp-0709-211927"]


def test_reaper_deletes_main_before_iam(cbd, monkeypatch):
    # The main stack references its -iam CFServiceRole; deleting -iam first can
    # strand the main stack. Order: non-iam stacks first, then -iam.
    old = cbd.IDP_STACK_STALE_AGE_SECONDS + 3600
    fake = _install(
        cbd,
        monkeypatch,
        [
            _summary("idp-0709-211927-iam", old),
            _summary("idp-0709-211927", old),
            _summary("idp-0709-211927-headless", old),
            _summary("idp-0709-211927-headless-iam", old),
        ],
    )
    cbd.cleanup_stale_idp_stacks()
    # Every -iam delete must come after all non-iam deletes.
    last_non_iam = max(
        i for i, n in enumerate(fake.deleted) if not n.endswith("-iam")
    )
    first_iam = min(i for i, n in enumerate(fake.deleted) if n.endswith("-iam"))
    assert last_non_iam < first_iam
    assert len(fake.deleted) == 4


def test_reaper_ignores_non_idp_stacks(cbd, monkeypatch):
    old = cbd.IDP_STACK_STALE_AGE_SECONDS + 3600
    fake = _install(
        cbd,
        monkeypatch,
        [
            _summary("genaiic-sdlc-codepipeline", old),  # the pipeline stack itself
            _summary("some-other-stack", old),
            _summary("idp-0709-211927", old),
        ],
    )
    cbd.cleanup_stale_idp_stacks()
    assert fake.deleted == ["idp-0709-211927"]


def test_reaper_never_raises_on_api_error(cbd, monkeypatch):
    class _Boom:
        def get_paginator(self, name):
            raise RuntimeError("throttled")

    monkeypatch.setattr(cbd.boto3, "client", lambda name, *a, **k: _Boom())
    # Best-effort: must swallow the error, not propagate it.
    cbd.cleanup_stale_idp_stacks()
