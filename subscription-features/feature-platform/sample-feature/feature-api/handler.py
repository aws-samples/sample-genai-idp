# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Docs-by-status feature API.

Route                          | Returns
------------------------------ | ------------------------------------------
GET /counts                    | {status: count} over the main stack's TrackingTable
GET /counts?window=24h         | Same, filtered to documents created in the last 24h

The HTTP API Gateway (template.yaml) is fronted by a Cognito JWT authorizer
pointing at the main stack's User Pool, so we only have to worry about
application logic here.

The main stack's TrackingTable is a multi-item-type table (documents,
sections, etc.). Document rows are identified by ItemType='document' and
have ObjectStatus / InitialEventTime attributes. We query the TypeDateIndex
GSI (partitioned by ItemType, sorted by InitialEventTime) rather than
scanning the base table.
"""

from __future__ import annotations

import collections
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_DOCUMENTS_TABLE = os.environ.get("DOCUMENTS_TABLE_NAME", "")
_dynamodb = boto3.resource("dynamodb")

# Canonical set of statuses the IDP main stack produces — we always return one
# entry per status so the UI pie chart has a stable palette.
_CANONICAL_STATUSES = (
    "NEW",
    "QUEUED",
    "RUNNING",
    "OCR",
    "CLASSIFYING",
    "EXTRACTING",
    "POSTPROCESSING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "HITL_PENDING",
)

_WINDOW_RE = re.compile(r"^(\d+)([hdw])$")


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


def _response(status: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            # CORS is handled by HTTP API's built-in preflight + the same-origin
            # CloudFront distribution; no Access-Control-* headers needed for
            # in-browser calls from the IDP UI.
        },
        "body": json.dumps(body),
    }


def _count(since: Optional[datetime]) -> Dict[str, int]:
    if not _DOCUMENTS_TABLE:
        raise RuntimeError("DOCUMENTS_TABLE_NAME env var is not set")
    table = _dynamodb.Table(_DOCUMENTS_TABLE)

    # Query the TypeDateIndex GSI, partitioned by ItemType and sorted by
    # InitialEventTime (ISO-8601 string). Documents are ItemType='document'.
    counts: collections.Counter = collections.Counter()
    key_cond = Key("ItemType").eq("document")
    if since:
        key_cond = key_cond & Key("InitialEventTime").gte(
            since.isoformat().replace("+00:00", "Z")
        )

    kwargs: Dict[str, Any] = {
        "IndexName": "TypeDateIndex",
        "KeyConditionExpression": key_cond,
        "ProjectionExpression": "ObjectStatus",
    }

    while True:
        resp = table.query(**kwargs)
        for item in resp.get("Items", []):
            status = item.get("ObjectStatus") or "UNKNOWN"
            counts[status] += 1
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    # Populate zeros for canonical statuses so the UI always has them.
    result = {s: counts.get(s, 0) for s in _CANONICAL_STATUSES}
    # Include any non-canonical statuses discovered at the end.
    for s, n in counts.items():
        if s not in result:
            result[s] = n
    return result


def lambda_handler(event: Dict[str, Any], _context: Any) -> Dict[str, Any]:
    path = event.get("rawPath", "/")
    qs = event.get("queryStringParameters") or {}
    logger.info(
        "docs-by-status API %s %s",
        event.get("requestContext", {}).get("http", {}).get("method"),
        path,
    )

    if path.rstrip("/") in ("/counts", ""):
        try:
            window = _parse_window(qs.get("window"))
        except ValueError as exc:
            return _response(400, {"error": str(exc)})

        since = datetime.now(timezone.utc) - window if window else None
        try:
            counts = _count(since)
        except Exception as exc:  # noqa: BLE001
            logger.exception("count failed")
            return _response(500, {"error": str(exc)})
        return _response(
            200,
            {
                "counts": counts,
                "total": sum(counts.values()),
                "window": qs.get("window") or "all",
                "asOf": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )

    return _response(404, {"error": f"unknown path {path}"})
