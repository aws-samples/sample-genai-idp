# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for the version_check_resolver Lambda."""

import importlib
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


def _stub_paginator(pages: list[list[dict[str, Any]]]) -> MagicMock:
    """Build a paginator mock that yields the provided pages."""
    paginator = MagicMock()
    paginator.paginate.return_value = [{"Contents": page} for page in pages]
    return paginator


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
def test_picks_highest_semver(reload_module):
    """Given a mix of versioned templates, the highest semver is returned."""
    mod = reload_module(
        {
            "PUBLIC_ARTIFACTS_BUCKET": "aws-ml-blog-us-west-2",
            "PUBLIC_ARTIFACTS_PREFIX": "artifacts/genai-idp",
            "PUBLIC_ARTIFACTS_REGION": "us-west-2",
        }
    )
    # Reset module-level cache from previous tests
    mod._CACHE.update(timestamp=0.0, value=None)

    pages = [
        [
            {"Key": "artifacts/genai-idp/idp-main.yaml"},  # unversioned (skipped)
            {"Key": "artifacts/genai-idp/idp-main_0.5.10.yaml"},
            {"Key": "artifacts/genai-idp/idp-main_0.5.11.dev1.yaml"},
            {"Key": "artifacts/genai-idp/idp-main_0.5.12.yaml"},
            {"Key": "artifacts/genai-idp/idp-main_0.5.11.yaml"},
            {"Key": "artifacts/genai-idp/idp-headless_0.5.12.yaml"},  # other basename
            {"Key": "artifacts/genai-idp/layers/foo.zip"},  # nested (skipped)
        ]
    ]
    s3_client = MagicMock()
    s3_client.get_paginator.return_value = _stub_paginator(pages)

    with patch.object(mod.boto3, "client", return_value=s3_client):
        result = mod.lambda_handler({}, None)

    assert result["checkEnabled"] is True
    assert result["latestVersion"] == "0.5.12"
    assert (
        result["templateUrl"]
        == "https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main_0.5.12.yaml"
    )
    assert result["errorMessage"] is None


@pytest.mark.unit
def test_dev_versions_rank_below_release(reload_module):
    """0.5.11.dev1 must NOT be reported as newer than 0.5.11."""
    mod = reload_module(
        {
            "PUBLIC_ARTIFACTS_BUCKET": "bucket",
            "PUBLIC_ARTIFACTS_PREFIX": "artifacts/genai-idp",
        }
    )
    mod._CACHE.update(timestamp=0.0, value=None)

    pages = [
        [
            {"Key": "artifacts/genai-idp/idp-main_0.5.11.dev1.yaml"},
            {"Key": "artifacts/genai-idp/idp-main_0.5.11.yaml"},
        ]
    ]
    s3_client = MagicMock()
    s3_client.get_paginator.return_value = _stub_paginator(pages)
    with patch.object(mod.boto3, "client", return_value=s3_client):
        result = mod.lambda_handler({}, None)

    assert result["latestVersion"] == "0.5.11"


@pytest.mark.unit
def test_dev_versions_ordered_among_themselves(reload_module):
    """When only dev pre-releases are published, the highest devN wins.

    This covers the user-feedback case where the deployed stack is
    `0.5.11.dev3` and a `0.5.11.dev4` pre-release has just been published —
    the resolver should pick dev4 as newer.
    """
    mod = reload_module(
        {
            "PUBLIC_ARTIFACTS_BUCKET": "bucket",
            "PUBLIC_ARTIFACTS_PREFIX": "artifacts/genai-idp",
        }
    )
    mod._CACHE.update(timestamp=0.0, value=None)

    pages = [
        [
            {"Key": "artifacts/genai-idp/idp-main_0.5.11.dev1.yaml"},
            {"Key": "artifacts/genai-idp/idp-main_0.5.11.dev2.yaml"},
            {"Key": "artifacts/genai-idp/idp-main_0.5.11.dev3.yaml"},
            {"Key": "artifacts/genai-idp/idp-main_0.5.11.dev4.yaml"},
        ]
    ]
    s3_client = MagicMock()
    s3_client.get_paginator.return_value = _stub_paginator(pages)
    with patch.object(mod.boto3, "client", return_value=s3_client):
        result = mod.lambda_handler({}, None)

    assert result["latestVersion"] == "0.5.11.dev4"


