# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for the PII Anonymization feature API (Redaction Report)."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from urllib.parse import quote

import boto3
import pytest
from moto import mock_aws

_HANDLER_DIR = Path(__file__).resolve().parents[1]
_AUDIT_TABLE = "TestRedactionAudit"


def _make_table():
    ddb = boto3.resource("dynamodb", region_name="us-west-2")
    ddb.create_table(
        TableName=_AUDIT_TABLE,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "documentId", "AttributeType": "S"},
            {"AttributeName": "gsiPk", "AttributeType": "S"},
            {"AttributeName": "createdAt", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "documentId", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "ByCreatedAt",
                "KeySchema": [
                    {"AttributeName": "gsiPk", "KeyType": "HASH"},
                    {"AttributeName": "createdAt", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )
    return ddb.Table(_AUDIT_TABLE)


@pytest.fixture
def mod(monkeypatch):
    monkeypatch.setenv("AUDIT_TABLE_NAME", _AUDIT_TABLE)
    monkeypatch.setenv("MAIN_STACK_NAME", "IDP")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    sys.path.insert(0, str(_HANDLER_DIR))
    sys.modules.pop("handler", None)
    m = importlib.import_module("handler")
    sys.path.remove(str(_HANDLER_DIR))
    return m


def _get(mod, path, qs=None):
    event = {
        "rawPath": path,
        "queryStringParameters": qs or {},
        "requestContext": {"http": {"method": "GET"}},
    }
    return mod.lambda_handler(event, None)


@mock_aws
def test_config_route(mod):
    resp = _get(mod, "/config")
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["feature"] == "pii-anonymizer"


@mock_aws
def test_report_list_and_aggregate(mod):
    table = _make_table()
    table.put_item(Item={"documentId": "a.pdf", "gsiPk": "ALL",
                         "createdAt": "2026-07-22T10:00:00Z", "piiCount": 3,
                         "mode": "redacted_only"})
    table.put_item(Item={"documentId": "b.pdf", "gsiPk": "ALL",
                         "createdAt": "2026-07-22T11:00:00Z", "piiCount": 5,
                         "mode": "redacted_and_unredacted"})
    resp = _get(mod, "/report")
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["total"] == 2
    assert body["totalPiiRedacted"] == 8
    # newest first (ScanIndexForward=False)
    assert body["rows"][0]["documentId"] == "b.pdf"


@mock_aws
def test_report_detail(mod):
    table = _make_table()
    table.put_item(Item={"documentId": "sub/dir/doc.pdf", "gsiPk": "ALL",
                         "createdAt": "2026-07-22T10:00:00Z", "piiCount": 2,
                         "redactedKey": "_pii_redacted/sub/dir/doc.pdf"})
    resp = _get(mod, f"/report/{quote('sub/dir/doc.pdf', safe='')}")
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["redactedKey"] == "_pii_redacted/sub/dir/doc.pdf"


@mock_aws
def test_report_detail_404(mod):
    _make_table()
    resp = _get(mod, "/report/missing.pdf")
    assert resp["statusCode"] == 404


@mock_aws
def test_bad_window(mod):
    _make_table()
    resp = _get(mod, "/report", {"window": "banana"})
    assert resp["statusCode"] == 400


def test_unknown_path(mod):
    resp = _get(mod, "/nope")
    assert resp["statusCode"] == 404
