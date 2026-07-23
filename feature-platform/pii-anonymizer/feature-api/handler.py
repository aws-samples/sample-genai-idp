# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""PII Anonymization feature API — backs the Redaction Report tab.

Route                              | Returns
---------------------------------- | -------------------------------------------
GET /config                        | Small bootstrap blob for the UI
GET /report                        | List of redaction audit rows (metadata only)
GET /report?window=7d              | Same, filtered to rows created in the window
GET /report/{docId}                | A single audit row

The audit rows are metadata ONLY — pii_count, mode, source/redacted keys,
companion version, timestamps. NO PII is ever stored or returned. The table is
OWNED by this feature and populated by the preprocessing hook (hook/handler.py).

The HTTP API Gateway (template.yaml) is fronted by a Cognito JWT authorizer
pointing at the main stack's User Pool, so we only handle application logic.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_AUDIT_TABLE = os.environ.get("AUDIT_TABLE_NAME", "")
_HOOK_FUNCTION_ARN = os.environ.get("HOOK_FUNCTION_ARN", "")
_USERS_TABLE = os.environ.get("USERS_TABLE_NAME", "")
_OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "")
_WINDOW_RE = re.compile(r"^(\d+)([hdw])$")

_dynamodb = boto3.resource("dynamodb")
_s3 = boto3.client("s3")


def _caller_claims(event: Dict[str, Any]) -> Dict[str, Any]:
    """JWT claims the HTTP API's Cognito authorizer attached to the request."""
    return (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    ) or {}


def _caller_email(event: Dict[str, Any]) -> str:
    c = _caller_claims(event)
    return c.get("email") or c.get("cognito:username") or c.get("sub") or ""


def _caller_groups(event: Dict[str, Any]) -> list:
    raw = _caller_claims(event).get("cognito:groups") or []
    if isinstance(raw, str):
        # Cognito serializes the groups claim as a bracketed string over HTTP API.
        raw = [g for g in raw.strip("[]").replace(",", " ").split() if g]
    return list(raw)


def _caller_allowed_versions(email: str) -> Optional[list]:
    """The caller's allowedConfigVersions scope from the host UsersTable, or
    None if unrestricted (no scope set / lookup unavailable)."""
    if not _USERS_TABLE or not email:
        return None
    try:
        from boto3.dynamodb.conditions import Key as _Key

        table = _dynamodb.Table(_USERS_TABLE)
        resp = table.query(
            IndexName="EmailIndex", KeyConditionExpression=_Key("email").eq(email)
        )
        items = resp.get("Items", [])
        if items:
            scope = items[0].get("allowedConfigVersions")
            return list(scope) if scope else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("User scope lookup failed for %s: %s", email, exc)
    return None


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


def _response(status: int, body: Any) -> Dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
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


def _list_report(since: Optional[datetime]) -> List[Dict[str, Any]]:
    if not _AUDIT_TABLE:
        raise RuntimeError("AUDIT_TABLE_NAME env var is not set")
    table = _dynamodb.Table(_AUDIT_TABLE)
    since_iso = since.isoformat().replace("+00:00", "Z") if since is not None else None

    items: List[Dict[str, Any]] = []
    # ByCreatedAt GSI: hash=gsiPk("ALL"), range=createdAt — a single partition
    # ordered by time, so we can range-filter and return newest-first cheaply.
    key_cond = Key("gsiPk").eq("ALL")
    if since_iso:
        key_cond = key_cond & Key("createdAt").gte(since_iso)
    kwargs: Dict[str, Any] = {
        "IndexName": "ByCreatedAt",
        "KeyConditionExpression": key_cond,
        "ScanIndexForward": False,  # newest first
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return [_to_plain(i) for i in items]


def _get_row(doc_id: str) -> Optional[Dict[str, Any]]:
    table = _dynamodb.Table(_AUDIT_TABLE)
    item = table.get_item(Key={"documentId": doc_id}).get("Item")
    return _to_plain(item) if item else None


def _read_mapping(uri: str) -> Optional[Dict[str, Any]]:
    """Read the stored mapping JSON (contains real PII) from its s3:// URI."""
    from urllib.parse import urlparse

    p = urlparse(uri)
    try:
        resp = _s3.get_object(Bucket=p.netloc, Key=p.path.lstrip("/"))
        body = json.loads(resp["Body"].read().decode("utf-8"))
        return body if isinstance(body, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read mapping %s: %s", uri, exc)
        return None


def lambda_handler(event: Dict[str, Any], _context: Any) -> Dict[str, Any]:
    path = event.get("rawPath", "/")
    qs = event.get("queryStringParameters") or {}
    logger.info(
        "pii-anonymizer API %s %s",
        event.get("requestContext", {}).get("http", {}).get("method"),
        path,
    )

    if path.rstrip("/") == "/config":
        return _response(
            200,
            {
                "feature": "pii-anonymizer",
                "hookFunctionArn": _HOOK_FUNCTION_ARN or None,
            },
        )

    if path.rstrip("/") == "/report":
        try:
            window = _parse_window(qs.get("window"))
        except ValueError as exc:
            return _response(400, {"error": str(exc)})
        since = datetime.now(timezone.utc) - window if window else None
        try:
            rows = _list_report(since)
        except Exception as exc:  # noqa: BLE001
            logger.exception("list report failed")
            return _response(500, {"error": str(exc)})
        # Aggregate a small summary for the report header.
        total_pii = sum(int(r.get("piiCount") or 0) for r in rows)
        return _response(
            200,
            {
                "rows": rows,
                "total": len(rows),
                "totalPiiRedacted": total_pii,
                "window": qs.get("window") or "all",
                "asOf": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )

    # GET /report/{docId}/mapping — RBAC-GATED. Returns the original->synthetic
    # PII mapping (a re-identification key) ONLY to a caller whose
    # allowedConfigVersions include the ORIGINAL document's config version.
    mm = re.match(r"^/report/(.+)/mapping$", path)
    if mm:
        doc_id = unquote(mm.group(1))
        try:
            row = _get_row(doc_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("get report row failed")
            return _response(500, {"error": str(exc)})
        if not row:
            return _response(404, {"error": f"no redaction record for {doc_id!r}"})
        if not row.get("mappingStored") or not row.get("mappingUri"):
            return _response(404, {"error": "no stored mapping for this document"})

        # RBAC: caller must be allowed the ORIGINAL's config version. Admins
        # (or users with no scope restriction) pass; a scoped user must have the
        # original's config version in their allowedConfigVersions.
        original_version = row.get("originalConfigVersion") or ""
        groups = _caller_groups(event)
        allowed = _caller_allowed_versions(_caller_email(event))
        is_admin = "Admin" in groups
        if not is_admin and allowed is not None and original_version not in allowed:
            return _response(
                403,
                {
                    "error": "Access denied: you do not have access to the "
                    "config version that processed the original document."
                },
            )

        mapping_doc = _read_mapping(row["mappingUri"])
        if mapping_doc is None:
            return _response(404, {"error": "stored mapping not readable"})
        return _response(200, mapping_doc)

    m = re.match(r"^/report/(.+)$", path)
    if m:
        doc_id = unquote(m.group(1))
        try:
            row = _get_row(doc_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("get report row failed")
            return _response(500, {"error": str(exc)})
        if not row:
            return _response(404, {"error": f"no redaction record for {doc_id!r}"})
        return _response(200, row)

    return _response(404, {"error": f"unknown path {path}"})
