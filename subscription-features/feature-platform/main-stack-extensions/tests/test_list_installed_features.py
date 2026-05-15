"""Unit tests for the list_installed_features Lambda."""

from __future__ import annotations

import json

import boto3
import pytest
from _helpers import make_appsync_event


def _preload(
    monkeypatch, table_name: str, load_lambda, seller_bucket: str | None = None
):
    monkeypatch.setenv("INSTALLED_FEATURES_TABLE", table_name)
    if seller_bucket:
        monkeypatch.setenv("SELLER_BUCKET", seller_bucket)
    else:
        monkeypatch.delenv("SELLER_BUCKET", raising=False)
    monkeypatch.setenv("SELLER_BUCKET_REGION", "us-east-1")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    return load_lambda("list_installed_features")


def _seed(table_name: str, items):
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(table_name)
    for item in items:
        table.put_item(Item=item)


def test_empty_returns_empty_list(monkeypatch, installed_features_table, load_lambda):
    mod = _preload(monkeypatch, installed_features_table, load_lambda)
    result = mod.handler(make_appsync_event("listInstalledFeatures"), None)
    assert result == []


def test_returns_features_sorted_by_display_name(
    monkeypatch, installed_features_table, load_lambda
):
    _seed(
        installed_features_table,
        [
            {
                "featureId": "zeta",
                "displayName": "Zeta Feature",
                "installedVersion": "1.0.0",
                "stackName": "idp-feature-zeta",
                "stackRegion": "us-east-1",
                "uiBundlePath": "features/zeta/v1.0.0/",
                "installedAt": "2026-01-01T00:00:00Z",
            },
            {
                "featureId": "alpha",
                "displayName": "Alpha Feature",
                "installedVersion": "2.0.0",
                "stackName": "idp-feature-alpha",
                "stackRegion": "us-east-1",
                "uiBundlePath": "features/alpha/v2.0.0/",
                "installedAt": "2026-01-01T00:00:00Z",
            },
        ],
    )

    mod = _preload(monkeypatch, installed_features_table, load_lambda)
    result = mod.handler(make_appsync_event("listInstalledFeatures"), None)
    assert [f["featureId"] for f in result] == ["alpha", "zeta"]
    # No seller bucket configured → latestVersion should be None and updateAvailable false.
    assert all(f["latestVersion"] is None for f in result)
    assert all(f["updateAvailable"] is False for f in result)


def test_update_available_when_latest_differs(monkeypatch, mock_stack, load_lambda):
    table_name = mock_stack["table_name"]
    bucket = mock_stack["bucket"]

    _seed(
        table_name,
        [
            {
                "featureId": "docs-by-status",
                "displayName": "Docs",
                "installedVersion": "1.0.0",
                "stackName": "s",
                "stackRegion": "us-east-1",
                "uiBundlePath": "features/docs-by-status/v1.0.0/",
                "installedAt": "2026-01-01T00:00:00Z",
            }
        ],
    )

    s3 = boto3.client("s3", region_name="us-east-1")
    s3.put_object(
        Bucket=bucket,
        Key="features/docs-by-status/latest.json",
        Body=json.dumps({"version": "1.1.0"}).encode("utf-8"),
    )

    mod = _preload(monkeypatch, table_name, load_lambda, seller_bucket=bucket)
    result = mod.handler(make_appsync_event("listInstalledFeatures"), None)

    assert len(result) == 1
    assert result[0]["installedVersion"] == "1.0.0"
    assert result[0]["latestVersion"] == "1.1.0"
    assert result[0]["updateAvailable"] is True


def test_update_not_available_when_versions_match(monkeypatch, mock_stack, load_lambda):
    table_name = mock_stack["table_name"]
    bucket = mock_stack["bucket"]

    _seed(
        table_name,
        [
            {
                "featureId": "docs-by-status",
                "displayName": "Docs",
                "installedVersion": "1.1.0",
                "stackName": "s",
                "stackRegion": "us-east-1",
                "uiBundlePath": "features/docs-by-status/v1.1.0/",
                "installedAt": "2026-01-01T00:00:00Z",
            }
        ],
    )
    boto3.client("s3", region_name="us-east-1").put_object(
        Bucket=bucket,
        Key="features/docs-by-status/latest.json",
        Body=json.dumps({"version": "1.1.0"}).encode("utf-8"),
    )

    mod = _preload(monkeypatch, table_name, load_lambda, seller_bucket=bucket)
    result = mod.handler(make_appsync_event("listInstalledFeatures"), None)
    assert result[0]["updateAvailable"] is False


def test_missing_latest_json_does_not_crash(monkeypatch, mock_stack, load_lambda):
    _seed(
        mock_stack["table_name"],
        [
            {
                "featureId": "ghost",
                "displayName": "Ghost",
                "installedVersion": "0.1.0",
                "stackName": "s",
                "stackRegion": "us-east-1",
                "uiBundlePath": "features/ghost/v0.1.0/",
                "installedAt": "2026-01-01T00:00:00Z",
            }
        ],
    )

    mod = _preload(
        monkeypatch,
        mock_stack["table_name"],
        load_lambda,
        seller_bucket=mock_stack["bucket"],
    )
    result = mod.handler(make_appsync_event("listInstalledFeatures"), None)
    assert result[0]["latestVersion"] is None
    assert result[0]["updateAvailable"] is False


def test_malformed_latest_json_does_not_crash(monkeypatch, mock_stack, load_lambda):
    _seed(
        mock_stack["table_name"],
        [
            {
                "featureId": "quirk",
                "displayName": "Quirk",
                "installedVersion": "0.1.0",
                "stackName": "s",
                "stackRegion": "us-east-1",
                "uiBundlePath": "features/quirk/v0.1.0/",
                "installedAt": "2026-01-01T00:00:00Z",
            }
        ],
    )
    boto3.client("s3", region_name="us-east-1").put_object(
        Bucket=mock_stack["bucket"],
        Key="features/quirk/latest.json",
        Body=b"this is not JSON",
    )

    mod = _preload(
        monkeypatch,
        mock_stack["table_name"],
        load_lambda,
        seller_bucket=mock_stack["bucket"],
    )
    result = mod.handler(make_appsync_event("listInstalledFeatures"), None)
    assert result[0]["latestVersion"] is None


def test_missing_env_var_raises(monkeypatch, load_lambda, aws_credentials):
    monkeypatch.delenv("INSTALLED_FEATURES_TABLE", raising=False)
    mod = load_lambda("list_installed_features")
    with pytest.raises(RuntimeError, match="INSTALLED_FEATURES_TABLE"):
        mod.handler(make_appsync_event("listInstalledFeatures"), None)
