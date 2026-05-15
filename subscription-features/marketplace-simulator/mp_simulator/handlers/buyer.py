"""Buyer REST API — simulator-only replacement for the AWS Marketplace buyer console.

Endpoints:
    POST /buyer/subscribe      buyer accepts an offer; simulator:
                                 1. creates a subscription row (status=trial if trial enabled,
                                    otherwise 'active')
                                 2. mints a registration token
                                 3. POSTs {x-amzn-marketplace-token: ...} to the product's
                                    fulfillment URL (the seller's webhook)
                                 4. emits 'subscribe-success' on the subscription topic
                                 5. seeds entitlements from the offer's contract tier

    POST /buyer/unsubscribe    emits unsubscribe-pending, then (after optional delay)
                                 unsubscribe-success; sets subscription.cancelled_at.
                                 Entitlements are removed so GetEntitlements returns empty.

    POST /buyer/quick-launch   returns the Quick Launch parameter bundle (endpoint URL,
                                 a generated api-key secret, and customerIdentifier) that
                                 the buyer would feed into the customer-side CFN.

    GET  /buyer/entitlements   buyer-side view — subscriptions + current entitlements
                                 for a given buyerAccountId.
"""

from __future__ import annotations

import json
import secrets
import uuid
from typing import Any

import requests

from .. import clock, db, notifications
from ..protocol import InvalidParameterException
from . import admin as admin_handler
from . import agreement as agreement_handler


