"""Full subscription lifecycle via admin + buyer APIs + boto3 SDK.

Exercises the path a production system would: create product, offer, subscribe,
validate with GetEntitlements, meter usage, check CloudWatch-style usage log,
unsubscribe, verify everything cleans up.
"""

from __future__ import annotations

import time

import boto3
import pytest

REGION = "us-east-1"
DIMS = [
    {
        "apiName": "cap_docs",
        "displayName": "Capacity",
        "category": "Units",
        "unitPrice": 0.01,
        "kind": "contract",
    },
    {
        "apiName": "docs_used",
        "displayName": "Docs used",
        "category": "Units",
        "unitPrice": 0.001,
        "kind": "usage",
    },
    {
        "apiName": "docs_over",
        "displayName": "Overage",
        "category": "Units",
        "unitPrice": 0.002,
        "kind": "overage",
    },
]


def test_end_to_end_happy_path(simulator):
    _base, client = simulator

    # 1. Seller admin: create product + private offer
    product = client.create_product(
        name="AutoTune (test)",
        pricingModel="contract-with-payg",
        dimensions=DIMS,
        trialDays=30,
        fulfillmentUrl=None,  # we're not testing the webhook POST-to-seller here
    )
    pc = product["product_code"]

    offer = client.create_offer(
        productCode=pc,
        kind="private",
        buyerAccountAllowlist=["123412341234"],
        contractTier={"dimension": "cap_docs", "quantity": 500},
        freeTrialEnabled=True,
    )

    # 2. Buyer: accept the offer
    sub = client.subscribe(offerId=offer["offer_id"], buyerAccountId="123412341234")
    assert sub["status"] == "trial"
    assert sub["trialEndsAt"]
    cid = sub["customerIdentifier"]
    token = sub["registrationToken"]

    # 3. Seller production code: resolve the token via SDK
    mp = boto3.client("meteringmarketplace", region_name=REGION)
    ent = boto3.client("marketplace-entitlement", region_name=REGION)

    resolved = mp.resolve_customer(RegistrationToken=token)
    assert resolved["CustomerIdentifier"] == cid
    assert resolved["CustomerAWSAccountId"] == "123412341234"

    # 4. Seller production code: check entitlement
    ents = ent.get_entitlements(ProductCode=pc, Filter={"CUSTOMER_IDENTIFIER": [cid]})[
        "Entitlements"
    ]
    assert len(ents) == 1
    assert ents[0]["Dimension"] == "cap_docs"
    assert ents[0]["Value"]["IntegerValue"] == 500

    # 5. Seller production code: meter some usage
    now = int(time.time())
    rec = mp.batch_meter_usage(
        ProductCode=pc,
        UsageRecords=[
            {"Timestamp": now, "CustomerIdentifier": cid, "Dimension": "docs_used", "Quantity": 10},
        ],
    )
    assert rec["Results"][0]["Status"] == "Success"

    # Admin can see the usage
    usage = client.list_usage(product_code=pc)
    assert len(usage) == 1
    assert usage[0]["quantity"] == 10

    # 6. Buyer: unsubscribe
    client.unsubscribe(customerIdentifier=cid)

    # 7. Entitlements are now empty, metering says CustomerNotSubscribed
    ents_after = ent.get_entitlements(ProductCode=pc, Filter={"CUSTOMER_IDENTIFIER": [cid]})[
        "Entitlements"
    ]
    assert ents_after == []

    rec2 = mp.batch_meter_usage(
        ProductCode=pc,
        UsageRecords=[
            {
                "Timestamp": int(time.time()),
                "CustomerIdentifier": cid,
                "Dimension": "docs_used",
                "Quantity": 1,
            },
        ],
    )
    assert rec2["Results"][0]["Status"] == "CustomerNotSubscribed"

    # 8. Lifecycle events captured
    notes = client.list_notifications(product_code=pc)
    actions = [n["action"] for n in notes]
    assert actions == [
        "subscribe-success",
        "unsubscribe-pending",
        "unsubscribe-success",
        "entitlement-updated",
    ]


def test_resubscribe_after_cancel_no_second_trial(simulator):
    """One-trial-per-account-per-product invariant (matches real Marketplace)."""
    _base, client = simulator
    product = client.create_product(
        name="AutoTune", pricingModel="contract", dimensions=DIMS, trialDays=7
    )
    offer = client.create_offer(
        productCode=product["product_code"],
        kind="public",
        freeTrialEnabled=True,
        contractTier={"dimension": "cap_docs", "quantity": 10},
    )

    sub1 = client.subscribe(offerId=offer["offer_id"], buyerAccountId="555566667777")
    assert sub1["status"] == "trial"
    client.unsubscribe(customerIdentifier=sub1["customerIdentifier"])

    sub2 = client.subscribe(offerId=offer["offer_id"], buyerAccountId="555566667777")
    assert sub2["status"] == "active", "second subscription should NOT grant trial"
    assert sub2["trialEndsAt"] is None


def test_private_offer_allowlist_enforced(simulator):
    _base, client = simulator
    product = client.create_product(
        name="Private", pricingModel="contract", dimensions=DIMS, trialDays=0
    )
    offer = client.create_offer(
        productCode=product["product_code"],
        kind="private",
        buyerAccountAllowlist=["111111111111"],
        contractTier={"dimension": "cap_docs", "quantity": 10},
    )

    from client.mp_simulator_client import MpSimulatorError

    with pytest.raises(MpSimulatorError) as exc_info:
        client.subscribe(offerId=offer["offer_id"], buyerAccountId="999999999999")
    assert exc_info.value.status == 403


def test_trial_expiry_via_clock_advance(simulator):
    """Advance the simulator clock past trial end; entitlements expire too."""
    _base, client = simulator
    product = client.create_product(
        name="AutoTune", pricingModel="contract", dimensions=DIMS, trialDays=7
    )
    offer = client.create_offer(
        productCode=product["product_code"],
        kind="public",
        freeTrialEnabled=True,
        contractTier={"dimension": "cap_docs", "quantity": 10},
        durationMonths=1,
    )
    sub = client.subscribe(offerId=offer["offer_id"], buyerAccountId="777788889999")

    ent = boto3.client("marketplace-entitlement", region_name=REGION)
    # Before advance: entitled
    ents = ent.get_entitlements(
        ProductCode=product["product_code"],
        Filter={"CUSTOMER_IDENTIFIER": [sub["customerIdentifier"]]},
    )["Entitlements"]
    assert len(ents) == 1

    # Advance ~31 days
    client.advance_time(31 * 86400)

    ents_after = ent.get_entitlements(
        ProductCode=product["product_code"],
        Filter={"CUSTOMER_IDENTIFIER": [sub["customerIdentifier"]]},
    )["Entitlements"]
    # Entitlement had ExpirationDate = now + duration_months*30 days; past 31 -> filtered
    assert ents_after == []
