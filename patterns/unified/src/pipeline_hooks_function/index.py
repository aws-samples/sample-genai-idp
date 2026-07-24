# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Pipeline-hooks dispatcher Lambda.

Invoked by the host's Step Functions workflow at each pipeline extension
point (preprocessing, postOcr, postClassification, postExtraction,
postRuleValidation, postSummarization). Reads the active configuration
version from the host's ConfigurationTable and dispatches to the hook
Lambdas listed under that section's hook-list field. The field is chosen
by the hook point prefix: `pre*` points read `preHook`, `post*` points
read `postHook`.

Hooks are stored *inline in the active config version* — under each
section — so that activating a different config version atomically swaps
the hook set:

    Config#<version>
      preprocessing:            # standalone section — runs FIRST, before the
        enabled: true           # BDA/pipeline routing. A SINGLE inline hook:
        arn: <lambda-arn>       # arn/args/onError live directly on the section
        onError: fail           # (no list), so it reads cleanly in the config UI.
        args: [ { key, value }, ... ]   # generic key/value config for the hook
      ocr:
        postHook:               # post-step points keep a LIST of hooks
          - { featureId, arn, order, onError, enabled, args }
      classification:
        postHook: [ ... ]
      extraction:
        postHook: [ ... ]
      rule_validation:
        postHook: [ ... ]
      summarization:
        postHook: [ ... ]

The dispatcher's return value includes a top-level `halt` flag (true if any
successful hook returned result.halt == true) so the workflow's post-hook
Choice can short-circuit the execution via a stable JSONPath.

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
_TRACKING_TABLE = os.environ.get("TRACKING_TABLE", "")

# Map hook point -> config section under the active config version.
#
# The hook LIST field within that section is chosen by the hook point's
# prefix: `pre*` points read `<section>.preHook`, `post*` points read
# `<section>.postHook` (see _hook_list_field). This lets a `pre*` and a
# `post*` hook coexist in the same section without colliding.
#
# `preprocessing` is a standalone top-level section (NOT nested under `ocr`):
# its hook runs FIRST in the workflow, before the BDA/pipeline routing
# decision, so it fires in both processing modes and even when OCR is
# disabled. Semantically it operates on the source document, not on OCR
# output, which is why it gets its own section.
_HOOK_TO_STEP = {
    "preprocessing": "preprocessing",
    "postOcr": "ocr",
    "postClassification": "classification",
    "postExtraction": "extraction",
    # postAssessment removed in v0.6 — confidence assessment is folded into
    # extraction, so its post-step hook point no longer exists.
    "postRuleValidation": "rule_validation",
    "postSummarization": "summarization",
}


def _hook_list_field(point: str) -> str:
    """The hook-list field name for a hook point: preHook for pre* points,
    postHook otherwise. Keeps pre/post hooks in the same section distinct."""
    return "preHook" if point.startswith("pre") else "postHook"


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
# Hooks run synchronously through this client, so its read timeout must cover
# the longest hook (the PII preprocessing hook budgets 900s); botocore's
# default ~60s read timeout would sever the invoke mid-run. Retries are
# disabled: hooks are not guaranteed idempotent, and the state machine's own
# Retry handles the transient Lambda.* errors.
_lambda = boto3.client(
    "lambda",
    config=boto3.session.Config(
        read_timeout=910, connect_timeout=10, retries={"max_attempts": 0}
    ),
)


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


