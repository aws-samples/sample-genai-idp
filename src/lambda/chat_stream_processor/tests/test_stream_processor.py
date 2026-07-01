# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for the chat streaming endpoint helpers and sink wiring.

These cover the parts that are independent of FastAPI/Bedrock:

1. ``sse`` emits a well-formed SSE frame (``data: {json}\\n\\n``) that round-trips.
2. ``caller_sub_from_request_context`` extracts the Cognito sub from the
   Function URL request context.
3. The doc-chat processor's ``set_sink`` redirects emission away from AppSync
   (skipped when ``idp_common`` is not importable in the test environment).
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


@pytest.mark.unit
def test_sse_frame_roundtrips():
    from sse import sse

    frame = sse({"method": "assistant_stream", "content": "hi"})
    assert frame.endswith("\n\n")
    assert frame.startswith("data: ")
    decoded = json.loads(frame[len("data: ") : -2])
    assert decoded["method"] == "assistant_stream"
    assert decoded["content"] == "hi"


@pytest.mark.unit
def test_sse_frame_has_single_blank_line_separator():
    """A frame must contain exactly one terminating blank line so the UI's
    split-on-`\\n\\n` framing yields one event per frame."""
    from sse import sse

    frame = sse({"content": "line1\nline2"})
    # Embedded newlines in the JSON value are preserved (json escapes them),
    # so the only literal "\n\n" is the frame terminator.
    assert frame.count("\n\n") == 1


@pytest.mark.unit
def test_caller_sub_from_assumed_role_arn():
    from sse import caller_sub_from_request_context

    ctx = {
        "authorizer": {
            "iam": {
                "userArn": (
                    "arn:aws:sts::123456789012:assumed-role/"
                    "MyAuthRole/the-cognito-sub"
                ),
            }
        }
    }
    assert caller_sub_from_request_context(json.dumps(ctx)) == "the-cognito-sub"


@pytest.mark.unit
def test_caller_sub_missing_or_bad_context_is_empty():
    from sse import caller_sub_from_request_context

    assert caller_sub_from_request_context(None) == ""
    assert caller_sub_from_request_context("") == ""
    assert caller_sub_from_request_context("not-json") == ""


@pytest.mark.unit
@pytest.mark.skipif(
    importlib.util.find_spec("idp_common") is None,
    reason="idp_common not installed in this test environment",
)
def test_doc_processor_set_sink_redirects_emission():
    """Installing a sink must redirect _emit away from the AppSync _publish."""
    doc_dir = os.path.join(os.path.dirname(_HERE), "chat_with_document_processor")
    if doc_dir not in sys.path:
        sys.path.insert(0, doc_dir)
    if "index" in sys.modules:
        del sys.modules["index"]
    import index as doc_proc

    captured = []

    def _sink(**kwargs):
        captured.append(kwargs)

    doc_proc.set_sink(_sink)
    try:
        doc_proc._emit(
            session_id="s1",
            method="assistant_stream",
            status="STREAMING",
            content="delta",
            model_id="m",
            is_processing=True,
        )
    finally:
        doc_proc.set_sink(None)

    assert len(captured) == 1
    assert captured[0]["method"] == "assistant_stream"
    assert captured[0]["content"] == "delta"
    assert doc_proc._active_sink is None
    del sys.modules["index"]
