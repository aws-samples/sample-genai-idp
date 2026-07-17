"""Unit tests for cleanup_stale_idp_buckets — the S3-bucket-leak startup reaper.

Buckets leak independently of stacks: CloudFormation can't delete a non-empty
bucket, so an interrupted `idp-cli delete` leaves the bucket behind even after
the stack is gone (thousands accumulated this way). This reaper is destructive,
so these mock-boto3 tests pin the SAFETY logic: never delete a bucket whose run
still has ANY CloudFormation stack (protected), never delete one younger than
the age gate, always empty versions before deleting, and only touch idp- names.
"""

from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.unit


class _FakeStackPaginator:
    def __init__(self, stack_names):
        self._names = stack_names

    def paginate(self, **kwargs):
        return [{"StackSummaries": [{"StackName": n} for n in self._names]}]


class _FakeS3Client:
    def __init__(self, buckets, live_stacks):
        # buckets: list of (name, age_seconds)
        self._buckets = buckets
        self._live_stacks = live_stacks
        self.deleted = []

    # used by _live_idp_run_prefixes
    def get_paginator(self, name):
        assert name == "list_stacks"
        return _FakeStackPaginator(self._live_stacks)

    def list_buckets(self):
        now = datetime.now(tz=timezone.utc)
        return {
            "Buckets": [
                {"Name": n, "CreationDate": now - timedelta(seconds=age)}
                for n, age in self._buckets
            ]
        }

    def delete_bucket(self, Bucket):
        self.deleted.append(Bucket)


class _FakeBucket:
    def __init__(self, name, emptied):
        self._name = name
        self._emptied = emptied

    @property
    def object_versions(self):
        parent = self

        class _OV:
            def delete(self):
                parent._emptied.append(parent._name)

        return _OV()


class _FakeS3Resource:
    def __init__(self):
        self.emptied = []

    def Bucket(self, name):
        return _FakeBucket(name, self.emptied)


def _install(cbd, monkeypatch, buckets, live_stacks):
    client = _FakeS3Client(buckets, live_stacks)
    resource = _FakeS3Resource()

    def fake_client(name, *a, **k):
        # both cloudformation (for _live_idp_run_prefixes) and s3 route to the
        # same fake — get_paginator/list_buckets/delete_bucket don't collide.
        return client

    monkeypatch.setattr(cbd.boto3, "client", fake_client)
    monkeypatch.setattr(cbd.boto3, "resource", lambda name, *a, **k: resource)
    return client, resource


def test_reaps_old_bucket_with_no_live_stack(cbd, monkeypatch):
    old = cbd.IDP_BUCKET_STALE_AGE_SECONDS + 3600
    client, resource = _install(
        cbd,
        monkeypatch,
        buckets=[("idp-0709-160356-inputbucket-abc", old)],
        live_stacks=[],  # no stacks at all → nothing protected
    )
    cbd.cleanup_stale_idp_buckets()
    assert client.deleted == ["idp-0709-160356-inputbucket-abc"]
    # must empty versions BEFORE deleting
    assert resource.emptied == ["idp-0709-160356-inputbucket-abc"]


def test_protects_bucket_whose_run_has_a_live_stack(cbd, monkeypatch):
    old = cbd.IDP_BUCKET_STALE_AGE_SECONDS + 3600
    client, _ = _install(
        cbd,
        monkeypatch,
        buckets=[("idp-0716-165247-outputbucket-xyz", old)],
        # the run's primary stack still exists → protect ALL its buckets
        live_stacks=["idp-0716-165247", "idp-0716-165247-headless-iam"],
    )
    cbd.cleanup_stale_idp_buckets()
    assert client.deleted == []


def test_skips_young_bucket_even_without_stack(cbd, monkeypatch):
    young = cbd.IDP_BUCKET_STALE_AGE_SECONDS - 600
    client, _ = _install(
        cbd,
        monkeypatch,
        buckets=[("idp-0716-170000-inputbucket-new", young)],
        live_stacks=[],
    )
    cbd.cleanup_stale_idp_buckets()
    # age gate is the backstop for a brand-new bucket whose stack hasn't
    # registered yet — must not delete it.
    assert client.deleted == []


def test_ignores_non_idp_buckets(cbd, monkeypatch):
    old = cbd.IDP_BUCKET_STALE_AGE_SECONDS + 3600
    client, _ = _install(
        cbd,
        monkeypatch,
        buckets=[
            ("some-other-bucket", old),
            ("genaiic-sdlc-sourcecode-020432867916-us-east-1", old),
            ("idp-0709-160356-inputbucket-abc", old),
        ],
        live_stacks=[],
    )
    cbd.cleanup_stale_idp_buckets()
    assert client.deleted == ["idp-0709-160356-inputbucket-abc"]


def test_mixed_batch_only_deletes_safe_ones(cbd, monkeypatch):
    old = cbd.IDP_BUCKET_STALE_AGE_SECONDS + 3600
    young = cbd.IDP_BUCKET_STALE_AGE_SECONDS - 600
    client, _ = _install(
        cbd,
        monkeypatch,
        buckets=[
            ("idp-0709-160356-inputbucket-a", old),  # delete
            ("idp-0716-165247-inputbucket-b", old),  # protected (live stack)
            ("idp-0716-170000-inputbucket-c", young),  # too young
            ("idp-0705-120000-outputbucket-d", old),  # delete
        ],
        live_stacks=["idp-0716-165247"],
    )
    cbd.cleanup_stale_idp_buckets()
    assert set(client.deleted) == {
        "idp-0709-160356-inputbucket-a",
        "idp-0705-120000-outputbucket-d",
    }


def test_delete_error_does_not_abort_batch(cbd, monkeypatch):
    old = cbd.IDP_BUCKET_STALE_AGE_SECONDS + 3600
    client, _ = _install(
        cbd,
        monkeypatch,
        buckets=[
            ("idp-0709-100000-inputbucket-a", old),
            ("idp-0709-200000-inputbucket-b", old),
        ],
        live_stacks=[],
    )
    orig = client.delete_bucket

    def flaky(Bucket):
        if Bucket.endswith("-a"):
            raise RuntimeError("BucketNotEmpty")
        orig(Bucket)

    monkeypatch.setattr(client, "delete_bucket", flaky)
    cbd.cleanup_stale_idp_buckets()
    # the second bucket still gets deleted despite the first raising
    assert client.deleted == ["idp-0709-200000-inputbucket-b"]


def test_never_raises_on_api_error(cbd, monkeypatch):
    class _Boom:
        def get_paginator(self, name):
            raise RuntimeError("throttled")

        def list_buckets(self):
            raise RuntimeError("throttled")

    monkeypatch.setattr(cbd.boto3, "client", lambda name, *a, **k: _Boom())
    monkeypatch.setattr(cbd.boto3, "resource", lambda name, *a, **k: object())
    cbd.cleanup_stale_idp_buckets()  # must swallow, not raise
