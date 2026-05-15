"""SDK compatibility tests.

These are the *primary* tests for the simulator — they assert that plain
boto3 clients work against it unchanged. If these pass, production seller
code that speaks real AWS Marketplace will work against the simulator.

We do not import anything from the simulator package here: we only use
``boto3``. The only signal that we're talking to the simulator is the
``endpoint_url`` (which conftest sets via ``AWS_ENDPOINT_URL_*``).
"""

from __future__ import annotations

import time

import boto3
import botocore
import pytest
from botocore.exceptions import ClientError

REGION = "us-east-1"
EXAMPLE_DIMS = [
    {
        "apiName": "cap_docs",
        "displayName": "Capacity (docs/month)",
        "category": "Units",
        "unitPrice": 0.01,
        "kind": "contract",
    },
    {
        "apiName": "docs_used",
        "displayName": "Documents used",
        "category": "Units",
        "unitPrice": 0.001,
        "kind": "usage",
    },
    {
        "apiName": "docs_over",
        "displayName": "Overage docs",
        "category": "Units",
        "unitPrice": 0.002,
        "kind": "overage",
    },
]


@pytest.fixture()
def product_and_subscription(simulator):
    """Shared setup: product + private offer + one subscribed customer."""
    _, client = simulator
    product = client.create_product(
        name="IDP Test Feature",
        pricingModel="contract-with-payg",
        dimensions=EXAMPLE_DIMS,
        trialDays=30,
        fulfillmentUrl=None,
    )
    offer = client.create_offer(
        productCode=product["product_code"],
        kind="private",
        buyerAccountAllowlist=["111122223333"],
        contractTier={"dimension": "cap_docs", "quantity": 100},
        freeTrialEnabled=True,
    )
    sub = client.subscribe(offerId=offer["offer_id"], buyerAccountId="111122223333")
    return product, offer, sub


# ─────────────────────────── ResolveCustomer ──────────────────────────────────
def test_resolve_customer_via_boto3(simulator, product_and_subscription):
    """boto3.client('meteringmarketplace').resolve_customer(...) works unchanged."""
    product, offer, sub = product_and_subscription
    mp = boto3.client("meteringmarketplace", region_name=REGION)
    resp = mp.resolve_customer(RegistrationToken=sub["registrationToken"])
    assert resp["CustomerIdentifier"] == sub["customerIdentifier"]
    assert resp["ProductCode"] == product["product_code"]
    assert resp["CustomerAWSAccountId"] == "111122223333"


def test_resolve_customer_invalid_token_raises_client_error(simulator):
    mp = boto3.client("meteringmarketplace", region_name=REGION)
    with pytest.raises(ClientError) as exc_info:
        mp.resolve_customer(RegistrationToken="nope-not-a-real-token")
    assert exc_info.value.response["Error"]["Code"] == "InvalidTokenException"


# ─────────────────────────── GetEntitlements ──────────────────────────────────
def test_get_entitlements_via_boto3(simulator, product_and_subscription):
    product, _, sub = product_and_subscription
    ent = boto3.client("marketplace-entitlement", region_name=REGION)
    resp = ent.get_entitlements(
        ProductCode=product["product_code"],
        Filter={"CUSTOMER_IDENTIFIER": [sub["customerIdentifier"]]},
    )
    ents = resp["Entitlements"]
    assert len(ents) == 1
    e = ents[0]
    assert e["ProductCode"] == product["product_code"]
    assert e["CustomerIdentifier"] == sub["customerIdentifier"]
    assert e["Dimension"] == "cap_docs"
    # Value is wrapped in one of IntegerValue/DoubleValue/BooleanValue/StringValue
    assert e["Value"]["IntegerValue"] == 100


def test_get_entitlements_cancelled_customer_returns_empty(simulator, product_and_subscription):
    _, client = simulator
    product, _, sub = product_and_subscription
    client.unsubscribe(customerIdentifier=sub["customerIdentifier"])

    ent = boto3.client("marketplace-entitlement", region_name=REGION)
    resp = ent.get_entitlements(
        ProductCode=product["product_code"],
        Filter={"CUSTOMER_IDENTIFIER": [sub["customerIdentifier"]]},
    )
    assert resp["Entitlements"] == []


