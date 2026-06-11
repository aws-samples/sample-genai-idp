"""Unit tests for the list_catalog_features Lambda.

Discovery is manifest-driven: the resolver reads ONE catalog.json from the
stack's ConfigurationBucket via a single GetObject. It performs NO
ListObjectsV2 (asserted indirectly — no bucket-listing fixtures exist).
"""

from __future__ import annotations

import json

import boto3
from _helpers import make_appsync_event

_CATALOG_KEY = "config_library/catalog.json"


def _preload(monkeypatch, load_lambda, configuration_bucket: str | None = None):
    """Configure env vars + (re-)import the lambda module fresh."""
    if configuration_bucket:
        monkeypatch.setenv("CONFIGURATION_BUCKET", configuration_bucket)
    else:
        monkeypatch.delenv("CONFIGURATION_BUCKET", raising=False)
    monkeypatch.setenv("CATALOG_KEY", _CATALOG_KEY)
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    return load_lambda("list_catalog_features")


def _put_catalog(bucket: str, features: list[dict]):
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.put_object(
        Bucket=bucket,
        Key=_CATALOG_KEY,
        Body=json.dumps({"schemaVersion": "1.0", "features": features}).encode("utf-8"),
    )


def test_no_configuration_bucket_returns_empty_list(
    monkeypatch, load_lambda, aws_credentials
):
    mod = _preload(monkeypatch, load_lambda, configuration_bucket=None)
    result = mod.handler(make_appsync_event("listCatalogFeatures"), None)
    assert result == []


def test_missing_catalog_returns_empty_list(
    monkeypatch, configuration_bucket, load_lambda
):
    # Bucket exists but no catalog.json object → empty (NoSuchKey).
    mod = _preload(monkeypatch, load_lambda, configuration_bucket=configuration_bucket)
    result = mod.handler(make_appsync_event("listCatalogFeatures"), None)
    assert result == []


def test_lists_features_sorted_by_display_name(
    monkeypatch, configuration_bucket, load_lambda
):
    _put_catalog(
        configuration_bucket,
        [
            {
                "featureId": "zeta",
                "displayName": "Zeta Widget",
                "latestVersion": "1.0.0",
                "source": "oss",
            },
            {
                "featureId": "alpha",
                "displayName": "Alpha Widget",
                "latestVersion": "2.1.0",
                "source": "oss",
                "iconUrl": "https://example.com/a.png",
            },
        ],
    )
    mod = _preload(monkeypatch, load_lambda, configuration_bucket=configuration_bucket)
    result = mod.handler(make_appsync_event("listCatalogFeatures"), None)

    assert [f["featureId"] for f in result] == ["alpha", "zeta"]
    assert result[0] == {
        "featureId": "alpha",
        "displayName": "Alpha Widget",
        "latestVersion": "2.1.0",
        "iconUrl": "https://example.com/a.png",
        "description": None,
        "docsUrl": None,
        "source": "oss",
        "productCode": None,
        "marketplaceListingUrl": None,
        "artifactBucket": None,
        "artifactPrefix": None,
    }


def test_description_is_surfaced(monkeypatch, configuration_bucket, load_lambda):
    _put_catalog(
        configuration_bucket,
        [
            {
                "featureId": "demo",
                "displayName": "Demo Extension",
                "latestVersion": "1.0.0",
                "source": "oss",
                "description": "Adds a Docs By Status page.",
                "docsUrl": "extensions/demo-extension",
            }
        ],
    )
    mod = _preload(monkeypatch, load_lambda, configuration_bucket=configuration_bucket)
    result = mod.handler(make_appsync_event("listCatalogFeatures"), None)
    assert result[0]["description"] == "Adds a Docs By Status page."
    assert result[0]["docsUrl"] == "extensions/demo-extension"


def test_marketplace_feature_carries_subscribe_metadata(
    monkeypatch, configuration_bucket, load_lambda
):
    _put_catalog(
        configuration_bucket,
        [
            {
                "featureId": "my-paid-extension",
                "displayName": "My Paid Extension",
                "latestVersion": "0.1.4",
                "source": "marketplace",
                "productCode": "abc123",
                "marketplaceListingUrl": "https://aws.amazon.com/marketplace/pp/x",
            }
        ],
    )
    mod = _preload(monkeypatch, load_lambda, configuration_bucket=configuration_bucket)
    result = mod.handler(make_appsync_event("listCatalogFeatures"), None)
    assert result[0]["source"] == "marketplace"
    assert result[0]["productCode"] == "abc123"
    assert result[0]["marketplaceListingUrl"].endswith("/x")


def test_falls_back_to_feature_id_and_defaults_source_oss(
    monkeypatch, configuration_bucket, load_lambda
):
    _put_catalog(configuration_bucket, [{"featureId": "widgetz"}])
    mod = _preload(monkeypatch, load_lambda, configuration_bucket=configuration_bucket)
    result = mod.handler(make_appsync_event("listCatalogFeatures"), None)
    assert len(result) == 1
    assert result[0]["displayName"] == "widgetz"
    assert result[0]["source"] == "oss"
    assert result[0]["latestVersion"] == ""


def test_malformed_catalog_does_not_crash(
    monkeypatch, configuration_bucket, load_lambda
):
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.put_object(
        Bucket=configuration_bucket, Key=_CATALOG_KEY, Body=b"this is not JSON"
    )
    mod = _preload(monkeypatch, load_lambda, configuration_bucket=configuration_bucket)
    result = mod.handler(make_appsync_event("listCatalogFeatures"), None)
    assert result == []


def test_skips_entries_without_feature_id(
    monkeypatch, configuration_bucket, load_lambda
):
    _put_catalog(
        configuration_bucket,
        [
            {"displayName": "No Id"},  # dropped
            {"featureId": "ok", "displayName": "OK", "latestVersion": "1.0.0"},
        ],
    )
    mod = _preload(monkeypatch, load_lambda, configuration_bucket=configuration_bucket)
    result = mod.handler(make_appsync_event("listCatalogFeatures"), None)
    assert [f["featureId"] for f in result] == ["ok"]


def test_missing_features_list_returns_empty(
    monkeypatch, configuration_bucket, load_lambda
):
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.put_object(
        Bucket=configuration_bucket,
        Key=_CATALOG_KEY,
        Body=json.dumps({"schemaVersion": "1.0"}).encode("utf-8"),
    )
    mod = _preload(monkeypatch, load_lambda, configuration_bucket=configuration_bucket)
    result = mod.handler(make_appsync_event("listCatalogFeatures"), None)
    assert result == []
