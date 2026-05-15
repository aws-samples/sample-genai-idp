"""Data-plane handler for ``AWSMPCommerceService_v20200301`` (marketplace-agreement SDK).

Operations:
    - DescribeAgreement(agreementId)
    - SearchAgreements(catalog, filters?, sort?, maxResults?, nextToken?)
    - GetAgreementTerms(agreementId, maxResults?, nextToken?)

Agreements are created in ``buyer.subscribe()`` and cancelled/expired via
``buyer.unsubscribe()`` or clock advance past ``end_time``. This handler is
the read-side that sellers and buyers use to list/inspect subscriptions.

Note: real AWS enforces "buyers can only see agreements they're party to"
via IAM/SigV4. The simulator accepts any request (no signature verification)
so callers should pass ``acceptor_account_id`` / ``proposer_account_id``
filters explicitly if they want to scope results.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from .. import db
from ..protocol import (
    ResourceNotFoundException,
    ValidationException,
)

MAX_RESULTS = 25


def _page_token(offset: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"o": offset}).encode()).decode()


def _parse_page_token(token: str | None) -> int:
    if not token:
        return 0
    try:
        return int(json.loads(base64.urlsafe_b64decode(token.encode())).get("o", 0))
    except Exception as exc:
        raise ValidationException(f"invalid nextToken: {exc}") from exc


def _agreement_to_describe(row: dict[str, Any]) -> dict[str, Any]:
    """Shape output matches real DescribeAgreementOutput."""
    out: dict[str, Any] = {
        "agreementId": row["agreement_id"],
        "acceptor": {"accountId": row["acceptor_account_id"]},
        "proposer": {"accountId": row["proposer_account_id"]},
        "startTime": row["start_time"],
        "acceptanceTime": row["acceptance_time"],
        "agreementType": row["agreement_type"],
        "status": row["status"],
        "proposalSummary": {
            "resources": [{"id": row["product_code"], "type": "SaaSProduct"}],
            "offerId": row["offer_id"],
        },
        "estimatedCharges": {"currencyCode": "USD", "agreementValue": "0.0"},
    }
    if row.get("end_time"):
        out["endTime"] = row["end_time"]
    return out


def _agreement_to_summary(row: dict[str, Any]) -> dict[str, Any]:
    """Shape for SearchAgreements results."""
    return {
        "agreementId": row["agreement_id"],
        "acceptor": {"accountId": row["acceptor_account_id"]},
        "proposer": {"accountId": row["proposer_account_id"]},
        "startTime": row["start_time"],
        "endTime": row.get("end_time"),
        "acceptanceTime": row["acceptance_time"],
        "agreementType": row["agreement_type"],
        "status": row["status"],
        "proposalSummary": {
            "resources": [{"id": row["product_code"], "type": "SaaSProduct"}],
            "offerId": row["offer_id"],
        },
    }


def describe_agreement(body: dict[str, Any]) -> dict[str, Any]:
    aid = body.get("agreementId")
    if not aid:
        raise ValidationException("agreementId required")
    with db.read() as c:
        row = c.execute("SELECT * FROM agreements WHERE agreement_id = ?", (aid,)).fetchone()
    if row is None:
        raise ResourceNotFoundException(f"no such agreementId: {aid}")
    return _agreement_to_describe(dict(row))


def search_agreements(body: dict[str, Any]) -> dict[str, Any]:
    """Filter model (real AWS):

    filters: [
      {name: "AcceptorAccountId", values: ["123"]},
      {name: "ProposerAccountId", values: ["456"]},
      {name: "AgreementType",     values: ["PurchaseAgreement"]},
      {name: "Status",            values: ["ACTIVE"]},
      {name: "ResourceIdentifier",values: ["<product_code>"]},
    ]
    """
    filters = body.get("filters") or []
    if not isinstance(filters, list):
        raise ValidationException("filters must be a list")

    where = []
    params: list[Any] = []
    for f in filters:
        name = f.get("name")
        vals = f.get("values") or []
        if not isinstance(vals, list) or not vals:
            continue
        if name == "AcceptorAccountId":
            where.append(f"acceptor_account_id IN ({','.join('?' * len(vals))})")
            params.extend(vals)
        elif name == "ProposerAccountId":
            where.append(f"proposer_account_id IN ({','.join('?' * len(vals))})")
            params.extend(vals)
        elif name == "AgreementType":
            where.append(f"agreement_type IN ({','.join('?' * len(vals))})")
            params.extend(vals)
        elif name == "Status":
            where.append(f"status IN ({','.join('?' * len(vals))})")
            params.extend(vals)
        elif name == "ResourceIdentifier":
            where.append(f"product_code IN ({','.join('?' * len(vals))})")
            params.extend(vals)
        else:
            raise ValidationException(f"unknown filter name: {name}")

    max_results = int(body.get("maxResults") or MAX_RESULTS)
    max_results = min(max(max_results, 1), MAX_RESULTS)
    offset = _parse_page_token(body.get("nextToken"))

    where_clause = f"WHERE {' AND '.join(where)}" if where else ""
    sql = f"""
        SELECT * FROM agreements
        {where_clause}
        ORDER BY acceptance_time DESC
        LIMIT ? OFFSET ?
    """
    params.extend([max_results + 1, offset])

    with db.read() as c:
        rows = [dict(r) for r in c.execute(sql, params).fetchall()]

    has_more = len(rows) > max_results
    rows = rows[:max_results]

    result: dict[str, Any] = {"agreementViewSummaries": [_agreement_to_summary(r) for r in rows]}
    if has_more:
        result["nextToken"] = _page_token(offset + max_results)
    return result


def get_agreement_terms(body: dict[str, Any]) -> dict[str, Any]:
    """Return the terms accepted by the buyer (contract, pricing, etc.).

    Real AWS returns a complex union of term types. For the simulator, we
    surface enough to be useful: the contract term with tier + duration.
    """
    aid = body.get("agreementId")
    if not aid:
        raise ValidationException("agreementId required")

    with db.read() as c:
        row = c.execute(
            """SELECT a.*, o.contract_tier_json, o.duration_months, o.free_trial_enabled
               FROM agreements a
               JOIN offers o ON a.offer_id = o.offer_id
               WHERE a.agreement_id = ?""",
            (aid,),
        ).fetchone()
    if row is None:
        raise ResourceNotFoundException(f"no such agreementId: {aid}")

    ag = dict(row)
    tier = json.loads(ag["contract_tier_json"]) if ag.get("contract_tier_json") else None

    accepted_terms: list[dict[str, Any]] = []
    if tier:
        accepted_terms.append(
            {
                "configurableUpfrontPricingTerm": {
                    "type": "CONFIGURABLE_UPFRONT",
                    "currencyCode": "USD",
                    "rateCards": [
                        {
                            "selector": {"type": "Duration", "value": f"P{ag['duration_months']}M"},
                            "rateCard": [
                                {
                                    "dimensionKey": tier["dimension"],
                                    "price": "0.05",  # placeholder
                                }
                            ],
                        }
                    ],
                }
            }
        )
    accepted_terms.append(
        {
            "validityTerm": {
                "type": "VALIDITY_TERM",
                "agreementStartDate": ag["start_time"],
                "agreementEndDate": ag.get("end_time"),
                "agreementDuration": f"P{ag['duration_months']}M",
            }
        }
    )
    if ag.get("free_trial_enabled"):
        accepted_terms.append({"freeTrialPricingTerm": {"type": "FREE_TRIAL"}})

    max_results = int(body.get("maxResults") or MAX_RESULTS)
    offset = _parse_page_token(body.get("nextToken"))
    page = accepted_terms[offset : offset + max_results]
    result: dict[str, Any] = {"acceptedTerms": page}
    if offset + len(page) < len(accepted_terms):
        result["nextToken"] = _page_token(offset + len(page))
    return result


# ─────────────────────────── agreement row helpers ───────────────────────────
def create_agreement_from_subscription(sub: dict[str, Any]) -> str:
    """Called from buyer.subscribe(). Returns the new agreement_id."""
    import uuid

    from .. import clock

    aid = f"agmt-{uuid.uuid4().hex[:16]}"
    # Proposer is the seller; the simulator doesn't model a specific seller
    # account so we use a placeholder. In real AWS this is the seller account id.
    proposer = "000000000000"  # seller of record
    acceptor = sub["customerAWSAccountId"]
    # startTime = "now" (acceptance). trialEndsAt is surfaced separately on
    # the subscription row and via GetAgreementTerms.
    now = clock.now()

    with db.write() as c:
        c.execute(
            """INSERT INTO agreements
               (agreement_id, customer_identifier, proposer_account_id,
                acceptor_account_id, product_code, offer_id,
                agreement_type, start_time, end_time,
                acceptance_time, status, cancelled_at)
               VALUES (?, ?, ?, ?, ?, ?, 'PurchaseAgreement',
                       ?, NULL, ?, 'ACTIVE', NULL)""",
            (
                aid,
                sub["customerIdentifier"],
                proposer,
                acceptor,
                sub["productCode"],
                sub.get("offerId") or sub.get("offer_id"),
                now,
                now,
            ),
        )
    return aid


def cancel_agreement_for_customer(customer_identifier: str) -> None:
    """Called from buyer.unsubscribe()."""
    from .. import clock

    now = clock.now()
    with db.write() as c:
        c.execute(
            """UPDATE agreements
               SET status = 'CANCELLED', cancelled_at = ?, end_time = ?
               WHERE customer_identifier = ?""",
            (now, now, customer_identifier),
        )
