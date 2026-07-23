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
    table.put_item(
        Item={
            "documentId": "a.pdf",
            "gsiPk": "ALL",
            "createdAt": "2026-07-22T10:00:00Z",
            "piiCount": 3,
            "mode": "redacted_only",
        }
    )
    table.put_item(
        Item={
            "documentId": "b.pdf",
            "gsiPk": "ALL",
            "createdAt": "2026-07-22T11:00:00Z",
            "piiCount": 5,
            "mode": "redacted_and_unredacted",
        }
    )
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
    table.put_item(
        Item={
            "documentId": "sub/dir/doc.pdf",
            "gsiPk": "ALL",
            "createdAt": "2026-07-22T10:00:00Z",
            "piiCount": 2,
            "redactedKey": "_pii_redacted/sub/dir/doc.pdf",
        }
    )
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


# ---- RBAC-gated PII mapping view -------------------------------------------

_USERS_TABLE = "TestUsers"
_OUT_BUCKET = "test-output-bkt"


def _make_users_table():
    ddb = boto3.resource("dynamodb", region_name="us-west-2")
    ddb.create_table(
        TableName=_USERS_TABLE,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "id", "AttributeType": "S"},
            {"AttributeName": "email", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "EmailIndex",
                "KeySchema": [{"AttributeName": "email", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )
    return ddb.Table(_USERS_TABLE)


@pytest.fixture
def mod_rbac(monkeypatch):
    monkeypatch.setenv("AUDIT_TABLE_NAME", _AUDIT_TABLE)
    monkeypatch.setenv("USERS_TABLE_NAME", _USERS_TABLE)
    monkeypatch.setenv("OUTPUT_BUCKET", _OUT_BUCKET)
    monkeypatch.setenv("MAIN_STACK_NAME", "IDP")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    sys.path.insert(0, str(_HANDLER_DIR))
    sys.modules.pop("handler", None)
    m = importlib.import_module("handler")
    sys.path.remove(str(_HANDLER_DIR))
    return m


def _get_as(mod, path, *, email="", groups=""):
    event = {
        "rawPath": path,
        "queryStringParameters": {},
        "requestContext": {
            "http": {"method": "GET"},
            "authorizer": {
                "jwt": {"claims": {"email": email, "cognito:groups": groups}}
            },
        },
    }
    return mod.lambda_handler(event, None)


def _seed_mapping_doc(audit_table, s3, doc_id, original_version):
    key = f"pii_mappings/{doc_id}/mapping.json"
    s3.create_bucket(
        Bucket=_OUT_BUCKET,
        CreateBucketConfiguration={"LocationConstraint": "us-west-2"},
    )
    s3.put_object(
        Bucket=_OUT_BUCKET,
        Key=key,
        Body=json.dumps(
            {
                "documentId": doc_id,
                "originalConfigVersion": original_version,
                "mapping": {"John Smith": "Jane Doe"},
            }
        ).encode(),
    )
    audit_table.put_item(
        Item={
            "documentId": doc_id,
            "gsiPk": "ALL",
            "createdAt": "2026-07-23T10:00:00Z",
            "mappingStored": True,
            "mappingUri": f"s3://{_OUT_BUCKET}/{key}",
            "originalConfigVersion": original_version,
        }
    )


@mock_aws
def test_mapping_denied_for_out_of_scope_user(mod_rbac):
    audit = _make_table()
    _make_users_table()
    s3 = boto3.client("s3", region_name="us-west-2")
    _seed_mapping_doc(audit, s3, "doc1.pdf", "secret-v1")
    # user scoped to a DIFFERENT version
    boto3.resource("dynamodb", region_name="us-west-2").Table(_USERS_TABLE).put_item(
        Item={"id": "u1", "email": "viewer@x", "allowedConfigVersions": ["other-v1"]}
    )
    resp = _get_as(
        mod_rbac, "/report/doc1.pdf/mapping", email="viewer@x", groups="[Viewer]"
    )
    assert resp["statusCode"] == 403


@mock_aws
def test_mapping_allowed_for_in_scope_user(mod_rbac):
    audit = _make_table()
    _make_users_table()
    s3 = boto3.client("s3", region_name="us-west-2")
    _seed_mapping_doc(audit, s3, "doc2.pdf", "secret-v1")
    boto3.resource("dynamodb", region_name="us-west-2").Table(_USERS_TABLE).put_item(
        Item={"id": "u2", "email": "ok@x", "allowedConfigVersions": ["secret-v1"]}
    )
    resp = _get_as(
        mod_rbac, "/report/doc2.pdf/mapping", email="ok@x", groups="[Viewer]"
    )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["mapping"]["John Smith"] == "Jane Doe"


@mock_aws
def test_mapping_allowed_for_admin(mod_rbac):
    audit = _make_table()
    _make_users_table()
    s3 = boto3.client("s3", region_name="us-west-2")
    _seed_mapping_doc(audit, s3, "doc3.pdf", "secret-v1")
    # Admin with a restrictive scope still passes (admin override)
    boto3.resource("dynamodb", region_name="us-west-2").Table(_USERS_TABLE).put_item(
        Item={"id": "a1", "email": "admin@x", "allowedConfigVersions": ["other-v1"]}
    )
    resp = _get_as(
        mod_rbac, "/report/doc3.pdf/mapping", email="admin@x", groups="[Admin]"
    )
    assert resp["statusCode"] == 200
