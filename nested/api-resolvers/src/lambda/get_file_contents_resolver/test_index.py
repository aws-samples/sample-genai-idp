# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for get_file_contents_resolver.

Covers both resolver fields:
  - getFileContents      -> inline file bytes (6 MB Lambda cap)
  - getFilePresignedUrl  -> presigned GET URL (no size limit; browser fetches
                            directly from S3)
"""

import importlib

import boto3
import pytest
from moto import mock_aws

OUTPUT_BUCKET = "output-bucket"
OTHER_BUCKET = "some-unrelated-bucket"


def _event(field, s3_uri, version_id=None):
    args = {"s3Uri": s3_uri}
    if version_id is not None:
        args["versionId"] = version_id
    return {
        "info": {"fieldName": field},
        "arguments": args,
        "identity": {"claims": {"cognito:groups": ["Admin"]}},
    }


@pytest.fixture
def resolver(monkeypatch):
    monkeypatch.setenv("OUTPUT_BUCKET", OUTPUT_BUCKET)
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=OUTPUT_BUCKET)
        s3.create_bucket(Bucket=OTHER_BUCKET)
        s3.put_object(
            Bucket=OUTPUT_BUCKET,
            Key="doc/sections/1/result.json",
            Body=b'{"hello": "world"}',
            ContentType="application/json",
        )

        # Import after mock + env are in place so the module-level S3 client and
        # ALLOWED_BUCKETS are built against moto/the test env.
        import index

        importlib.reload(index)
        yield index, s3


@pytest.mark.unit
def test_get_file_contents_returns_inline_bytes(resolver):
    index, _ = resolver
    result = index.handler(
        _event("getFileContents", f"s3://{OUTPUT_BUCKET}/doc/sections/1/result.json"),
        None,
    )
    assert result["content"] == '{"hello": "world"}'
    assert result["contentType"] == "application/json"
    assert result["isBinary"] is False


@pytest.mark.unit
def test_get_file_presigned_url_returns_url_and_metadata(resolver):
    index, _ = resolver
    result = index.handler(
        _event(
            "getFilePresignedUrl",
            f"s3://{OUTPUT_BUCKET}/doc/sections/1/result.json",
        ),
        None,
    )
    assert result["presignedUrl"].startswith("https://")
    assert "doc/sections/1/result.json" in result["presignedUrl"]
    assert result["contentType"] == "application/json"
    assert result["size"] == len(b'{"hello": "world"}')
    # Must NOT return the file bytes inline.
    assert "content" not in result


@pytest.mark.unit
def test_get_file_presigned_url_missing_object_raises(resolver):
    index, _ = resolver
    with pytest.raises(Exception, match="File not found"):
        index.handler(
            _event("getFilePresignedUrl", f"s3://{OUTPUT_BUCKET}/doc/does-not-exist.json"),
            None,
        )


@pytest.mark.unit
def test_bucket_allow_list_enforced_for_presigned_url(resolver):
    index, _ = resolver
    with pytest.raises(Exception, match="Error fetching file|Unauthorized"):
        index.handler(
            _event("getFilePresignedUrl", f"s3://{OTHER_BUCKET}/secret.json"),
            None,
        )


@pytest.mark.unit
def test_invalid_uri_raises(resolver):
    index, _ = resolver
    with pytest.raises(Exception):
        index.handler(_event("getFilePresignedUrl", "not-an-s3-uri"), None)
