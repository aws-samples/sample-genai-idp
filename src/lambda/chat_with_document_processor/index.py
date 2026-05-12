# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Long-running Chat-with-Document processor.

Invoked asynchronously by ``send_chat_document_message_resolver``. Does the
heavy lifting that cannot fit inside AppSync's 30-second synchronous resolver
budget:

  1. Looks up the document in the TrackingTable (to get ``ConfigVersion``).
  2. Enforces RBAC ``allowedConfigVersions`` scope for non-admin callers —
     same pattern as ``reprocess_document_resolver`` in the AppSync stack.
  3. Loads the ``chat`` section from the document's config version via
     ``idp_common.config.get_config``.
  4. Fetches the full document text from S3 (cached per-document under
     ``<objectKey>/summary/fulltext.txt``).
  5. Invokes Bedrock via the Converse Stream API and publishes incremental
     token deltas (``assistant_stream``) to the AppSync subscription with
     light throttling (~200 ms / 200-char batches) so the UI can render the
     answer as it's generated.
  6. Publishes status updates (``LOADING_DOCUMENT``, ``CALLING_MODEL``,
     ``STREAMING``) and a final ``assistant_final`` event with the full
     accumulated text.

Errors are caught and published as ``assistant_error`` so the UI can render
them inline instead of leaving the user with a spinning wheel.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

from idp_common.appsync.client import AppSyncClient, AppSyncError
from idp_common.bedrock.client import is_claude_4_7_model
from idp_common.bedrock.model_utils import parse_model_id
from idp_common.config import get_config

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_s3 = boto3.client("s3")
_dynamodb = boto3.resource("dynamodb")
_bedrock_runtime = None  # Lazily created in the target region

# Cached clients
_appsync_client: AppSyncClient | None = None


DEFAULT_SYSTEM_PROMPT = (
    "You are an assistant that answers questions about the attached document "
    "text. If you don't know the answer, say so. Do not invent information. "
    "Use the prior chat history provided as context. Respond in plain text, "
    "not JSON."
)

# Streaming throttle: publish a delta at most every ``STREAM_FLUSH_INTERVAL_S``
# seconds OR once the pending buffer crosses ``STREAM_FLUSH_CHAR_THRESHOLD``
# characters — whichever happens first. Keeps AppSync mutation rate well under
# throttling limits without making the UI feel choppy.
STREAM_FLUSH_INTERVAL_S = 0.2
STREAM_FLUSH_CHAR_THRESHOLD = 200


# AppSync enhanced subscriptions push the full mutation result to subscribers,
# filtered by the subscription's selection set. The mutation response MUST
# select every field that subscribers may request — otherwise fields missing
# from the mutation selection arrive as null at the subscriber. Select the
# full ChatDocumentMessage shape here so the UI receives role/content/etc.
_PUBLISH_MUTATION = """
mutation PublishChatDocumentMessage(
  $sessionId: String!
  $prompt: String!
  $method: String
  $status: String
  $content: String
  $role: String
  $modelId: String
  $isProcessing: Boolean
  $timestamp: String
) {
  sendChatDocumentMessage(
    sessionId: $sessionId
    prompt: $prompt
    method: $method
    status: $status
    content: $content
    role: $role
    modelId: $modelId
    isProcessing: $isProcessing
    timestamp: $timestamp
  ) {
    sessionId
    role
    content
    timestamp
    method
    status
    modelId
    isProcessing
  }
}
"""


def _get_appsync_client() -> AppSyncClient:
    global _appsync_client
    if _appsync_client is None:
        _appsync_client = AppSyncClient()
    return _appsync_client


def _get_bedrock_runtime():
    global _bedrock_runtime
    if _bedrock_runtime is None:
        _bedrock_runtime = boto3.client(
            "bedrock-runtime",
            region_name=os.environ.get("AWS_REGION"),
        )
    return _bedrock_runtime


def _now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _default_model_for_region() -> str:
    region = os.environ.get("AWS_REGION", "us-east-1")
    if region.startswith("eu-"):
        return "eu.anthropic.claude-opus-4-7:1m"
    return "us.anthropic.claude-opus-4-7:1m"


def _publish(
    session_id: str,
    method: str,
    status: str,
    content: str,
    role: str = "assistant",
    model_id: str = "",
    is_processing: bool = True,
) -> None:
    """Publish a progress/delta/final event to the AppSync subscription.

    Failures are logged but not re-raised — we never want a subscription
    publish failure to abort the actual chat work.
    """
    try:
        client = _get_appsync_client()
        # `prompt` is a required schema field but unused for processor-originated
        # publishes; pass an empty string for consistency.
        client.execute_mutation(
            _PUBLISH_MUTATION,
            {
                "sessionId": session_id,
                "prompt": "",
                "method": method,
                "status": status,
                "content": content,
                "role": role,
                "modelId": model_id,
                "isProcessing": is_processing,
                "timestamp": _now_iso(),
            },
        )
    except (AppSyncError, Exception) as e:  # noqa: BLE001
        logger.warning(
            "Failed to publish chat-doc message (method=%s status=%s): %s",
            method,
            status,
            e,
        )


