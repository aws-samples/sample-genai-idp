"""Unit tests for the list_catalog_features Lambda."""

from __future__ import annotations

import json

import boto3
from _helpers import make_appsync_event


def _preload(monkeypatch, load_lambda, seller_bucket: str | None = None):
    """Configure env vars + (re-)import the lambda module fresh."""
    if seller_bucket:
        monkeypatch.setenv("SELLER_BUCKET", seller_bucket)
    else:
        monkeypatch.delenv("SELLER_BUCKET", raising=False)
    monkeypatch.setenv("SELLER_BUCKET_REGION", "us-east-1")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    return load_lambda("list_catalog_features")


def _put_latest(
    bucket: str, feature_id: str, version: str, display_name: str | None = None
):
    s3 = boto3.client("s3", region_name="us-east-1")
    body: dict = {"featureId": feature_id, "version": version}
    if display_name is not None:
        body["displayName"] = display_name
    s3.put_object(
        Bucket=bucket,
        Key=f"features/{feature_id}/latest.json",
        Body=json.dumps(body).encode("utf-8"),
    )


def _put_manifest(
    bucket: str,
    feature_id: str,
    version: str,
    display_name: str | None = None,
    icon_url: str | None = None,
):
    s3 = boto3.client("s3", region_name="us-east-1")
    body: dict = {"featureId": feature_id, "version": version}
    if display_name is not None:
        body["displayName"] = display_name
    if icon_url is not None:
        body["iconUrl"] = icon_url
    s3.put_object(
        Bucket=bucket,
        Key=f"features/{feature_id}/v{version}/manifest.json",
        Body=json.dumps(body).encode("utf-8"),
    )


def test_no_seller_bucket_returns_empty_list(monkeypatch, load_lambda, aws_credentials):
    mod = _preload(monkeypatch, load_lambda, seller_bucket=None)
    result = mod.handler(make_appsync_event("listCatalogFeatures"), None)
    assert result == []


def test_empty_seller_bucket_returns_empty_list(
    monkeypatch, seller_bucket, load_lambda
):
    mod = _preload(monkeypatch, load_lambda, seller_bucket=seller_bucket)
    result = mod.handler(make_appsync_event("listCatalogFeatures"), None)
    assert result == []


def test_lists_published_features_sorted_by_display_name(
    monkeypatch, seller_bucket, load_lambda
):
    _put_latest(seller_bucket, "zeta", "1.0.0")
    _put_manifest(seller_bucket, "zeta", "1.0.0", display_name="Zeta Widget")
    _put_latest(seller_bucket, "alpha", "2.1.0")
    _put_manifest(
        seller_bucket,
        "alpha",
        "2.1.0",
        display_name="Alpha Widget",
        icon_url="https://example.com/a.png",
    )

    mod = _preload(monkeypatch, load_lambda, seller_bucket=seller_bucket)
    result = mod.handler(make_appsync_event("listCatalogFeatures"), None)

    assert [f["featureId"] for f in result] == ["alpha", "zeta"]
    assert result[0] == {
        "featureId": "alpha",
        "displayName": "Alpha Widget",
        "latestVersion": "2.1.0",
        "iconUrl": "https://example.com/a.png",
    }
    assert result[1]["displayName"] == "Zeta Widget"
    assert result[1]["iconUrl"] is None


def test_falls_back_to_feature_id_when_no_display_name(
    monkeypatch, seller_bucket, load_lambda
):
    # Only latest.json without displayName, and no manifest.json at all.
    _put_latest(seller_bucket, "widgetz", "1.0.0")
    mod = _preload(monkeypatch, load_lambda, seller_bucket=seller_bucket)
    result = mod.handler(make_appsync_event("listCatalogFeatures"), None)
    assert len(result) == 1
    assert result[0]["displayName"] == "widgetz"
    assert result[0]["latestVersion"] == "1.0.0"
    assert result[0]["iconUrl"] is None


def test_manifest_display_name_overrides_latest_json(
    monkeypatch, seller_bucket, load_lambda
):
    # latest.json says one thing, manifest says something nicer — manifest wins.
    _put_latest(seller_bucket, "docs-by-status", "1.0.0", display_name="DocsByStatus")
    _put_manifest(
        seller_bucket,
        "docs-by-status",
        "1.0.0",
        display_name="DemoFeature - Docs By Status",
    )
    mod = _preload(monkeypatch, load_lambda, seller_bucket=seller_bucket)
    result = mod.handler(make_appsync_event("listCatalogFeatures"), None)
    assert result[0]["displayName"] == "DemoFeature - Docs By Status"


def test_skips_feature_with_missing_latest_json(
    monkeypatch, seller_bucket, load_lambda
):
    # Put only a versioned manifest (no latest.json) → feature is not discoverable.
    _put_manifest(seller_bucket, "orphan", "1.0.0", display_name="Orphan")
    # And a well-formed sibling.
    _put_latest(seller_bucket, "good", "1.0.0", display_name="Good")

    mod = _preload(monkeypatch, load_lambda, seller_bucket=seller_bucket)
    result = mod.handler(make_appsync_event("listCatalogFeatures"), None)

    feature_ids = [f["featureId"] for f in result]
    assert "good" in feature_ids
    assert "orphan" not in feature_ids


def test_skips_feature_with_malformed_latest_json(
    monkeypatch, seller_bucket, load_lambda
):
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.put_object(
        Bucket=seller_bucket,
        Key="features/broken/latest.json",
        Body=b"this is not JSON",
    )
    _put_latest(seller_bucket, "ok", "1.0.0")

    mod = _preload(monkeypatch, load_lambda, seller_bucket=seller_bucket)
    result = mod.handler(make_appsync_event("listCatalogFeatures"), None)
    assert [f["featureId"] for f in result] == ["ok"]


def test_skips_feature_with_missing_version_field(
    monkeypatch, seller_bucket, load_lambda
):
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.put_object(
        Bucket=seller_bucket,
        Key="features/no-version/latest.json",
        Body=json.dumps(
            {"featureId": "no-version", "displayName": "No Version"}
        ).encode("utf-8"),
    )
    _put_latest(seller_bucket, "ok", "1.0.0")

    mod = _preload(monkeypatch, load_lambda, seller_bucket=seller_bucket)
    result = mod.handler(make_appsync_event("listCatalogFeatures"), None)
    assert [f["featureId"] for f in result] == ["ok"]


def test_malformed_manifest_does_not_crash(monkeypatch, seller_bucket, load_lambda):
    # latest.json is valid but manifest is garbage → feature should still appear,
    # with the displayName from latest.json.
    _put_latest(seller_bucket, "loose", "1.0.0", display_name="Loose Cannon")
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.put_object(
        Bucket=seller_bucket,
        Key="features/loose/v1.0.0/manifest.json",
        Body=b"not JSON either",
    )

    mod = _preload(monkeypatch, load_lambda, seller_bucket=seller_bucket)
    result = mod.handler(make_appsync_event("listCatalogFeatures"), None)
    assert len(result) == 1
    assert result[0]["displayName"] == "Loose Cannon"
    assert result[0]["iconUrl"] is None
