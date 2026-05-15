"""SDK compatibility tests for boto3 marketplace-catalog.

These prove the **seller-side** catalog SDK surface works unchanged: a seller
creating / updating / publishing products through the real AWS SDK (what
sophisticated sellers use to programmatically manage listings, bypassing AMMP).
"""

from __future__ import annotations

import json
import time

import boto3
import pytest
from botocore.exceptions import ClientError

REGION = "us-east-1"

DIMS = [
    {
        "apiName": "cap_docs",
        "displayName": "Capacity",
        "category": "Units",
        "unitPrice": 0.05,
        "kind": "contract",
    },
    {
        "apiName": "docs_used",
        "displayName": "Used",
        "category": "Units",
        "unitPrice": 0.001,
        "kind": "usage",
    },
]


def _poll_status(cat, cs_id: str, timeout: float = 2.0) -> dict:
    """ChangeSets are applied synchronously in the simulator, so this returns
    quickly. Pattern mirrors what a real SDK user would write."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = cat.describe_change_set(Catalog="AWSMarketplace", ChangeSetId=cs_id)
        if r["Status"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            return r
        time.sleep(0.05)
    raise AssertionError(f"change set {cs_id} did not terminate in {timeout}s")


def test_create_product_via_boto3_change_set(simulator):
    """The main seller workflow: StartChangeSet with CreateProduct."""
    cat = boto3.client("marketplace-catalog", region_name=REGION)
    resp = cat.start_change_set(
        Catalog="AWSMarketplace",
        ChangeSetName="initial-listing",
        ChangeSet=[
            {
                "ChangeType": "CreateProduct",
                "Entity": {"Type": "SaaSProduct"},
                "Details": json.dumps(
                    {
                        "Product": {
                            "Name": "Catalog-created product",
                            "PricingModel": "contract-with-payg",
                            "TrialDays": 14,
                            "Dimensions": DIMS,
                        }
                    }
                ),
            }
        ],
    )
    assert resp["ChangeSetId"].startswith("cs-")
    status = _poll_status(cat, resp["ChangeSetId"])
    assert status["Status"] == "SUCCEEDED"


def test_list_entities_via_boto3(simulator):
    _, client = simulator
    # Seed with an admin product
    client.create_product(name="P1", pricingModel="contract", dimensions=DIMS)
    client.create_product(name="P2", pricingModel="contract", dimensions=DIMS)

    cat = boto3.client("marketplace-catalog", region_name=REGION)
    resp = cat.list_entities(Catalog="AWSMarketplace", EntityType="SaaSProduct")
    assert len(resp["EntitySummaryList"]) == 2
    for e in resp["EntitySummaryList"]:
        assert e["EntityType"] == "SaaSProduct"


def test_describe_entity_product(simulator):
    _, client = simulator
    p = client.create_product(name="P", pricingModel="contract", dimensions=DIMS, trialDays=30)
    cat = boto3.client("marketplace-catalog", region_name=REGION)
    resp = cat.describe_entity(Catalog="AWSMarketplace", EntityId=p["product_code"])
    assert resp["EntityType"] == "SaaSProduct"
    assert resp["EntityIdentifier"] == p["product_code"]
    details = json.loads(resp["Details"])
    assert details["PricingModel"] == "contract"
    assert details["TrialDays"] == 30


def test_describe_entity_not_found(simulator):
    cat = boto3.client("marketplace-catalog", region_name=REGION)
    with pytest.raises(ClientError) as exc_info:
        cat.describe_entity(Catalog="AWSMarketplace", EntityId="no-such-thing")
    assert exc_info.value.response["Error"]["Code"] == "ResourceNotFoundException"


def test_release_product_via_change_set(simulator):
    _, client = simulator
    p = client.create_product(name="Draft", pricingModel="contract", dimensions=DIMS)
    assert p["published"] == 0

    cat = boto3.client("marketplace-catalog", region_name=REGION)
    cs = cat.start_change_set(
        Catalog="AWSMarketplace",
        ChangeSet=[
            {
                "ChangeType": "ReleaseProduct",
                "Entity": {"Type": "SaaSProduct", "Identifier": p["product_code"]},
            }
        ],
    )
    status = _poll_status(cat, cs["ChangeSetId"])
    assert status["Status"] == "SUCCEEDED"

    fresh = client.get_product(p["product_code"])
    assert fresh["published"] == 1


def test_add_dimensions_via_change_set(simulator):
    _, client = simulator
    p = client.create_product(name="P", pricingModel="contract", dimensions=DIMS)

    cat = boto3.client("marketplace-catalog", region_name=REGION)
    cs = cat.start_change_set(
        Catalog="AWSMarketplace",
        ChangeSet=[
            {
                "ChangeType": "AddDimensions",
                "Entity": {"Type": "SaaSProduct", "Identifier": p["product_code"]},
                "Details": json.dumps(
                    {
                        "Dimensions": [
                            {
                                "apiName": "docs_over",
                                "displayName": "Overage",
                                "category": "Units",
                                "unitPrice": 0.002,
                                "kind": "overage",
                            }
                        ]
                    }
                ),
            }
        ],
    )
    status = _poll_status(cat, cs["ChangeSetId"])
    assert status["Status"] == "SUCCEEDED"

    fresh = client.get_product(p["product_code"])
    api_names = [d["apiName"] for d in fresh["dimensions"]]
    assert "docs_over" in api_names


def test_unsupported_change_type_fails_the_change_set(simulator):
    cat = boto3.client("marketplace-catalog", region_name=REGION)
    cs = cat.start_change_set(
        Catalog="AWSMarketplace",
        ChangeSet=[
            {
                "ChangeType": "WeirdThing",
                "Entity": {"Type": "SaaSProduct"},
                "Details": "{}",
            }
        ],
    )
    status = _poll_status(cat, cs["ChangeSetId"])
    assert status["Status"] == "FAILED"
    assert status["FailureCode"] == "ValidationException"


def test_list_change_sets(simulator):
    cat = boto3.client("marketplace-catalog", region_name=REGION)
    # Seed one
    cat.start_change_set(
        Catalog="AWSMarketplace",
        ChangeSet=[
            {
                "ChangeType": "CreateProduct",
                "Entity": {"Type": "SaaSProduct"},
                "Details": json.dumps(
                    {
                        "Product": {"Name": "P", "PricingModel": "contract", "Dimensions": DIMS},
                    }
                ),
            }
        ],
    )

    resp = cat.list_change_sets(Catalog="AWSMarketplace")
    assert len(resp["ChangeSetSummaryList"]) >= 1
    assert resp["ChangeSetSummaryList"][0]["Status"] in ("SUCCEEDED", "PREPARING")


def test_seller_and_buyer_full_flow_via_sdk_only(simulator):
    """Bookend test: a seller creates the product + offer via marketplace-catalog,
    a buyer subscribes (via simulator's /buyer since real AWS has no SDK for it),
    then the buyer inspects the agreement via marketplace-agreement, and the
    seller meters via meteringmarketplace. All SDK calls boto3-native."""
    _, client = simulator
    cat = boto3.client("marketplace-catalog", region_name=REGION)
    agmt = boto3.client("marketplace-agreement", region_name=REGION)
    mp = boto3.client("meteringmarketplace", region_name=REGION)

    # Seller: CreateProduct + ReleaseProduct + CreateOffer in one ChangeSet
    cs = cat.start_change_set(
        Catalog="AWSMarketplace",
        ChangeSet=[
            {
                "ChangeType": "CreateProduct",
                "Entity": {"Type": "SaaSProduct"},
                "Details": json.dumps(
                    {
                        "Product": {
                            "Name": "E2E via SDK",
                            "PricingModel": "contract-with-payg",
                            "TrialDays": 7,
                            "Dimensions": DIMS,
                        }
                    }
                ),
            }
        ],
    )
    assert _poll_status(cat, cs["ChangeSetId"])["Status"] == "SUCCEEDED"

    prods = cat.list_entities(Catalog="AWSMarketplace", EntityType="SaaSProduct")
    product_code = prods["EntitySummaryList"][-1]["EntityId"]

    # Seller: CreateOffer
    cs = cat.start_change_set(
        Catalog="AWSMarketplace",
        ChangeSet=[
            {
                "ChangeType": "CreateOffer",
                "Entity": {"Type": "SaaSProductOffer", "Identifier": product_code},
                "Details": json.dumps(
                    {
                        "Offer": {
                            "Kind": "public",
                            "ContractTier": {"dimension": "cap_docs", "quantity": 100},
                            "DurationMonths": 1,
                            "FreeTrialEnabled": True,
                        }
                    }
                ),
            }
        ],
    )
    assert _poll_status(cat, cs["ChangeSetId"])["Status"] == "SUCCEEDED"

    offers_list = client.list_offers(product_code=product_code)
    offer_id = offers_list[0]["offer_id"]

    # Buyer: subscribe (simulator REST — real AWS has no SDK for this)
    sub = client.subscribe(offerId=offer_id, buyerAccountId="123123123123")

    # Buyer-side SDK: describe the agreement
    ag = agmt.describe_agreement(agreementId=sub["agreementId"])
    assert ag["status"] == "ACTIVE"

    # Seller-side SDK: meter some usage
    rec = mp.batch_meter_usage(
        ProductCode=product_code,
        UsageRecords=[
            {
                "Timestamp": int(time.time()),
                "CustomerIdentifier": sub["customerIdentifier"],
                "Dimension": "docs_used",
                "Quantity": 5,
            }
        ],
    )
    assert rec["Results"][0]["Status"] == "Success"
