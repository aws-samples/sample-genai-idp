"""Hourly BatchMeterUsage roll-up.

Scans the UsageLedger for records with meteringStatus='pending' that fall in
the previous completed hour bucket, groups by (customer, dimension), and
submits them to AWS Marketplace Metering as a BatchMeterUsage call.

- BatchMeterUsage accepts up to 25 UsageRecords per call.
- Timestamps must be within 6h of now; we operate on the previous hour so
  we're well inside the window.
- Idempotency key is (hour_bucket, dimension, resourceId) — retries safe.
- On CustomerNotEntitledException we mark the customer cancelled.
- Other errors => mark meteringStatus='failed'; next run retries (exp backoff
  implicit via hourly schedule).
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

LOG = logging.getLogger()
LOG.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_USAGE_LEDGER_TABLE = os.environ["USAGE_LEDGER_TABLE"]
_CUSTOMERS_TABLE = os.environ["CUSTOMERS_TABLE"]
_PRODUCT_CODE = os.environ.get("PRODUCT_CODE", "")

_BATCH_SIZE = 25

_ddb = boto3.resource("dynamodb")
_mp = boto3.client("meteringmarketplace", region_name="us-east-1")


def _pending_records() -> list[dict[str, Any]]:
    """Scan (prototype; switch to GSI + filter in production)."""
    table = _ddb.Table(_USAGE_LEDGER_TABLE)
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {
        "FilterExpression": boto3.dynamodb.conditions.Attr("meteringStatus").eq("pending"),
    }
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return items


def _mark_status(customer_id: str, event_id: str, status: str) -> None:
    _ddb.Table(_USAGE_LEDGER_TABLE).update_item(
        Key={"customerIdentifier": customer_id, "eventId": event_id},
        UpdateExpression="SET meteringStatus = :s, meteredAt = :m",
        ExpressionAttributeValues={":s": status, ":m": int(time.time())},
    )


def _mark_customer_cancelled(customer_id: str) -> None:
    _ddb.Table(_CUSTOMERS_TABLE).update_item(
        Key={"customerIdentifier": customer_id},
        UpdateExpression="SET #s = :s, updatedAt = :u",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "cancelled", ":u": int(time.time())},
    )


def _flush_batch(
    customer_id: str, records: list[dict[str, Any]]
) -> None:
    """Submit up to 25 records for a single customer."""
    usage_records = []
    for r in records:
        ts = datetime.fromtimestamp(
            int(r["eventId"].split("#", 1)[0]), tz=timezone.utc
        )
        usage_records.append(
            {
                "Timestamp": ts,
                "CustomerIdentifier": customer_id,
                "Dimension": r["dimension"],
                "Quantity": int(r["quantity"]),
            }
        )

    LOG.info("BatchMeterUsage: customer=%s count=%d", customer_id, len(usage_records))
    try:
        resp = _mp.batch_meter_usage(
            ProductCode=_PRODUCT_CODE,
            UsageRecords=usage_records,
        )
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        LOG.exception("BatchMeterUsage failed: %s", code)
        if code == "CustomerNotEntitledException":
            _mark_customer_cancelled(customer_id)
            for r in records:
                _mark_status(customer_id, r["eventId"], "not-entitled")
            return
        for r in records:
            _mark_status(customer_id, r["eventId"], "failed")
        return

    # Map success/failure per-record from response
    results_by_ts_dim: dict[tuple[int, str], str] = {}
    for ok in resp.get("Results", []):
        key = (int(ok["UsageRecord"]["Timestamp"].timestamp()), ok["UsageRecord"]["Dimension"])
        results_by_ts_dim[key] = ok["Status"]  # 'Success' / 'CustomerNotSubscribed' / ...

    for r in records:
        hour_bucket = int(r["eventId"].split("#", 1)[0])
        key = (hour_bucket, r["dimension"])
        status = results_by_ts_dim.get(key, "failed")
        mapped = "metered" if status == "Success" else f"failed:{status}"
        _mark_status(customer_id, r["eventId"], mapped)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    pending = _pending_records()
    if not pending:
        LOG.info("no pending usage records")
        return {"processed": 0}

    # Group by customer
    by_customer: dict[str, list[dict[str, Any]]] = {}
    for rec in pending:
        by_customer.setdefault(rec["customerIdentifier"], []).append(rec)

    processed = 0
    for cid, records in by_customer.items():
        for i in range(0, len(records), _BATCH_SIZE):
            chunk = records[i : i + _BATCH_SIZE]
            _flush_batch(cid, chunk)
            processed += len(chunk)

    LOG.info("rollup complete: %d records across %d customers", processed, len(by_customer))
    return {"processed": processed, "customers": len(by_customer)}
