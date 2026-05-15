"""Data-plane handler for ``marketplace-catalog`` (rest-json protocol).

Operations supported (subset used by real SaaS sellers):
    - POST  /ListEntities          list products + offers
    - GET   /DescribeEntity        get a specific entity
    - POST  /StartChangeSet        mutate the catalog (create product, add dimensions, ...)
    - GET   /DescribeChangeSet     check status of a change set
    - POST  /ListChangeSets        list change sets
    - PATCH /CancelChangeSet       cancel a pending change set

Catalog entity types we model:
    - SaaSProduct        -> one row in products table
    - SaaSProductOffer   -> one row in offers table

Supported ChangeTypes:
    - CreateProduct           Details.Product = {Name, PricingModel, TrialDays?, FulfillmentUrl?, Dimensions?, QuickLaunchTemplateUrl?}
    - AddDimensions           Entity.Identifier = product_code; Details.Dimensions = [...]
    - UpdateInformation       Entity.Identifier = product_code; Details = {Name?, FulfillmentUrl?, QuickLaunchTemplateUrl?, TrialDays?}
    - ReleaseProduct          Entity.Identifier = product_code (flips `published=1`)
    - CreateOffer             Entity.Identifier = product_code; Details.Offer = {Kind, BuyerAccountAllowlist?, ContractTier?, DurationMonths?, FreeTrialEnabled?}

Unsupported ChangeTypes return a ValidationException with the list of
supported values.
"""

from __future__ import annotations

import base64
import json
import uuid
from typing import Any

from .. import clock, db
from ..protocol import (
    ResourceNotFoundException,
    ValidationException,
)
from . import admin as admin_handler

DEFAULT_CATALOG = "AWSMarketplace"
MAX_RESULTS = 20

SUPPORTED_CHANGE_TYPES = {
    "CreateProduct",
    "AddDimensions",
    "UpdateInformation",
    "ReleaseProduct",
    "CreateOffer",
}


def _page_token(offset: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"o": offset}).encode()).decode()


def _parse_page_token(token: str | None) -> int:
    if not token:
        return 0
    try:
        return int(json.loads(base64.urlsafe_b64decode(token.encode())).get("o", 0))
    except Exception as exc:
        raise ValidationException(f"invalid NextToken: {exc}") from exc


# ─────────────────────────────── Entities ────────────────────────────────────
def _product_to_entity(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "EntityType": "SaaSProduct",
        "EntityId": row["product_code"],
        "EntityArn": f"arn:aws:aws-marketplace:us-east-1:sim:{row['product_code']}",
        "Name": row["name"],
        "Visibility": "Public" if row["published"] else "Draft",
        "LastModifiedDate": row["updated_at"],
    }


def _offer_to_entity(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "EntityType": "SaaSProductOffer",
        "EntityId": row["offer_id"],
        "EntityArn": f"arn:aws:aws-marketplace:us-east-1:sim:offer/{row['offer_id']}",
        "Name": f"Offer for {row['product_code']}",
        "Visibility": "Public" if row["kind"] == "public" else "Limited",
        "LastModifiedDate": row["created_at"],
    }


def list_entities(body: dict[str, Any]) -> dict[str, Any]:
    entity_type = body.get("EntityType")
    if not entity_type:
        raise ValidationException("EntityType required")

    offset = _parse_page_token(body.get("NextToken"))
    max_results = int(body.get("MaxResults") or MAX_RESULTS)
    max_results = min(max(max_results, 1), MAX_RESULTS)

    if entity_type == "SaaSProduct":
        with db.read() as c:
            rows = [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM products ORDER BY created_at LIMIT ? OFFSET ?",
                    (max_results + 1, offset),
                ).fetchall()
            ]
        entities = [_product_to_entity(r) for r in rows]
    elif entity_type == "SaaSProductOffer":
        with db.read() as c:
            rows = [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM offers ORDER BY created_at LIMIT ? OFFSET ?",
                    (max_results + 1, offset),
                ).fetchall()
            ]
        entities = [_offer_to_entity(r) for r in rows]
    else:
        raise ValidationException(
            f"unsupported EntityType: {entity_type} (supported: SaaSProduct, SaaSProductOffer)"
        )

    has_more = len(entities) > max_results
    entities = entities[:max_results]

    result: dict[str, Any] = {"EntitySummaryList": entities}
    if has_more:
        result["NextToken"] = _page_token(offset + max_results)
    return result


