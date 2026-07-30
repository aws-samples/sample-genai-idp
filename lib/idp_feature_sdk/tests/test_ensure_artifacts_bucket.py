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


def test_new_bucket_default_is_private(aws_credentials):
    """A freshly-created bucket (no --public) gets ALL four BPA flags on
    and gets NO public bucket policy."""
    with mock_aws():
        bucket = ensure_artifacts_bucket(region=REGION)
        s3 = boto3.client("s3", region_name=REGION)

        pab = _get_pab(s3, bucket)
        assert pab["BlockPublicAcls"] is True
        assert pab["IgnorePublicAcls"] is True
        assert pab["BlockPublicPolicy"] is True
        assert pab["RestrictPublicBuckets"] is True

        # No public-read policy should have been attached.
        with pytest.raises(Exception) as exc:
            s3.get_bucket_policy(Bucket=bucket)
        assert "NoSuchBucketPolicy" in str(exc.value)


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
        with pytest.raises(Exception) as exc:
            s3.get_bucket_policy(Bucket=bucket)
        assert "NoSuchBucketPolicy" in str(exc.value)


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
