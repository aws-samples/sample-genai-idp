"""Registration URL handler.

AWS Marketplace POSTs to this endpoint after a buyer accepts the subscription.
The request body contains `x-amzn-marketplace-token` (form-encoded). We exchange
it for a customer identity via ResolveCustomer and persist to DDB.

Ref: https://docs.aws.amazon.com/marketplace/latest/userguide/saas-integrate-subscription.html
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any
from urllib.parse import parse_qs

import boto3

LOG = logging.getLogger()
LOG.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_CUSTOMERS_TABLE = os.environ["CUSTOMERS_TABLE"]
_USE_2026 = os.environ.get("USE_2026_API", "true").lower() == "true"

_ddb = boto3.resource("dynamodb")
_mp = boto3.client("meteringmarketplace", region_name="us-east-1")


def _extract_token(event: dict[str, Any]) -> str | None:
    """AWS Marketplace sends the token either as a form field or raw body."""
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        import base64

        body = base64.b64decode(body).decode("utf-8")

    # form-urlencoded: x-amzn-marketplace-token=...
    try:
        parsed = parse_qs(body)
        if "x-amzn-marketplace-token" in parsed:
            return parsed["x-amzn-marketplace-token"][0]
    except Exception:
        pass

    # JSON fallback (used by mock harness)
    try:
        j = json.loads(body)
        return j.get("x-amzn-marketplace-token") or j.get("token")
    except Exception:
        return None


def _resolve_customer(token: str) -> dict[str, Any]:
    """Call ResolveCustomer. Returns both legacy and 2026 identifiers when available."""
    resp = _mp.resolve_customer(RegistrationToken=token)
    return {
        "customerIdentifier": resp.get("CustomerIdentifier"),
        "customerAWSAccountId": resp.get("CustomerAWSAccountId"),
        "productCode": resp.get("ProductCode"),
    }


def _persist(customer: dict[str, Any]) -> None:
    table = _ddb.Table(_CUSTOMERS_TABLE)
    now = int(time.time())
    table.put_item(
        Item={
            "customerIdentifier": customer["customerIdentifier"],
            "customerAWSAccountId": customer.get("customerAWSAccountId") or "unknown",
            "productCode": customer.get("productCode") or "unknown",
            "status": "trial",
            "trialEndsAt": now + 30 * 86400,
            "createdAt": now,
            "updatedAt": now,
            "use2026Api": _USE_2026,
        }
    )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    LOG.info("registration event: %s", json.dumps(event)[:500])
    token = _extract_token(event)
    if not token:
        return {"statusCode": 400, "body": "missing x-amzn-marketplace-token"}

    try:
        customer = _resolve_customer(token)
    except Exception as exc:  # pragma: no cover - AWS error surfaces
        LOG.exception("ResolveCustomer failed")
        return {"statusCode": 502, "body": f"ResolveCustomer failed: {exc}"}

    if not customer.get("customerIdentifier"):
        return {"statusCode": 400, "body": "ResolveCustomer returned no identifier"}

    _persist(customer)
    LOG.info("registered customer %s", customer["customerIdentifier"])

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/html"},
        "body": (
            "<html><body>"
            "<h2>Subscription confirmed</h2>"
            "<p>You can now return to the GenAI IDP Accelerator and launch "
            "the Test Feature via Quick Launch.</p>"
            f"<!-- customer: {customer['customerIdentifier']} -->"
            "</body></html>"
        ),
    }
