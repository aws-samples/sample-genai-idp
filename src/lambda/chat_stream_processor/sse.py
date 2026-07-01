# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Dependency-free helpers for the chat streaming endpoint.

Kept separate from ``app.py`` (which imports FastAPI and the processor modules)
so the pure logic — SSE framing and Cognito-sub extraction — can be unit-tested
without those heavier runtime dependencies.
"""

from __future__ import annotations

import json
from datetime import datetime


def now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def sse(payload: dict) -> str:
    """Encode one event as a Server-Sent-Events frame: ``data: {json}\\n\\n``."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def caller_sub_from_request_context(raw_request_context: str | None) -> str:
    """Extract the Cognito ``sub`` from a Function URL request context header.

    Lambda Function URLs with ``AuthType=AWS_IAM`` forward the SigV4 caller
    identity. With the Lambda Web Adapter the original Lambda event's
    ``requestContext`` is available on the ``x-amzn-request-context`` header. For
    Cognito Identity Pool credentials the assumed-role ARN's session name holds
    the caller's identity (``...:assumed-role/<role>/<session-name>``).

    Returns an empty string when the context is missing or unparseable.
    """
    if not raw_request_context:
        return ""
    try:
        ctx = json.loads(raw_request_context)
    except (TypeError, ValueError):
        return ""
    identity = (ctx.get("authorizer") or {}).get("iam") or {}
    user_arn = identity.get("userArn") or ""
    if ":assumed-role/" in user_arn:
        # arn:aws:sts::acct:assumed-role/<role>/<session-name>
        return user_arn.rsplit("/", 1)[-1]
    return identity.get("userId") or ""
