# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Tests for the ``EnforceSSLOnly`` bucket policy applied to buckets the CLIs
create imperatively (``idp-cli publish`` artifacts bucket, ``idp-cli deploy``
config-staging bucket).

Buckets created by CloudFormation get this statement from an
``AWS::S3::BucketPolicy`` in ``template.yaml``; these guard the equivalent for
the API-created ones.
"""

from __future__ import annotations

import json

import boto3
import botocore.exceptions
import pytest
from moto import mock_aws

from idp_sdk._core.s3_security import (
    apply_enforce_ssl_only,
    enforce_ssl_only_policy,
    get_partition,
    merge_enforce_ssl_only,
    statement_list,
)

REGION = "us-west-2"


@pytest.fixture
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)


def _statement(s3, bucket: str, sid: str = "EnforceSSLOnly") -> dict | None:
    policy = json.loads(s3.get_bucket_policy(Bucket=bucket)["Policy"])
    return next((s for s in policy["Statement"] if s.get("Sid") == sid), None)


def _make_bucket(s3, bucket: str, region: str = REGION) -> None:
    if region == "us-east-1":
        s3.create_bucket(Bucket=bucket)
    else:
        s3.create_bucket(
            Bucket=bucket,
            CreateBucketConfiguration={"LocationConstraint": region},
        )


# --------------------------------------------------------------------------
# Policy-document shape
# --------------------------------------------------------------------------


def test_policy_document_shape():
    """Deny s3:* for every principal when aws:SecureTransport is false, on both
    the bucket ARN and its objects."""
    policy = enforce_ssl_only_policy("my-bucket", REGION)
    assert policy["Version"] == "2012-10-17"
    (stmt,) = policy["Statement"]
    assert stmt["Sid"] == "EnforceSSLOnly"
    assert stmt["Effect"] == "Deny"
    assert stmt["Principal"] == "*"
    assert stmt["Action"] == "s3:*"
    assert stmt["Condition"] == {"Bool": {"aws:SecureTransport": "false"}}
    assert set(stmt["Resource"]) == {
        "arn:aws:s3:::my-bucket",
        "arn:aws:s3:::my-bucket/*",
    }


@pytest.mark.parametrize(
    "region,expected",
    [
        ("us-west-2", "aws"),
        ("us-east-1", "aws"),
        ("us-gov-west-1", "aws-us-gov"),
        ("cn-north-1", "aws-cn"),
        (None, "aws"),
    ],
)
def test_get_partition(region, expected):
    assert get_partition(region) == expected


def test_govcloud_arns_use_gov_partition():
    stmt = enforce_ssl_only_policy("gov-bucket", "us-gov-west-1")["Statement"][0]
    assert set(stmt["Resource"]) == {
        "arn:aws-us-gov:s3:::gov-bucket",
        "arn:aws-us-gov:s3:::gov-bucket/*",
    }


# --------------------------------------------------------------------------
# Merge semantics
# --------------------------------------------------------------------------


def test_merge_into_empty_policy():
    merged = merge_enforce_ssl_only(None, "b", REGION)
    assert [s["Sid"] for s in merged["Statement"]] == ["EnforceSSLOnly"]


def test_merge_preserves_other_statements():
    existing = {
        "Version": "2012-10-17",
        "Statement": [{"Sid": "OperatorGrant", "Effect": "Allow"}],
    }
    merged = merge_enforce_ssl_only(existing, "b", REGION)
    assert [s["Sid"] for s in merged["Statement"]] == [
        "OperatorGrant",
        "EnforceSSLOnly",
    ]


def test_merge_handles_single_object_statement():
    """``Statement`` may legally be a single object rather than an array — the
    IAM grammar allows both. Iterating the object form naively yields its
    *keys*, which would replace the operator's statement with the strings
    "Sid", "Effect", … and produce an invalid policy."""
    existing = {
        "Version": "2012-10-17",
        "Statement": {
            "Sid": "OperatorGrant",
            "Effect": "Allow",
            "Principal": {"AWS": "123456789012"},
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::b/*",
        },
    }
    merged = merge_enforce_ssl_only(existing, "b", REGION)
    # Every statement is still a dict — no stringified key leaked in.
    assert all(isinstance(s, dict) for s in merged["Statement"])
    assert [s["Sid"] for s in merged["Statement"]] == [
        "OperatorGrant",
        "EnforceSSLOnly",
    ]
    # The operator's grant survives intact, not reduced to its field names.
    operator = merged["Statement"][0]
    assert operator["Action"] == "s3:GetObject"
    assert operator["Principal"] == {"AWS": "123456789012"}


def test_merge_replaces_stale_enforce_ssl_in_single_object_form():
    """A single-object Statement that IS the EnforceSSLOnly statement is
    replaced rather than duplicated."""
    existing = {
        "Version": "2012-10-17",
        "Statement": {
            "Sid": "EnforceSSLOnly",
            "Effect": "Deny",
            "Resource": ["stale"],
        },
    }
    merged = merge_enforce_ssl_only(existing, "b", REGION)
    assert [s["Sid"] for s in merged["Statement"]] == ["EnforceSSLOnly"]
    assert merged["Statement"][0]["Resource"] == [
        "arn:aws:s3:::b",
        "arn:aws:s3:::b/*",
    ]


@pytest.mark.parametrize("raw", ["a-string", 42])
def test_statement_list_refuses_malformed_statement(raw):
    """A Statement that's neither object nor list is refused rather than
    silently dropped — writing a policy that discarded it would be worse."""
    with pytest.raises(ValueError, match="Unsupported"):
        statement_list({"Version": "2012-10-17", "Statement": raw})


def test_statement_list_normalizes_both_forms():
    assert statement_list(None) == []
    assert statement_list({}) == []
    assert statement_list({"Statement": {"Sid": "A"}}) == [{"Sid": "A"}]
    assert statement_list({"Statement": [{"Sid": "A"}]}) == [{"Sid": "A"}]


def test_merge_replaces_stale_enforce_ssl_statement():
    """A pre-existing EnforceSSLOnly (e.g. with a wrong partition) is replaced,
    not duplicated."""
    existing = {
        "Version": "2012-10-17",
        "Statement": [
            {"Sid": "EnforceSSLOnly", "Effect": "Deny", "Resource": ["stale"]},
            {"Sid": "Other", "Effect": "Allow"},
        ],
    }
    merged = merge_enforce_ssl_only(existing, "b", REGION)
    sids = [s["Sid"] for s in merged["Statement"]]
    assert sids.count("EnforceSSLOnly") == 1
    assert "Other" in sids
    stmt = next(s for s in merged["Statement"] if s["Sid"] == "EnforceSSLOnly")
    assert stmt["Resource"] == ["arn:aws:s3:::b", "arn:aws:s3:::b/*"]


# --------------------------------------------------------------------------
# apply_enforce_ssl_only against S3
# --------------------------------------------------------------------------


def test_apply_to_bucket_with_no_policy(aws_credentials):
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        _make_bucket(s3, "no-policy-bucket")

        assert apply_enforce_ssl_only(s3, "no-policy-bucket", REGION) is True
        stmt = _statement(s3, "no-policy-bucket")
        assert stmt is not None and stmt["Effect"] == "Deny"


def test_apply_is_idempotent(aws_credentials):
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        _make_bucket(s3, "idem-bucket")

        apply_enforce_ssl_only(s3, "idem-bucket", REGION)
        apply_enforce_ssl_only(s3, "idem-bucket", REGION)

        policy = json.loads(s3.get_bucket_policy(Bucket="idem-bucket")["Policy"])
        sids = [s.get("Sid") for s in policy["Statement"]]
        assert sids.count("EnforceSSLOnly") == 1


def test_apply_preserves_existing_statements(aws_credentials):
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        _make_bucket(s3, "shared-bucket")
        s3.put_bucket_policy(
            Bucket="shared-bucket",
            Policy=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Sid": "OperatorGrant",
                            "Effect": "Allow",
                            "Principal": {"AWS": "123456789012"},
                            "Action": "s3:GetObject",
                            "Resource": "arn:aws:s3:::shared-bucket/*",
                        }
                    ],
                }
            ),
        )

        apply_enforce_ssl_only(s3, "shared-bucket", REGION)

        policy = json.loads(s3.get_bucket_policy(Bucket="shared-bucket")["Policy"])
        assert {s.get("Sid") for s in policy["Statement"]} == {
            "OperatorGrant",
            "EnforceSSLOnly",
        }


def test_apply_preserves_a_single_object_statement_end_to_end(aws_credentials):
    """End-to-end guard for the single-object ``Statement`` form: the written
    policy must keep the operator's grant as a real statement, not as the
    stringified field names iterating a dict would produce."""
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        _make_bucket(s3, "single-stmt-bucket")
        s3.put_bucket_policy(
            Bucket="single-stmt-bucket",
            Policy=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": {
                        "Sid": "OperatorGrant",
                        "Effect": "Allow",
                        "Principal": {"AWS": "123456789012"},
                        "Action": "s3:GetObject",
                        "Resource": "arn:aws:s3:::single-stmt-bucket/*",
                    },
                }
            ),
        )

        assert apply_enforce_ssl_only(s3, "single-stmt-bucket", REGION) is True

        policy = json.loads(s3.get_bucket_policy(Bucket="single-stmt-bucket")["Policy"])
        assert all(isinstance(s, dict) for s in policy["Statement"]), (
            f"non-dict statement written: {policy['Statement']}"
        )
        assert {s["Sid"] for s in policy["Statement"]} == {
            "OperatorGrant",
            "EnforceSSLOnly",
        }
        operator = next(s for s in policy["Statement"] if s["Sid"] == "OperatorGrant")
        assert operator["Action"] == "s3:GetObject"


def _s3_denying_put_policy(region: str = REGION):
    """Real moto S3 client whose PutBucketPolicy raises AccessDenied."""
    client = boto3.client("s3", region_name=region)

    def _boom(**_):
        raise botocore.exceptions.ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "denied"}},
            "PutBucketPolicy",
        )

    client.put_bucket_policy = _boom  # type: ignore[method-assign]
    return client


def test_apply_raises_by_default_on_failure(aws_credentials):
    with mock_aws():
        s3 = _s3_denying_put_policy()
        _make_bucket(boto3.client("s3", region_name=REGION), "deny-bucket")

        with pytest.raises(RuntimeError) as exc:
            apply_enforce_ssl_only(s3, "deny-bucket", REGION)
        assert "EnforceSSLOnly" in str(exc.value)


def test_apply_warns_instead_of_raising_when_asked(aws_credentials, caplog):
    with mock_aws():
        s3 = _s3_denying_put_policy()
        _make_bucket(boto3.client("s3", region_name=REGION), "warn-bucket")

        result = apply_enforce_ssl_only(s3, "warn-bucket", REGION, raise_on_error=False)
        assert result is False
        assert "EnforceSSLOnly" in caplog.text


# --------------------------------------------------------------------------
# Call sites: publish artifacts bucket + deploy config-staging bucket
# --------------------------------------------------------------------------


def test_publish_setup_artifacts_bucket_applies_policy(aws_credentials):
    """`idp-cli publish` hardens the artifacts bucket it creates."""
    with mock_aws():
        from idp_sdk._core.publish import IDPPublisher

        publisher = IDPPublisher()
        publisher.region = REGION
        publisher.bucket = "publish-artifacts-bucket"
        publisher.s3_client = boto3.client("s3", region_name=REGION)

        publisher.setup_artifacts_bucket()

        stmt = _statement(publisher.s3_client, "publish-artifacts-bucket")
        assert stmt is not None
        assert stmt["Condition"] == {"Bool": {"aws:SecureTransport": "false"}}


def test_publish_setup_artifacts_bucket_hardens_existing_bucket(aws_credentials):
    """An operator-supplied --bucket-basename that already exists also gets
    the TLS denial (additive, so it can't revert a remediation)."""
    with mock_aws():
        from idp_sdk._core.publish import IDPPublisher

        s3 = boto3.client("s3", region_name=REGION)
        _make_bucket(s3, "preexisting-artifacts")

        publisher = IDPPublisher()
        publisher.region = REGION
        publisher.bucket = "preexisting-artifacts"
        publisher.s3_client = s3

        publisher.setup_artifacts_bucket()

        assert _statement(s3, "preexisting-artifacts") is not None


def test_deploy_config_bucket_applies_policy(aws_credentials):
    """`idp-cli deploy` hardens the config-staging bucket it creates."""
    with mock_aws():
        from idp_sdk._core.stack import get_or_create_config_bucket

        bucket = get_or_create_config_bucket(REGION)
        s3 = boto3.client("s3", region_name=REGION)

        stmt = _statement(s3, bucket)
        assert stmt is not None
        assert stmt["Effect"] == "Deny"
        assert set(stmt["Resource"]) == {
            f"arn:aws:s3:::{bucket}",
            f"arn:aws:s3:::{bucket}/*",
        }


def test_deploy_config_bucket_hardens_reused_bucket(aws_credentials):
    """A config bucket left behind by an older idp-cli (created without the
    policy) is hardened when it's reused, not just when it's created.

    `get_or_create_config_bucket` returns early on a prefix match, so these —
    the buckets most likely to be unhardened — would otherwise stay that way
    forever, since this function is the only code that touches them.
    """
    with mock_aws():
        from idp_sdk._core.stack import get_or_create_config_bucket

        first = get_or_create_config_bucket(REGION)
        s3 = boto3.client("s3", region_name=REGION)

        # Simulate the pre-fix state: bucket exists, no policy.
        s3.delete_bucket_policy(Bucket=first)

        second = get_or_create_config_bucket(REGION)
        assert second == first, "expected the existing bucket to be reused"
        assert _statement(s3, second) is not None


def test_deploy_config_bucket_reuse_survives_put_policy_denial(aws_credentials):
    """Hardening a reused config bucket is best-effort: a PutBucketPolicy
    denial must not break the deploy that just needs to stage a config."""
    with mock_aws():
        import idp_sdk._core.stack as stack_mod

        get_or_create_config_bucket = stack_mod.get_or_create_config_bucket
        bucket = get_or_create_config_bucket(REGION)
        s3 = boto3.client("s3", region_name=REGION)
        s3.delete_bucket_policy(Bucket=bucket)

        real_client = stack_mod.boto3.client

        def _boom(**_):
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "denied"}},
                "PutBucketPolicy",
            )

        def _deny(service, **kwargs):
            # Build the client from the *unpatched* factory — calling the
            # patched name here would recurse.
            client = real_client(service, **kwargs)
            if service == "s3":
                client.put_bucket_policy = _boom
            return client

        stack_mod.boto3.client = _deny
        try:
            assert get_or_create_config_bucket(REGION) == bucket
        finally:
            stack_mod.boto3.client = real_client

        # Still no policy (the denial stood), but the deploy path continued.
        with pytest.raises(Exception, match="NoSuchBucketPolicy"):
            s3.get_bucket_policy(Bucket=bucket)
