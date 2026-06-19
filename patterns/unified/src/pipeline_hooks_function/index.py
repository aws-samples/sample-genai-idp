# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Pipeline-hooks dispatcher Lambda.

Invoked by the host's Step Functions workflow at each pipeline extension
point (postOcr, postClassification, postExtraction, postAssessment,
postRuleValidation, postSummarization). Reads the active configuration
version from the host's ConfigurationTable and dispatches to the hook
Lambdas listed under that step's `postHook` field.

Hooks are stored *inline in the active config version* — under each
processing step's section — so that activating a different config
version atomically swaps the hook set:

    Config#<version>
      ocr:
        postHook:
          - { featureId, arn, order, onError, enabled }
      classification:
        postHook: [ ... ]
      extraction:
        postHook: [ ... ]
      assessment:
        postHook: [ ... ]
      rule_validation:
        postHook: [ ... ]
      summarization:
        postHook: [ ... ]

Resolution rules:
  1. If the SFN input has `document.config_version`, use it.
  2. Else, scan the table for the row with IsActive=true.
  3. Else, fall back to `Config#default`.

Returns immediately when the requested step has no `postHook` entries,
keeping the no-vertical-pack overhead at one DDB GetItem.
"""

from __future__ import annotations

import base64
import gzip
import json
import logging
import os
from typing import Any, Dict, List, Optional

import boto3

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_CONFIG_TABLE = os.environ.get("CONFIGURATION_TABLE_NAME", "")

# Map hook point -> config path under the active config version.
# Each entry's value is the dotted path `<step>.postHook` we look up.
_HOOK_TO_STEP = {
    "postOcr": "ocr",
    "postClassification": "classification",
    "postExtraction": "extraction",
    "postAssessment": "assessment",
    "postRuleValidation": "rule_validation",
    "postSummarization": "summarization",
}

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
_lambda = boto3.client("lambda")


def _decompress_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Inline mirror of idp_common.config.configuration_manager._decompress_item.
    Returns the config payload as a plain dict, regardless of whether the
    DDB row was stored compressed (gzip+base64) or inline.
    """
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
            logger.warning("Config decompress failed: %s", exc)
            return {}
    return {
        k: v
        for k, v in item.items()
        if k not in _CONFIG_METADATA_FIELDS and not k.startswith("_")
    }


def _resolve_active_version(table: Any, pinned: Optional[str]) -> Optional[str]:
    """Determine which config version's hooks the dispatcher should read.

    Order: explicit pin from the document → IsActive=true row → default.
    Returns the version segment ("claims-pack-v0.1.0", "default", …) or
    None if the table has no Config rows at all.
    """
    if pinned:
        return pinned
    try:
        resp = table.scan(
            FilterExpression="begins_with(Configuration, :p) AND IsActive = :t",
            ExpressionAttributeValues={
                ":p": "Config#",
                ":t": True,
            },
            ProjectionExpression="Configuration",
            Limit=10,
        )
        items = resp.get("Items") or []
        if items:
            key = items[0]["Configuration"]
            return key.split("#", 1)[1] if "#" in key else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Active-version scan failed: %s", exc)
    return "default"


def _read_hooks_from_config(
    table: Any, version: str, point: str
) -> List[Dict[str, Any]]:
    """Read <step>.postHook from Config#<version>, returning enabled entries."""
    step = _HOOK_TO_STEP.get(point)
    if not step:
        logger.warning("Unknown hook point %s", point)
        return []
    try:
        resp = table.get_item(Key={"Configuration": f"Config#{version}"})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Config row read failed for version=%s: %s", version, exc)
        return []
    item = resp.get("Item") or {}
    if not item:
        return []
    payload = _decompress_item(item)
    step_block = payload.get(step) or {}
    if not isinstance(step_block, dict):
        return []
    raw = step_block.get("postHook") or []
    if not isinstance(raw, list):
        return []
    valid: List[Dict[str, Any]] = []
    for h in raw:
        if not isinstance(h, dict):
            continue
        # Defaults: enabled=true, order=100, onError=continue
        enabled = h.get("enabled")
        if enabled is False:
            continue
        arn = h.get("arn")
        if not arn:
            continue
        valid.append(
            {
                "featureId": h.get("featureId") or "unknown",
                "arn": arn,
                "order": int(h.get("order", 100))
                if h.get("order") is not None
                else 100,
                "onError": h.get("onError") or "continue",
            }
        )
    valid.sort(key=lambda h: (h["order"], h["featureId"]))
    return valid


def _invoke_hook(hook: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        resp = _lambda.invoke(
            FunctionName=hook["arn"],
            InvocationType="RequestResponse",
            Payload=json.dumps(payload, default=str).encode("utf-8"),
        )
        body = resp.get("Payload")
        parsed: Any = None
        if body is not None:
            try:
                parsed = json.loads(body.read().decode("utf-8"))
            except Exception:  # noqa: BLE001
                parsed = None
        if resp.get("FunctionError"):
            return {
                "featureId": hook["featureId"],
                "arn": hook["arn"],
                "ok": False,
                "error": parsed or "Unknown FunctionError",
            }
        return {
            "featureId": hook["featureId"],
            "arn": hook["arn"],
            "ok": True,
            "result": parsed,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("Hook invocation failed: %s", hook["arn"])
        return {
            "featureId": hook["featureId"],
            "arn": hook["arn"],
            "ok": False,
            "error": str(exc),
        }


def lambda_handler(event: Dict[str, Any], _ctx: Any) -> Dict[str, Any]:
    point = event.get("hookPoint")
    if point not in _HOOK_TO_STEP:
        logger.warning("Unknown hookPoint=%s — returning empty result", point)
        return {"hookPoint": point, "invoked": 0, "results": []}
    if not _CONFIG_TABLE:
        logger.info("CONFIGURATION_TABLE_NAME not set — no hooks dispatched")
        return {"hookPoint": point, "invoked": 0, "results": []}

    table = _dynamodb.Table(_CONFIG_TABLE)
    document = event.get("document") or {}
    pinned = document.get("config_version") if isinstance(document, dict) else None
    version = _resolve_active_version(table, pinned)
    if not version:
        logger.info("No config version resolvable; returning no-hooks")
        return {"hookPoint": point, "invoked": 0, "results": []}

    hooks = _read_hooks_from_config(table, version, point)
    if not hooks:
        logger.info("No hooks registered for %s in Config#%s", point, version)
        return {"hookPoint": point, "invoked": 0, "results": []}

    results: List[Dict[str, Any]] = []
    for h in hooks:
        payload = {
            "hookPoint": point,
            "featureId": h["featureId"],
            "document": event.get("document"),
            "section": event.get("section"),
            "executionArn": event.get("executionArn"),
        }
        r = _invoke_hook(h, payload)
        results.append(r)
        if not r["ok"] and h["onError"] == "fail":
            raise RuntimeError(
                f"Pipeline hook {h['featureId']} at {point} failed and onError=fail: {r.get('error')}"
            )
        if not r["ok"] and h["onError"] == "skip-remaining":
            logger.warning(
                "Hook %s reported failure with onError=skip-remaining; stopping",
                h["featureId"],
            )
            break
    return {
        "hookPoint": point,
        "configVersion": version,
        "invoked": len(results),
        "results": results,
    }