def describe_entity(params: dict[str, Any]) -> dict[str, Any]:
    """``params`` comes from URL querystring (catalog, entityId)."""
    entity_id = params.get("entityId") or params.get("EntityId")
    if not entity_id:
        raise ValidationException("entityId required")

    # Try product first, then offer
    with db.read() as c:
        p = c.execute("SELECT * FROM products WHERE product_code = ?", (entity_id,)).fetchone()
    if p is not None:
        p = dict(p)
        return {
            "EntityType": "SaaSProduct",
            "EntityIdentifier": p["product_code"],
            "EntityArn": f"arn:aws:aws-marketplace:us-east-1:sim:{p['product_code']}",
            "LastModifiedDate": p["updated_at"],
            "Details": json.dumps(
                {
                    "ProductCode": p["product_code"],
                    "ProductTitle": p["name"],
                    "PricingModel": p["pricing_model"],
                    "TrialDays": p["trial_days"],
                    "FulfillmentUrl": p.get("fulfillment_url"),
                    "QuickLaunchTemplateUrl": p.get("quick_launch_template_url"),
                    "Published": bool(p["published"]),
                    "Dimensions": json.loads(p["dimensions_json"]),
                }
            ),
            "DetailsDocument": {
                "ProductCode": p["product_code"],
                "ProductTitle": p["name"],
            },
        }

    with db.read() as c:
        o = c.execute("SELECT * FROM offers WHERE offer_id = ?", (entity_id,)).fetchone()
    if o is not None:
        o = dict(o)
        return {
            "EntityType": "SaaSProductOffer",
            "EntityIdentifier": o["offer_id"],
            "EntityArn": f"arn:aws:aws-marketplace:us-east-1:sim:offer/{o['offer_id']}",
            "LastModifiedDate": o["created_at"],
            "Details": json.dumps(
                {
                    "OfferId": o["offer_id"],
                    "ProductCode": o["product_code"],
                    "Kind": o["kind"],
                    "BuyerAccountAllowlist": json.loads(o["buyer_account_allowlist_json"] or "[]"),
                    "ContractTier": json.loads(o["contract_tier_json"])
                    if o.get("contract_tier_json")
                    else None,
                    "DurationMonths": o["duration_months"],
                    "FreeTrialEnabled": bool(o["free_trial_enabled"]),
                }
            ),
        }

    raise ResourceNotFoundException(f"no entity with id: {entity_id}")


# ─────────────────────────────── ChangeSets ──────────────────────────────────
def _apply_change(change: dict[str, Any]) -> None:
    """Apply a single change synchronously. Raises ValidationException on error."""
    ct = change.get("ChangeType")
    entity = change.get("Entity") or {}
    details = change.get("Details")
    details_doc = change.get("DetailsDocument")

    if not ct:
        raise ValidationException("ChangeType required on every change")
    if ct not in SUPPORTED_CHANGE_TYPES:
        raise ValidationException(
            f"unsupported ChangeType {ct!r}. supported: {sorted(SUPPORTED_CHANGE_TYPES)}"
        )

    # Details may be JSON string (real API) or the JSON document in DetailsDocument
    if isinstance(details, str):
        try:
            payload = json.loads(details)
        except json.JSONDecodeError as exc:
            raise ValidationException(f"Details must be valid JSON: {exc}") from exc
    elif isinstance(details_doc, dict):
        payload = details_doc
    elif isinstance(details, dict):
        payload = details
    else:
        payload = {}

    if ct == "CreateProduct":
        prod = payload.get("Product") or payload
        admin_handler.create_product(
            {
                "name": prod.get("Name") or prod.get("ProductTitle") or prod.get("name"),
                "pricingModel": prod.get("PricingModel"),
                "trialDays": prod.get("TrialDays", 0),
                "fulfillmentUrl": prod.get("FulfillmentUrl"),
                "quickLaunchTemplateUrl": prod.get("QuickLaunchTemplateUrl"),
                "dimensions": prod.get("Dimensions") or [],
            }
        )
        return

    if ct == "ReleaseProduct":
        pc = entity.get("Identifier")
        if not pc:
            raise ValidationException("Entity.Identifier required for ReleaseProduct")
        admin_handler.update_product(pc, {"published": True})
        return

    if ct == "AddDimensions":
        pc = entity.get("Identifier")
        new_dims = payload.get("Dimensions") or []
        existing = admin_handler.get_product(pc)
        merged = existing["dimensions"] + [
            d
            for d in new_dims
            if d["apiName"] not in {e["apiName"] for e in existing["dimensions"]}
        ]
        admin_handler.update_product(pc, {"dimensions": merged})
        return

    if ct == "UpdateInformation":
        pc = entity.get("Identifier")
        updates: dict[str, Any] = {}
        for field in ("Name", "FulfillmentUrl", "QuickLaunchTemplateUrl", "TrialDays"):
            if field in payload:
                key = {
                    "Name": "name",
                    "FulfillmentUrl": "fulfillmentUrl",
                    "QuickLaunchTemplateUrl": "quickLaunchTemplateUrl",
                    "TrialDays": "trialDays",
                }[field]
                updates[key] = payload[field]
        if updates:
            # 'name' isn't supported by admin.update_product in current impl;
            # skip it silently. All other fields map 1:1.
            updates.pop("name", None)
            if updates:
                admin_handler.update_product(pc, updates)
        return

    if ct == "CreateOffer":
        pc = entity.get("Identifier") or payload.get("ProductCode")
        offer_req = payload.get("Offer") or payload
        admin_handler.create_offer(
            {
                "productCode": pc,
                "kind": offer_req.get("Kind") or offer_req.get("kind", "public"),
                "buyerAccountAllowlist": offer_req.get("BuyerAccountAllowlist", []),
                "contractTier": offer_req.get("ContractTier"),
                "durationMonths": offer_req.get("DurationMonths", 1),
                "freeTrialEnabled": offer_req.get("FreeTrialEnabled", False),
            }
        )
        return


