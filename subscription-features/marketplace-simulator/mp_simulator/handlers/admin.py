"""Admin REST API — simulator-only replacement for AMMP.

Products, offers, lifecycle sinks, time advance, subscriptions, usage-log.
Returns plain JSON (not AWS JSON-RPC).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from .. import clock, db
from ..protocol import InvalidParameterException, SimulatorError

# ─────────────────────────────── constraints ─────────────────────────────────
_VALID_PRICING_MODELS = {"contract", "contract-with-payg", "subscription", "free"}
_VALID_SINK_TOPICS = {"subscription", "entitlement"}
_VALID_SINK_TRANSPORTS = {"webhook", "sns", "inproc"}


def _require(body: dict[str, Any], *keys: str) -> None:
    missing = [k for k in keys if body.get(k) is None]
    if missing:
        raise InvalidParameterException(f"missing required fields: {missing}")


# ─────────────────────────────── products ────────────────────────────────────
def create_product(body: dict[str, Any]) -> dict[str, Any]:
    _require(body, "name", "pricingModel", "dimensions")
    if body["pricingModel"] not in _VALID_PRICING_MODELS:
        raise InvalidParameterException(f"pricingModel must be one of {_VALID_PRICING_MODELS}")

    dims = body["dimensions"]
    if not isinstance(dims, list) or not dims:
        raise InvalidParameterException("dimensions must be a non-empty list")
    for d in dims:
        for k in ("apiName", "displayName"):
            if not d.get(k):
                raise InvalidParameterException(f"dimension missing {k}: {d}")
        if len(d["apiName"]) > 15:
            raise InvalidParameterException(
                f"dimension apiName '{d['apiName']}' exceeds 15-char limit"
            )

    product_code = body.get("productCode") or f"mp-sim-{uuid.uuid4().hex[:12]}"
    license_arn = body.get("licenseArn") or f"arn:aws:license-manager::sim:license/{product_code}"
    now = clock.now()

    with db.write() as c:
        try:
            c.execute(
                """INSERT INTO products
                   (product_code, license_arn, name, pricing_model, published,
                    trial_days, fulfillment_url, quick_launch_template_url,
                    dimensions_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    product_code,
                    license_arn,
                    body["name"],
                    body["pricingModel"],
                    1 if body.get("published") else 0,
                    int(body.get("trialDays", 0)),
                    body.get("fulfillmentUrl"),
                    body.get("quickLaunchTemplateUrl"),
                    json.dumps(dims),
                    now,
                    now,
                ),
            )
        except Exception as exc:
            raise SimulatorError(f"create_product failed: {exc}") from exc

    return get_product(product_code)


def get_product(product_code: str) -> dict[str, Any]:
    with db.read() as c:
        row = c.execute("SELECT * FROM products WHERE product_code = ?", (product_code,)).fetchone()
    if row is None:
        raise InvalidParameterException(f"unknown product: {product_code}", http_status=404)
    return db.row_to_dict(row)


def list_products() -> list[dict[str, Any]]:
    with db.read() as c:
        rows = c.execute("SELECT * FROM products ORDER BY created_at").fetchall()
    return [db.row_to_dict(r) for r in rows]


def update_product(product_code: str, body: dict[str, Any]) -> dict[str, Any]:
    """Enforces real-world constraints:
    - pricingModel CANNOT be changed after published=1
    - existing dimension apiName CANNOT be removed/renamed; new ones OK to add
    """
    existing = get_product(product_code)
    published = bool(existing["published"])
    updates: list[str] = []
    params: list[Any] = []

    if "pricingModel" in body:
        if body["pricingModel"] not in _VALID_PRICING_MODELS:
            raise InvalidParameterException("invalid pricingModel")
        if published and body["pricingModel"] != existing["pricing_model"]:
            raise InvalidParameterException(
                "pricingModel cannot be changed after the product is published"
            )
        updates.append("pricing_model = ?")
        params.append(body["pricingModel"])

    if "trialDays" in body:
        updates.append("trial_days = ?")
        params.append(int(body["trialDays"]))

    if "fulfillmentUrl" in body:
        updates.append("fulfillment_url = ?")
        params.append(body["fulfillmentUrl"])

    if "quickLaunchTemplateUrl" in body:
        updates.append("quick_launch_template_url = ?")
        params.append(body["quickLaunchTemplateUrl"])

    if "dimensions" in body:
        new_dims = body["dimensions"]
        existing_api_names = {d["apiName"] for d in json.loads(existing["dimensions_json"])}
        new_api_names = {d["apiName"] for d in new_dims}
        removed = existing_api_names - new_api_names
        if published and removed:
            raise InvalidParameterException(
                f"cannot remove/rename existing dimensions after publish: {sorted(removed)}"
            )
        updates.append("dimensions_json = ?")
        params.append(json.dumps(new_dims))

    if "published" in body and bool(body["published"]):
        updates.append("published = 1")

    if not updates:
        return existing

    updates.append("updated_at = ?")
    params.append(clock.now())
    params.append(product_code)

    with db.write() as c:
        c.execute(f"UPDATE products SET {', '.join(updates)} WHERE product_code = ?", params)
    return get_product(product_code)


