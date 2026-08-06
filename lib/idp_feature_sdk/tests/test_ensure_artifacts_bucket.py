# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Tests for ``ensure_artifacts_bucket`` S3 Block Public Access (BPA) behaviour.

These guard the security contract that pack publishing is **private by
default** and only opens a bucket to the world when ``make_public=True`` is
explicitly requested — and that a *pre-existing* bucket's BPA settings are
never weakened (so a manual security remediation can't be silently reverted
by a publish run).
"""

from __future__ import annotations

import json

import boto3
import pytest
from moto import mock_aws

from idp_feature_sdk.pack import apply_public_artifacts_policy, ensure_artifacts_bucket

REGION = "us-west-2"


def _bucket_name(account_id: str = "123456789012") -> str:
    return f"idp-accelerator-artifacts-{account_id}-{REGION}"


def _get_pab(s3, bucket: str) -> dict:
    return s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]


@pytest.fixture
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)


def _statement(s3, bucket: str, sid: str) -> dict | None:
    policy = json.loads(s3.get_bucket_policy(Bucket=bucket)["Policy"])
    return next((s for s in policy["Statement"] if s.get("Sid") == sid), None)


def _assert_enforce_ssl_only(s3, bucket: str) -> None:
    """The bucket policy denies every principal all S3 actions over plain HTTP,
    on both the bucket and its objects."""
    stmt = _statement(s3, bucket, "EnforceSSLOnly")
    assert stmt is not None, "EnforceSSLOnly statement missing"
    assert stmt["Effect"] == "Deny"
    assert stmt["Principal"] == "*"
    assert stmt["Action"] == "s3:*"
    assert stmt["Condition"] == {"Bool": {"aws:SecureTransport": "false"}}
    assert set(stmt["Resource"]) == {
        f"arn:aws:s3:::{bucket}",
        f"arn:aws:s3:::{bucket}/*",
    }


def test_new_bucket_default_is_private(aws_credentials):
    """A freshly-created bucket (no --public) gets ALL four BPA flags on
    and gets NO public-read bucket policy."""
    with mock_aws():
        bucket = ensure_artifacts_bucket(region=REGION)
        s3 = boto3.client("s3", region_name=REGION)

        pab = _get_pab(s3, bucket)
        assert pab["BlockPublicAcls"] is True
        assert pab["IgnorePublicAcls"] is True
        assert pab["BlockPublicPolicy"] is True
        assert pab["RestrictPublicBuckets"] is True

        # Only the TLS-enforcement statement — no public-read grant.
        policy = json.loads(s3.get_bucket_policy(Bucket=bucket)["Policy"])
        assert {s.get("Sid") for s in policy["Statement"]} == {"EnforceSSLOnly"}
        _assert_enforce_ssl_only(s3, bucket)


def test_new_bucket_gets_enforce_ssl_only_policy(aws_credentials):
    """Every bucket the pack CLI creates denies non-TLS access, matching the
    EnforceSSLOnly statement the CloudFormation-managed buckets carry."""
    with mock_aws():
        bucket = ensure_artifacts_bucket(region=REGION)
        _assert_enforce_ssl_only(boto3.client("s3", region_name=REGION), bucket)


def test_enforce_ssl_only_is_idempotent(aws_credentials):
    """Re-running against the same bucket leaves exactly one EnforceSSLOnly
    statement rather than appending duplicates."""
    with mock_aws():
        ensure_artifacts_bucket(region=REGION)
        bucket = ensure_artifacts_bucket(region=REGION)
        s3 = boto3.client("s3", region_name=REGION)
        policy = json.loads(s3.get_bucket_policy(Bucket=bucket)["Policy"])
        sids = [s.get("Sid") for s in policy["Statement"]]
        assert sids.count("EnforceSSLOnly") == 1


def test_enforce_ssl_only_preserves_operator_statements(aws_credentials):
    """Hardening is additive — an operator's own bucket-policy statement
    survives, and the public-read grant coexists with the TLS denial."""
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        bucket = _bucket_name()
        s3.create_bucket(
            Bucket=bucket,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
        s3.put_bucket_policy(
            Bucket=bucket,
            Policy=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Sid": "OperatorOwnGrant",
                            "Effect": "Allow",
                            "Principal": {"AWS": "123456789012"},
                            "Action": "s3:GetObject",
                            "Resource": f"arn:aws:s3:::{bucket}/*",
                        }
                    ],
                }
            ),
        )

        ensure_artifacts_bucket(region=REGION, make_public=True)

        policy = json.loads(s3.get_bucket_policy(Bucket=bucket)["Policy"])
        sids = {s.get("Sid") for s in policy["Statement"]}
        assert sids == {"OperatorOwnGrant", "EnforceSSLOnly", "PackPublicArtifactsRead"}
        _assert_enforce_ssl_only(s3, bucket)


def test_enforce_ssl_only_handles_single_object_statement(aws_credentials):
    """``Statement`` may legally be a single object rather than an array — the
    IAM grammar allows both. Iterating the object form naively yields its
    *keys*, which would replace the operator's statement with the strings
    "Sid", "Effect", … and produce an invalid policy."""
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        bucket = _bucket_name()
        s3.create_bucket(
            Bucket=bucket,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
        s3.put_bucket_policy(
            Bucket=bucket,
            Policy=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": {
                        "Sid": "OperatorOwnGrant",
                        "Effect": "Allow",
                        "Principal": {"AWS": "123456789012"},
                        "Action": "s3:GetObject",
                        "Resource": f"arn:aws:s3:::{bucket}/*",
                    },
                }
            ),
        )

        ensure_artifacts_bucket(region=REGION)

        policy = json.loads(s3.get_bucket_policy(Bucket=bucket)["Policy"])
        assert all(isinstance(s, dict) for s in policy["Statement"]), (
            f"non-dict statement written: {policy['Statement']}"
        )
        assert {s["Sid"] for s in policy["Statement"]} == {
            "OperatorOwnGrant",
            "EnforceSSLOnly",
        }
        operator = next(
            s for s in policy["Statement"] if s["Sid"] == "OperatorOwnGrant"
        )
        assert operator["Action"] == "s3:GetObject"
        _assert_enforce_ssl_only(s3, bucket)


def test_public_artifacts_policy_handles_single_object_statement(aws_credentials):
    """The same normalization applies to the public-read merge path, which had
    the identical latent flaw."""
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        bucket = "explicit-single-stmt-us-west-2"
        s3.create_bucket(
            Bucket=bucket,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
        s3.put_bucket_policy(
            Bucket=bucket,
            Policy=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": {
                        "Sid": "OperatorOwnGrant",
                        "Effect": "Allow",
                        "Principal": {"AWS": "123456789012"},
                        "Action": "s3:GetObject",
                        "Resource": f"arn:aws:s3:::{bucket}/*",
                    },
                }
            ),
        )

        apply_public_artifacts_policy(s3, bucket)

        policy = json.loads(s3.get_bucket_policy(Bucket=bucket)["Policy"])
        assert all(isinstance(s, dict) for s in policy["Statement"]), (
            f"non-dict statement written: {policy['Statement']}"
        )
        assert {s["Sid"] for s in policy["Statement"]} == {
            "OperatorOwnGrant",
            "PackPublicArtifactsRead",
        }


def test_enforce_ssl_only_uses_govcloud_partition(aws_credentials):
    """A GovCloud region yields arn:aws-us-gov ARNs, not arn:aws."""
    gov_region = "us-gov-west-1"
    with mock_aws():
        bucket = ensure_artifacts_bucket(region=gov_region)
        s3 = boto3.client("s3", region_name=gov_region)
        stmt = _statement(s3, bucket, "EnforceSSLOnly")
        assert stmt is not None
        assert set(stmt["Resource"]) == {
            f"arn:aws-us-gov:s3:::{bucket}",
            f"arn:aws-us-gov:s3:::{bucket}/*",
        }


def test_enforce_ssl_only_failure_is_not_fatal_on_existing_bucket(aws_credentials):
    """If we can't set the policy on a bucket we didn't create (operator owns
    it / no s3:PutBucketPolicy), publishing continues with a warning."""
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        bucket = _bucket_name()
        s3.create_bucket(
            Bucket=bucket,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )

        import botocore.exceptions

        import idp_feature_sdk.pack as pack_mod

        real_client = boto3.client

        def _deny_put_policy(service, **kwargs):
            client = real_client(service, **kwargs)
            if service == "s3":

                def _boom(**_):
                    raise botocore.exceptions.ClientError(
                        {"Error": {"Code": "AccessDenied", "Message": "denied"}},
                        "PutBucketPolicy",
                    )

                client.put_bucket_policy = _boom
            return client

        pack_mod.boto3.client = _deny_put_policy
        try:
            # Must not raise — the bucket already existed.
            assert ensure_artifacts_bucket(region=REGION) == bucket
        finally:
            pack_mod.boto3.client = real_client


def test_preexisting_bucket_bpa_left_untouched(aws_credentials):
    """If the bucket already exists (default-secure), a default publish run
    must NOT touch its Block Public Access settings — so a manual remediation
    is never reverted."""
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        bucket = _bucket_name()
        s3.create_bucket(
            Bucket=bucket,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
        # Operator's manual remediation: lock the bucket down fully.
        secure = {
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        }
        s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration=secure)

        returned = ensure_artifacts_bucket(region=REGION)
        assert returned == bucket

        # Still fully locked down — unchanged.
        assert _get_pab(s3, bucket) == secure
        # The only policy added is the (additive, tightening) TLS denial —
        # no public-read grant.
        policy = json.loads(s3.get_bucket_policy(Bucket=bucket)["Policy"])
        assert {s.get("Sid") for s in policy["Statement"]} == {"EnforceSSLOnly"}


def test_make_public_opt_in_relaxes_bpa_and_sets_policy(aws_credentials):
    """With make_public=True, BlockPublicPolicy/RestrictPublicBuckets are
    relaxed and the extensions/host public-read bucket policy is applied."""
    with mock_aws():
        bucket = ensure_artifacts_bucket(region=REGION, make_public=True)
        s3 = boto3.client("s3", region_name=REGION)

        pab = _get_pab(s3, bucket)
        assert pab["BlockPublicAcls"] is True
        assert pab["IgnorePublicAcls"] is True
        assert pab["BlockPublicPolicy"] is False
        assert pab["RestrictPublicBuckets"] is False

        policy = json.loads(s3.get_bucket_policy(Bucket=bucket)["Policy"])
        sids = {s.get("Sid") for s in policy["Statement"]}
        assert "PackPublicArtifactsRead" in sids
        # Public read on the artifact prefixes, but still HTTPS-only.
        assert "EnforceSSLOnly" in sids
        stmt = next(
            s for s in policy["Statement"] if s.get("Sid") == "PackPublicArtifactsRead"
        )
        assert stmt["Principal"] == "*"
        assert stmt["Action"] == "s3:GetObject"
        assert any(f"{bucket}/extensions/" in r for r in stmt["Resource"])
        assert any(f"{bucket}/host/" in r for r in stmt["Resource"])


def test_apply_public_artifacts_policy_on_explicit_bucket(aws_credentials):
    """`apply_public_artifacts_policy` (used by publish-pack --public on an
    explicit --bucket-basename) relaxes BPA and applies the public-read
    policy on a bucket it didn't create."""
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        bucket = "my-explicit-artifacts-us-west-2"
        s3.create_bucket(
            Bucket=bucket,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )

        apply_public_artifacts_policy(s3, bucket)

        pab = _get_pab(s3, bucket)
        assert pab["BlockPublicPolicy"] is False
        assert pab["RestrictPublicBuckets"] is False

        policy = json.loads(s3.get_bucket_policy(Bucket=bucket)["Policy"])
        sids = {s.get("Sid") for s in policy["Statement"]}
        assert "PackPublicArtifactsRead" in sids
