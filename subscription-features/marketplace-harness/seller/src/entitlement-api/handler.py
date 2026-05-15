"""Entitlement + Metering API.

Two endpoints:

POST /validate
    body: { "customerIdentifier": "...", "dimension": "test_capacity_docs" }
    returns: { "entitled": bool, "remaining": int, "contractLimit": int,
               "status": "trial"|"active"|"cancelled", "trialEndsAt": int|null,
               "blockedByCapacity": bool }

POST /meter
    body: { "customerIdentifier": "...", "dimension": "test_docs_processed",
            "quantity": 1, "resourceId": "doc-123" }
    returns: { "accepted": bool, "eventId": "..." }

Both endpoints are auth'd via a shared API key header `x-api-key` that matches
the `apiKey` field inside the Secrets Manager secret. Good enough for a
prototype; production would use SigV4 / IAM auth on the API Gateway stage.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

LOG = logging.getLogger()
LOG.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_CUSTOMERS_TABLE = os.environ["CUSTOMERS_TABLE"]
_ENTITLEMENTS_TABLE = os.environ["ENTITLEMENTS_TABLE"]
_USAGE_LEDGER_TABLE = os.environ["USAGE_LEDGER_TABLE"]
_PRODUCT_CODE = os.environ.get("PRODUCT_CODE", "")
_API_KEY_SECRET_ARN = os.environ["API_KEY_SECRET_ARN"]

_CAPACITY_DIM = "test_capacity_docs"
_USAGE_DIM = "test_docs_processed"
_OVERAGE_DIM = "test_docs_overage"

_ddb = boto3.resource("dynamodb")
_sm = boto3.client("secretsmanager")
_ent = boto3.client("marketplace-entitlement", region_name="us-east-1")

_api_key_cache: dict[str, Any] = {"value": None, "refreshedAt": 0}


def _api_key() -> str:
    now = time.time()
    if _api_key_cache["value"] and now - _api_key_cache["refreshedAt"] < 300:
        return _api_key_cache["value"]
    secret = _sm.get_secret_value(SecretId=_API_KEY_SECRET_ARN)
    parsed = json.loads(secret["SecretString"])
    _api_key_cache.update(value=parsed["apiKey"], refreshedAt=now)
    return parsed["apiKey"]


def _unauthorized() -> dict[str, Any]:
    return {"statusCode": 401, "body": json.dumps({"error": "unauthorized"})}


def _bad_request(msg: str) -> dict[str, Any]:
    return {"statusCode": 400, "body": json.dumps({"error": msg})}


def _ok(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }


def _authenticate(event: dict[str, Any]) -> bool:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    supplied = headers.get("x-api-key", "")
    expected = _api_key()
    return bool(supplied) and hmac.compare_digest(supplied, expected)


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64

        body = base64.b64decode(body).decode("utf-8")
    return json.loads(body)


# ─────────────────────────────── /validate ────────────────────────────────────
def _billing_period_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m")


def _current_usage(customer_identifier: str, billing_period: str) -> int:
    table = _ddb.Table(_USAGE_LEDGER_TABLE)
    # GSI query: billingPeriod-customerIdentifier-index
    resp = table.query(
        IndexName="billingPeriod-customerIdentifier-index",
        KeyConditionExpression=(
            boto3.dynamodb.conditions.Key("billingPeriod").eq(billing_period)
            & boto3.dynamodb.conditions.Key("customerIdentifier").eq(customer_identifier)
        ),
    )
    return sum(int(item.get("quantity", 0)) for item in resp.get("Items", []))


def _capacity_from_entitlements(customer_identifier: str) -> int:
    table = _ddb.Table(_ENTITLEMENTS_TABLE)
    resp = table.get_item(
        Key={"customerIdentifier": customer_identifier, "dimension": _CAPACITY_DIM}
    )
    item = resp.get("Item") or {}
    try:
        return int(item.get("value", 0))
    except (TypeError, ValueError):
        return 0


def _get_customer(customer_identifier: str) -> dict[str, Any] | None:
    table = _ddb.Table(_CUSTOMERS_TABLE)
    resp = table.get_item(Key={"customerIdentifier": customer_identifier})
    return resp.get("Item")


def _handle_validate(body: dict[str, Any]) -> dict[str, Any]:
    cid = body.get("customerIdentifier")
    if not cid:
        return _bad_request("customerIdentifier required")

    customer = _get_customer(cid)
    if not customer:
        return _ok({"entitled": False, "reason": "unknown-customer"})

    status = customer.get("status", "unknown")
    if status in ("cancelled",):
        return _ok({"entitled": False, "status": status})

    capacity = _capacity_from_entitlements(cid) or int(customer.get("contractEntitlement", 0) or 100)
    used = _current_usage(cid, _billing_period_now())
    remaining = max(capacity - used, 0)
    overage_enabled = bool(customer.get("overageEnabled", True))
    blocked_by_capacity = remaining == 0 and not overage_enabled

    return _ok(
        {
            "entitled": status in ("trial", "active", "unsubscribe-pending"),
            "status": status,
            "contractLimit": capacity,
            "used": used,
            "remaining": remaining,
            "overageEnabled": overage_enabled,
            "blockedByCapacity": blocked_by_capacity,
            "trialEndsAt": customer.get("trialEndsAt"),
        }
    )


# ─────────────────────────────── /meter ───────────────────────────────────────
def _handle_meter(body: dict[str, Any]) -> dict[str, Any]:
    cid = body.get("customerIdentifier")
    quantity = int(body.get("quantity", 1))
    resource_id = body.get("resourceId", "unknown")
    if not cid:
        return _bad_request("customerIdentifier required")

    customer = _get_customer(cid)
    if not customer or customer.get("status") == "cancelled":
        return _ok({"accepted": False, "reason": "not-entitled"})

    capacity = _capacity_from_entitlements(cid) or int(customer.get("contractEntitlement", 0) or 100)
    period = _billing_period_now()
    used = _current_usage(cid, period)

    # Decide base vs overage dimension
    overage_enabled = bool(customer.get("overageEnabled", True))
    if used + quantity > capacity:
        if not overage_enabled:
            return _ok(
                {
                    "accepted": False,
                    "reason": "capacity-exceeded",
                    "used": used,
                    "contractLimit": capacity,
                }
            )
        dimension = _OVERAGE_DIM
    else:
        dimension = _USAGE_DIM

    hour_bucket = int(time.time() // 3600) * 3600
    event_id = f"{hour_bucket}#{dimension}#{resource_id}"

    table = _ddb.Table(_USAGE_LEDGER_TABLE)
    try:
        table.put_item(
            Item={
                "customerIdentifier": cid,
                "eventId": event_id,
                "dimension": dimension,
                "quantity": quantity,
                "billingPeriod": period,
                "meteredAt": None,
                "meteringStatus": "pending",
                "recordedAt": int(time.time()),
            },
            ConditionExpression="attribute_not_exists(eventId)",
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            # Idempotent replay — already recorded in this hour bucket
            return _ok({"accepted": True, "eventId": event_id, "deduped": True})
        raise

    return _ok(
        {
            "accepted": True,
            "eventId": event_id,
            "dimension": dimension,
            "used": used + quantity,
            "contractLimit": capacity,
        }
    )


# ─────────────────────────────── Entry point ──────────────────────────────────
def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    if not _authenticate(event):
        return _unauthorized()

    try:
        body = _parse_body(event)
    except json.JSONDecodeError:
        return _bad_request("invalid JSON")

    path = event.get("path") or event.get("resource") or ""
    if path.endswith("/validate"):
        return _handle_validate(body)
    if path.endswith("/meter"):
        return _handle_meter(body)
    return _bad_request(f"unknown path {path}")
