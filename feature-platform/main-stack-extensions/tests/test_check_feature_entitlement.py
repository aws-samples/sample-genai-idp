"""Unit tests for the check_feature_entitlement Lambda.

moto does not implement marketplace-entitlement, so we use botocore.stub.Stubber
to programme the boto3 client inside the module after import.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from _helpers import make_appsync_event
from botocore.stub import Stubber


def _preload(
    monkeypatch,
    load_lambda,
    *,
    product_map='{"docs-by-status":"prod123"}',
    default_customer="CUST-default",
    source_tag="simulator",
):
    monkeypatch.setenv("FEATURE_PRODUCT_CODE_MAP", product_map)
    monkeypatch.setenv("DEFAULT_CUSTOMER_IDENTIFIER", default_customer)
    monkeypatch.setenv("SIMULATOR_SOURCE_TAG", source_tag)
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    return load_lambda("check_feature_entitlement")


def _stub(
    mod,
    entitlements=None,
    *,
    expected_product="prod123",
    expected_customer="CUST-default",
):
    """Inject a Stubber against the module's boto3 client and seed a response."""
    client = mod._client()
    stubber = Stubber(client)
    stubber.add_response(
        "get_entitlements",
        {"Entitlements": entitlements or []},
        {
            "ProductCode": expected_product,
            "Filter": {"CUSTOMER_IDENTIFIER": [expected_customer]},
        },
    )
    stubber.activate()
    return stubber


def test_none_when_no_product_code_mapped_marketplace_mode(monkeypatch, load_lambda):
    """Marketplace mode: unmapped featureId returns NONE (can't synthesize)."""
    mod = _preload(
        monkeypatch, load_lambda, product_map='{"other":"x"}', source_tag="marketplace"
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


def test_synthesized_product_code_simulator_mode(monkeypatch, load_lambda):
    """Simulator mode: unmapped featureId uses synthesized prod-<id>-sim code
    and calls GetEntitlements against it. Here we seed an empty response so
    the caller sees NONE but productCode + source should reflect the synthesis."""
    mod = _preload(
        monkeypatch, load_lambda, product_map='{"other":"x"}', source_tag="simulator"
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


def test_none_when_no_customer_identifier_marketplace_mode(monkeypatch, load_lambda):
    """Marketplace mode: no CustomerIdentifier returns NONE."""
    mod = _preload(
        monkeypatch, load_lambda, default_customer="", source_tag="marketplace"
    )
    result = mod.handler(
        make_appsync_event("checkFeatureEntitlement", {"featureId": "docs-by-status"}),
        None,
    )
    assert result["state"] == "NONE"
    assert result["customerIdentifier"] is None
    assert result["productCode"] == "prod123"
    assert result["source"] == "marketplace"


def test_synthesized_customer_identifier_simulator_mode(monkeypatch, load_lambda):
    """Simulator mode: missing CustomerIdentifier falls back to 'cust-idp-default'
    and calls GetEntitlements against it."""
    mod = _preload(
        monkeypatch, load_lambda, default_customer="", source_tag="simulator"
    )
    _stub(
        mod,
        entitlements=[],
        expected_product="prod123",
        expected_customer="cust-idp-default",
    )
    result = mod.handler(
        make_appsync_event("checkFeatureEntitlement", {"featureId": "docs-by-status"}),
        None,
    )
    assert result["state"] == "NONE"
    assert result["customerIdentifier"] == "cust-idp-default"
    assert result["productCode"] == "prod123"
    assert result["source"] == "simulator"


def test_active_when_active_entitlement(monkeypatch, load_lambda):
    mod = _preload(monkeypatch, load_lambda)
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


def test_expired_when_only_expired_entitlement(monkeypatch, load_lambda):
    mod = _preload(monkeypatch, load_lambda)
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


def test_active_beats_expired_when_both_present(monkeypatch, load_lambda):
    mod = _preload(monkeypatch, load_lambda)
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


def test_active_when_no_expiration(monkeypatch, load_lambda):
    mod = _preload(monkeypatch, load_lambda)
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


def test_none_when_empty_entitlements(monkeypatch, load_lambda):
    mod = _preload(monkeypatch, load_lambda)
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


def test_header_customer_identifier_takes_precedence(monkeypatch, load_lambda):
    mod = _preload(monkeypatch, load_lambda, default_customer="CUST-default")
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


def test_malformed_env_var_map_falls_back_to_empty(monkeypatch, load_lambda):
    # Malformed JSON → empty map → marketplace mode returns NONE for any feature.
    mod = _preload(
        monkeypatch,
        load_lambda,
        product_map="this-is-not-json",
        source_tag="marketplace",
    )
    result = mod.handler(
        make_appsync_event("checkFeatureEntitlement", {"featureId": "docs-by-status"}),
        None,
    )
    assert result["state"] == "NONE"
    assert result["source"] == "none"