def _issue_token(customer_identifier: str, customer_aws_account_id: str, product_code: str) -> str:
    token = f"mp-sim-tok-{secrets.token_urlsafe(16)}"
    now = clock.now()
    with db.write() as c:
        c.execute(
            """INSERT INTO tokens
               (token, customer_identifier, customer_aws_account_id, product_code,
                created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (token, customer_identifier, customer_aws_account_id, product_code, now, now + 3600),
        )
    return token


def _seed_entitlements_from_offer(
    *, customer_identifier: str, product_code: str, offer: dict[str, Any], duration_months: int
) -> None:
    """When a contract offer is accepted, the buyer gets an Integer-valued
    entitlement for the contracted dimension with a quantity == tier quantity.

    For feature-flag products (pricingModel=contract but dimension.kind='feature'),
    seed a Boolean-valued entitlement.
    """
    now = clock.now()
    expiration = now + duration_months * 30 * 86400
    tier = offer.get("contract_tier")

    with db.read() as c:
        product_row = c.execute(
            "SELECT * FROM products WHERE product_code = ?", (product_code,)
        ).fetchone()
    product = dict(product_row)
    dimensions = json.loads(product["dimensions_json"])

    with db.write() as c:
        if tier:
            # Contract tier: value is the quantity
            dim_name = tier["dimension"]
            qty = int(tier["quantity"])
            c.execute(
                """INSERT OR REPLACE INTO entitlements
                   (customer_identifier, product_code, dimension, value_type,
                    value_json, expiration_date)
                   VALUES (?, ?, ?, 'Integer', ?, ?)""",
                (customer_identifier, product_code, dim_name, json.dumps(qty), expiration),
            )

        # Seed feature-flag entitlements for every 'feature' dimension
        for d in dimensions:
            if d.get("kind") == "feature":
                c.execute(
                    """INSERT OR REPLACE INTO entitlements
                       (customer_identifier, product_code, dimension, value_type,
                        value_json, expiration_date)
                       VALUES (?, ?, ?, 'Boolean', ?, ?)""",
                    (customer_identifier, product_code, d["apiName"], json.dumps(True), expiration),
                )


def subscribe(body: dict[str, Any]) -> dict[str, Any]:
    offer_id = body.get("offerId")
    buyer_account_id = body.get("buyerAccountId")
    if not offer_id or not buyer_account_id:
        raise InvalidParameterException("offerId and buyerAccountId required")

    offer = admin_handler.get_offer(offer_id)

    # Private offer allowlist enforcement
    if offer["kind"] == "private":
        allowlist = offer.get("buyer_account_allowlist", [])
        if buyer_account_id not in allowlist:
            raise InvalidParameterException(
                f"buyerAccountId {buyer_account_id} is not on the allowlist for offer {offer_id}",
                http_status=403,
            )

    product = admin_handler.get_product(offer["product_code"])

    # One-subscription-per-account-per-product: re-subscribe allowed if prior is cancelled
    with db.read() as c:
        existing = c.execute(
            """SELECT * FROM subscriptions
               WHERE customer_aws_account_id = ? AND product_code = ?
               ORDER BY subscribed_at DESC LIMIT 1""",
            (buyer_account_id, offer["product_code"]),
        ).fetchone()
    had_prior_trial = False
    if existing is not None:
        existing_d = dict(existing)
        if existing_d["status"] != "cancelled":
            raise InvalidParameterException(
                f"account {buyer_account_id} already has an active subscription to "
                f"{offer['product_code']}",
                http_status=409,
            )
        had_prior_trial = existing_d.get("trial_ends_at") is not None

    customer_identifier = f"cust-{uuid.uuid4().hex[:12]}"
    now = clock.now()
    trial_enabled = bool(offer.get("free_trial_enabled")) and int(product["trial_days"]) > 0
    # One trial per (account, product) — real AWS behaviour
    if had_prior_trial:
        trial_enabled = False

    trial_ends_at = now + int(product["trial_days"]) * 86400 if trial_enabled else None
    status = "trial" if trial_enabled else "active"

    with db.write() as c:
        c.execute(
            """INSERT INTO subscriptions
               (customer_identifier, customer_aws_account_id, product_code,
                offer_id, status, trial_ends_at, subscribed_at, cancelled_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, NULL)""",
            (
                customer_identifier,
                buyer_account_id,
                offer["product_code"],
                offer_id,
                status,
                trial_ends_at,
                now,
            ),
        )

    _seed_entitlements_from_offer(
        customer_identifier=customer_identifier,
        product_code=offer["product_code"],
        offer=offer,
        duration_months=int(offer["duration_months"]),
    )

    # Mint token + POST to fulfillment URL (if configured)
    token = _issue_token(customer_identifier, buyer_account_id, offer["product_code"])
    fulfillment_post_status: str | int = "skipped"
    if product.get("fulfillment_url"):
        try:
            resp = requests.post(
                product["fulfillment_url"],
                data={"x-amzn-marketplace-token": token},
                timeout=5,
            )
            fulfillment_post_status = resp.status_code
        except Exception as exc:
            fulfillment_post_status = f"error: {exc}"

    # Emit lifecycle notification
    notifications.emit(
        product_code=offer["product_code"],
        topic="subscription",
        action="subscribe-success",
        customer_identifier=customer_identifier,
        extra={
            "offer-identifier": offer_id,
            "isFreeTrialTermPresent": trial_enabled,
        },
    )

    result = {
        "customerIdentifier": customer_identifier,
        "customerAWSAccountId": buyer_account_id,
        "productCode": offer["product_code"],
        "offerId": offer_id,
        "status": status,
        "trialEndsAt": trial_ends_at,
        "registrationToken": token,
        "fulfillmentPostStatus": fulfillment_post_status,
    }
    # Create a marketplace-agreement row so SearchAgreements / DescribeAgreement
    # see this subscription. We add the new id onto the response for convenience.
    result["agreementId"] = agreement_handler.create_agreement_from_subscription(result)
    return result


def unsubscribe(body: dict[str, Any]) -> dict[str, Any]:
    customer_identifier = body.get("customerIdentifier")
    if not customer_identifier:
        raise InvalidParameterException("customerIdentifier required")

    with db.read() as c:
        row = c.execute(
            "SELECT * FROM subscriptions WHERE customer_identifier = ?",
            (customer_identifier,),
        ).fetchone()
    if row is None:
        raise InvalidParameterException(
            f"unknown customerIdentifier: {customer_identifier}", http_status=404
        )
    sub = dict(row)

    now = clock.now()
    # Fire unsubscribe-pending first
    with db.write() as c:
        c.execute(
            "UPDATE subscriptions SET status = 'unsubscribe-pending' WHERE customer_identifier = ?",
            (customer_identifier,),
        )
    notifications.emit(
        product_code=sub["product_code"],
        topic="subscription",
        action="unsubscribe-pending",
        customer_identifier=customer_identifier,
        extra={"offer-identifier": sub["offer_id"]},
    )

    # Immediate cancellation (real AWS: seller has ~1h to flush meters)
    with db.write() as c:
        c.execute(
            """UPDATE subscriptions
               SET status = 'cancelled', cancelled_at = ?
               WHERE customer_identifier = ?""",
            (now, customer_identifier),
        )
        # Remove entitlements — real AWS: GetEntitlements returns empty for cancelled
        c.execute(
            "DELETE FROM entitlements WHERE customer_identifier = ? AND product_code = ?",
            (customer_identifier, sub["product_code"]),
        )
    notifications.emit(
        product_code=sub["product_code"],
        topic="subscription",
        action="unsubscribe-success",
        customer_identifier=customer_identifier,
        extra={"offer-identifier": sub["offer_id"]},
    )
    notifications.emit(
        product_code=sub["product_code"],
        topic="entitlement",
        action="entitlement-updated",
        customer_identifier=customer_identifier,
    )

    agreement_handler.cancel_agreement_for_customer(customer_identifier)
    return {"customerIdentifier": customer_identifier, "status": "cancelled"}


def quick_launch(body: dict[str, Any]) -> dict[str, Any]:
    """Return Quick Launch parameter bundle for a given customer."""
    customer_identifier = body.get("customerIdentifier")
    if not customer_identifier:
        raise InvalidParameterException("customerIdentifier required")

    with db.read() as c:
        row = c.execute(
            "SELECT * FROM subscriptions WHERE customer_identifier = ?",
            (customer_identifier,),
        ).fetchone()
    if row is None:
        raise InvalidParameterException(
            f"unknown customerIdentifier: {customer_identifier}", http_status=404
        )
    sub = dict(row)
    product = admin_handler.get_product(sub["product_code"])
    api_key = secrets.token_urlsafe(32)

    return {
        "customerIdentifier": customer_identifier,
        "customerAWSAccountId": sub["customer_aws_account_id"],
        "productCode": sub["product_code"],
        "quickLaunchTemplateUrl": product.get("quick_launch_template_url"),
        "parameters": {
            "CustomerIdentifier": customer_identifier,
            "SellerApiKeySecretValue": api_key,  # buyer stashes this in Secrets Manager
        },
    }


def entitlements(buyer_account_id: str) -> dict[str, Any]:
    """Buyer-side view of their own subscriptions + entitlements."""
    with db.read() as c:
        subs = c.execute(
            "SELECT * FROM subscriptions WHERE customer_aws_account_id = ?",
            (buyer_account_id,),
        ).fetchall()
    subs_d = [dict(s) for s in subs]

    out: list[dict[str, Any]] = []
    for s in subs_d:
        with db.read() as c:
            ents = c.execute(
                """SELECT dimension, value_type, value_json, expiration_date
                   FROM entitlements WHERE customer_identifier = ? AND product_code = ?""",
                (s["customer_identifier"], s["product_code"]),
            ).fetchall()
        s["entitlements"] = [
            {
                "dimension": e["dimension"],
                "valueType": e["value_type"],
                "value": json.loads(e["value_json"]),
                "expirationDate": e["expiration_date"],
            }
            for e in ents
        ]
        out.append(s)
    return {"buyerAccountId": buyer_account_id, "subscriptions": out}
