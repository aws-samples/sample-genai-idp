# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Unit tests for the chat_with_document_processor Lambda.

Covers the three critical behaviors of the processor:

1. **Happy path (streaming)** — Bedrock ``converse_stream`` yields several
   deltas; the processor publishes status → stream × N → final events in
   order, with the final text equal to the concatenation of deltas.
2. **RBAC scope denial** — when the caller's ``allowedConfigVersions`` does
   not include the document's ``ConfigVersion``, the processor publishes a
   single ``assistant_error`` and does not call Bedrock.
3. **Missing fields** — incomplete events return early with ``assistant_error``.
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reload_handler():
    """Ensure each test imports a fresh module so patches stick."""
    if "index" in sys.modules:
        del sys.modules["index"]
    # Adjust sys.path so `import index` works whether pytest is invoked
    # from the repo root or from the Lambda directory.
    import os

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if here not in sys.path:
        sys.path.insert(0, here)
    import index  # noqa: F401

    yield
    if "index" in sys.modules:
        del sys.modules["index"]


def _make_stream_events(deltas: list[str]) -> list[dict]:
    events: list[dict] = [{"messageStart": {"role": "assistant"}}]
    for chunk in deltas:
        events.append({"contentBlockDelta": {"delta": {"text": chunk}}})
    events.append({"contentBlockStop": {}})
    events.append({"messageStop": {"stopReason": "end_turn"}})
    return events


class TestProcessorHappyPath:
    @pytest.mark.unit
    def test_streams_deltas_and_publishes_final(self):
        import index

        tracking_table = MagicMock()
        tracking_table.get_item.return_value = {
            "Item": {
                "PK": "doc#uploads/x.pdf",
                "SK": "none",
                "ConfigVersion": "default",
                "Pages": [
                    {"Id": 1, "TextUri": "s3://output-bucket/uploads/x.pdf/pages/1.txt"},
                ],
            }
        }
        dyn_resource = MagicMock()
        dyn_resource.Table.return_value = tracking_table

        # Pretend the cached fulltext already exists so we don't need to
        # exercise the page-assembly branch.
        s3 = MagicMock()
        s3.head_object.return_value = {}
        s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"FULL DOC TEXT")),
        }

        # Bedrock mock: return a streaming response with several deltas.
        bedrock = MagicMock()
        bedrock.converse_stream.return_value = {
            "stream": iter(_make_stream_events(["Hello, ", "world", "!"]))
        }

        # Capture every publish call so we can assert ordering.
        publishes: list[dict] = []
        fake_client = MagicMock()

        def _exec(_mutation, variables):
            publishes.append(dict(variables))

        fake_client.execute_mutation.side_effect = _exec

        with (
            patch.object(index, "_s3", s3),
            patch.object(index, "_dynamodb", dyn_resource),
            patch.object(index, "_get_bedrock_runtime", return_value=bedrock),
            patch.object(index, "_get_appsync_client", return_value=fake_client),
            patch.object(
                index, "_resolve_chat_settings",
                return_value={
                    "model_id": "us.anthropic.claude-opus-4-7:1m",
                    "system_prompt": "sys",
                    "temperature": 0.0,
                    "max_tokens": 128,
                },
            ),
            # Bypass streaming throttling so every delta triggers a publish.
            patch.object(index, "STREAM_FLUSH_INTERVAL_S", 0.0),
            patch.object(index, "STREAM_FLUSH_CHAR_THRESHOLD", 1),
        ):
            result = index.handler(
                {
                    "sessionId": "s-1",
                    "turnId": "t-1",
                    "prompt": "what is this?",
                    "s3Uri": "uploads/x.pdf",
                    "modelId": "",
                    "callerSub": "caller-sub",
                },
                None,
            )

        assert result == {"ok": True, "turnId": "t-1"}

        methods = [p.get("method") for p in publishes]
        # We expect: LOADING status, CALLING status, STREAMING status (on first
        # delta), one or more assistant_stream deltas, then assistant_final.
        assert methods[0] == "assistant_status"
        assert publishes[0]["status"] == "LOADING_DOCUMENT"
        assert "assistant_status" in methods
        assert methods.count("assistant_stream") >= 1
        assert methods[-1] == "assistant_final"

        # Final text should be the concatenation of streamed deltas.
        final = publishes[-1]
        assert final["status"] == "COMPLETE"
        assert final["content"] == "Hello, world!"
        assert final["isProcessing"] is False