# ─────────────────────────────── offers ──────────────────────────────────────
def create_offer(body: dict[str, Any]) -> dict[str, Any]:
    _require(body, "productCode", "kind")
    if body["kind"] not in ("public", "private"):
        raise InvalidParameterException("kind must be 'public' or 'private'")
    get_product(body["productCode"])

    offer_id = body.get("offerId") or f"offer-{uuid.uuid4().hex[:10]}"
    allowlist = body.get("buyerAccountAllowlist", [])
    if body["kind"] == "private" and not allowlist:
        raise InvalidParameterException("private offers require buyerAccountAllowlist")
    with db.write() as c:
        c.execute(
            """INSERT INTO offers
               (offer_id, product_code, kind, buyer_account_allowlist_json,
                contract_tier_json, duration_months, free_trial_enabled, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                offer_id,
                body["productCode"],
                body["kind"],
                json.dumps(allowlist),
                json.dumps(body.get("contractTier")) if body.get("contractTier") else None,
                int(body.get("durationMonths", 1)),
                1 if body.get("freeTrialEnabled") else 0,
                clock.now(),
            ),
        )
    return get_offer(offer_id)


def get_offer(offer_id: str) -> dict[str, Any]:
    with db.read() as c:
        row = c.execute("SELECT * FROM offers WHERE offer_id = ?", (offer_id,)).fetchone()
    if row is None:
        raise InvalidParameterException(f"unknown offer: {offer_id}", http_status=404)
    return db.row_to_dict(row)


def list_offers(product_code: str | None = None) -> list[dict[str, Any]]:
    with db.read() as c:
        if product_code:
            rows = c.execute(
                "SELECT * FROM offers WHERE product_code = ? ORDER BY created_at",
                (product_code,),
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM offers ORDER BY created_at").fetchall()
    return [db.row_to_dict(r) for r in rows]


# ─────────────────────────────── lifecycle sinks ─────────────────────────────
def create_lifecycle_sink(body: dict[str, Any]) -> dict[str, Any]:
    _require(body, "productCode", "transport", "target", "topic")
    if body["transport"] not in _VALID_SINK_TRANSPORTS:
        raise InvalidParameterException(f"transport must be one of {_VALID_SINK_TRANSPORTS}")
    if body["topic"] not in _VALID_SINK_TOPICS:
        raise InvalidParameterException(f"topic must be one of {_VALID_SINK_TOPICS}")
    get_product(body["productCode"])

    sink_id = body.get("sinkId") or f"sink-{uuid.uuid4().hex[:8]}"
    with db.write() as c:
        c.execute(
            """INSERT INTO lifecycle_sinks
               (sink_id, product_code, transport, target, topic, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                sink_id,
                body["productCode"],
                body["transport"],
                body["target"],
                body["topic"],
                clock.now(),
            ),
        )
    with db.read() as c:
        row = c.execute("SELECT * FROM lifecycle_sinks WHERE sink_id = ?", (sink_id,)).fetchone()
    return dict(row)