def _s3_object_exists(bucket: str, key: str) -> bool:
    try:
        _s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        raise


def _get_document_record(object_key: str) -> dict:
    tracking_table = _dynamodb.Table(os.environ["TRACKING_TABLE_NAME"])
    resp = tracking_table.get_item(Key={"PK": f"doc#{object_key}", "SK": "none"})
    return resp.get("Item") or {}


def _get_user_allowed_config_versions(caller_sub: str) -> list[str] | None:
    """Fetch caller's ``allowedConfigVersions`` for scope enforcement.

    Returns:
      - ``None`` when the user has no scope restriction (admin or unrestricted)
      - A list of version names the user is allowed to read
    """
    users_table_name = os.environ.get("USERS_TABLE_NAME") or ""
    if not users_table_name or not caller_sub:
        return None
    try:
        table = _dynamodb.Table(users_table_name)
        resp = table.query(
            IndexName="SubIndex",
            KeyConditionExpression=boto3.dynamodb.conditions.Key("sub").eq(caller_sub),
            Limit=1,
        )
        items = resp.get("Items") or []
        if not items:
            return None
        scope = items[0].get("allowedConfigVersions")
        return list(scope) if scope else None
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not fetch user scope (failing open): %s", e)
        return None


def _get_full_text(bucket: str, object_key: str, document: dict) -> str:
    pages = document.get("Pages") or []
    sorted_pages = sorted(pages, key=lambda p: p.get("Id", 0))
    parts: list[str] = []
    for page in sorted_pages:
        text_uri = page.get("TextUri")
        if not text_uri:
            continue
        text_key = text_uri.replace(f"s3://{bucket}/", "")
        try:
            resp = _s3.get_object(Bucket=bucket, Key=text_key)
            parts.append(
                f"<page-number>{page.get('Id')}</page-number>\n"
                + resp["Body"].read().decode("utf-8")
                + "\n"
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to load page %s: %s", page.get("Id"), e)
    return "\n".join(parts)


def _resolve_chat_settings(config_version: str | None):
    """Load ``chat.*`` settings from the document's config version.

    Falls back to ``summarization.*`` for configs created before the chat
    section existed. See ``ChatConfig`` in ``idp_common.config.models`` for
    defaults.
    """
    config_table = os.environ["CONFIGURATION_TABLE_NAME"]
    try:
        config = get_config(
            table_name=config_table,
            as_model=False,
            version=config_version,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "Failed to load config version=%s via idp_common: %s", config_version, e
        )
        config = {}

    chat_cfg = (config or {}).get("chat") or {}
    summ_cfg = (config or {}).get("summarization") or {}

    model_id = (
        chat_cfg.get("model")
        or summ_cfg.get("model")
        or _default_model_for_region()
    )
    system_prompt = (
        chat_cfg.get("system_prompt")
        or summ_cfg.get("system_prompt")
        or DEFAULT_SYSTEM_PROMPT
    )

    def _to_float(v, default: float) -> float:
        try:
            return float(v) if v not in (None, "") else default
        except (TypeError, ValueError):
            return default

    def _to_int(v, default: int) -> int:
        try:
            return int(v) if v not in (None, "") else default
        except (TypeError, ValueError):
            return default

    return {
        "model_id": model_id,
        "system_prompt": system_prompt,
        "temperature": _to_float(chat_cfg.get("temperature"), 0.0),
        "max_tokens": _to_int(chat_cfg.get("max_tokens"), 4096),
    }


def _invoke_bedrock_stream_and_publish(
    session_id: str,
    selected_model_id: str,
    system_prompt: str,
    user_text: str,
    temperature: float,
    max_tokens: int,
) -> str:
    """Stream a Bedrock Converse response, publishing deltas + a final event.

    Mirrors the suffix-handling and parameter-exclusion behavior of
    ``idp_common.bedrock.client.BedrockClient`` — which currently only exposes
    the non-streaming Converse API. Specifically:

      * ``:1m`` suffix  → stripped from modelId, ``anthropic_beta`` opt-in flag
        added to ``additionalModelRequestFields``.
      * ``:priority`` / ``:flex`` suffix → stripped from modelId, passed as the
        Converse ``serviceTier={"type": ...}`` parameter. (Note: this is the
        Bedrock *service tier* parameter, not ``performanceConfig.latency`` —
        those are separate: ``performanceConfig.latency`` only accepts
        ``optimized``/``standard``; ``serviceTier.type`` accepts
        ``priority``/``flex``/``default``.)
      * Claude 4.7+ models → ``temperature`` / ``top_p`` are skipped (Bedrock
        rejects them for these models).

    When idp_common grows a streaming helper, this function should delegate
    to it.

    Returns the full accumulated assistant text.
    """
    client = _get_bedrock_runtime()

    # Claude 4.7+ rejects temperature/top_p; everything else gets temperature.
    inference_config: dict = {"maxTokens": max_tokens}
    if not is_claude_4_7_model(selected_model_id) and temperature is not None:
        inference_config["temperature"] = temperature

    # Start with the user-supplied model ID, then peel off the service-tier
    # suffix first (``:priority`` / ``:flex``) and the ``:1m`` context suffix
    # second. parse_model_id only recognizes tier suffixes at the end of the
    # ID and leaves ``:1m`` alone.
    use_model_id, tier_from_suffix = parse_model_id(selected_model_id)

    additional_model_fields: dict | None = None
    if use_model_id.endswith(":1m"):
        use_model_id = use_model_id[:-3]
        additional_model_fields = {"anthropic_beta": ["context-1m-2025-08-07"]}

    # Normalize service tier for the Converse ``serviceTier`` parameter.
    # Only ``priority`` and ``flex`` are valid to send explicitly; ``standard``
    # is the implicit default and should be omitted. Same normalization as
    # idp_common.bedrock.client.BedrockClient (see lines 703-732 of client.py).
    service_tier_param: dict | None = None
    if tier_from_suffix in ("priority", "flex"):
        service_tier_param = {"type": tier_from_suffix}
        logger.info(
            "Extracted service tier '%s' from model ID; base=%s",
            tier_from_suffix,
            use_model_id,
        )

    messages = [
        {
            "role": "user",
            "content": [{"text": user_text}],
        }
    ]
    system = [{"text": system_prompt}] if system_prompt else None

    logger.info(
        "Calling bedrock:converse_stream model=%s max_tokens=%d tier=%s (raw=%s)",
        use_model_id,
        max_tokens,
        tier_from_suffix or "default",
        selected_model_id,
    )

    kwargs: dict = {
        "modelId": use_model_id,
        "messages": messages,
        "inferenceConfig": inference_config,
    }
    if system:
        kwargs["system"] = system
    if additional_model_fields:
        kwargs["additionalModelRequestFields"] = additional_model_fields
    if service_tier_param:
        kwargs["serviceTier"] = service_tier_param

    response = client.converse_stream(**kwargs)
    stream = response.get("stream")
    if stream is None:
        raise RuntimeError("Bedrock converse_stream returned no stream")

    # Let the UI switch from "Calling model…" to "Streaming response…" as
    # soon as the first delta arrives (not earlier — avoids a "Streaming"
    # pill on errors that fire before any tokens).
    first_delta_seen = False

    buffer: list[str] = []
    buffer_len = 0
    last_flush_ts = time.time()
    full_text_parts: list[str] = []

    def _flush_if_needed(force: bool = False) -> None:
        nonlocal buffer, buffer_len, last_flush_ts
        if not buffer:
            return
        now = time.time()
        should_flush = (
            force
            or buffer_len >= STREAM_FLUSH_CHAR_THRESHOLD
            or (now - last_flush_ts) >= STREAM_FLUSH_INTERVAL_S
        )
        if not should_flush:
            return
        delta = "".join(buffer)
        buffer = []
        buffer_len = 0
        last_flush_ts = now
        _publish(
            session_id=session_id,
            method="assistant_stream",
            status="STREAMING",
            content=delta,
            model_id=selected_model_id,
            is_processing=True,
        )

    try:
        for event in stream:
            if "contentBlockDelta" in event:
                delta = event["contentBlockDelta"].get("delta") or {}
                text = delta.get("text") or ""
                if not text:
                    continue
                if not first_delta_seen:
                    first_delta_seen = True
                    _publish(
                        session_id=session_id,
                        method="assistant_status",
                        status="STREAMING",
                        content="Streaming response…",
                        model_id=selected_model_id,
                    )
                full_text_parts.append(text)
                buffer.append(text)
                buffer_len += len(text)
                _flush_if_needed()
            elif "messageStop" in event:
                # Stream complete — make sure pending buffer is published
                # before the final event.
                _flush_if_needed(force=True)
            elif "internalServerException" in event or "throttlingException" in event:
                err_msg = (
                    event.get("internalServerException", event.get("throttlingException", {}))
                    .get("message", "Bedrock stream error")
                )
                raise RuntimeError(f"Bedrock stream error: {err_msg}")
            # Other event types (messageStart, metadata, etc.) are ignored.
    finally:
        _flush_if_needed(force=True)

    return "".join(full_text_parts)


def _remove_text_between_brackets(text: str) -> str:
    """Strip a leading JSON object that some models wrap error messages in."""
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        return text[:start] + text[end + 1 :]
    return text


def handler(event, _context):  # noqa: ANN001
    """Process one Chat-with-Document turn end-to-end.

    Expected event payload (from ``send_chat_document_message_resolver``)::

        {
          "sessionId": "...",
          "turnId":    "...",
          "prompt":    "...",
          "s3Uri":     "uploads/doc.pdf",
          "modelId":   "us.anthropic.claude-opus-4-7:1m" | "",
          "callerSub": "<cognito sub>"
        }
    """
    logger.info("chat-doc processor invoked: session=%s", event.get("sessionId"))

    session_id = event.get("sessionId") or ""
    turn_id = event.get("turnId") or ""
    prompt = event.get("prompt") or ""
    object_key = event.get("s3Uri") or ""
    ui_model_id = (event.get("modelId") or "").strip()
    caller_sub = event.get("callerSub") or ""

    if not (session_id and prompt and object_key):
        logger.error("Missing required fields in chat-doc event: %s", event)
        _publish(
            session_id=session_id or "unknown",
            method="assistant_error",
            status="ERROR",
            content="Internal error: missing required fields.",
            is_processing=False,
        )
        return {"ok": False, "reason": "invalid_event"}

    try:
        # --- 1. Look up the document record ---------------------------------
        _publish(
            session_id=session_id,
            method="assistant_status",
            status="LOADING_DOCUMENT",
            content="Loading document…",
        )
        document = _get_document_record(object_key)
        if not document:
            raise Exception(f"Document '{object_key}' not found")

        config_version = (
            document.get("ConfigVersion")
            or document.get("ConfigurationVersion")
            or None
        )

        # --- 2. RBAC scope enforcement --------------------------------------
        allowed_versions = _get_user_allowed_config_versions(caller_sub)
        if (
            allowed_versions is not None
            and config_version
            and config_version not in allowed_versions
        ):
            logger.warning(
                "Scope denied: caller_sub=%s allowed=%s doc_version=%s",
                caller_sub,
                allowed_versions,
                config_version,
            )
            _publish(
                session_id=session_id,
                method="assistant_error",
                status="ERROR",
                content=(
                    "You do not have access to this document's configuration "
                    "version."
                ),
                is_processing=False,
            )
            return {"ok": False, "reason": "scope_denied"}

        # --- 3. Resolve chat settings ---------------------------------------
        chat_settings = _resolve_chat_settings(config_version)
        selected_model_id = ui_model_id or chat_settings["model_id"]

        # --- 4. Assemble or load cached full text ---------------------------
        output_bucket = os.environ["OUTPUT_BUCKET"]
        fulltext_key = object_key + "/summary/fulltext.txt"
        if not _s3_object_exists(output_bucket, fulltext_key):
            page_count = len(document.get("Pages") or [])
            _publish(
                session_id=session_id,
                method="assistant_status",
                status="LOADING_DOCUMENT",
                content=f"Loading document text ({page_count} pages)…",
            )
            content_str = _get_full_text(output_bucket, object_key, document)
            _s3.put_object(
                Bucket=output_bucket,
                Key=fulltext_key,
                Body=content_str.encode("utf-8"),
            )
        else:
            resp = _s3.get_object(Bucket=output_bucket, Key=fulltext_key)
            content_str = resp["Body"].read().decode("utf-8")

        # --- 5. Invoke Bedrock (streaming) ---------------------------------
        _publish(
            session_id=session_id,
            method="assistant_status",
            status="CALLING_MODEL",
            content=f"Querying {selected_model_id}…",
            model_id=selected_model_id,
        )

        user_text = content_str + "\n\n" + "The user's question is: " + prompt
        t_start = time.time()
        full_text = _invoke_bedrock_stream_and_publish(
            session_id=session_id,
            selected_model_id=selected_model_id,
            system_prompt=chat_settings["system_prompt"],
            user_text=user_text,
            temperature=chat_settings["temperature"],
            max_tokens=chat_settings["max_tokens"],
        )
        elapsed_s = time.time() - t_start
        cleaned = _remove_text_between_brackets(full_text).strip("\n")
        logger.info(
            "Bedrock streamed %.1fs (model=%s, chars=%d)",
            elapsed_s,
            selected_model_id,
            len(cleaned),
        )

        # --- 6. Publish final answer ---------------------------------------
        _publish(
            session_id=session_id,
            method="assistant_final",
            status="COMPLETE",
            content=cleaned,
            model_id=selected_model_id,
            is_processing=False,
        )
        return {"ok": True, "turnId": turn_id}

    except Exception as e:  # noqa: BLE001
        logger.exception("chat-doc processor failed: %s", e)
        _publish(
            session_id=session_id,
            method="assistant_error",
            status="ERROR",
            content=str(e),
            is_processing=False,
        )
        return {"ok": False, "error": str(e)}
