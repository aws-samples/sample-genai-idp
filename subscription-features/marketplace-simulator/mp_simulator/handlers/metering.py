"""Data-plane handlers for ``AWSMPMeteringService``.

All four ops consume/produce AWS JSON-RPC 1.1 payloads matching boto3's
``meteringmarketplace`` client.
"""

from __future__ import annotations

import json
import secrets
import uuid
from typing import Any

from .. import clock, db
from ..protocol import (
    CustomerNotEntitledException,
    DuplicateRequestException,
    InvalidProductCodeException,
    InvalidTokenException,
    InvalidUsageDimensionException,
    SimulatorError,
    TimestampOutOfBoundsException,
)

_METERING_WINDOW_SECONDS = 6 * 3600  # real AWS: records >6h old are rejected


# ────────────────────────────── helpers ──────────────────────────────────────
def _lookup_product(product_code: str) -> dict[str, Any]:
    with db.read() as c:
        row = c.execute("SELECT * FROM products WHERE product_code = ?", (product_code,)).fetchone()
    if row is None:
        raise InvalidProductCodeException(f"unknown ProductCode: {product_code}")
    return dict(row)


def _lookup_subscription(customer_identifier: str, product_code: str) -> dict[str, Any] | None:
    with db.read() as c:
        row = c.execute(
            """SELECT * FROM subscriptions
               WHERE customer_identifier = ? AND product_code = ?""",
            (customer_identifier, product_code),
        ).fetchone()
    return dict(row) if row else None


def _dimension_defined(product: dict[str, Any], dimension: str) -> bool:
    dims = json.loads(product["dimensions_json"])
    return any(d["apiName"] == dimension for d in dims)


def _timestamp_to_epoch(ts: Any) -> float:
    """boto3 marshals ``Timestamp`` shapes as numeric epoch seconds on the wire.
    Accept either that or ISO-8601 strings for friendliness in curl-based tests.
    """
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            return float(ts)
        except ValueError:
            from datetime import datetime

            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return dt.timestamp()
            except Exception:
                pass
    raise TimestampOutOfBoundsException(f"unparseable timestamp: {ts!r}")


# ────────────────────────────── operations ───────────────────────────────────
def resolve_customer(body: dict[str, Any]) -> dict[str, Any]:
    """Exchange a registration token for customer identity.

    Tokens are minted by ``/buyer/subscribe`` and inserted into the ``tokens``
    table. Here we just look one up.
    """
    token = body.get("RegistrationToken")
    if not token or not isinstance(token, str):
        raise InvalidTokenException("RegistrationToken required")

    now = clock.now()
    with db.read() as c:
        row = c.execute("SELECT * FROM tokens WHERE token = ?", (token,)).fetchone()
    if row is None:
        raise InvalidTokenException("registration token not recognized")
    rec = dict(row)
    if rec["expires_at"] < now:
        raise InvalidTokenException("registration token expired")

    return {
        "CustomerIdentifier": rec["customer_identifier"],
        "CustomerAWSAccountId": rec["customer_aws_account_id"],
        "ProductCode": rec["product_code"],
    }


def batch_meter_usage(body: dict[str, Any]) -> dict[str, Any]:
    """Accept up to 25 usage records for a product, returning per-record status.

    Matches boto3 shape:
        Results: [{UsageRecord: {...}, MeteringRecordId, Status}]
        UnprocessedRecords: [UsageRecord, ...]
    """
    product_code = body.get("ProductCode")
    if not product_code:
        raise InvalidProductCodeException("ProductCode required")
    product = _lookup_product(product_code)

    records = body.get("UsageRecords") or []
    if not isinstance(records, list):
        raise SimulatorError("UsageRecords must be a list", error_type="InvalidParameterException")
    if len(records) > 25:
        raise SimulatorError(
            "at most 25 UsageRecords per BatchMeterUsage call",
            error_type="InvalidParameterException",
        )

    now = clock.now()
    results: list[dict[str, Any]] = []
    unprocessed: list[dict[str, Any]] = []

    for rec in records:
        cid = rec.get("CustomerIdentifier")
        dim = rec.get("Dimension")
        qty = int(rec.get("Quantity", 0))
        try:
            ts = _timestamp_to_epoch(rec.get("Timestamp"))
        except TimestampOutOfBoundsException:
            unprocessed.append(rec)
            continue

        if not cid:
            results.append(
                {"UsageRecord": rec, "MeteringRecordId": "", "Status": "CustomerNotSubscribed"}
            )
            continue
        if not dim or not _dimension_defined(product, dim):
            results.append(
                {
                    "UsageRecord": rec,
                    "MeteringRecordId": "",
                    "Status": "DimensionNotFound",
                }
            )
            continue
        if now - ts > _METERING_WINDOW_SECONDS:
            # Real service returns TimestampOutOfBoundsException on the whole call
            # when records are old. We'll mirror that precisely:
            raise TimestampOutOfBoundsException(
                f"UsageRecord timestamp {ts} is more than 6 hours old"
            )
        if ts > now + 300:  # 5 min grace for clock skew
            raise TimestampOutOfBoundsException(f"UsageRecord timestamp {ts} is in the future")

        sub = _lookup_subscription(cid, product_code)
        status = "Success"
        if sub is None:
            status = "CustomerNotSubscribed"
        elif sub["status"] in ("cancelled",):
            status = "CustomerNotSubscribed"

        metering_id = f"mri-{uuid.uuid4()}"
        with db.write() as c:
            c.execute(
                """INSERT INTO usage_records
                   (product_code, customer_identifier, dimension, quantity,
                    timestamp, status, client_token, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, NULL, ?)""",
                (product_code, cid, dim, qty, ts, status, now),
            )

        results.append(
            {
                "UsageRecord": {
                    "CustomerIdentifier": cid,
                    "Dimension": dim,
                    "Quantity": qty,
                    "Timestamp": ts,
                },
                "MeteringRecordId": metering_id,
                "Status": status,
            }
        )

    return {"Results": results, "UnprocessedRecords": unprocessed}


