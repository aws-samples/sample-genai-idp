"""Unit tests for the docs-by-status feature API handler."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

_HANDLER_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def stack(aws_credentials, monkeypatch):
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        # Mirror the main stack's TrackingTable schema: composite PK+SK plus
        # the TypeDateIndex GSI (ItemType hash, InitialEventTime range).
        table = ddb.create_table(
            TableName="TrackingTest",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "ItemType", "AttributeType": "S"},
                {"AttributeName": "InitialEventTime", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "TypeDateIndex",
                    "KeySchema": [
                        {"AttributeName": "ItemType", "KeyType": "HASH"},
                        {"AttributeName": "InitialEventTime", "KeyType": "RANGE"},
                    ],
                    "Projection": {
                        "ProjectionType": "INCLUDE",
                        "NonKeyAttributes": ["ObjectKey", "ObjectStatus"],
                    },
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
        for i, status in enumerate(
            ["NEW", "QUEUED", "COMPLETED", "COMPLETED", "FAILED"]
        ):
            table.put_item(
                Item={
                    "PK": f"doc#doc-{i}.pdf",
                    "SK": "none",
                    "ItemType": "document",
                    "ObjectKey": f"doc-{i}.pdf",
                    "ObjectStatus": status,
                    "InitialEventTime": "2026-05-01T10:00:00Z",
                }
            )
        # Add a non-document row to verify the ItemType filter works.
        table.put_item(
            Item={
                "PK": "section#x",
                "SK": "1",
                "ItemType": "section",
                "ObjectStatus": "SHOULD_NOT_COUNT",
                "InitialEventTime": "2026-05-01T10:00:00Z",
            }
        )
        monkeypatch.setenv("DOCUMENTS_TABLE_NAME", "TrackingTest")
        # Fresh import so the module picks up the new env var.
        sys.path.insert(0, str(_HANDLER_DIR))
        sys.modules.pop("handler", None)
        mod = importlib.import_module("handler")
        sys.path.remove(str(_HANDLER_DIR))
        yield mod


def _event(path: str = "/counts", qs: dict | None = None) -> dict:
    return {
        "rawPath": path,
        "queryStringParameters": qs,
        "requestContext": {"http": {"method": "GET"}},
    }


def test_counts_returns_canonical_zeroed_buckets(stack):
    resp = stack.lambda_handler(_event(), None)
    assert resp["statusCode"] == 200
    import json

    body = json.loads(resp["body"])
    counts = body["counts"]
    assert counts["COMPLETED"] == 2
    assert counts["NEW"] == 1
    assert counts["FAILED"] == 1
    assert counts["QUEUED"] == 1
    # Zero-filled bucket must still be present.
    assert "RUNNING" in counts and counts["RUNNING"] == 0
    assert body["total"] == 5


def test_bad_window_returns_400(stack):
    resp = stack.lambda_handler(_event(qs={"window": "foo"}), None)
    assert resp["statusCode"] == 400


def test_unknown_path_returns_404(stack):
    resp = stack.lambda_handler(_event(path="/other"), None)
    assert resp["statusCode"] == 404
