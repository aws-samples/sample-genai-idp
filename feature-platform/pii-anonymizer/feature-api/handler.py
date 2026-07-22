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
_WINDOW_RE = re.compile(r"^(\d+)([hdw])$")

_dynamodb = boto3.resource("dynamodb")


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
            {"feature": "pii-anonymizer", "hookFunctionArn": _HOOK_FUNCTION_ARN or None},
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
