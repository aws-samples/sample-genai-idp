"""Unit tests for the sample-health-insurance-review feature API handler."""

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

_CLAIMS_TABLE = "TestClaimsStatus"
_OUTPUT_BUCKET = "test-output-bucket"
_DOC_ID = "claims/Prior-Auth-12345678.pdf"
_SUMMARY_KEY = f"{_DOC_ID}/rule_validation/consolidated/consolidated_summary.json"
_SUMMARY_URI = f"s3://{_OUTPUT_BUCKET}/{_SUMMARY_KEY}"
_MD_URI = _SUMMARY_URI[: -len(".json")] + ".md"


@pytest.fixture
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


def _claim_row(doc_id: str, status: str, updated_at: str) -> dict:
    return {
        "documentId": doc_id,
        "status": status,
        "passCount": 4,
        "failCount": 1 if status == "REVIEW_REQUIRED" else 0,
        "notFoundCount": 0,
        "totalRules": 5,
        "recommendationCounts": {"Pass": 4, "Fail": 1},  # nosec B105 - rule counter fixture
        "policyTypes": ["global_periods"],
        "summaryJsonUri": _SUMMARY_URI,
        "summaryMdUri": _MD_URI,
        "executionArn": "arn:aws:states:us-east-1:111:execution:wf:run-1",
        "updatedAt": updated_at,
    }


