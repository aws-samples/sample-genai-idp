# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Claims Review feature API.

Route                              | Returns
---------------------------------- | -------------------------------------------
GET /config                        | Small bootstrap blob for the UI (the host's
                                   | Discovery bucket name, for Rules Discovery)
GET /claims                        | List of claim rows from the ClaimsStatus table
GET /claims?status=REVIEW_REQUIRED | Same, filtered via the ByStatus GSI
GET /claims?window=7d              | Same, filtered to rows updated in the window
GET /claims/{docId}                | Claim row merged with the consolidated
                                   | rule-validation summary (per-rule details)
GET /claims/{docId}/summary.md     | The markdown summary, proxied as text
DELETE /claims/{docId}             | Delete a claim row (Admin/Author only) —
                                   | removes the ClaimsStatus record; the
                                   | document + rule-validation outputs in the
                                   | host stack are untouched

`{docId}` is the URL-encoded document id (the input S3 key, which may contain
slashes — the UI must encodeURIComponent it).

The HTTP API Gateway (template.yaml) is fronted by a Cognito JWT authorizer
pointing at the main stack's User Pool, so we only worry about application
logic here. The ClaimsStatus table is OWNED by this feature and populated by
the postRuleValidation hook (hook/handler.py); the consolidated summary JSON
is read from the host's Output bucket via the scoped s3:GetObject grant in
template.yaml.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_CLAIMS_TABLE = os.environ.get("CLAIMS_TABLE_NAME", "")
_DISCOVERY_BUCKET = os.environ.get("DISCOVERY_BUCKET", "")
_VALID_STATUSES = {"CLEAN_CLAIM", "REVIEW_REQUIRED", "INSUFFICIENT_DOCUMENTATION"}
_WINDOW_RE = re.compile(r"^(\d+)([hdw])$")

_dynamodb = boto3.resource("dynamodb")
_s3 = boto3.client("s3")


def _parse_window(raw: Optional[str]) -> Optional[timedelta]:
    if not raw:
        return None
    m = _WINDOW_RE.match(raw)
    if not m:
        raise ValueError(f"Unsupported window {raw!r}; examples: 24h, 7d, 4w")
    n, unit = int(m.group(1)), m.group(2)
    return {"h": timedelta(hours=n), "d": timedelta(days=n), "w": timedelta(weeks=n)}[
        unit
    ]


def _response(
    status: int, body: Any, content_type: str = "application/json"
) -> Dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": content_type,
            # CORS is handled by HTTP API's built-in preflight handler
            # (CorsConfiguration in template.yaml); no Access-Control-*
            # headers needed here.
        },
        "body": body if isinstance(body, str) else json.dumps(body, default=str),
    }


def _to_plain(value: Any) -> Any:
    """Convert DynamoDB Decimals to int/float for JSON serialization."""
    from decimal import Decimal

    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, dict):
        return {k: _to_plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_plain(v) for v in value]
    return value


