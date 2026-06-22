# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for the version_check_resolver Lambda.

The resolver reads a single pointer object (``<prefix>/idp-main-latest.json``)
via GetObject — it performs **no ListObjectsV2** (the public release bucket only
permits GetObject). These tests stub ``get_object`` to return that pointer JSON.
"""

import importlib
import json
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def reload_module(monkeypatch: pytest.MonkeyPatch):
    """Reload the resolver module after env-var changes (module-level config)."""

    def _reload(env: dict[str, str]) -> Any:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        # Drop any cached import so module-level constants pick up new env
        sys.modules.pop("index", None)
        return importlib.import_module("index")

    return _reload


def _pointer_body(pointer: dict[str, Any]) -> dict[str, Any]:
    """A get_object response whose Body yields the given pointer JSON."""
    body = MagicMock()
    body.read.return_value = json.dumps(pointer).encode("utf-8")
    return {"Body": body}


def _client_returning(pointer: dict[str, Any]) -> MagicMock:
    """An S3 client mock whose get_object returns the pointer JSON."""
    client = MagicMock()
    client.get_object.return_value = _pointer_body(pointer)
    return client


@pytest.mark.unit
def test_returns_disabled_when_bucket_unset(reload_module):
    """An empty PUBLIC_ARTIFACTS_BUCKET disables the check (default behaviour)."""
    mod = reload_module({"PUBLIC_ARTIFACTS_BUCKET": ""})
    result = mod.lambda_handler({}, None)
    assert result == {
        "checkEnabled": False,
        "latestVersion": None,
        "templateUrl": None,
        "errorMessage": None,
    }


@pytest.mark.unit
def test_pointer_version_and_url_returned(reload_module):
    """The pointer's version + templateUrl are returned verbatim."""
    mod = reload_module(
        {
            "PUBLIC_ARTIFACTS_BUCKET": "aws-ml-blog-us-west-2",
            "PUBLIC_ARTIFACTS_PREFIX": "artifacts/genai-idp",
            "PUBLIC_ARTIFACTS_REGION": "us-west-2",
        }
    )
    mod._CACHE.update(timestamp=0.0, value=None)

    pointer = {
        "version": "0.5.12",
        "templateUrl": (
            "https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/"
            "artifacts/genai-idp/idp-main_0.5.12.yaml"
        ),
    }
    s3_client = _client_returning(pointer)
    with patch.object(mod.boto3, "client", return_value=s3_client):
        result = mod.lambda_handler({}, None)

    assert result["checkEnabled"] is True
    assert result["latestVersion"] == "0.5.12"
    assert result["templateUrl"] == pointer["templateUrl"]
    assert result["errorMessage"] is None
    # GetObject of the version-stripped pointer key — never a list call.
    s3_client.get_object.assert_called_with(
        Bucket="aws-ml-blog-us-west-2",
        Key="artifacts/genai-idp/idp-main-latest.json",
    )
    assert not s3_client.get_paginator.called


@pytest.mark.unit
def test_falls_back_to_conventional_url_when_pointer_omits_it(reload_module):
    """If the pointer carries only a version, the resolver builds the
    conventional ``idp-main_<version>.yaml`` URL from prefix + region."""
    mod = reload_module(
        {
            "PUBLIC_ARTIFACTS_BUCKET": "bucket",
            "PUBLIC_ARTIFACTS_PREFIX": "artifacts/genai-idp",
            "PUBLIC_ARTIFACTS_REGION": "us-east-1",
        }
    )
    mod._CACHE.update(timestamp=0.0, value=None)

    s3_client = _client_returning({"version": "0.5.11"})
    with patch.object(mod.boto3, "client", return_value=s3_client):
        result = mod.lambda_handler({}, None)

    assert result["latestVersion"] == "0.5.11"
    assert result["templateUrl"] == (
        "https://s3.us-east-1.amazonaws.com/bucket/"
        "artifacts/genai-idp/idp-main_0.5.11.yaml"
    )


@pytest.mark.unit
def test_missing_pointer_returns_enabled_with_no_version(reload_module):
    """NoSuchKey on the pointer → checkEnabled=True but no version."""
    from botocore.exceptions import ClientError

    mod = reload_module(
        {
            "PUBLIC_ARTIFACTS_BUCKET": "bucket",
            "PUBLIC_ARTIFACTS_PREFIX": "artifacts/genai-idp",
        }
    )
    mod._CACHE.update(timestamp=0.0, value=None)

    err = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "GetObject"
    )
    s3_client = MagicMock()
    s3_client.get_object.side_effect = err
    with patch.object(mod.boto3, "client", return_value=s3_client):
        result = mod.lambda_handler({}, None)

    assert result["checkEnabled"] is True
    assert result["latestVersion"] is None
    assert result["templateUrl"] is None


@pytest.mark.unit
def test_malformed_pointer_returns_enabled_with_no_version(reload_module):
    """A pointer that isn't valid JSON is treated as absent (no crash)."""
    mod = reload_module(
        {
            "PUBLIC_ARTIFACTS_BUCKET": "bucket",
            "PUBLIC_ARTIFACTS_PREFIX": "artifacts/genai-idp",
        }
    )
    mod._CACHE.update(timestamp=0.0, value=None)

    body = MagicMock()
    body.read.return_value = b"this is not json"
    s3_client = MagicMock()
    s3_client.get_object.return_value = {"Body": body}
    with patch.object(mod.boto3, "client", return_value=s3_client):
        result = mod.lambda_handler({}, None)

    assert result["checkEnabled"] is True
    assert result["latestVersion"] is None


@pytest.mark.unit
def test_caches_result_within_ttl(reload_module):
    """Subsequent invocations within the TTL must not hit S3 again."""
    mod = reload_module(
        {
            "PUBLIC_ARTIFACTS_BUCKET": "bucket",
            "PUBLIC_ARTIFACTS_PREFIX": "artifacts/genai-idp",
            "VERSION_CHECK_CACHE_TTL": "600",
        }
    )
    mod._CACHE.update(timestamp=0.0, value=None)

    s3_client = _client_returning({"version": "1.0.0"})
    with patch.object(mod.boto3, "client", return_value=s3_client) as mocked:
        first = mod.lambda_handler({}, None)
        second = mod.lambda_handler({}, None)

    assert first == second
    # boto3.client should only have been built once — the second call is cached.
    assert mocked.call_count == 1


@pytest.mark.unit
def test_client_error_does_not_crash(reload_module):
    """A non-404 S3 error returns a structured response with errorMessage."""
    from botocore.exceptions import ClientError

    mod = reload_module(
        {
            "PUBLIC_ARTIFACTS_BUCKET": "bucket",
            "PUBLIC_ARTIFACTS_PREFIX": "artifacts/genai-idp",
        }
    )
    mod._CACHE.update(timestamp=0.0, value=None)

    # A throttling/server error is NOT swallowed as "missing pointer" — it
    # surfaces as an errorMessage so the next page load retries.
    err = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow down"}},
        "GetObject",
    )
    s3_client = MagicMock()
    s3_client.get_object.side_effect = err
    with patch.object(mod.boto3, "client", return_value=s3_client):
        result = mod.lambda_handler({}, None)

    assert result["checkEnabled"] is True
    assert result["latestVersion"] is None
    assert "ThrottlingException" in (result["errorMessage"] or "")
