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

It ALSO always includes a top-level `document` — the document the next
workflow step should consume. A hook that wants to change the document for
downstream steps returns `{"updatedDocument": <doc>}`; the dispatcher
validates it, threads it into the next hook at the same point, and returns it
here. Hooks that return anything else (the historical, read-only contract) get
their input document echoed back verbatim, so the pipeline is byte-identical
to the pre-mutation behavior. The state machine copies this value into the
canonical path the next step reads via a small `Apply<Point>HookDocument`
Pass state (see statemachine/workflow.asl.json).

Resolution rules:
  1. If the SFN input has `document.config_version`, use it.
  2. Else, scan the table for the row with IsActive=true.
  3. Else, fall back to `Config#default`.

Returns immediately when the requested step has no `postHook` entries,
keeping the no-vertical-pack overhead at one DDB GetItem.
"""

from __future__ import annotations

import base64
import copy
import gzip
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import boto3

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_CONFIG_TABLE = os.environ.get("CONFIGURATION_TABLE_NAME", "")
_TRACKING_TABLE = os.environ.get("TRACKING_TABLE", "")
# Needed only to spill a hook-returned INLINE document dict to S3 in the same
# compressed-wrapper shape the step Lambdas use. Hooks that write the document
# themselves and return a compressed reference need nothing here.
_WORKING_BUCKET = os.environ.get("WORKING_BUCKET", "")

# The key a hook sets to hand a modified document to the next workflow step.
# Deliberately NOT "document": no existing hook returns `updatedDocument`, so a
# read-only hook that happens to echo its input under "document" cannot
# accidentally start mutating the pipeline.
_UPDATED_DOC_KEY = "updatedDocument"

# Identity fields a hook may never change. Rewriting these mid-pipeline would
# corrupt the tracking-table row and the output S3 prefixes (both keyed off the
# document id / input key). A hook that needs a DIFFERENT document should spawn
# one and `halt` (the pattern the PII preprocessing hook uses) rather than
# swapping identity underneath the running execution.
_IMMUTABLE_DOC_FIELDS = (
    "id",
    "document_id",
    "input_bucket",
    "input_key",
    "output_bucket",
)

# Ceiling on an inline document dict returned by a hook, before compression.
# Lambda's own 6MB synchronous response limit is the real gate; this bounds the
# JSON we will re-serialize and PutObject.
_MAX_INLINE_DOC_BYTES = 5 * 1024 * 1024

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
_s3 = boto3.client("s3")


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
        # Admin kill-switch for document mutation on a per-hook basis. Defaults
        # to True (a registered hook is already admin-approved and IAM-gated,
        # and can already rewrite the S3 objects the document points at), but an
        # admin can pin a specific hook to observe-only.
        "allowDocumentUpdate": h.get("allowDocumentUpdate") is not False,
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


def _doc_identity(doc: Any) -> Dict[str, Any]:
    """The immutable identity fields present on a document payload.

    Works on both shapes the workflow passes around: a full document dict
    (`id`/`input_key`/…) and a compressed wrapper (`document_id`/`s3_uri`/…).
    Only fields actually present are returned, so a compressed wrapper (which
    carries `document_id` but not `input_key`) is compared on what it has.
    """
    if not isinstance(doc, dict):
        return {}
    return {f: doc[f] for f in _IMMUTABLE_DOC_FIELDS if f in doc}


def _identity_matches(previous: Any, candidate: Any) -> Optional[str]:
    """None if `candidate` keeps `previous`'s identity, else a reason string.

    A compressed wrapper's `document_id` and a full dict's `id` are the same
    logical value, so they are compared against each other as well — this
    catches a hook that decompresses, changes `id`, and returns an inline dict.
    """
    prev_id = _doc_identity(previous)
    cand_id = _doc_identity(candidate)
    prev_logical = prev_id.get("id") or prev_id.get("document_id")
    cand_logical = cand_id.get("id") or cand_id.get("document_id")
    if prev_logical is not None and cand_logical is not None:
        if str(prev_logical) != str(cand_logical):
            return (
                f"document identity changed: {prev_logical!r} -> {cand_logical!r}"
            )
    for f in _IMMUTABLE_DOC_FIELDS:
        if f in prev_id and f in cand_id and prev_id[f] != cand_id[f]:
            return f"immutable field {f!r} changed: {prev_id[f]!r} -> {cand_id[f]!r}"
    return None


def _validate_compressed_ref(ref: Dict[str, Any]) -> Optional[str]:
    """None if `ref` is a usable compressed-document wrapper, else a reason.

    `sections` must be a list of STRING section ids: the workflow's
    ProcessSections Map iterates that list directly (ItemsPath
    $.ClassificationResult.document.sections), so a malformed value would fail
    the whole execution rather than just the hook.
    """
    s3_uri = ref.get("s3_uri")
    if not isinstance(s3_uri, str) or not s3_uri.startswith("s3://"):
        return f"compressed document reference has invalid s3_uri: {s3_uri!r}"
    sections = ref.get("sections")
    if sections is not None:
        if not isinstance(sections, list) or not all(
            isinstance(s, str) for s in sections
        ):
            return (
                "compressed document reference `sections` must be a list of "
                f"section-id strings, got {type(sections).__name__}"
            )
    return None


def _compress_inline_document(
    doc: Dict[str, Any], point: str, feature_id: str
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Spill a hook-returned INLINE document dict to the working bucket.

    Returns (compressed_wrapper, None) on success or (None, reason) on failure.
    Mirrors idp_common.models.Document.compress() so the wrapper is
    indistinguishable from one a step Lambda produced — the dispatcher stays
    deliberately free of the idp_common layer (see module docstring), so the
    ~15 lines are inlined rather than imported.
    """
    if not _WORKING_BUCKET:
        return None, "WORKING_BUCKET is not configured; cannot store inline document"
    doc_id = doc.get("id") or doc.get("input_key")
    if not doc_id:
        return None, "inline document has no id/input_key"
    try:
        body = json.dumps(doc, default=str).encode("utf-8")
    except Exception as exc:  # noqa: BLE001
        return None, f"inline document is not JSON-serializable: {exc}"
    if len(body) > _MAX_INLINE_DOC_BYTES:
        return None, (
            f"inline document is {len(body)} bytes, over the "
            f"{_MAX_INLINE_DOC_BYTES}-byte limit; return a compressed reference "
            "instead"
        )

    timestamp = str(int(time.time() * 1000))
    key = (
        f"compressed_documents/{doc_id}/{timestamp}_hook_{point}_"
        f"{feature_id}_state.json"
    )
    try:
        _s3.put_object(
            Bucket=_WORKING_BUCKET,
            Key=key,
            Body=body,
            ContentType="application/json",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to store hook document for %s", doc_id)
        return None, f"could not store inline document in working bucket: {exc}"

    # Section ids only — the Map state iterates this list.
    sections = [
        s.get("section_id")
        for s in (doc.get("sections") or [])
        if isinstance(s, dict) and s.get("section_id") is not None
    ]
    status = doc.get("status")
    return {
        "document_id": doc_id,
        "s3_uri": f"s3://{_WORKING_BUCKET}/{key}",
        "timestamp": timestamp,
        "status": status if isinstance(status, str) else str(status or ""),
        "num_pages": doc.get("num_pages", 0),
        "sections": [str(s) for s in sections],
        "config_version": doc.get("config_version"),
        "compressed": True,
    }, None


def _resolve_updated_document(
    result: Dict[str, Any],
    previous: Any,
    hook: Dict[str, Any],
    point: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Extract + validate a hook's `updatedDocument`, if it returned one.

    Returns (document_to_use, None) when the hook handed back a valid document,
    (None, None) when it returned no document at all (the read-only contract —
    by far the common case), or (None, reason) when it returned one the
    dispatcher refuses. On refusal the CALLER keeps the previous document, so a
    malformed hook response degrades to the historical passive behavior instead
    of corrupting the pipeline.
    """
    payload = result.get("result")
    if not isinstance(payload, dict) or _UPDATED_DOC_KEY not in payload:
        return None, None
    if not hook.get("allowDocumentUpdate", True):
        return None, (
            "hook returned updatedDocument but allowDocumentUpdate=false for "
            f"{hook['featureId']}"
        )

    candidate = payload.get(_UPDATED_DOC_KEY)
    if not isinstance(candidate, dict) or not candidate:
        return None, (
            f"updatedDocument must be a non-empty object, got "
            f"{type(candidate).__name__}"
        )

    reason = _identity_matches(previous, candidate)
    if reason:
        return None, reason

    prev_version = (
        previous.get("config_version") if isinstance(previous, dict) else None
    )
    if candidate.get("compressed") is True:
        reason = _validate_compressed_ref(candidate)
        if reason:
            return None, reason
        resolved = copy.deepcopy(candidate)
    else:
        resolved, reason = _compress_inline_document(
            candidate, point, hook["featureId"]
        )
        if reason or resolved is None:
            return None, reason or "could not process inline document"

    # config_version drives hook resolution for the REST of the pipeline (this
    # dispatcher reads it on every invoke), so a hook must not silently drop or
    # repoint it. Restore the inbound value rather than rejecting the whole
    # update — the hook's real intent is the document content.
    if prev_version is not None and resolved.get("config_version") != prev_version:
        logger.warning(
            "Hook %s changed config_version (%r -> %r); restoring the inbound "
            "value",
            hook["featureId"],
            prev_version,
            resolved.get("config_version"),
        )
        resolved["config_version"] = prev_version
    return resolved, None


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


def _noop(point: Any, document: Any) -> Dict[str, Any]:
    """An empty dispatch result.

    Carries halt=False AND the inbound document unchanged, so both state-machine
    reads — $.HookResults.<point>.Payload.halt (the Choice) and
    ...Payload.document (the Apply Pass state) — resolve unconditionally, even
    when no hook is registered or the point is unknown.
    """
    return {
        "hookPoint": point,
        "invoked": 0,
        "halt": False,
        "document": document,
        "results": [],
    }


def lambda_handler(event: Dict[str, Any], _ctx: Any) -> Dict[str, Any]:
    point = event.get("hookPoint")
    inbound_document = event.get("document")
    if point not in _HOOK_TO_STEP:
        logger.warning("Unknown hookPoint=%s — returning empty result", point)
        return _noop(point, inbound_document)
    if not _CONFIG_TABLE:
        logger.info("CONFIGURATION_TABLE_NAME not set — no hooks dispatched")
        return _noop(point, inbound_document)

    table = _dynamodb.Table(_CONFIG_TABLE)
    document = inbound_document or {}
    pinned = document.get("config_version") if isinstance(document, dict) else None
    version = _resolve_active_version(table, pinned)
    if not version:
        logger.info("No config version resolvable; returning no-hooks")
        return _noop(point, inbound_document)

    hooks = _read_hooks_from_config(table, version, point)
    if not hooks:
        logger.info("No hooks registered for %s in Config#%s", point, version)
        return _noop(point, inbound_document)

    # Surface the preprocessing step in the document's visible status (the
    # generic RUNNING otherwise persists for the whole — possibly long —
    # redaction pass). Only when a hook will actually run.
    if point == "preprocessing":
        _set_preprocessing_status(document)

    results: List[Dict[str, Any]] = []
    # The document threaded through the chain. Each hook sees the OUTPUT of the
    # previous hook at this point (not the original), so hooks compose; and this
    # is what the dispatcher hands back for the next workflow step.
    current_document: Any = inbound_document
    updated_by: List[str] = []
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
            "document": current_document,
            "section": event.get("section"),
            "executionArn": event.get("executionArn"),
            "args": args_list,
            "argsMap": args_map,
        }
        r = _invoke_hook(h, payload)
        results.append(r)

        if r["ok"]:
            updated, reason = _resolve_updated_document(
                r, current_document, h, str(point)
            )
            if updated is not None:
                logger.info(
                    "Hook %s returned an updated document for %s", h["featureId"], point
                )
                current_document = updated
                updated_by.append(h["featureId"])
                # Record WHAT the workflow will consume, not the (possibly
                # multi-MB) inline dict the hook returned, keeping the SFN
                # execution history readable.
                r["result"] = {
                    k: v for k, v in r["result"].items() if k != _UPDATED_DOC_KEY
                }
                r["documentUpdated"] = True
            elif reason:
                # Refused: keep the previous document (degrade to passive) and
                # surface why in the execution history.
                logger.warning(
                    "Rejected document update from hook %s at %s: %s",
                    h["featureId"],
                    point,
                    reason,
                )
                r["documentUpdateRejected"] = reason

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
        # Always present. Equals the inbound document unless a hook returned a
        # validated `updatedDocument`. The state machine's Apply<Point>Hook-
        # Document Pass state copies this into the path the next step reads.
        "document": current_document,
        "documentUpdatedBy": updated_by,
        "results": results,
    }
