"""SDK compatibility tests for boto3 marketplace-agreement.

These prove the **buyer-side** SDK surface works unchanged: a buyer's
production code calling boto3.client('marketplace-agreement').
"""

from __future__ import annotations

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


@pytest.fixture()
def subscribed(simulator):
    _, client = simulator
    p = client.create_product(name="Ag", pricingModel="contract", dimensions=DIMS, trialDays=0)
    offer = client.create_offer(
        productCode=p["product_code"],
        kind="public",
        contractTier={"dimension": "cap_docs", "quantity": 250},
        durationMonths=1,
        freeTrialEnabled=False,
    )
    sub = client.subscribe(offerId=offer["offer_id"], buyerAccountId="444455556666")
    return p, offer, sub


def test_describe_agreement_via_boto3(simulator, subscribed):
    p, offer, sub = subscribed
    agmt = boto3.client("marketplace-agreement", region_name=REGION)
    resp = agmt.describe_agreement(agreementId=sub["agreementId"])
    assert resp["agreementId"] == sub["agreementId"]
    assert resp["acceptor"]["accountId"] == "444455556666"
    assert resp["proposer"]["accountId"]  # seller placeholder
    assert resp["status"] == "ACTIVE"
    assert resp["agreementType"] == "PurchaseAgreement"
    assert resp["proposalSummary"]["resources"][0]["id"] == p["product_code"]
    assert resp["proposalSummary"]["offerId"] == offer["offer_id"]


def test_describe_agreement_not_found_raises(simulator):
    agmt = boto3.client("marketplace-agreement", region_name=REGION)
    with pytest.raises(ClientError) as exc_info:
        agmt.describe_agreement(agreementId="agmt-nonexistent")
    assert exc_info.value.response["Error"]["Code"] == "ResourceNotFoundException"


def test_search_agreements_filter_by_acceptor(simulator, subscribed):
    _p, _offer, sub = subscribed
    agmt = boto3.client("marketplace-agreement", region_name=REGION)
    resp = agmt.search_agreements(
        catalog="AWSMarketplace",
        filters=[{"name": "AcceptorAccountId", "values": ["444455556666"]}],
    )
    summaries = resp["agreementViewSummaries"]
    assert len(summaries) == 1
    assert summaries[0]["agreementId"] == sub["agreementId"]


def test_search_agreements_filter_by_status_excludes_cancelled(simulator, subscribed):
    _p, _offer, sub = subscribed
    _, client = simulator
    client.unsubscribe(customerIdentifier=sub["customerIdentifier"])

    agmt = boto3.client("marketplace-agreement", region_name=REGION)
    active = agmt.search_agreements(
        filters=[{"name": "Status", "values": ["ACTIVE"]}],
    )["agreementViewSummaries"]
    assert active == []

    cancelled = agmt.search_agreements(
        filters=[{"name": "Status", "values": ["CANCELLED"]}],
    )["agreementViewSummaries"]
    assert len(cancelled) == 1
    assert cancelled[0]["agreementId"] == sub["agreementId"]


def test_get_agreement_terms(simulator, subscribed):
    _p, _offer, sub = subscribed
    agmt = boto3.client("marketplace-agreement", region_name=REGION)
    resp = agmt.get_agreement_terms(agreementId=sub["agreementId"])
    terms = resp["acceptedTerms"]
    # expect validity term + configurable upfront term (free trial disabled)
    assert len(terms) >= 2
    kinds = set()
    for t in terms:
        kinds.update(t.keys())
    assert "validityTerm" in kinds
    assert "configurableUpfrontPricingTerm" in kinds