def test_get_entitlements_mutually_exclusive_filters(simulator, product_and_subscription):
    product, _, _ = product_and_subscription
    ent = boto3.client("marketplace-entitlement", region_name=REGION)
    with pytest.raises(ClientError) as exc_info:
        ent.get_entitlements(
            ProductCode=product["product_code"],
            Filter={
                "CUSTOMER_IDENTIFIER": ["x"],
                "CUSTOMER_AWS_ACCOUNT_ID": ["y"],
            },
        )
    assert exc_info.value.response["Error"]["Code"] == "InvalidParameterException"


# ─────────────────────────── BatchMeterUsage ──────────────────────────────────
def test_batch_meter_usage_via_boto3(simulator, product_and_subscription):
    product, _, sub = product_and_subscription
    mp = boto3.client("meteringmarketplace", region_name=REGION)
    now = int(time.time())
    resp = mp.batch_meter_usage(
        ProductCode=product["product_code"],
        UsageRecords=[
            {
                "Timestamp": now,
                "CustomerIdentifier": sub["customerIdentifier"],
                "Dimension": "docs_used",
                "Quantity": 5,
            },
            {
                "Timestamp": now,
                "CustomerIdentifier": sub["customerIdentifier"],
                "Dimension": "docs_used",
                "Quantity": 3,
            },
        ],
    )
    statuses = [r["Status"] for r in resp["Results"]]
    assert statuses == ["Success", "Success"]
    assert resp["UnprocessedRecords"] == []


def test_batch_meter_usage_cancelled_customer_flagged(simulator, product_and_subscription):
    _, client = simulator
    product, _, sub = product_and_subscription
    client.unsubscribe(customerIdentifier=sub["customerIdentifier"])

    mp = boto3.client("meteringmarketplace", region_name=REGION)
    resp = mp.batch_meter_usage(
        ProductCode=product["product_code"],
        UsageRecords=[
            {
                "Timestamp": int(time.time()),
                "CustomerIdentifier": sub["customerIdentifier"],
                "Dimension": "docs_used",
                "Quantity": 1,
            }
        ],
    )
    assert resp["Results"][0]["Status"] == "CustomerNotSubscribed"


def test_batch_meter_usage_timestamp_out_of_bounds(simulator, product_and_subscription):
    product, _, sub = product_and_subscription
    mp = boto3.client("meteringmarketplace", region_name=REGION)
    stale = int(time.time()) - 7 * 3600  # > 6h
    with pytest.raises(ClientError) as exc_info:
        mp.batch_meter_usage(
            ProductCode=product["product_code"],
            UsageRecords=[
                {
                    "Timestamp": stale,
                    "CustomerIdentifier": sub["customerIdentifier"],
                    "Dimension": "docs_used",
                    "Quantity": 1,
                }
            ],
        )
    assert exc_info.value.response["Error"]["Code"] == "TimestampOutOfBoundsException"


# ─────────────────────────── MeterUsage / RegisterUsage ───────────────────────
def test_meter_usage_idempotent(simulator, product_and_subscription):
    product, _, _sub = product_and_subscription
    mp = boto3.client("meteringmarketplace", region_name=REGION)
    ts = int(time.time())
    args = {
        "ProductCode": product["product_code"],
        "Timestamp": ts,
        "UsageDimension": "docs_used",
        "UsageQuantity": 7,
        "ClientToken": "tok-same",
    }
    # Real AWS MeterUsage derives the customer from the caller's instance role.
    # The simulator uses the most-recent active subscription for the product
    # (see handlers/metering.py:meter_usage). Same ClientToken + same params =>
    # same MeteringRecordId.
    r1 = mp.meter_usage(**args)
    r2 = mp.meter_usage(**args)
    assert r1["MeteringRecordId"] == r2["MeteringRecordId"]


def test_register_usage_returns_signature(simulator, product_and_subscription):
    product, _, _ = product_and_subscription
    mp = boto3.client("meteringmarketplace", region_name=REGION)
    resp = mp.register_usage(ProductCode=product["product_code"], PublicKeyVersion=1)
    assert resp["Signature"].startswith("mp-sim.")


# ─────────────────────────── sanity ─────────────────────────────────────────
def test_boto3_is_really_being_used():
    """Paranoid guard — make sure we're using the real SDK, not a mock."""
    assert "boto3" in boto3.__name__
    assert botocore.__version__


def test_endpoint_url_is_set(simulator):
    import os

    assert os.environ["AWS_ENDPOINT_URL_MARKETPLACE_METERING"].startswith("http://127.0.0.1:")
    assert os.environ["AWS_ENDPOINT_URL_MARKETPLACE_ENTITLEMENT_SERVICE"].startswith(
        "http://127.0.0.1:"
    )