class TestProcessorRBAC:
    @pytest.mark.unit
    def test_scope_denied_does_not_call_bedrock(self):
        import index

        tracking_table = MagicMock()
        tracking_table.get_item.return_value = {
            "Item": {
                "PK": "doc#uploads/restricted.pdf",
                "SK": "none",
                "ConfigVersion": "secret-v1",
                "Pages": [],
            }
        }
        dyn_resource = MagicMock()
        dyn_resource.Table.return_value = tracking_table

        bedrock = MagicMock()
        publishes: list[dict] = []
        fake_client = MagicMock()
        fake_client.execute_mutation.side_effect = (
            lambda _m, v: publishes.append(dict(v))
        )

        with (
            patch.object(index, "_dynamodb", dyn_resource),
            patch.object(index, "_get_bedrock_runtime", return_value=bedrock),
            patch.object(index, "_get_appsync_client", return_value=fake_client),
            patch.object(
                index, "_get_user_allowed_config_versions", return_value=["other-v2"]
            ),
        ):
            result = index.handler(
                {
                    "sessionId": "s-1",
                    "turnId": "t-1",
                    "prompt": "leak the doc",
                    "s3Uri": "uploads/restricted.pdf",
                    "modelId": "",
                    "callerSub": "caller-sub",
                },
                None,
            )

        assert result == {"ok": False, "reason": "scope_denied"}
        bedrock.converse_stream.assert_not_called()
        methods = [p.get("method") for p in publishes]
        assert "assistant_error" in methods
        err = [p for p in publishes if p.get("method") == "assistant_error"][0]
        assert err["status"] == "ERROR"
        assert "configuration" in err["content"].lower()


class TestProcessorValidation:
    @pytest.mark.unit
    def test_missing_prompt_publishes_error(self):
        import index

        publishes: list[dict] = []
        fake_client = MagicMock()
        fake_client.execute_mutation.side_effect = (
            lambda _m, v: publishes.append(dict(v))
        )

        with patch.object(index, "_get_appsync_client", return_value=fake_client):
            result = index.handler(
                {
                    "sessionId": "s-1",
                    "turnId": "t-1",
                    "prompt": "",  # missing
                    "s3Uri": "uploads/x.pdf",
                },
                None,
            )

        assert result == {"ok": False, "reason": "invalid_event"}
        assert publishes and publishes[0]["method"] == "assistant_error"


