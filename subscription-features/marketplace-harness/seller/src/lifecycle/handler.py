"""Lifecycle SQS handler.

Consumes `aws-mp-subscription-notification` and `aws-mp-entitlement-notification`
messages and keeps the Customers + Entitlements DDB tables in sync.

Actions we care about:
    - subscribe-success       -> customer transitions to 'active' (or stays 'trial')
    - unsubscribe-pending     -> mark 'unsubscribe-pending' (final meter window ~1h)
    - unsubscribe-success     -> mark 'cancelled'
    - entitlement-updated     -> re-fetch GetEntitlements, refresh cache
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import boto3

LOG = logging.getLogger()
LOG.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_CUSTOMERS_TABLE = os.environ["CUSTOMERS_TABLE"]
_ENTITLEMENTS_TABLE = os.environ["ENTITLEMENTS_TABLE"]
_PRODUCT_CODE = os.environ.get("PRODUCT_CODE", "")

_ddb = boto3.resource("dynamodb")
_ent = boto3.client("marketplace-entitlement", region_name="us-east-1")


def _refresh_entitlements(customer_identifier: str) -> None:
    """Query GetEntitlements and overwrite cache. Empty set => cancelled."""
    try:
        resp = _ent.get_entitlements(
            ProductCode=_PRODUCT_CODE,
            Filter={"CUSTOMER_IDENTIFIER": [customer_identifier]},
        )
    except Exception:
        LOG.exception("GetEntitlements failed for %s", customer_identifier)
        return

    table = _ddb.Table(_ENTITLEMENTS_TABLE)
    now = int(time.time())
    ttl = now + 300  # 5 min cache

    records = resp.get("Entitlements", []) or []
    if not records:
        LOG.info("customer %s has empty entitlement set -> cancelled", customer_identifier)
        _set_customer_status(customer_identifier, "cancelled")
        return

    for e in records:
        value = e.get("Value", {})
        unwrapped = (
            value.get("IntegerValue")
            or value.get("DoubleValue")
            or value.get("BooleanValue")
            or value.get("StringValue")
        )
        table.put_item(
            Item={
                "customerIdentifier": customer_identifier,
                "dimension": e["Dimension"],
                "value": unwrapped,
                "expirationDate": int(e["ExpirationDate"].timestamp())
                if e.get("ExpirationDate")
                else 0,
                "refreshedAt": now,
                "ttl": ttl,
            }
        )


def _set_customer_status(customer_identifier: str, status: str) -> None:
    table = _ddb.Table(_CUSTOMERS_TABLE)
    table.update_item(
        Key={"customerIdentifier": customer_identifier},
        UpdateExpression="SET #s = :s, updatedAt = :u",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": status, ":u": int(time.time())},
    )


def _handle_message(msg_body: str) -> None:
    """SNS messages are wrapped; inner 'Message' is JSON."""
    envelope = json.loads(msg_body)
    inner = envelope.get("Message")
    if inner is None:
        # Raw or local mock publish — treat whole body as the message
        payload = envelope
    else:
        payload = json.loads(inner) if isinstance(inner, str) else inner

    action = payload.get("action")
    customer_identifier = (
        payload.get("customer-identifier")
        or payload.get("customerIdentifier")
        or payload.get("CustomerIdentifier")
    )
    LOG.info("lifecycle action=%s customer=%s", action, customer_identifier)

    if not customer_identifier:
        LOG.warning("no customer identifier in message: %s", payload)
        return

    if action == "subscribe-success":
        _set_customer_status(customer_identifier, "active")
        _refresh_entitlements(customer_identifier)
    elif action == "unsubscribe-pending":
        _set_customer_status(customer_identifier, "unsubscribe-pending")
    elif action == "unsubscribe-success":
        _set_customer_status(customer_identifier, "cancelled")
        _refresh_entitlements(customer_identifier)
    elif action == "entitlement-updated":
        _refresh_entitlements(customer_identifier)
    else:
        LOG.warning("unknown action: %s", action)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    for record in event.get("Records", []):
        try:
            _handle_message(record["body"])
        except Exception:
            LOG.exception("failed to process record %s", record.get("messageId"))
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