@pytest.fixture
def stack(aws_credentials, monkeypatch):
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        # Mirror template.yaml: PK documentId, GSI ByStatus (status, updatedAt).
        ddb.create_table(
            TableName=_CLAIMS_TABLE,
            KeySchema=[{"AttributeName": "documentId", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "documentId", "AttributeType": "S"},
                {"AttributeName": "status", "AttributeType": "S"},
                {"AttributeName": "updatedAt", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "ByStatus",
                    "KeySchema": [
                        {"AttributeName": "status", "KeyType": "HASH"},
                        {"AttributeName": "updatedAt", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        ).wait_until_exists()
        table = ddb.Table(_CLAIMS_TABLE)
        table.put_item(
            Item=_claim_row(_DOC_ID, "REVIEW_REQUIRED", "2026-06-10T10:00:00Z")
        )
        table.put_item(
            Item=_claim_row(
                "claims/other-claim.pdf", "CLEAN_CLAIM", "2026-06-01T10:00:00Z"
            )
        )

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=_OUTPUT_BUCKET)
        s3.put_object(
            Bucket=_OUTPUT_BUCKET,
            Key=_SUMMARY_KEY,
            Body=json.dumps(
                {
                    "rule_summary": {"global_periods": {"Pass": 4, "Fail": 1}},  # nosec B105 - rule counter fixture
                    "rule_details": {
                        "global_periods": {
                            "rules": [
                                {
                                    "rule": "Rule 1",
                                    "recommendation": "Fail",
                                    "supporting_pages": ["2"],
                                    "reasoning": "Modifier missing",
                                }
                            ]
                        }
                    },
                    "supporting_pages": ["1", "2"],
                    "overall_statistics": {
                        "total_rules": 5,
                        "recommendation_counts": {"Pass": 4, "Fail": 1},  # nosec B105 - rule counter fixture
                    },
                }
            ).encode("utf-8"),
        )
        s3.put_object(
            Bucket=_OUTPUT_BUCKET,
            Key=_SUMMARY_KEY[: -len(".json")] + ".md",
            Body=b"# Rule Validation Summary\n\nDetails here.",
        )

        monkeypatch.setenv("CLAIMS_TABLE_NAME", _CLAIMS_TABLE)
        monkeypatch.setenv("DISCOVERY_BUCKET", "test-discovery-bucket")
        sys.path.insert(0, str(_HANDLER_DIR))
        sys.modules.pop("handler", None)
        mod = importlib.import_module("handler")
        sys.path.remove(str(_HANDLER_DIR))
        yield mod


def _event(
    path: str,
    qs: dict | None = None,
    method: str = "GET",
    groups: str | None = None,
) -> dict:
    ctx: dict = {"http": {"method": method}}
    if groups is not None:
        # API GW HTTP API stringifies the cognito:groups list claim.
        ctx["authorizer"] = {"jwt": {"claims": {"cognito:groups": groups}}}
    return {
        "rawPath": path,
        "queryStringParameters": qs,
        "requestContext": ctx,
    }


def _body(resp: dict) -> dict:
    return json.loads(resp["body"])


def test_config_returns_discovery_bucket(stack):
    resp = stack.lambda_handler(_event("/config"), None)
    assert resp["statusCode"] == 200
    assert _body(resp)["discoveryBucket"] == "test-discovery-bucket"


def test_list_claims_sorted_newest_first(stack):
    resp = stack.lambda_handler(_event("/claims"), None)
    assert resp["statusCode"] == 200
    body = _body(resp)
    assert body["total"] == 2
    assert body["claims"][0]["documentId"] == _DOC_ID  # 2026-06-10 > 2026-06-01
    assert body["claims"][0]["passCount"] == 4  # Decimal -> int


def test_list_claims_status_filter_uses_gsi(stack):
    resp = stack.lambda_handler(_event("/claims", {"status": "CLEAN_CLAIM"}), None)
    body = _body(resp)
    assert body["total"] == 1
    assert body["claims"][0]["documentId"] == "claims/other-claim.pdf"


def test_list_claims_rejects_unknown_status(stack):
    resp = stack.lambda_handler(_event("/claims", {"status": "BOGUS"}), None)
    assert resp["statusCode"] == 400


def test_list_claims_rejects_bad_window(stack):
    resp = stack.lambda_handler(_event("/claims", {"window": "soon"}), None)
    assert resp["statusCode"] == 400


def test_claim_detail_merges_summary(stack):
    resp = stack.lambda_handler(_event(f"/claims/{quote(_DOC_ID, safe='')}"), None)
    assert resp["statusCode"] == 200
    detail = _body(resp)
    assert detail["status"] == "REVIEW_REQUIRED"
    assert detail["ruleDetails"]["global_periods"]["rules"][0]["rule"] == "Rule 1"
    assert detail["supportingPages"] == ["1", "2"]
    assert detail["overallStatistics"]["total_rules"] == 5


def test_claim_detail_survives_missing_summary(stack):
    """Row exists but S3 object is gone — return the row without rule details."""
    boto3.client("s3", region_name="us-east-1").delete_object(
        Bucket=_OUTPUT_BUCKET, Key=_SUMMARY_KEY
    )
    resp = stack.lambda_handler(_event(f"/claims/{quote(_DOC_ID, safe='')}"), None)
    assert resp["statusCode"] == 200
    detail = _body(resp)
    assert detail["status"] == "REVIEW_REQUIRED"
    assert "ruleDetails" not in detail


def test_markdown_proxy(stack):
    resp = stack.lambda_handler(
        _event(f"/claims/{quote(_DOC_ID, safe='')}/summary.md"), None
    )
    assert resp["statusCode"] == 200
    assert resp["headers"]["Content-Type"] == "text/markdown"
    assert resp["body"].startswith("# Rule Validation Summary")


def test_unknown_claim_returns_404(stack):
    resp = stack.lambda_handler(_event("/claims/nope.pdf"), None)
    assert resp["statusCode"] == 404


def test_delete_claim_as_admin(stack):
    path = f"/claims/{quote(_DOC_ID, safe='')}"
    resp = stack.lambda_handler(_event(path, method="DELETE", groups="[Admin]"), None)
    assert resp["statusCode"] == 200
    assert _body(resp)["deleted"] == _DOC_ID
    # Row is gone
    resp2 = stack.lambda_handler(_event(path), None)
    assert resp2["statusCode"] == 404


def test_delete_claim_as_author(stack):
    path = f"/claims/{quote(_DOC_ID, safe='')}"
    resp = stack.lambda_handler(
        _event(path, method="DELETE", groups="[Author Viewer]"), None
    )
    assert resp["statusCode"] == 200


def test_delete_claim_forbidden_for_reviewer(stack):
    path = f"/claims/{quote(_DOC_ID, safe='')}"
    resp = stack.lambda_handler(
        _event(path, method="DELETE", groups="[Reviewer]"), None
    )
    assert resp["statusCode"] == 403
    # Row untouched
    resp2 = stack.lambda_handler(_event(path), None)
    assert resp2["statusCode"] == 200


def test_delete_claim_forbidden_without_groups(stack):
    path = f"/claims/{quote(_DOC_ID, safe='')}"
    resp = stack.lambda_handler(_event(path, method="DELETE"), None)
    assert resp["statusCode"] == 403


def test_delete_unknown_claim_returns_404(stack):
    resp = stack.lambda_handler(
        _event("/claims/nope.pdf", method="DELETE", groups="[Admin]"), None
    )
    assert resp["statusCode"] == 404


def test_delete_non_claims_path_returns_404(stack):
    resp = stack.lambda_handler(
        _event("/config", method="DELETE", groups="[Admin]"), None
    )
    assert resp["statusCode"] == 404


def test_unknown_path_returns_404(stack):
    resp = stack.lambda_handler(_event("/other"), None)
    assert resp["statusCode"] == 404
