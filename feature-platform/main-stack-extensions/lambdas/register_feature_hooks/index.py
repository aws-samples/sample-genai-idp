# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""AppSync resolver for registerFeatureHooks / unregisterFeatureHooks.

Hooks are stored INLINE in the active config version, under each
processing step's `postHook` list:

    Config#<active-version>
      ocr:
        postHook: [ {featureId, arn, order, onError, enabled}, … ]
      classification:    { …, postHook: [ … ] }
      extraction:        { …, postHook: [ … ] }
      assessment:        { …, postHook: [ … ] }
      rule_validation:   { …, postHook: [ … ] }
      summarization:     { …, postHook: [ … ] }

So this resolver:
  1. Resolves the active config version (IsActive=true), or `default`
     when none is set.
  2. For each input hook entry, removes any existing entry in the
     corresponding step's `postHook` list with the same featureId, then
     appends the new entry.
  3. Writes the row back.

Hooks contributed by other features are preserved untouched.
"""

from __future__ import annotations

import base64
import gzip
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

import boto3

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_CONFIG_TABLE = os.environ["CONFIGURATION_TABLE"]

_HOOK_POINT_TO_STEP = {
    "postOcr": "ocr",
    "postClassification": "classification",
    "postExtraction": "extraction",
    # postAssessment removed in v0.6 (confidence folded into extraction).
    "postRuleValidation": "rule_validation",
    "postSummarization": "summarization",
}
_VALID_POINTS = set(_HOOK_POINT_TO_STEP)
_VALID_ON_ERROR = {"continue", "fail", "skip-remaining"}

_CONFIG_METADATA_FIELDS = {
    "Configuration",
    "CreatedAt",
    "UpdatedAt",
    "IsActive",
    "Description",
    "Managed",
    "BdaProjectArn",
    "BdaSyncStatus",
    "BdaLastSyncedAt",
}

_dynamodb = boto3.resource("dynamodb")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _decompress(item: Dict[str, Any]) -> Dict[str, Any]:
    storage = item.get("_config_storage")
    compressed = item.get("_compressed_config")
    if storage == "compressed" and compressed is not None:
        try:
            raw = compressed.value if hasattr(compressed, "value") else compressed
            if isinstance(raw, str):
                raw = base64.b64decode(raw)
            text = gzip.decompress(raw).decode("utf-8")
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception as exc:  # noqa: BLE001
            logger.warning("Decompress failed: %s", exc)
            return {}
    return {
        k: v
        for k, v in item.items()
        if k not in _CONFIG_METADATA_FIELDS and not k.startswith("_")
    }


def _resolve_active_version(table: Any) -> str:
    try:
        resp = table.scan(
            FilterExpression="begins_with(Configuration, :p) AND IsActive = :t",
            ExpressionAttributeValues={":p": "Config#", ":t": True},
            ProjectionExpression="Configuration",
            Limit=1,
        )
        items = resp.get("Items") or []
        if items:
            key = items[0]["Configuration"]
            if "#" in key:
                return key.split("#", 1)[1]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Active-version scan failed (defaulting to 'default'): %s", exc)
    return "default"


def _validate_hook(h: Dict[str, Any]) -> Dict[str, Any]:
    point = h.get("point")
    arn = h.get("arn")
    if point not in _VALID_POINTS:
        raise ValueError(
            f"Invalid hook point {point!r}; must be one of {sorted(_VALID_POINTS)}"
        )
    if not isinstance(arn, str) or not arn.startswith("arn:") or ":lambda:" not in arn:
        raise ValueError(f"Invalid hook arn {arn!r}; expected a Lambda ARN")
    order = h.get("order")
    if order is None:
        order = 100
    if not isinstance(order, int):
        raise ValueError(f"Hook order must be an integer; got {order!r}")
    on_error = h.get("onError") or "continue"
    if on_error not in _VALID_ON_ERROR:
        raise ValueError(
            f"Invalid onError {on_error!r}; must be one of {sorted(_VALID_ON_ERROR)}"
        )
    enabled = h.get("enabled")
    if enabled is None:
        enabled = True
    if not isinstance(enabled, bool):
        raise ValueError(f"Hook enabled must be a bool; got {enabled!r}")
    return {
        "point": point,
        "arn": arn,
        "order": int(order),
        "onError": on_error,
        "enabled": enabled,
    }


def _replace_pack_entries(
    payload: Dict[str, Any],
    feature_id: str,
    new_by_step: Dict[str, List[Dict[str, Any]]],
) -> int:
    """Mutate `payload` so each step's `postHook` list has THIS featureId's
    entries replaced with the new ones; entries from other features survive.
    Returns the total number of entries this featureId now contributes.
    """
    total = 0
    for point, step in _HOOK_POINT_TO_STEP.items():
        new_entries = new_by_step.get(step, [])
        block = payload.get(step)
        if not isinstance(block, dict):
            block = {} if block is None else {"_legacy_value": block}
            payload[step] = block
        existing = block.get("postHook") or []
        if not isinstance(existing, list):
            existing = []
        kept = [
            e
            for e in existing
            if not (isinstance(e, dict) and e.get("featureId") == feature_id)
        ]
        block["postHook"] = kept + new_entries
        total += len(new_entries)
    return total


def _register(feature_id: str, hooks_in: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not feature_id:
        raise ValueError("featureId is required")
    table = _dynamodb.Table(_CONFIG_TABLE)
    version = _resolve_active_version(table)
    config_key = f"Config#{version}"

    resp = table.get_item(Key={"Configuration": config_key})
    item = resp.get("Item")
    if not item:
        raise RuntimeError(
            f"Active config version {config_key} not found; cannot register hooks"
        )
    payload = _decompress(item)

    # Group input hooks by step.
    by_step: Dict[str, List[Dict[str, Any]]] = {}
    for raw in hooks_in:
        v = _validate_hook(raw)
        step = _HOOK_POINT_TO_STEP[v["point"]]
        by_step.setdefault(step, []).append(
            {
                "featureId": feature_id,
                "arn": v["arn"],
                "order": v["order"],
                "onError": v["onError"],
                "enabled": v["enabled"],
            }
        )

    pack_count = _replace_pack_entries(payload, feature_id, by_step)

    # Write back. We rewrite the whole row from the decompressed payload to
    # ensure compressed-storage rows become inline (the manager-side
    # writer in idp_common normalises this on next read anyway).
    timestamp = _now()
    new_item: Dict[str, Any] = {
        "Configuration": config_key,
        "_config_format": "full",
        "CreatedAt": item.get("CreatedAt", timestamp),
        "UpdatedAt": timestamp,
        "IsActive": item.get("IsActive", True),
        "Description": item.get("Description", ""),
        "Managed": item.get("Managed", False),
        **{k: v for k, v in payload.items() if k not in _CONFIG_METADATA_FIELDS},
    }
    table.put_item(Item=new_item)
    logger.info(
        "Registered %d hook(s) for %s into %s",
        pack_count,
        feature_id,
        config_key,
    )
    return {
        "featureId": feature_id,
        "hookCount": pack_count,
        "registeredAt": timestamp,
    }


def _unregister(feature_id: str) -> bool:
    if not feature_id:
        raise ValueError("featureId is required")
    table = _dynamodb.Table(_CONFIG_TABLE)
    version = _resolve_active_version(table)
    config_key = f"Config#{version}"

    resp = table.get_item(Key={"Configuration": config_key})
    item = resp.get("Item")
    if not item:
        return True
    payload = _decompress(item)
    _replace_pack_entries(payload, feature_id, {})
    timestamp = _now()
    new_item: Dict[str, Any] = {
        "Configuration": config_key,
        "_config_format": "full",
        "CreatedAt": item.get("CreatedAt", timestamp),
        "UpdatedAt": timestamp,
        "IsActive": item.get("IsActive", True),
        "Description": item.get("Description", ""),
        "Managed": item.get("Managed", False),
        **{k: v for k, v in payload.items() if k not in _CONFIG_METADATA_FIELDS},
    }
    table.put_item(Item=new_item)
    logger.info("Unregistered hooks for %s in %s", feature_id, config_key)
    return True


def handler(event: Dict[str, Any], _context: Any) -> Any:
    logger.info("registerFeatureHooks event: %s", event)
    field = event.get("info", {}).get("fieldName", "")
    args = event.get("arguments", {}) or {}
    if field == "registerFeatureHooks":
        payload = args.get("input", {}) or {}
        return _register(payload.get("featureId", ""), payload.get("hooks") or [])
    if field == "unregisterFeatureHooks":
        return _unregister(args.get("featureId", ""))
    raise ValueError(f"Unknown field: {field!r}")