def list_lifecycle_sinks(product_code: str | None = None) -> list[dict[str, Any]]:
    with db.read() as c:
        if product_code:
            rows = c.execute(
                "SELECT * FROM lifecycle_sinks WHERE product_code = ?", (product_code,)
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM lifecycle_sinks").fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────── direct entitlement management ───────────────────
# These endpoints are simulator-only shortcuts for dev/testing. Real AWS
# Marketplace never lets a seller directly grant / expire an entitlement —
# entitlements are derived from subscriptions. But for the feature-platform
# "Subscribe" / "Cancel subscription" buttons we want a one-call admin path
# that bypasses the full product → offer → subscribe ceremony.
#
# The idiomatic flow in the feature-platform is:
#   1. `/admin/entitlements` (grant)  → feature's entitlement becomes ACTIVE
#   2. `/admin/entitlements/expire`   → entitlement becomes EXPIRED
#
# Both endpoints auto-create the minimum product row so the downstream
# data-plane `GetEntitlements` call resolves to something.
def _ensure_product(product_code: str, feature_id: str | None = None) -> None:
    """Create a minimal product row if one doesn't already exist. Used by the
    simulator-only shortcut endpoints so the admin doesn't have to call
    create_product/create_offer/subscribe just to flip an entitlement.
    """
    with db.read() as c:
        existing = c.execute(
            "SELECT 1 FROM products WHERE product_code = ?", (product_code,)
        ).fetchone()
    if existing is not None:
        return
    display = feature_id or product_code
    dims = [
        {
            "apiName": "feature",
            "displayName": "Feature flag",
            "category": "Units",
            "unitPrice": 0.0,
            "kind": "feature",
        }
    ]
    license_arn = f"arn:aws:license-manager::sim:license/{product_code}"
    now = clock.now()
    with db.write() as c:
        c.execute(
            """INSERT INTO products
               (product_code, license_arn, name, pricing_model, published,
                trial_days, fulfillment_url, quick_launch_template_url,
                dimensions_json, created_at, updated_at)
               VALUES (?, ?, ?, 'free', 1, 0, NULL, NULL, ?, ?, ?)""",
            (
                product_code,
                license_arn,
                f"Auto-provisioned product for feature {display}",
                json.dumps(dims),
                now,
                now,
            ),
        )


def grant_entitlement(body: dict[str, Any]) -> dict[str, Any]:
    """Seed an ACTIVE entitlement for (customerIdentifier, productCode).

    Body:
        customerIdentifier   str     (required)
        productCode          str     (required; auto-created if not present)
        featureId            str     (optional, for display)
        expiresInSeconds     int     (optional; default 365 days)
        dimension            str     (optional; default "feature")

    Idempotent: if an entitlement row already exists it is refreshed with the
    new expiration. Returns `{customerIdentifier, productCode, state, expiresAt}`.
    """
    _require(body, "customerIdentifier", "productCode")
    customer_identifier = body["customerIdentifier"]
    product_code = body["productCode"]
    feature_id = body.get("featureId")
    dimension = body.get("dimension") or "feature"
    expires_in = int(body.get("expiresInSeconds") or 365 * 86400)

    _ensure_product(product_code, feature_id)

    now = clock.now()
    expires_at = now + expires_in
    with db.write() as c:
        c.execute(
            """INSERT OR REPLACE INTO entitlements
               (customer_identifier, product_code, dimension, value_type,
                value_json, expiration_date)
               VALUES (?, ?, ?, 'Boolean', ?, ?)""",
            (
                customer_identifier,
                product_code,
                dimension,
                json.dumps(True),
                expires_at,
            ),
        )
    return {
        "customerIdentifier": customer_identifier,
        "productCode": product_code,
        "featureId": feature_id,
        "state": "ACTIVE",
        "expiresAt": expires_at,
        "dimension": dimension,
    }


def expire_entitlement(body: dict[str, Any]) -> dict[str, Any]:
    """Mark all entitlements for (customerIdentifier, productCode) as expired
    by setting expiration_date to `clock.now()`.

    Body:
        customerIdentifier   str     (required)
        productCode          str     (required)
        featureId            str     (optional, echoed back)

    Idempotent: returns `{state: "EXPIRED"}` even if no entitlement existed.
    """
    _require(body, "customerIdentifier", "productCode")
    customer_identifier = body["customerIdentifier"]
    product_code = body["productCode"]
    feature_id = body.get("featureId")

    now = clock.now()
    with db.write() as c:
        c.execute(
            """UPDATE entitlements
               SET expiration_date = ?
               WHERE customer_identifier = ? AND product_code = ?""",
            (now, customer_identifier, product_code),
        )
    return {
        "customerIdentifier": customer_identifier,
        "productCode": product_code,
        "featureId": feature_id,
        "state": "EXPIRED",
        "expiresAt": now,
    }


# ─────────────────────────────── time / misc ─────────────────────────────────
def advance_time(body: dict[str, Any]) -> dict[str, Any]:
    seconds = float(body.get("seconds", 0))
    now = clock.advance(seconds)
    return {"now": now, "offset": clock.offset()}


def list_subscriptions() -> list[dict[str, Any]]:
    with db.read() as c:
        rows = c.execute("SELECT * FROM subscriptions ORDER BY subscribed_at").fetchall()
    return [dict(r) for r in rows]


def list_usage(product_code: str | None = None) -> list[dict[str, Any]]:
    with db.read() as c:
        if product_code:
            rows = c.execute(
                "SELECT * FROM usage_records WHERE product_code = ? ORDER BY recorded_at DESC",
                (product_code,),
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM usage_records ORDER BY recorded_at DESC").fetchall()
    return [dict(r) for r in rows]


def list_notifications(product_code: str | None = None) -> list[dict[str, Any]]:
    with db.read() as c:
        if product_code:
            rows = c.execute(
                "SELECT * FROM notifications WHERE product_code = ? ORDER BY created_at",
                (product_code,),
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM notifications ORDER BY created_at").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d.pop("payload_json"))
        except Exception:
            pass
        out.append(d)
    return out