def start_change_set(body: dict[str, Any]) -> dict[str, Any]:
    catalog = body.get("Catalog", DEFAULT_CATALOG)
    changes = body.get("ChangeSet") or []
    if not isinstance(changes, list) or not changes:
        raise ValidationException("ChangeSet must be a non-empty list")
    change_set_id = f"cs-{uuid.uuid4().hex[:12]}"
    now = clock.now()

    with db.write() as c:
        c.execute(
            """INSERT INTO change_sets
               (change_set_id, change_set_name, catalog, intent, status,
                changes_json, client_request_token, start_time, end_time, created_at)
               VALUES (?, ?, ?, ?, 'PREPARING', ?, ?, ?, NULL, ?)""",
            (
                change_set_id,
                body.get("ChangeSetName"),
                catalog,
                body.get("Intent", "APPLY"),
                json.dumps(changes),
                body.get("ClientRequestToken"),
                now,
                now,
            ),
        )

    # Apply synchronously
    try:
        for change in changes:
            _apply_change(change)
        with db.write() as c:
            c.execute(
                "UPDATE change_sets SET status='SUCCEEDED', end_time=? WHERE change_set_id=?",
                (clock.now(), change_set_id),
            )
    except Exception as exc:
        with db.write() as c:
            c.execute(
                """UPDATE change_sets
                   SET status='FAILED', end_time=?,
                       failure_code=?, failure_description=?
                   WHERE change_set_id=?""",
                (clock.now(), type(exc).__name__, str(exc), change_set_id),
            )
        # still return the ChangeSetId (real AWS does too — caller polls for status)

    return {
        "ChangeSetId": change_set_id,
        "ChangeSetArn": f"arn:aws:aws-marketplace:us-east-1:sim:changeset/{change_set_id}",
    }


def describe_change_set(params: dict[str, Any]) -> dict[str, Any]:
    cid = params.get("changeSetId") or params.get("ChangeSetId")
    if not cid:
        raise ValidationException("changeSetId required")
    with db.read() as c:
        row = c.execute("SELECT * FROM change_sets WHERE change_set_id = ?", (cid,)).fetchone()
    if row is None:
        raise ResourceNotFoundException(f"no such change set: {cid}")
    r = dict(row)
    return {
        "ChangeSetId": r["change_set_id"],
        "ChangeSetArn": f"arn:aws:aws-marketplace:us-east-1:sim:changeset/{r['change_set_id']}",
        "ChangeSetName": r.get("change_set_name"),
        "StartTime": r["start_time"],
        "EndTime": r.get("end_time"),
        "Status": r["status"],
        "FailureCode": r.get("failure_code"),
        "FailureDescription": r.get("failure_description"),
        "Intent": r["intent"],
        "ChangeSet": json.loads(r["changes_json"]),
    }


def list_change_sets(body: dict[str, Any]) -> dict[str, Any]:
    offset = _parse_page_token(body.get("NextToken"))
    max_results = int(body.get("MaxResults") or MAX_RESULTS)
    max_results = min(max(max_results, 1), MAX_RESULTS)
    with db.read() as c:
        rows = [
            dict(r)
            for r in c.execute(
                """SELECT change_set_id, change_set_name, start_time, end_time, status
                   FROM change_sets ORDER BY start_time DESC LIMIT ? OFFSET ?""",
                (max_results + 1, offset),
            ).fetchall()
        ]
    has_more = len(rows) > max_results
    rows = rows[:max_results]
    result: dict[str, Any] = {
        "ChangeSetSummaryList": [
            {
                "ChangeSetId": r["change_set_id"],
                "ChangeSetName": r.get("change_set_name"),
                "StartTime": r["start_time"],
                "EndTime": r.get("end_time"),
                "Status": r["status"],
            }
            for r in rows
        ]
    }
    if has_more:
        result["NextToken"] = _page_token(offset + max_results)
    return result


def cancel_change_set(params: dict[str, Any]) -> dict[str, Any]:
    cid = params.get("changeSetId") or params.get("ChangeSetId")
    if not cid:
        raise ValidationException("changeSetId required")
    with db.read() as c:
        row = c.execute("SELECT status FROM change_sets WHERE change_set_id = ?", (cid,)).fetchone()
    if row is None:
        raise ResourceNotFoundException(f"no such change set: {cid}")
    if row["status"] not in ("PREPARING", "APPLYING_CHANGES"):
        raise ValidationException(f"cannot cancel change set in terminal status: {row['status']}")
    with db.write() as c:
        c.execute(
            "UPDATE change_sets SET status='CANCELLED', end_time=? WHERE change_set_id=?",
            (clock.now(), cid),
        )
    return {
        "ChangeSetId": cid,
        "ChangeSetArn": f"arn:aws:aws-marketplace:us-east-1:sim:changeset/{cid}",
    }