def meter_usage(body: dict[str, Any]) -> dict[str, Any]:
    """AMI path. Caller's own account is the implicit CustomerAWSAccountId —
    simulator allows the buyer to pass ``CustomerIdentifier`` explicitly via an
    extension field (kept off-wire in real AWS).

    Handles idempotency via ClientToken.
    """
    product_code = body.get("ProductCode")
    if not product_code:
        raise InvalidProductCodeException("ProductCode required")
    product = _lookup_product(product_code)

    dim = body.get("UsageDimension")
    if not dim or not _dimension_defined(product, dim):
        raise InvalidUsageDimensionException(f"unknown dimension: {dim}")

    ts = _timestamp_to_epoch(body.get("Timestamp"))
    now = clock.now()
    if now - ts > _METERING_WINDOW_SECONDS:
        raise TimestampOutOfBoundsException("timestamp > 6h old")
    if ts > now + 300:
        raise TimestampOutOfBoundsException("timestamp is in the future")

    qty = int(body.get("UsageQuantity", 0))
    client_token = body.get("ClientToken") or str(uuid.uuid4())

    # Idempotency
    with db.read() as c:
        dup = c.execute(
            "SELECT * FROM usage_records WHERE product_code = ? AND client_token = ?",
            (product_code, client_token),
        ).fetchone()
    if dup:
        # Real service: same params -> return same id; diff params -> IdempotencyConflictException
        if dup["dimension"] != dim or dup["quantity"] != qty:
            raise DuplicateRequestException(
                "ClientToken reused with different parameters",
                error_type="IdempotencyConflictException",
            )
        return {"MeteringRecordId": f"mri-{dup['id']}"}

    # MeterUsage is for running instances; real AWS derives the caller's
    # identity from the instance role. boto3's param validator rejects any
    # field not in the Smithy model, so we cannot take CustomerIdentifier on
    # the wire. Instead, the simulator resolves the caller using the most-
    # recent active subscription for the product. This is sufficient for the
    # typical unit-under-test scenario (one instance = one customer).
    with db.read() as c:
        sub_row = c.execute(
            """SELECT * FROM subscriptions
               WHERE product_code = ? AND status IN ('trial', 'active')
               ORDER BY subscribed_at DESC LIMIT 1""",
            (product_code,),
        ).fetchone()
    if sub_row is None:
        raise CustomerNotEntitledException(
            f"no active subscription found for product {product_code}"
        )
    cid = sub_row["customer_identifier"]

    with db.write() as c:
        cur = c.execute(
            """INSERT INTO usage_records
               (product_code, customer_identifier, dimension, quantity,
                timestamp, status, client_token, recorded_at)
               VALUES (?, ?, ?, ?, ?, 'Success', ?, ?)""",
            (product_code, cid, dim, qty, ts, client_token, now),
        )
        rec_id = cur.lastrowid
    return {"MeteringRecordId": f"mri-{rec_id}"}


def register_usage(body: dict[str, Any]) -> dict[str, Any]:
    """Container path. Returns a JWT-shaped signature; we don't actually sign
    anything — just echo a random token so callers have something to stash.
    """
    product_code = body.get("ProductCode")
    if not product_code:
        raise InvalidProductCodeException("ProductCode required")
    _lookup_product(product_code)
    if "PublicKeyVersion" not in body:
        raise SimulatorError(
            "PublicKeyVersion required", error_type="InvalidPublicKeyVersionException"
        )
    # Real AWS: return JWT + optional PublicKeyRotationTimestamp when rotation pending
    fake_jwt = f"mp-sim.{secrets.token_urlsafe(24)}.sig"
    return {"Signature": fake_jwt}
