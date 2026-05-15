"""Data-plane handler for ``AWSMPEntitlementService.GetEntitlements``.

Supports the two filters real Marketplace supports:

- CUSTOMER_IDENTIFIER     (list of strings, UNION within list)
- CUSTOMER_AWS_ACCOUNT_ID (list of strings)  — mutually exclusive with CUSTOMER_IDENTIFIER
- DIMENSION               (list of strings, INTERSECTED with customer filter)

Pagination: opaque ``NextToken``; ``MaxResults`` default 25, max 25.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from .. import clock, db
from ..protocol import InvalidParameterException, InvalidProductCodeException

MAX_RESULTS = 25


def _page_token(offset: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"o": offset}).encode()).decode()


def _parse_page_token(token: str | None) -> int:
    if not token:
        return 0
    try:
        return int(json.loads(base64.urlsafe_b64decode(token.encode())).get("o", 0))
    except Exception as exc:
        raise InvalidParameterException(f"invalid NextToken: {exc}") from exc


def get_entitlements(body: dict[str, Any]) -> dict[str, Any]:
    product_code = body.get("ProductCode")
    if not product_code:
        raise InvalidProductCodeException("ProductCode required")

    with db.read() as c:
        prod = c.execute(
            "SELECT 1 FROM products WHERE product_code = ?", (product_code,)
        ).fetchone()
    if prod is None:
        raise InvalidProductCodeException(f"unknown ProductCode: {product_code}")

    filt = body.get("Filter") or {}
    if "CUSTOMER_IDENTIFIER" in filt and "CUSTOMER_AWS_ACCOUNT_ID" in filt:
        raise InvalidParameterException(
            "CUSTOMER_IDENTIFIER and CUSTOMER_AWS_ACCOUNT_ID are mutually exclusive"
        )

    max_results = int(body.get("MaxResults") or MAX_RESULTS)
    max_results = min(max(max_results, 1), MAX_RESULTS)
    offset = _parse_page_token(body.get("NextToken"))

    # Resolve the set of customer_identifiers the filter is asking about.
    #
    # Real AWS: when no customer filter is supplied, every entitlement for the
    # product is returned (across all customers).
    where = ["e.product_code = ?"]
    params: list[Any] = [product_code]

    cid_list = filt.get("CUSTOMER_IDENTIFIER")
    account_list = filt.get("CUSTOMER_AWS_ACCOUNT_ID")
    dim_list = filt.get("DIMENSION")

    if cid_list:
        placeholders = ",".join("?" * len(cid_list))
        where.append(f"e.customer_identifier IN ({placeholders})")
        params.extend(cid_list)
    elif account_list:
        placeholders = ",".join("?" * len(account_list))
        where.append(
            f"""e.customer_identifier IN (
                SELECT customer_identifier FROM subscriptions
                WHERE product_code = ?
                AND customer_aws_account_id IN ({placeholders})
            )"""
        )
        params.extend([product_code] + list(account_list))

    if dim_list:
        placeholders = ",".join("?" * len(dim_list))
        where.append(f"e.dimension IN ({placeholders})")
        params.extend(dim_list)

    # Exclude cancelled customers — real AWS returns empty set for them.
    where.append(
        """e.customer_identifier NOT IN (
            SELECT customer_identifier FROM subscriptions
            WHERE product_code = ? AND status = 'cancelled'
        )"""
    )
    params.append(product_code)

    sql = f"""
        SELECT e.customer_identifier, e.dimension, e.value_type, e.value_json,
               e.expiration_date
        FROM entitlements e
        WHERE {" AND ".join(where)}
        ORDER BY e.customer_identifier, e.dimension
        LIMIT ? OFFSET ?
    """
    params.extend([max_results + 1, offset])

    with db.read() as c:
        rows = c.execute(sql, params).fetchall()

    has_more = len(rows) > max_results
    rows = rows[:max_results]

    entitlements = []
    for r in rows:
        v = json.loads(r["value_json"])
        vtype = r["value_type"]  # 'Integer' | 'Double' | 'Boolean' | 'String'
        entitlements.append(
            {
                "ProductCode": product_code,
                "Dimension": r["dimension"],
                "CustomerIdentifier": r["customer_identifier"],
                "Value": {f"{vtype}Value": v},
                "ExpirationDate": float(r["expiration_date"]),
            }
        )

    # Filter expired entitlements at response time (don't delete — customers may
    # want to see "why was I cut off"; let caller decide).
    now = clock.now()
    entitlements = [e for e in entitlements if e["ExpirationDate"] > now]

    result: dict[str, Any] = {"Entitlements": entitlements}
    if has_more:
        result["NextToken"] = _page_token(offset + max_results)
    return result
