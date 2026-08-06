"""Unit tests for the list_installed_features Lambda.

`latestVersion` (for the "Update available" badge) comes from catalog.json in
ConfigurationBucket — a single GetObject, no per-feature bucket reads.
"""

from __future__ import annotations

import json

import boto3
import pytest
from _helpers import make_appsync_event

_CATALOG_KEY = "config_library/catalog.json"


def _preload(
    monkeypatch, table_name: str, load_lambda, configuration_bucket: str | None = None
):
    monkeypatch.setenv("INSTALLED_FEATURES_TABLE", table_name)
    if configuration_bucket:
        monkeypatch.setenv("CONFIGURATION_BUCKET", configuration_bucket)
    else:
        monkeypatch.delenv("CONFIGURATION_BUCKET", raising=False)
    monkeypatch.setenv("CATALOG_KEY", _CATALOG_KEY)
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    return load_lambda("list_installed_features")


def _seed(table_name: str, items):
    table = boto3.resource("dynamodb", region_name="us-east-1").Table(table_name)
    for item in items:
        table.put_item(Item=item)


def _put_catalog(bucket: str, features: list):
    boto3.client("s3", region_name="us-east-1").put_object(
        Bucket=bucket,
        Key=_CATALOG_KEY,
        Body=json.dumps({"schemaVersion": "1.0", "features": features}).encode("utf-8"),
    )


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
    # No catalog configured → latestVersion None and updateAvailable false.
    assert all(f["latestVersion"] is None for f in result)
    assert all(f["updateAvailable"] is False for f in result)


def test_update_available_when_catalog_version_differs(
    monkeypatch, mock_stack, load_lambda
):
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
    _put_catalog(
        bucket,
        [{"featureId": "docs-by-status", "source": "oss", "latestVersion": "1.1.0"}],
    )

    mod = _preload(monkeypatch, table_name, load_lambda, configuration_bucket=bucket)
    result = mod.handler(make_appsync_event("listInstalledFeatures"), None)

    assert len(result) == 1
    assert result[0]["installedVersion"] == "1.0.0"
    assert result[0]["latestVersion"] == "1.1.0"
    assert result[0]["updateAvailable"] is True


def test_no_update_when_catalog_is_BEHIND_installed(
    monkeypatch, mock_stack, load_lambda
):
    """A catalog OLDER than the installed version is not an update.

    This is the routine case, not an edge case: `idp-feature-cli deploy
    --from-code` (the documented dev loop) installs a newer extension
    immediately, while catalog.json only refreshes on a host stack
    create/update. The previous `latest != installed` check reported
    "Update available: v0.1.0" to an admin already running v0.1.1 — an
    invitation to downgrade.
    """
    table_name = mock_stack["table_name"]
    bucket = mock_stack["bucket"]

    _seed(
        table_name,
        [
            {
                "featureId": "confbench-testset",
                "displayName": "Test Set - ConfBench",
                "installedVersion": "0.1.1",
                "stackName": "s",
                "stackRegion": "us-west-2",
                "uiBundlePath": "features/confbench-testset/v0.1.1/",
                "installedAt": "2026-01-01T00:00:00Z",
            }
        ],
    )
    _put_catalog(
        bucket,
        [{"featureId": "confbench-testset", "source": "oss", "latestVersion": "0.1.0"}],
    )

    mod = _preload(monkeypatch, table_name, load_lambda, configuration_bucket=bucket)
    result = mod.handler(make_appsync_event("listInstalledFeatures"), None)

    assert result[0]["installedVersion"] == "0.1.1"
    assert result[0]["latestVersion"] == "0.1.0"
    assert result[0]["updateAvailable"] is False


def test_version_comparison_is_numeric_not_lexicographic(
    monkeypatch, mock_stack, load_lambda
):
    """0.1.10 > 0.1.9 numerically, even though it sorts earlier as a string."""
    table_name = mock_stack["table_name"]
    bucket = mock_stack["bucket"]

    _seed(
        table_name,
        [
            {
                "featureId": "f",
                "displayName": "F",
                "installedVersion": "0.1.9",
                "stackName": "s",
                "stackRegion": "us-east-1",
                "uiBundlePath": "features/f/v0.1.9/",
                "installedAt": "2026-01-01T00:00:00Z",
            }
        ],
    )
    _put_catalog(bucket, [{"featureId": "f", "latestVersion": "0.1.10"}])

    mod = _preload(monkeypatch, table_name, load_lambda, configuration_bucket=bucket)
    assert (
        mod.handler(make_appsync_event("listInstalledFeatures"), None)[0][
            "updateAvailable"
        ]
        is True
    )


