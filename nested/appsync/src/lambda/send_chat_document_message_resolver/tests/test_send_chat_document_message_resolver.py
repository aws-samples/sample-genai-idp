# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for send_chat_document_message_resolver.

Exercises the three call paths:

1. **UI path** (``method="chat"``) — records session ownership in DDB,
   async-invokes the processor Lambda, returns a ``QUEUED`` ACK.
2. **Processor passthrough** (``method in {"assistant_*"}``) — returns the
   event directly without invoking anything.
3. **Ownership mismatch** — second user trying to use another user's session
   is rejected.
"""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reload_handler():
    if "index" in sys.modules:
        del sys.modules["index"]
    import os

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if here not in sys.path:
        sys.path.insert(0, here)
    import index  # noqa: F401

    yield
    if "index" in sys.modules:
        del sys.modules["index"]


def _make_event(arguments: dict, sub: str | None = "caller-sub") -> dict:
    identity: dict = {}
    if sub is not None:
        identity = {"sub": sub, "username": "caller", "claims": {"sub": sub}}
    return {"arguments": arguments, "identity": identity}


class TestResolverUIPath:
    @pytest.mark.unit
    def test_first_message_records_ownership_and_invokes_processor(self):
        import index

        # Session does not exist yet — resolver will put_item and claim ownership.
        table = MagicMock()
        table.get_item.return_value = {}
        dyn = MagicMock()
        dyn.Table.return_value = table

        lam = MagicMock()
        lam.invoke.return_value = {"StatusCode": 202}

        with (
            patch.object(index, "_dynamodb", dyn),
            patch.object(index, "_lambda", lam),
        ):
            result = index.handler(
                _make_event(
                    {
                        "sessionId": "s-1",
                        "prompt": "hi",
                        "s3Uri": "uploads/x.pdf",
                        "modelId": "us.anthropic.claude-opus-4-8:1m",
                        "method": "chat",
                    }
                ),
                None,
            )

        # ACK shape
        assert result["sessionId"] == "s-1"
        assert result["method"] == "chat"
        assert result["status"] == "QUEUED"
        assert result["role"] == "user"
        assert result["isProcessing"] is True

        # Claimed ownership
        table.put_item.assert_called_once()
        claim = table.put_item.call_args.kwargs["Item"]
        assert claim["sessionId"] == "s-1"
        assert claim["ownerSub"] == "caller-sub"

        # Async invoke (Event)
        lam.invoke.assert_called_once()
        call_kwargs = lam.invoke.call_args.kwargs
        assert call_kwargs["InvocationType"] == "Event"
        payload = json.loads(call_kwargs["Payload"].decode("utf-8"))
        assert payload["sessionId"] == "s-1"
        assert payload["prompt"] == "hi"
        assert payload["s3Uri"] == "uploads/x.pdf"
        assert payload["callerSub"] == "caller-sub"

    @pytest.mark.unit
    def test_missing_s3uri_raises(self):
        import index

        table = MagicMock()
        table.get_item.return_value = {}
        dyn = MagicMock()
        dyn.Table.return_value = table

        with (
            patch.object(index, "_dynamodb", dyn),
            patch.object(index, "_lambda", MagicMock()),
            pytest.raises(Exception, match="s3Uri is required"),
        ):
            index.handler(
                _make_event({"sessionId": "s-1", "prompt": "hi", "method": "chat"}),
                None,
            )


class TestResolverProcessorPassthrough:
    @pytest.mark.unit
    def test_assistant_stream_passes_through_without_invoking_processor(self):
        import index

        lam = MagicMock()
        dyn = MagicMock()
        with (
            patch.object(index, "_dynamodb", dyn),
            patch.object(index, "_lambda", lam),
        ):
            result = index.handler(
                _make_event(
                    {
                        "sessionId": "s-1",
                        "prompt": "",
                        "method": "assistant_stream",
                        "content": "Hello",
                        "status": "STREAMING",
                        "role": "assistant",
                        "isProcessing": True,
                    },
                    sub="",  # IAM/system call, no Cognito sub
                ),
                None,
            )

        # No invoke, no put_item
        lam.invoke.assert_not_called()

        assert result["method"] == "assistant_stream"
        assert result["content"] == "Hello"
        assert result["status"] == "STREAMING"
        assert result["role"] == "assistant"
        assert result["isProcessing"] is True

    @pytest.mark.unit
    def test_assistant_final_default_is_processing_false(self):
        import index

        # When the processor publishes a terminal event without explicitly
        # passing isProcessing, the resolver should default it to False so the
        # UI knows the bubble is done.
        lam = MagicMock()
        dyn = MagicMock()
        with (
            patch.object(index, "_dynamodb", dyn),
            patch.object(index, "_lambda", lam),
        ):
            result = index.handler(
                _make_event(
                    {
                        "sessionId": "s-1",
                        "prompt": "",
                        "method": "assistant_final",
                        "content": "answer",
                        "status": "COMPLETE",
                    },
                    sub="",
                ),
                None,
            )

        assert result["isProcessing"] is False


class TestResolverOwnership:
    @pytest.mark.unit
    def test_different_user_rejected(self):
        import index

        table = MagicMock()
        table.get_item.return_value = {
            "Item": {"sessionId": "s-1", "ownerSub": "owner-a"}
        }
        dyn = MagicMock()
        dyn.Table.return_value = table

        with (
            patch.object(index, "_dynamodb", dyn),
            patch.object(index, "_lambda", MagicMock()),
            pytest.raises(Exception, match="Unauthorized"),
        ):
            index.handler(
                _make_event(
                    {
                        "sessionId": "s-1",
                        "prompt": "hi",
                        "s3Uri": "uploads/x.pdf",
                        "method": "chat",
                    },
                    sub="attacker",
                ),
                None,
            )
