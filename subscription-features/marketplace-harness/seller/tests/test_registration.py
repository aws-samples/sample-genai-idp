"""Smoke tests for seller/src/registration/handler.py.

Uses moto to stub DynamoDB and botocore Stubber to stub ResolveCustomer.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import boto3
import pytest
from botocore.stub import Stubber
from moto import mock_aws

SRC = Path(__file__).parent.parent / "src" / "registration"
sys.path.insert(0, str(SRC))


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("CUSTOMERS_TABLE", "mp-harness-Customers-test")
    monkeypatch.setenv("ENTITLEMENTS_TABLE", "mp-harness-Entitlements-test")
    monkeypatch.setenv("USAGE_LEDGER_TABLE", "mp-harness-UsageLedger-test")
    yield


@mock_aws
def test_registration_happy_path(env):  # noqa: ARG001  fixture side effects
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName=os.environ["CUSTOMERS_TABLE"],
        AttributeDefinitions=[
            {"AttributeName": "customerIdentifier", "AttributeType": "S"}
        ],
        KeySchema=[{"AttributeName": "customerIdentifier", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
    )

    # Fresh import so module-level boto3 clients bind to the mocked region
    if "handler" in sys.modules:
        importlib.reload(sys.modules["handler"])
    import handler  # type: ignore[import-not-found]

    stub = Stubber(handler._mp)
    stub.add_response(
        "resolve_customer",
        {
            "CustomerIdentifier": "cust-abc",
            "CustomerAWSAccountId": "123456789012",
            "ProductCode": "placeholder-product-code",
        },
        {"RegistrationToken": "tok-123"},
    )
    stub.activate()

    event = {"body": "x-amzn-marketplace-token=tok-123"}
    resp = handler.lambda_handler(event, None)

    stub.assert_no_pending_responses()
    assert resp["statusCode"] == 200
    item = ddb.Table(os.environ["CUSTOMERS_TABLE"]).get_item(
        Key={"customerIdentifier": "cust-abc"}
    )["Item"]
    assert item["status"] == "trial"
    assert item["productCode"] == "placeholder-product-code"


@mock_aws
def test_registration_missing_token(env):  # noqa: ARG001
    if "handler" in sys.modules:
        importlib.reload(sys.modules["handler"])
    import handler  # type: ignore[import-not-found]

    resp = handler.lambda_handler({"body": ""}, None)
    assert resp["statusCode"] == 400