def _list_claims(
    status_filter: Optional[str], since: Optional[datetime]
) -> List[Dict[str, Any]]:
    if not _CLAIMS_TABLE:
        raise RuntimeError("CLAIMS_TABLE_NAME env var is not set")
    table = _dynamodb.Table(_CLAIMS_TABLE)
    since_iso = since.isoformat().replace("+00:00", "Z") if since is not None else None

    items: List[Dict[str, Any]] = []
    if status_filter:
        # ByStatus GSI: hash=status, range=updatedAt — one partition per status.
        key_cond = Key("status").eq(status_filter)
        if since_iso:
            key_cond = key_cond & Key("updatedAt").gte(since_iso)
        kwargs: Dict[str, Any] = {
            "IndexName": "ByStatus",
            "KeyConditionExpression": key_cond,
        }
        while True:
            resp = table.query(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    else:
        kwargs = {}
        if since_iso:
            kwargs["FilterExpression"] = Key("updatedAt").gte(since_iso)
        while True:
            resp = table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    items.sort(key=lambda r: r.get("updatedAt") or "", reverse=True)
    return [_to_plain(i) for i in items]


def _read_s3(uri: str) -> Optional[bytes]:
    parsed = urlparse(uri)
    try:
        resp = _s3.get_object(Bucket=parsed.netloc, Key=parsed.path.lstrip("/"))
        return resp["Body"].read()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read %s: %s", uri, exc)
        return None


def _get_claim_row(doc_id: str) -> Optional[Dict[str, Any]]:
    table = _dynamodb.Table(_CLAIMS_TABLE)
    return table.get_item(Key={"documentId": doc_id}).get("Item")


def _caller_groups(event: Dict[str, Any]) -> List[str]:
    """Cognito groups from the HTTP API JWT authorizer claims.

    The `cognito:groups` claim arrives as a string like "[Admin Author]"
    (API GW stringifies the list) or occasionally a real list — handle both.
    """
    claims = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    raw = claims.get("cognito:groups")
    if isinstance(raw, list):
        return [str(g) for g in raw]
    if isinstance(raw, str):
        return raw.strip("[]").split()
    return []


def _get_claim_detail(doc_id: str) -> Optional[Dict[str, Any]]:
    """Claim row merged with the consolidated summary's per-rule details."""
    row = _get_claim_row(doc_id)
    if not row:
        return None
    detail = dict(_to_plain(row))

    raw = _read_s3(row.get("summaryJsonUri") or "")
    if raw:
        try:
            summary = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            summary = None
        if isinstance(summary, dict):
            detail["ruleSummary"] = summary.get("rule_summary") or {}
            detail["ruleDetails"] = summary.get("rule_details") or {}
            detail["supportingPages"] = summary.get("supporting_pages") or []
            detail["overallStatistics"] = summary.get("overall_statistics") or {}
    return detail


def lambda_handler(event: Dict[str, Any], _context: Any) -> Dict[str, Any]:
    path = event.get("rawPath", "/")
    qs = event.get("queryStringParameters") or {}
    method = event.get("requestContext", {}).get("http", {}).get("method") or "GET"
    logger.info("sample-health-insurance-review API %s %s", method, path)

    # DELETE /claims/{docId} — remove a claim row. Restricted to Admin/Author
    # (Reviewer/Viewer roles are read-only across the accelerator). Deleting a
    # claim only removes this feature's dashboard record; the document and its
    # rule-validation outputs in the host stack are untouched, and reprocessing
    # the document recreates the row.
    if method == "DELETE":
        m = re.match(r"^/claims/(.+)$", path)
        if not m:
            return _response(404, {"error": f"unknown path {path}"})
        groups = _caller_groups(event)
        if not ({"Admin", "Author"} & set(groups)):
            return _response(
                403,
                {"error": "Deleting claims requires the Admin or Author role"},
            )
        doc_id = unquote(m.group(1))
        try:
            row = _get_claim_row(doc_id)
            if not row:
                return _response(404, {"error": f"no claim found for {doc_id!r}"})
            _dynamodb.Table(_CLAIMS_TABLE).delete_item(Key={"documentId": doc_id})
        except Exception as exc:  # noqa: BLE001
            logger.exception("delete claim failed")
            return _response(500, {"error": str(exc)})
        logger.info("Deleted claim %s (by groups=%s)", doc_id, groups)
        return _response(200, {"deleted": doc_id})

    # GET /config — bootstrap blob the UI needs before it can drive the
    # host's Rules Discovery flow (the Discovery bucket name to pass to
    # uploadDiscoveryDocument). Imported from the host's exports in
    # template.yaml; null when the host did not export it.
    if path.rstrip("/") == "/config":
        return _response(200, {"discoveryBucket": _DISCOVERY_BUCKET or None})

    # GET /claims — list with optional ?status= and ?window= filters
    if path.rstrip("/") == "/claims":
        status_filter = qs.get("status")
        if status_filter and status_filter not in _VALID_STATUSES:
            return _response(
                400,
                {
                    "error": f"Unknown status {status_filter!r}; "
                    f"expected one of {sorted(_VALID_STATUSES)}"
                },
            )
        try:
            window = _parse_window(qs.get("window"))
        except ValueError as exc:
            return _response(400, {"error": str(exc)})
        since = datetime.now(timezone.utc) - window if window else None
        try:
            claims = _list_claims(status_filter, since)
        except Exception as exc:  # noqa: BLE001
            logger.exception("list claims failed")
            return _response(500, {"error": str(exc)})
        return _response(
            200,
            {
                "claims": claims,
                "total": len(claims),
                "status": status_filter or "all",
                "window": qs.get("window") or "all",
                "asOf": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )

    # GET /claims/{docId}[/summary.md] — docId is URL-encoded and may contain
    # encoded slashes, so match on the raw path prefix rather than API GW
    # path parameters.
    m = re.match(r"^/claims/(.+?)(/summary\.md)?$", path)
    if m:
        doc_id = unquote(m.group(1))
        wants_markdown = bool(m.group(2))
        try:
            row = _get_claim_row(doc_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("get claim failed")
            return _response(500, {"error": str(exc)})
        if not row:
            return _response(404, {"error": f"no claim found for {doc_id!r}"})

        if wants_markdown:
            raw = _read_s3(row.get("summaryMdUri") or "")
            if raw is None:
                return _response(404, {"error": "markdown summary not found"})
            return _response(200, raw.decode("utf-8"), content_type="text/markdown")

        detail = _get_claim_detail(doc_id)
        return _response(200, detail)

    return _response(404, {"error": f"unknown path {path}"})