@pytest.mark.unit
def test_legacy_invalid_versions_do_not_outrank_pep440(reload_module):
    """Legacy ``-wipN`` style versions don't conform to PEP 440 and must
    be ignored — otherwise the buggy fallback would rank them above
    ``.devN`` releases (regression test for the dev3→dev4 case where
    ``0.5.7-wip5`` was being reported as the latest).
    """
    mod = reload_module(
        {
            "PUBLIC_ARTIFACTS_BUCKET": "bucket",
            "PUBLIC_ARTIFACTS_PREFIX": "artifacts/genai-idp",
        }
    )
    mod._CACHE.update(timestamp=0.0, value=None)

    pages = [
        [
            # PEP 440-invalid legacy versions still in the bucket
            {"Key": "artifacts/genai-idp/idp-main_0.5.7-wip5.yaml"},
            {"Key": "artifacts/genai-idp/idp-main_0.4.10-wip1.yaml"},
            # Current PEP 440 dev release we want as the answer
            {"Key": "artifacts/genai-idp/idp-main_0.5.11.dev3.yaml"},
            {"Key": "artifacts/genai-idp/idp-main_0.5.11.dev4.yaml"},
        ]
    ]
    s3_client = MagicMock()
    s3_client.get_paginator.return_value = _stub_paginator(pages)
    with patch.object(mod.boto3, "client", return_value=s3_client):
        result = mod.lambda_handler({}, None)

    assert result["latestVersion"] == "0.5.11.dev4"


@pytest.mark.unit
def test_no_versions_returns_enabled_with_no_version(reload_module):

    """Empty bucket prefix → checkEnabled=True but no version."""
    mod = reload_module(
        {
            "PUBLIC_ARTIFACTS_BUCKET": "bucket",
            "PUBLIC_ARTIFACTS_PREFIX": "artifacts/genai-idp",
        }
    )
    mod._CACHE.update(timestamp=0.0, value=None)

    s3_client = MagicMock()
    s3_client.get_paginator.return_value = _stub_paginator([[]])
    with patch.object(mod.boto3, "client", return_value=s3_client):
        result = mod.lambda_handler({}, None)

    assert result["checkEnabled"] is True
    assert result["latestVersion"] is None
    assert result["templateUrl"] is None


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

    pages = [[{"Key": "artifacts/genai-idp/idp-main_1.0.0.yaml"}]]
    s3_client = MagicMock()
    s3_client.get_paginator.return_value = _stub_paginator(pages)

    with patch.object(mod.boto3, "client", return_value=s3_client) as mocked:
        first = mod.lambda_handler({}, None)
        second = mod.lambda_handler({}, None)

    assert first == second
    # boto3.client should only have been called once for the cached path
    assert mocked.call_count == 1


@pytest.mark.unit
def test_client_error_does_not_crash(reload_module):
    """An S3 listing error returns a structured response with errorMessage."""
    from botocore.exceptions import ClientError

    mod = reload_module(
        {
            "PUBLIC_ARTIFACTS_BUCKET": "bucket",
            "PUBLIC_ARTIFACTS_PREFIX": "artifacts/genai-idp",
        }
    )
    mod._CACHE.update(timestamp=0.0, value=None)

    err = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "denied"}}, "ListObjectsV2"
    )

    def _raise(*_args, **_kwargs):
        raise err

    s3_client = MagicMock()
    s3_client.get_paginator.return_value.paginate.side_effect = _raise
    with patch.object(mod.boto3, "client", return_value=s3_client):
        result = mod.lambda_handler({}, None)

    assert result["checkEnabled"] is True
    assert result["latestVersion"] is None
    assert "AccessDenied" in (result["errorMessage"] or "")
