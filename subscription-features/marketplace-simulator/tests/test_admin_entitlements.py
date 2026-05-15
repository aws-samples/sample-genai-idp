"""Tests for the simulator-only `/admin/entitlements[/expire]` shortcut endpoints.

These are the endpoints the feature-platform's subscribe_feature /
unsubscribe_feature Lambdas hit. They let an admin grant/expire a per-feature
entitlement without going through the full product+offer+subscribe ceremony.
"""

from __future__ import annotations

import boto3


def _ent_client() -> "boto3.client":
    return boto3.client("marketplace-entitlement", region_name="us-east-1")


def test_grant_entitlement_auto_creates_product_and_returns_active(simulator):
    _, client = simulator
    result = client.grant_entitlement(
        customerIdentifier="CUST-1",
        productCode="prod-feat-a",
        featureId="feat-a",
    )
    assert result["state"] == "ACTIVE"
    assert result["customerIdentifier"] == "CUST-1"
    assert result["productCode"] == "prod-feat-a"
    assert result["featureId"] == "feat-a"
    # expiresAt is epoch seconds, roughly now + 365 days
    assert result["expiresAt"] > 1_000_000_000

    # The product row was auto-created
    products = client.list_products()
    assert any(p["product_code"] == "prod-feat-a" for p in products)


def test_grant_entitlement_then_get_entitlements_returns_it(simulator):
    """The real test: the entitlement granted via the shortcut must be visible
    over the boto3 data-plane (`GetEntitlements`) — that's what the
    check_feature_entitlement Lambda reads.
    """
    _, client = simulator
    client.grant_entitlement(
        customerIdentifier="CUST-2",
        productCode="prod-feat-b",
        featureId="feat-b",
    )
    resp = _ent_client().get_entitlements(
        ProductCode="prod-feat-b",
        Filter={"CUSTOMER_IDENTIFIER": ["CUST-2"]},
    )
    assert len(resp["Entitlements"]) == 1
    ent = resp["Entitlements"][0]
    assert ent["CustomerIdentifier"] == "CUST-2"
    assert ent["ProductCode"] == "prod-feat-b"
    assert ent["Dimension"] == "feature"
    assert ent["Value"] == {"BooleanValue": True}


def test_expire_entitlement_removes_it_from_get_entitlements(simulator):
    """After POSTing /admin/entitlements/expire, GetEntitlements should return
    an empty list (the simulator drops past-dated entitlements from the
    response, matching real Marketplace)."""
    _, client = simulator
    client.grant_entitlement(
        customerIdentifier="CUST-3",
        productCode="prod-feat-c",
        featureId="feat-c",
    )
    result = client.expire_entitlement(
        customerIdentifier="CUST-3",
        productCode="prod-feat-c",
        featureId="feat-c",
    )
    assert result["state"] == "EXPIRED"

    resp = _ent_client().get_entitlements(
        ProductCode="prod-feat-c",
        Filter={"CUSTOMER_IDENTIFIER": ["CUST-3"]},
    )
    assert resp["Entitlements"] == []


def test_grant_is_idempotent(simulator):
    """Granting twice should leave a single entitlement row with the latest
    expiration."""
    _, client = simulator
    client.grant_entitlement(
        customerIdentifier="CUST-4",
        productCode="prod-feat-d",
        expiresInSeconds=60,
    )
    client.grant_entitlement(
        customerIdentifier="CUST-4",
        productCode="prod-feat-d",
        expiresInSeconds=3600,
    )
    resp = _ent_client().get_entitlements(
        ProductCode="prod-feat-d",
        Filter={"CUSTOMER_IDENTIFIER": ["CUST-4"]},
    )
    assert len(resp["Entitlements"]) == 1


def test_grant_respects_existing_product(simulator):
    """If the product already exists (created via the normal flow), don't
    replace it — just seed the entitlement."""
    _, client = simulator
    product = client.create_product(
        name="My Feature",
        pricingModel="contract",
        dimensions=[
            {
                "apiName": "feature",
                "displayName": "Feature flag",
                "category": "Units",
                "unitPrice": 0.0,
                "kind": "feature",
            }
        ],
    )
    pc = product["product_code"]
    before = client.get_product(pc)
    client.grant_entitlement(customerIdentifier="CUST-5", productCode=pc)
    after = client.get_product(pc)
    # The product row was not overwritten (same name)
    assert before["name"] == after["name"] == "My Feature"


def test_expire_is_idempotent_when_no_entitlement_exists(simulator):
    """Expiring a non-existent entitlement should succeed quietly."""
    _, client = simulator
    # Product doesn't exist yet, and no entitlement — still OK
    result = client.expire_entitlement(customerIdentifier="CUST-nobody", productCode="prod-nothing")
    assert result["state"] == "EXPIRED"


def test_grant_requires_customer_identifier_and_product_code(simulator):
    """Missing either required field → 400 InvalidParameterException."""
    import pytest
    from client.mp_simulator_client import MpSimulatorError

    _, client = simulator
    with pytest.raises(MpSimulatorError) as ei:
        client._req("POST", "/admin/entitlements", json_body={"productCode": "p"})
    assert ei.value.status == 400
    with pytest.raises(MpSimulatorError) as ei:
        client._req(
            "POST",
            "/admin/entitlements",
            json_body={"customerIdentifier": "c"},
        )
    assert ei.value.status == 400