def test_prerelease_ordering(monkeypatch, mock_stack, load_lambda):
    """SemVer 11: a prerelease has LOWER precedence than its release, so
    1.0.0 is an update over 1.0.0-rc1 but 1.0.0-rc1 is not over 1.0.0."""
    table_name = mock_stack["table_name"]
    bucket = mock_stack["bucket"]

    for installed, latest, expected in (
        ("1.0.0-rc1", "1.0.0", True),
        ("1.0.0", "1.0.0-rc1", False),
    ):
        _seed(
            table_name,
            [
                {
                    "featureId": "p",
                    "displayName": "P",
                    "installedVersion": installed,
                    "stackName": "s",
                    "stackRegion": "us-east-1",
                    "uiBundlePath": "features/p/",
                    "installedAt": "2026-01-01T00:00:00Z",
                }
            ],
        )
        _put_catalog(bucket, [{"featureId": "p", "latestVersion": latest}])
        mod = _preload(
            monkeypatch, table_name, load_lambda, configuration_bucket=bucket
        )
        got = mod.handler(make_appsync_event("listInstalledFeatures"), None)[0][
            "updateAvailable"
        ]
        assert got is expected, f"installed={installed} latest={latest}"


def test_unparseable_version_falls_back_to_inequality(
    monkeypatch, mock_stack, load_lambda
):
    """Non-SemVer strings keep the old behavior rather than silently hiding the
    badge — better to over-report than to strand a real update."""
    table_name = mock_stack["table_name"]
    bucket = mock_stack["bucket"]

    _seed(
        table_name,
        [
            {
                "featureId": "odd",
                "displayName": "Odd",
                "installedVersion": "latest",
                "stackName": "s",
                "stackRegion": "us-east-1",
                "uiBundlePath": "features/odd/",
                "installedAt": "2026-01-01T00:00:00Z",
            }
        ],
    )
    _put_catalog(bucket, [{"featureId": "odd", "latestVersion": "2026-08-01"}])

    mod = _preload(monkeypatch, table_name, load_lambda, configuration_bucket=bucket)
    assert (
        mod.handler(make_appsync_event("listInstalledFeatures"), None)[0][
            "updateAvailable"
        ]
        is True
    )


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
    _put_catalog(
        bucket,
        [{"featureId": "docs-by-status", "source": "oss", "latestVersion": "1.1.0"}],
    )

    mod = _preload(monkeypatch, table_name, load_lambda, configuration_bucket=bucket)
    result = mod.handler(make_appsync_event("listInstalledFeatures"), None)
    assert result[0]["updateAvailable"] is False


def test_feature_absent_from_catalog_does_not_crash(
    monkeypatch, mock_stack, load_lambda
):
    # Installed feature not in the catalog (e.g. unadvertised / catalog absent
    # for it) → latestVersion None, still listed.
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
    _put_catalog(mock_stack["bucket"], [])  # empty catalog

    mod = _preload(
        monkeypatch,
        mock_stack["table_name"],
        load_lambda,
        configuration_bucket=mock_stack["bucket"],
    )
    result = mod.handler(make_appsync_event("listInstalledFeatures"), None)
    assert result[0]["latestVersion"] is None
    assert result[0]["updateAvailable"] is False


def test_malformed_catalog_does_not_crash(monkeypatch, mock_stack, load_lambda):
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
        Bucket=mock_stack["bucket"], Key=_CATALOG_KEY, Body=b"this is not JSON"
    )

    mod = _preload(
        monkeypatch,
        mock_stack["table_name"],
        load_lambda,
        configuration_bucket=mock_stack["bucket"],
    )
    result = mod.handler(make_appsync_event("listInstalledFeatures"), None)
    assert result[0]["latestVersion"] is None


def test_missing_env_var_raises(monkeypatch, load_lambda, aws_credentials):
    monkeypatch.delenv("INSTALLED_FEATURES_TABLE", raising=False)
    mod = load_lambda("list_installed_features")
    with pytest.raises(RuntimeError, match="INSTALLED_FEATURES_TABLE"):
        mod.handler(make_appsync_event("listInstalledFeatures"), None)