class TestProcessorModelIdSuffixes:
    """Verify the processor's model-ID-suffix handling for Bedrock Converse:

      * ``:1m``        → strip suffix, add ``additionalModelRequestFields.anthropic_beta``
      * ``:priority``  → strip suffix, pass ``performanceConfig={"latency": "priority"}``
      * ``:flex``      → strip suffix, pass ``performanceConfig={"latency": "flex"}``
      * Any combination of the above

    These must match idp_common.bedrock.client.BedrockClient behavior so the
    Chat-with-Document feature supports the same model ID forms used
    elsewhere in the pipeline.
    """

    def _invoke_with_model(self, model_id: str) -> dict:
        """Run the processor end-to-end with the given model ID and return the
        kwargs that Bedrock ``converse_stream`` was called with.
        """
        import index

        tracking_table = MagicMock()
        tracking_table.get_item.return_value = {
            "Item": {
                "PK": f"doc#uploads/x.pdf",
                "SK": "none",
                "ConfigVersion": "default",
                "Pages": [
                    {"Id": 1, "TextUri": "s3://output-bucket/uploads/x.pdf/pages/1.txt"},
                ],
            }
        }
        dyn_resource = MagicMock()
        dyn_resource.Table.return_value = tracking_table

        s3 = MagicMock()
        s3.head_object.return_value = {}
        s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"DOC")),
        }

        bedrock = MagicMock()
        bedrock.converse_stream.return_value = {
            "stream": iter(_make_stream_events(["ok"]))
        }

        fake_client = MagicMock()

        with (
            patch.object(index, "_s3", s3),
            patch.object(index, "_dynamodb", dyn_resource),
            patch.object(index, "_get_bedrock_runtime", return_value=bedrock),
            patch.object(index, "_get_appsync_client", return_value=fake_client),
            patch.object(
                index, "_resolve_chat_settings",
                return_value={
                    "model_id": model_id,
                    "system_prompt": "sys",
                    "temperature": 0.0,
                    "max_tokens": 128,
                },
            ),
            patch.object(index, "STREAM_FLUSH_INTERVAL_S", 0.0),
            patch.object(index, "STREAM_FLUSH_CHAR_THRESHOLD", 1),
        ):
            result = index.handler(
                {
                    "sessionId": "s-tier",
                    "turnId": "t-tier",
                    "prompt": "q?",
                    "s3Uri": "uploads/x.pdf",
                    "modelId": "",
                    "callerSub": "caller",
                },
                None,
            )

        assert result["ok"] is True, f"processor failed: {result}"
        assert bedrock.converse_stream.call_count == 1
        return bedrock.converse_stream.call_args.kwargs

    @pytest.mark.unit
    def test_1m_suffix_stripped_and_anthropic_beta_passed(self):
        kwargs = self._invoke_with_model("us.anthropic.claude-opus-4-7:1m")
        # Suffix stripped from modelId
        assert kwargs["modelId"] == "us.anthropic.claude-opus-4-7"
        # Beta flag sent via additionalModelRequestFields
        assert kwargs.get("additionalModelRequestFields") == {
            "anthropic_beta": ["context-1m-2025-08-07"]
        }
        # Claude 4.7 → temperature omitted
        assert "temperature" not in kwargs["inferenceConfig"]
        # No service tier for :1m alone
        assert "serviceTier" not in kwargs
        assert "performanceConfig" not in kwargs

    @pytest.mark.unit
    def test_priority_suffix_stripped_and_service_tier_passed(self):
        kwargs = self._invoke_with_model("global.amazon.nova-2-lite-v1:0:priority")
        # Suffix stripped from modelId
        assert kwargs["modelId"] == "global.amazon.nova-2-lite-v1:0"
        # serviceTier populated (NOT performanceConfig — those are separate
        # Bedrock params; see the processor's _invoke_bedrock_stream_and_publish
        # docstring).
        assert kwargs.get("serviceTier") == {"type": "priority"}
        assert "performanceConfig" not in kwargs
        # Non-Claude-4.7 model → temperature preserved
        assert kwargs["inferenceConfig"].get("temperature") == 0.0
        # No 1M beta flag
        assert "additionalModelRequestFields" not in kwargs

    @pytest.mark.unit
    def test_flex_suffix_stripped_and_service_tier_passed(self):
        kwargs = self._invoke_with_model("eu.amazon.nova-2-lite-v1:0:flex")
        assert kwargs["modelId"] == "eu.amazon.nova-2-lite-v1:0"
        assert kwargs.get("serviceTier") == {"type": "flex"}
        assert "performanceConfig" not in kwargs

    @pytest.mark.unit
    def test_plain_model_id_no_extra_fields(self):
        kwargs = self._invoke_with_model("us.amazon.nova-lite-v1:0")
        assert kwargs["modelId"] == "us.amazon.nova-lite-v1:0"
        assert "serviceTier" not in kwargs
        assert "performanceConfig" not in kwargs
        assert "additionalModelRequestFields" not in kwargs
