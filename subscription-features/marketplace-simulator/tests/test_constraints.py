"""Real-world constraint tests.

The simulator only earns its keep if it enforces the same friction real AWS
Marketplace does, so sellers don't discover these rules only during AMMP
listing review. The feasibility doc lists the ones we care about:

- pricing model cannot change after a product is published
- existing dimensions cannot be renamed/deleted after publish (new OK)
- dimension apiName ≤ 15 chars
- metering records >6h old are rejected (covered by test_sdk_compat)
- one free trial per (buyer account, product)           (covered by test_full_lifecycle)
- private-offer allowlist enforced                      (covered by test_full_lifecycle)
- BatchMeterUsage max 25 records per call
- ResolveCustomer token expires
"""

from __future__ import annotations

import time

import boto3
import pytest
from botocore.exceptions import ClientError

from client.mp_simulator_client import MpSimulatorError

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
]


def test_pricing_model_locked_after_publish(simulator):
    _, client = simulator
    p = client.create_product(name="P", pricingModel="contract", dimensions=DIMS)
    # Unpublished: changing pricing model is allowed
    p2 = client.update_product(p["product_code"], pricingModel="contract-with-payg")
    assert p2["pricing_model"] == "contract-with-payg"

    client.publish_product(p["product_code"])
    # After publish: cannot change
    with pytest.raises(MpSimulatorError) as exc_info:
        client.update_product(p["product_code"], pricingModel="subscription")
    assert exc_info.value.error_type == "InvalidParameterException"
    assert "cannot be changed" in exc_info.value.message


def test_dimension_removal_blocked_after_publish(simulator):
    _, client = simulator
    p = client.create_product(name="P", pricingModel="contract", dimensions=DIMS)
    client.publish_product(p["product_code"])

    # Adding a dimension is OK
    new_dims = DIMS + [
        {
            "apiName": "docs_new",
            "displayName": "New",
            "category": "Units",
            "unitPrice": 0.003,
            "kind": "usage",
        }
    ]
    p2 = client.update_product(p["product_code"], dimensions=new_dims)
    assert len(p2["dimensions"]) == 3

    # Removing an existing dimension is NOT OK
    with pytest.raises(MpSimulatorError) as exc_info:
        client.update_product(p["product_code"], dimensions=[DIMS[0]])  # drop docs_used
    assert exc_info.value.error_type == "InvalidParameterException"
    assert "cannot remove" in exc_info.value.message


def test_dimension_name_length_limit(simulator):
    _, client = simulator
    bad = [
        {
            "apiName": "this_is_way_too_long_to_fit_15_chars",
            "displayName": "Oops",
            "category": "Units",
            "unitPrice": 0.01,
            "kind": "usage",
        }
    ]
    with pytest.raises(MpSimulatorError) as exc_info:
        client.create_product(name="P", pricingModel="contract", dimensions=bad)
    assert exc_info.value.error_type == "InvalidParameterException"
    assert "15-char" in exc_info.value.message


def test_batch_meter_usage_rejects_more_than_25_records(simulator):
    _, client = simulator
    p = client.create_product(name="P", pricingModel="contract-with-payg", dimensions=DIMS)
    offer = client.create_offer(
        productCode=p["product_code"],
        kind="public",
        contractTier={"dimension": "cap_docs", "quantity": 10},
    )
    sub = client.subscribe(offerId=offer["offer_id"], buyerAccountId="123")

    mp = boto3.client("meteringmarketplace", region_name=REGION)
    now = int(time.time())
    too_many = [
        {
            "Timestamp": now,
            "CustomerIdentifier": sub["customerIdentifier"],
            "Dimension": "docs_used",
            "Quantity": 1,
        }
        for _ in range(26)
    ]
    with pytest.raises(ClientError) as exc_info:
        mp.batch_meter_usage(ProductCode=p["product_code"], UsageRecords=too_many)
    # boto3 reports via 'Error.Code'
    assert exc_info.value.response["Error"]["Code"] == "InvalidParameterException"


def test_resolve_customer_token_expires(simulator):
    _, client = simulator
    p = client.create_product(name="P", pricingModel="contract", dimensions=DIMS)
    offer = client.create_offer(
        productCode=p["product_code"],
        kind="public",
        contractTier={"dimension": "cap_docs", "quantity": 1},
    )
    sub = client.subscribe(offerId=offer["offer_id"], buyerAccountId="123")

    mp = boto3.client("meteringmarketplace", region_name=REGION)
    # Within expiration window (1 hour): works
    assert (
        mp.resolve_customer(RegistrationToken=sub["registrationToken"])["CustomerIdentifier"]
        == sub["customerIdentifier"]
    )

    # Advance 2 hours: token expired
    client.advance_time(2 * 3600)
    with pytest.raises(ClientError) as exc_info:
        mp.resolve_customer(RegistrationToken=sub["registrationToken"])
    assert exc_info.value.response["Error"]["Code"] == "InvalidTokenException"


def test_published_product_surfaces_via_list(simulator):
    """Smoke: published=1 is persisted and discoverable."""
    _, client = simulator
    p = client.create_product(name="P", pricingModel="contract", dimensions=DIMS)
    assert p["published"] == 0
    client.publish_product(p["product_code"])
    fresh = client.get_product(p["product_code"])
    assert fresh["published"] == 1