def _normalize_hook(h: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Validate + normalize one hook entry. Returns None if disabled or arn-less.
    Generic `args` is an optional list of {key, value} string pairs the hook
    reads its own settings from (keeps the platform hook-agnostic)."""
    if not isinstance(h, dict) or h.get("enabled") is False:
        return None
    arn = h.get("arn")
    if not arn:
        return None
    raw_args = h.get("args")
    args = (
        [a for a in raw_args if isinstance(a, dict) and "key" in a]
        if isinstance(raw_args, list)
        else []
    )
    return {
        "featureId": h.get("featureId") or "unknown",
        "arn": arn,
        "order": int(h.get("order", 100)) if h.get("order") is not None else 100,
        "onError": h.get("onError") or "continue",
        "args": args,
    }


def _read_hooks_from_config(
    table: Any, version: str, point: str
) -> List[Dict[str, Any]]:
    """Read the hooks for a point from Config#<version>, returning enabled,
    normalized entries.

    Two shapes:
      - `preprocessing` (pre* points): a SINGLE inline hook — arn/args/onError/
        enabled live directly on the `preprocessing` section (not a list).
      - post-step points: a `<section>.postHook` LIST.
    """
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

    # Pre* points: the section IS the single hook (flattened arn/args/...).
    if point.startswith("pre"):
        h = _normalize_hook(step_block)
        return [h] if h else []

    # Post* points: a list under <section>.postHook.
    raw = step_block.get(_hook_list_field(point)) or []
    if not isinstance(raw, list):
        return []
    valid = [n for n in (_normalize_hook(h) for h in raw) if n]
    valid.sort(key=lambda h: (h["order"], h["featureId"]))
    return valid


def _set_preprocessing_status(document: Any) -> None:
    """Best-effort: flip the doc row's ObjectStatus to PREPROCESSING while a
    preprocessing hook runs, so the UI shows a real step name instead of the
    generic RUNNING (mirrors how OCR/CLASSIFYING/... set per-step statuses).

    Minimal, idp_common-free write (this function deliberately has no layer
    deps). Never fatal — a preprocessing hook must not fail because a status
    cosmetic couldn't be written. The next step (OCR etc.) or the workflow
    tracker overwrites the status, so no reset is needed here."""
    if not _TRACKING_TABLE or not isinstance(document, dict):
        return
    doc_id = document.get("document_id") or document.get("input_key")
    if not doc_id:
        return
    try:
        _dynamodb.Table(_TRACKING_TABLE).update_item(
            Key={"PK": f"doc#{doc_id}", "SK": "none"},
            UpdateExpression="SET #s = :s",
            ConditionExpression="attribute_exists(PK)",
            ExpressionAttributeNames={"#s": "ObjectStatus"},
            ExpressionAttributeValues={":s": "PREPROCESSING"},
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("Could not set PREPROCESSING status for %s: %s", doc_id, exc)


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
    # Every early return carries halt=false so the state machine Choice can
    # rely on $.HookResults.<point>.Payload.halt existing unconditionally.
    if point not in _HOOK_TO_STEP:
        logger.warning("Unknown hookPoint=%s — returning empty result", point)
        return {"hookPoint": point, "invoked": 0, "halt": False, "results": []}
    if not _CONFIG_TABLE:
        logger.info("CONFIGURATION_TABLE_NAME not set — no hooks dispatched")
        return {"hookPoint": point, "invoked": 0, "halt": False, "results": []}

    table = _dynamodb.Table(_CONFIG_TABLE)
    document = event.get("document") or {}
    pinned = document.get("config_version") if isinstance(document, dict) else None
    version = _resolve_active_version(table, pinned)
    if not version:
        logger.info("No config version resolvable; returning no-hooks")
        return {"hookPoint": point, "invoked": 0, "halt": False, "results": []}

    hooks = _read_hooks_from_config(table, version, point)
    if not hooks:
        logger.info("No hooks registered for %s in Config#%s", point, version)
        return {"hookPoint": point, "invoked": 0, "halt": False, "results": []}

    # Surface the preprocessing step in the document's visible status (the
    # generic RUNNING otherwise persists for the whole — possibly long —
    # redaction pass). Only when a hook will actually run.
    if point == "preprocessing":
        _set_preprocessing_status(document)

    results: List[Dict[str, Any]] = []
    for h in hooks:
        # Provide args both as the raw list and a flattened {key: value} map for
        # hook convenience. Values are strings; the hook parses as needed.
        args_list = h.get("args") or []
        args_map = {
            str(a["key"]): a.get("value")
            for a in args_list
            if isinstance(a, dict) and "key" in a
        }
        payload = {
            "hookPoint": point,
            "featureId": h["featureId"],
            "document": event.get("document"),
            "section": event.get("section"),
            "executionArn": event.get("executionArn"),
            "args": args_list,
            "argsMap": args_map,
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

    # Aggregate a top-level `halt` flag so the state machine's post-hook
    # Choice can read a STABLE path ($.HookResults.<point>.Payload.halt)
    # without indexing into a possibly-empty results array (JSONPath can't
    # do that safely). Any successful hook returning result.halt == true
    # halts the workflow. Used by the preprocessing hook to short-circuit a
    # document whose only purpose was to spawn a redacted copy.
    halt = any(
        r.get("ok")
        and isinstance(r.get("result"), dict)
        and r["result"].get("halt") is True
        for r in results
    )
    return {
        "hookPoint": point,
        "configVersion": version,
        "invoked": len(results),
        "halt": halt,
        "results": results,
    }
