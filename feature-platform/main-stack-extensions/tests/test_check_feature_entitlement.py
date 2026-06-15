"""Unit tests for the check_feature_entitlement Lambda.

moto does not implement marketplace-entitlement, so we use botocore.stub.Stubber
to programme the boto3 client inside the module after import. The product code
now comes from the feature's InstalledFeatures row (DynamoDB, via moto) — baked
from the manifest at install — rather than a host env map.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import boto3
import pytest
from _helpers import make_appsync_event
from botocore.stub import Stubber

_CATALOG_KEY = "config_library/catalog.json"


def _seed_row(table_name, feature_id, *, product_code=None):
    item = {"featureId": feature_id}
    if product_code is not None:
        item["productCode"] = product_code
    boto3.resource("dynamodb", region_name="us-east-1").Table(table_name).put_item(
        Item=item
    )


def _preload(
    monkeypatch,
    load_lambda,
    *,
    table_name="",
    default_customer="CUST-default",
    buyer_account="111122223333",
    source_tag="simulator",
    configuration_bucket="",
):
    monkeypatch.setenv("INSTALLED_FEATURES_TABLE", table_name)
    monkeypatch.setenv("DEFAULT_CUSTOMER_IDENTIFIER", default_customer)
    monkeypatch.setenv("DEFAULT_BUYER_ACCOUNT_ID", buyer_account)
    monkeypatch.setenv("SIMULATOR_SOURCE_TAG", source_tag)
    monkeypatch.setenv("CONFIGURATION_BUCKET", configuration_bucket)
    monkeypatch.setenv("CATALOG_KEY", _CATALOG_KEY)
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    return load_lambda("check_feature_entitlement")


def _put_catalog(bucket: str, features: list) -> None:
    boto3.client("s3", region_name="us-east-1").put_object(
        Bucket=bucket,
        Key=_CATALOG_KEY,
        Body=json.dumps({"schemaVersion": "1.0", "features": features}).encode("utf-8"),
    )


def _stub(
    mod,
    entitlements=None,
    *,
    expected_product="prod123",
    expected_customer="CUST-default",
    expected_account=None,
):
    """Inject a Stubber against the module's boto3 client and seed a response.

    Pass `expected_account` to assert the buyer-account filter
    (CUSTOMER_AWS_ACCOUNT_ID) instead of the CUSTOMER_IDENTIFIER filter.
    """
    client = mod._client()
    stubber = Stubber(client)
    filt = (
        {"CUSTOMER_AWS_ACCOUNT_ID": [expected_account]}
        if expected_account is not None
        else {"CUSTOMER_IDENTIFIER": [expected_customer]}
    )
    stubber.add_response(
        "get_entitlements",
        {"Entitlements": entitlements or []},
        {"ProductCode": expected_product, "Filter": filt},
    )
    stubber.activate()
    return stubber


def test_none_when_no_product_code_marketplace_mode(
    monkeypatch, load_lambda, installed_features_table
):
    """Marketplace mode: a feature whose install row has no productCode → NONE."""
    _seed_row(installed_features_table, "docs-by-status")  # no productCode
    mod = _preload(
        monkeypatch,
        load_lambda,
        table_name=installed_features_table,
        source_tag="marketplace",
    )
    result = mod.handler(
        make_appsync_event("checkFeatureEntitlement", {"featureId": "docs-by-status"}),
        None,
    )
    assert result == {
        "featureId": "docs-by-status",
        "state": "NONE",
        "expiresAt": None,
        "customerIdentifier": None,
        "productCode": None,
        "source": "none",
    }


def test_synthesized_product_code_simulator_mode(
    monkeypatch, load_lambda, installed_features_table
):
    """Simulator mode: a row without a productCode uses synthesized prod-<id>-sim
    and calls GetEntitlements against it."""
    _seed_row(installed_features_table, "docs-by-status")  # no productCode
    mod = _preload(
        monkeypatch,
        load_lambda,
        table_name=installed_features_table,
        source_tag="simulator",
    )
    _stub(
        mod,
        entitlements=[],
        expected_product="prod-docs-by-status-sim",
        expected_customer="CUST-default",
    )
    result = mod.handler(
        make_appsync_event("checkFeatureEntitlement", {"featureId": "docs-by-status"}),
        None,
    )
    assert result["state"] == "NONE"
    assert result["productCode"] == "prod-docs-by-status-sim"
    assert result["customerIdentifier"] == "CUST-default"
    assert result["source"] == "simulator"


def test_none_when_no_customer_identifier_marketplace_mode(
    monkeypatch, load_lambda, installed_features_table
):
    """Marketplace mode: no CustomerIdentifier returns NONE."""
    _seed_row(installed_features_table, "docs-by-status", product_code="prod123")
    mod = _preload(
        monkeypatch,
        load_lambda,
        table_name=installed_features_table,
        default_customer="",
        source_tag="marketplace",
    )
    result = mod.handler(
        make_appsync_event("checkFeatureEntitlement", {"featureId": "docs-by-status"}),
        None,
    )
    assert result["state"] == "NONE"
    assert result["customerIdentifier"] is None
    assert result["productCode"] == "prod123"
    assert result["source"] == "marketplace"


def test_missing_customer_identifier_filters_by_buyer_account_simulator_mode(
    monkeypatch, load_lambda, installed_features_table
):
    """Simulator mode: with no CustomerIdentifier, GetEntitlements is filtered by
    the buyer AWS account (the deterministic key shared with subscribe) — NOT a
    synthesized customer id. The resolved customer id is echoed from the matched
    entitlement."""
    _seed_row(installed_features_table, "docs-by-status", product_code="prod123")
    mod = _preload(
        monkeypatch,
        load_lambda,
        table_name=installed_features_table,
        default_customer="",
        buyer_account="111122223333",
        source_tag="simulator",
    )
    future = datetime.now(timezone.utc) + timedelta(days=30)
    _stub(
        mod,
        entitlements=[
            {
                "ProductCode": "prod123",
                "CustomerIdentifier": "cust-62c036d80d5c",
                "ExpirationDate": future,
            }
        ],
        expected_product="prod123",
        expected_account="111122223333",
    )
    result = mod.handler(
        make_appsync_event("checkFeatureEntitlement", {"featureId": "docs-by-status"}),
        None,
    )
    assert result["state"] == "ACTIVE"
    # Customer id is echoed from the matched entitlement (looked up by account).
    assert result["customerIdentifier"] == "cust-62c036d80d5c"
    assert result["productCode"] == "prod123"
    assert result["source"] == "simulator"


def test_active_when_active_entitlement(
    monkeypatch, load_lambda, installed_features_table
):
    _seed_row(installed_features_table, "docs-by-status", product_code="prod123")
    mod = _preload(monkeypatch, load_lambda, table_name=installed_features_table)
    future = datetime.now(timezone.utc) + timedelta(days=30)
    stubber = _stub(
        mod,
        entitlements=[
            {
                "ProductCode": "prod123",
                "Dimension": "USERS",
                "CustomerIdentifier": "CUST-default",
                "ExpirationDate": future,
            }
        ],
    )
    try:
        result = mod.handler(
            make_appsync_event(
                "checkFeatureEntitlement", {"featureId": "docs-by-status"}
            ),
            None,
        )
    finally:
        stubber.deactivate()
    assert result["state"] == "ACTIVE"
    assert result["expiresAt"]
    assert result["expiresAt"].endswith("Z")
    assert result["customerIdentifier"] == "CUST-default"
    assert result["productCode"] == "prod123"


def test_expired_when_only_expired_entitlement(
    monkeypatch, load_lambda, installed_features_table
):
    _seed_row(installed_features_table, "docs-by-status", product_code="prod123")
    mod = _preload(monkeypatch, load_lambda, table_name=installed_features_table)
    past = datetime.now(timezone.utc) - timedelta(days=30)
    stubber = _stub(mod, entitlements=[{"ExpirationDate": past}])
    try:
        result = mod.handler(
            make_appsync_event(
                "checkFeatureEntitlement", {"featureId": "docs-by-status"}
            ),
            None,
        )
    finally:
        stubber.deactivate()
    assert result["state"] == "EXPIRED"
    assert result["expiresAt"]


def test_active_beats_expired_when_both_present(
    monkeypatch, load_lambda, installed_features_table
):
    _seed_row(installed_features_table, "docs-by-status", product_code="prod123")
    mod = _preload(monkeypatch, load_lambda, table_name=installed_features_table)
    past = datetime.now(timezone.utc) - timedelta(days=30)
    future = datetime.now(timezone.utc) + timedelta(days=30)
    stubber = _stub(
        mod,
        entitlements=[
            {"ExpirationDate": past, "Dimension": "A"},
            {"ExpirationDate": future, "Dimension": "B"},
        ],
    )
    try:
        result = mod.handler(
            make_appsync_event(
                "checkFeatureEntitlement", {"featureId": "docs-by-status"}
            ),
            None,
        )
    finally:
        stubber.deactivate()
    assert result["state"] == "ACTIVE"


def test_active_when_no_expiration(monkeypatch, load_lambda, installed_features_table):
    _seed_row(installed_features_table, "docs-by-status", product_code="prod123")
    mod = _preload(monkeypatch, load_lambda, table_name=installed_features_table)
    stubber = _stub(mod, entitlements=[{"Dimension": "X"}])
    try:
        result = mod.handler(
            make_appsync_event(
                "checkFeatureEntitlement", {"featureId": "docs-by-status"}
            ),
            None,
        )
    finally:
        stubber.deactivate()
    assert result["state"] == "ACTIVE"
    assert result["expiresAt"] is None


def test_none_when_empty_entitlements(
    monkeypatch, load_lambda, installed_features_table
):
    _seed_row(installed_features_table, "docs-by-status", product_code="prod123")
    mod = _preload(monkeypatch, load_lambda, table_name=installed_features_table)
    stubber = _stub(mod, entitlements=[])
    try:
        result = mod.handler(
            make_appsync_event(
                "checkFeatureEntitlement", {"featureId": "docs-by-status"}
            ),
            None,
        )
    finally:
        stubber.deactivate()
    assert result["state"] == "NONE"


def test_header_customer_identifier_takes_precedence(
    monkeypatch, load_lambda, installed_features_table
):
    _seed_row(installed_features_table, "docs-by-status", product_code="prod123")
    mod = _preload(
        monkeypatch,
        load_lambda,
        table_name=installed_features_table,
        default_customer="CUST-default",
    )
    future = datetime.now(timezone.utc) + timedelta(days=30)
    stubber = _stub(
        mod,
        entitlements=[{"ExpirationDate": future}],
        expected_customer="CUST-from-header",
    )
    try:
        result = mod.handler(
            make_appsync_event(
                "checkFeatureEntitlement",
                {"featureId": "docs-by-status"},
                headers={"x-amzn-marketplace-customer-identifier": "CUST-from-header"},
            ),
            None,
        )
    finally:
        stubber.deactivate()
    assert result["state"] == "ACTIVE"
    assert result["customerIdentifier"] == "CUST-from-header"


def test_missing_featureId_raises(monkeypatch, load_lambda):
    mod = _preload(monkeypatch, load_lambda)
    with pytest.raises(ValueError, match="featureId"):
        mod.handler(make_appsync_event("checkFeatureEntitlement", {}), None)


def test_auto_mode_returns_active_without_marketplace_call(monkeypatch, load_lambda):
    """Auto-subscribe mode (no simulator, no Marketplace endpoint) short-circuits
    to ACTIVE for every featureId. The boto3 marketplace-entitlement client must
    never be instantiated — that's the contract that lets the stack run with no
    Marketplace credentials."""
    mod = _preload(monkeypatch, load_lambda, source_tag="auto")
    # Sanity: no client created yet at module load.
    assert mod._entitlement_client is None
    result = mod.handler(
        make_appsync_event("checkFeatureEntitlement", {"featureId": "docs-by-status"}),
        None,
    )
    assert result == {
        "featureId": "docs-by-status",
        "state": "ACTIVE",
        "expiresAt": None,
        "customerIdentifier": None,
        "productCode": None,
        "source": "auto",
    }
    # Contract: no boto3 client is constructed in auto mode.
    assert mod._entitlement_client is None


def test_no_table_falls_back_to_none_marketplace_mode(monkeypatch, load_lambda):
    # No InstalledFeatures table configured → no productCode → marketplace NONE.
    mod = _preload(
        monkeypatch,
        load_lambda,
        table_name="",
        source_tag="marketplace",
    )
    result = mod.handler(
        make_appsync_event("checkFeatureEntitlement", {"featureId": "docs-by-status"}),
        None,
    )
    assert result["state"] == "NONE"
    assert result["source"] == "none"


def test_oss_feature_short_circuits_to_active_marketplace_mode(
    monkeypatch, mock_stack, load_lambda
):
    """OSS catalog features have no Marketplace contract — even with a simulator/
    Marketplace endpoint configured (source_tag=marketplace), they short-circuit
    to ACTIVE so the UI shows the Install prompt, not 'Subscription required'.
    No entitlement client is constructed for the OSS path."""
    bucket = mock_stack["bucket"]
    _put_catalog(
        bucket,
        [{"featureId": "docs-by-status", "source": "oss", "latestVersion": "1.0.0"}],
    )
    # No productCode on the install row — marketplace mode would otherwise be NONE.
    mod = _preload(
        monkeypatch,
        load_lambda,
        table_name=mock_stack["table_name"],
        source_tag="marketplace",
        configuration_bucket=bucket,
    )
    result = mod.handler(
        make_appsync_event("checkFeatureEntitlement", {"featureId": "docs-by-status"}),
        None,
    )
    assert result == {
        "featureId": "docs-by-status",
        "state": "ACTIVE",
        "expiresAt": None,
        "customerIdentifier": None,
        "productCode": None,
        "source": "oss",
    }
    # Contract: the OSS path never touches the marketplace-entitlement client.
    assert mod._entitlement_client is None


def test_marketplace_feature_still_gated_when_catalog_present(
    monkeypatch, mock_stack, load_lambda
):
    """A catalog entry with source=marketplace does NOT short-circuit — the
    entitlement check still runs (here: no productCode on the row → NONE)."""
    bucket = mock_stack["bucket"]
    _put_catalog(
        bucket,
        [{"featureId": "idp-monitor", "source": "marketplace", "latestVersion": "1.0"}],
    )
    mod = _preload(
        monkeypatch,
        load_lambda,
        table_name=mock_stack["table_name"],
        source_tag="marketplace",
        configuration_bucket=bucket,
    )
    result = mod.handler(
        make_appsync_event("checkFeatureEntitlement", {"featureId": "idp-monitor"}),
        None,
    )
    assert result["state"] == "NONE"
    assert result["source"] == "none"
