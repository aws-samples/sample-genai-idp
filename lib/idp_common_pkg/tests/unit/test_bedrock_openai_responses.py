# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for the OpenAI Responses (bedrock-mantle) backend."""

import json
from unittest.mock import MagicMock, patch

import pytest

from idp_common.bedrock import openai_responses as oar
from idp_common.bedrock.client import BedrockClient


def _make_http_response(status_code, payload):
    """Build a fake botocore HTTP response object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = json.dumps(payload) if isinstance(payload, dict) else payload
    return resp


_SAMPLE_RESPONSE = {
    "status": "completed",
    "output": [
        {"type": "reasoning", "content": []},
        {
            "type": "message",
            "content": [
                {"type": "output_text", "text": "Hello "},
                {"type": "output_text", "text": "world"},
            ],
        },
    ],
    "usage": {
        "input_tokens": 100,
        "output_tokens": 40,
        "total_tokens": 140,
        "input_tokens_details": {"cached_tokens": 25},
        "output_tokens_details": {"reasoning_tokens": 12},
    },
}


@pytest.mark.unit
class TestModelDetection:
    def test_detects_gpt_5_4(self):
        assert oar.is_openai_responses_model("openai.gpt-5.4") is True

    def test_detects_gpt_5_5(self):
        assert oar.is_openai_responses_model("openai.gpt-5.5") is True

    def test_detects_future_gpt_5_variant(self):
        assert oar.is_openai_responses_model("openai.gpt-5.6") is True

    def test_detects_gpt_5_6_sol(self):
        assert oar.is_openai_responses_model("openai.gpt-5.6-sol") is True

    def test_detects_gpt_5_6_terra(self):
        assert oar.is_openai_responses_model("openai.gpt-5.6-terra") is True

    def test_detects_gpt_5_6_luna(self):
        assert oar.is_openai_responses_model("openai.gpt-5.6-luna") is True

    def test_rejects_claude(self):
        assert oar.is_openai_responses_model("us.anthropic.claude-opus-4-8") is False

    def test_rejects_nova(self):
        assert oar.is_openai_responses_model("us.amazon.nova-pro-v1:0") is False

    def test_rejects_none(self):
        assert oar.is_openai_responses_model(None) is False


@pytest.mark.unit
class TestRegionResolution:
    def test_env_var_wins(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_MANTLE_REGION", "us-west-2")
        assert oar.resolve_mantle_region("openai.gpt-5.5", "us-east-1") == "us-west-2"

    def test_uses_configured_region_when_available(self, monkeypatch):
        monkeypatch.delenv("BEDROCK_MANTLE_REGION", raising=False)
        assert oar.resolve_mantle_region("openai.gpt-5.4", "us-west-2") == "us-west-2"

    def test_falls_back_for_gpt_5_5(self, monkeypatch):
        monkeypatch.delenv("BEDROCK_MANTLE_REGION", raising=False)
        # gpt-5.5 is in us-east-1/us-east-2; an unavailable region falls back to
        # the per-model default (us-east-1).
        assert oar.resolve_mantle_region("openai.gpt-5.5", "eu-west-1") == "us-east-1"

    def test_falls_back_to_gov_region(self, monkeypatch):
        monkeypatch.delenv("BEDROCK_MANTLE_REGION", raising=False)
        assert (
            oar.resolve_mantle_region("openai.gpt-5.4", "us-gov-east-1")
            == "us-gov-west-1"
        )

    def test_gpt_5_6_terra_available_in_us_west_2(self, monkeypatch):
        monkeypatch.delenv("BEDROCK_MANTLE_REGION", raising=False)
        assert (
            oar.resolve_mantle_region("openai.gpt-5.6-terra", "us-west-2")
            == "us-west-2"
        )

    def test_gpt_5_6_sol_not_in_us_west_2_falls_back(self, monkeypatch):
        monkeypatch.delenv("BEDROCK_MANTLE_REGION", raising=False)
        # Sol is only in us-east-1/us-east-2; us-west-2 is not available for it.
        assert (
            oar.resolve_mantle_region("openai.gpt-5.6-sol", "us-west-2") == "us-east-1"
        )


@pytest.mark.unit
class TestRequestTranslation:
    def test_text_and_image_translation(self):
        body = oar.build_responses_request(
            system_prompt="You are helpful",
            content=[
                {"text": "extract <<CACHEPOINT>> fields"},
                {"image": {"format": "png", "source": {"bytes": b"abc"}}},
            ],
            max_tokens=500,
            model_id="openai.gpt-5.4",
        )
        assert body["model"] == "openai.gpt-5.4"
        assert body["instructions"] == "You are helpful"
        assert body["max_output_tokens"] == 500
        # Defaults to medium when no reasoning_effort given
        assert body["reasoning"]["effort"] == "medium"
        # No sampling parameters
        assert "temperature" not in body
        assert "top_p" not in body
        assert "top_k" not in body

        items = body["input"][0]["content"]
        text_items = [i for i in items if i["type"] == "input_text"]
        image_items = [i for i in items if i["type"] == "input_image"]
        assert len(text_items) == 1
        assert "<<CACHEPOINT>>" not in text_items[0]["text"]
        assert len(image_items) == 1
        assert image_items[0]["image_url"].startswith("data:image/png;base64,")

    def test_max_tokens_capped_to_model_limit(self):
        body = oar.build_responses_request(
            system_prompt="sys",
            content=[{"text": "hi"}],
            max_tokens=10_000_000,
            model_id="openai.gpt-5.4",
        )
        # Capped to the model_config_limits value (128000)
        assert body["max_output_tokens"] == 128000

    def test_cachepoint_block_skipped(self):
        body = oar.build_responses_request(
            system_prompt="sys",
            content=[{"text": "hi"}, {"cachePoint": {"type": "default"}}],
            max_tokens=100,
            model_id="openai.gpt-5.5",
        )
        items = body["input"][0]["content"]
        assert all("cachePoint" not in str(i) for i in items)
        assert len(items) == 1

    def test_gpt_5_6_cachepoint_marker_emits_explicit_breakpoint(self):
        body = oar.build_responses_request(
            system_prompt="You are helpful",
            content=[
                {"text": "static instructions <<CACHEPOINT>>"},
                {"text": "dynamic question"},
            ],
            max_tokens=100,
            model_id="openai.gpt-5.6-sol",
        )
        assert body["prompt_cache_options"] == {"mode": "explicit"}
        assert body["prompt_cache_key"].startswith("idp:")
        items = body["input"][0]["content"]
        # Marker stripped from the text, breakpoint attached to the first block.
        assert "<<CACHEPOINT>>" not in items[0]["text"]
        assert items[0]["prompt_cache_breakpoint"] == {"mode": "explicit"}
        # The second (dynamic) block carries no breakpoint.
        assert "prompt_cache_breakpoint" not in items[1]

    def test_gpt_5_6_cachepoint_block_emits_explicit_breakpoint(self):
        body = oar.build_responses_request(
            system_prompt="sys",
            content=[{"text": "prefix"}, {"cachePoint": {"type": "default"}}],
            max_tokens=100,
            model_id="openai.gpt-5.6-terra",
        )
        items = body["input"][0]["content"]
        assert len(items) == 1  # cachePoint block itself is not emitted
        assert items[0]["prompt_cache_breakpoint"] == {"mode": "explicit"}
        assert body["prompt_cache_options"] == {"mode": "explicit"}

    def test_gpt_5_5_does_not_emit_explicit_cache_fields(self):
        body = oar.build_responses_request(
            system_prompt="sys",
            content=[{"text": "prefix <<CACHEPOINT>>"}, {"text": "rest"}],
            max_tokens=100,
            model_id="openai.gpt-5.5",
        )
        # 5.5 caches automatically: no explicit fields, marker stripped.
        assert "prompt_cache_options" not in body
        assert "prompt_cache_key" not in body
        items = body["input"][0]["content"]
        assert "<<CACHEPOINT>>" not in items[0]["text"]
        assert all("prompt_cache_breakpoint" not in i for i in items)

    def test_gpt_5_6_no_marker_no_cache_fields(self):
        body = oar.build_responses_request(
            system_prompt="sys",
            content=[{"text": "no marker here"}],
            max_tokens=100,
            model_id="openai.gpt-5.6-luna",
        )
        assert "prompt_cache_options" not in body
        assert "prompt_cache_key" not in body

    def test_cache_key_stable_for_identical_prefix_and_differs_otherwise(self):
        def key_for(prefix_text, model="openai.gpt-5.6-sol", system="sys"):
            body = oar.build_responses_request(
                system_prompt=system,
                content=[{"text": f"{prefix_text} <<CACHEPOINT>>"}, {"text": "q"}],
                max_tokens=100,
                model_id=model,
            )
            return body["prompt_cache_key"]

        assert key_for("same prefix") == key_for("same prefix")
        assert key_for("prefix A") != key_for("prefix B")
        # Different system prompt → different key.
        assert key_for("p", system="sys1") != key_for("p", system="sys2")

    def test_reasoning_effort_passed_through(self):
        body = oar.build_responses_request(
            system_prompt="sys",
            content=[{"text": "hi"}],
            max_tokens=100,
            model_id="openai.gpt-5.4",
            reasoning_effort="high",
        )
        assert body["reasoning"]["effort"] == "high"

    def test_reasoning_effort_invalid_falls_back_to_default(self):
        body = oar.build_responses_request(
            system_prompt="sys",
            content=[{"text": "hi"}],
            max_tokens=100,
            model_id="openai.gpt-5.4",
            reasoning_effort="turbo",  # not a valid level
        )
        assert body["reasoning"]["effort"] == oar.DEFAULT_REASONING_EFFORT

    def test_reasoning_effort_none_uses_default(self):
        body = oar.build_responses_request(
            system_prompt="sys",
            content=[{"text": "hi"}],
            max_tokens=100,
            model_id="openai.gpt-5.4",
            reasoning_effort=None,
        )
        assert body["reasoning"]["effort"] == "medium"


@pytest.mark.unit
class TestResponseTranslation:
    def test_text_extraction_and_usage_mapping(self):
        result = oar.translate_response(
            _SAMPLE_RESPONSE, "openai.gpt-5.4", "Extraction"
        )
        text = result["response"]["output"]["message"]["content"][0]["text"]
        assert text == "Hello world"

        usage = result["response"]["usage"]
        # OpenAI input_tokens (100) is the TOTAL and includes cached_tokens (25);
        # inputTokens is reported as the DISJOINT fresh count (100 - 25 = 75) so
        # cached tokens are not billed at both the input and cache-read rate.
        assert usage == {
            "inputTokens": 75,
            "outputTokens": 40,
            "totalTokens": 140,
            "cacheReadInputTokens": 25,
            "cacheWriteInputTokens": 0,
        }

        metering = result["metering"]["Extraction/bedrock/openai.gpt-5.4"]
        assert metering["requests"] == 1
        assert metering["inputTokens"] == 75
        # reasoning_tokens must NOT be a metering key
        assert "reasoning_tokens" not in metering
        assert "reasoningTokens" not in metering

    def test_extract_text_from_response_compatibility(self):
        result = oar.translate_response(
            _SAMPLE_RESPONSE, "openai.gpt-5.4", "Extraction"
        )
        client = BedrockClient(metrics_enabled=False)
        assert client.extract_text_from_response(result) == "Hello world"

    def test_reasoning_tokens_helper(self):
        assert oar._reasoning_tokens(_SAMPLE_RESPONSE) == 12

    def test_map_usage_reports_cache_write_tokens_when_present(self):
        payload = {
            "usage": {
                "input_tokens": 100,
                "output_tokens": 40,
                "total_tokens": 140,
                "input_tokens_details": {
                    "cached_tokens": 25,
                    "cache_creation_tokens": 60,
                },
            }
        }
        usage = oar._map_usage(payload)
        assert usage["cacheReadInputTokens"] == 25
        assert usage["cacheWriteInputTokens"] == 60
        # Fresh input = total(100) - cached(25) - cache_write(60) = 15
        assert usage["inputTokens"] == 15

    def test_map_usage_cache_write_defaults_zero(self):
        usage = oar._map_usage(_SAMPLE_RESPONSE)
        assert usage["cacheWriteInputTokens"] == 0

    def test_map_usage_disjoint_token_accounting_matches_converse(self):
        """OpenAI input_tokens is a TOTAL; we report disjoint fresh input so the
        cost model does not bill cached tokens twice (input rate + cache rate).

        Mirrors the live-observed GPT-5.6 warm-cache case: input_tokens 4508 with
        cached_tokens 3193 must yield fresh inputTokens 1315.
        """
        warm = {
            "usage": {
                "input_tokens": 4508,
                "output_tokens": 558,
                "total_tokens": 5066,
                "input_tokens_details": {"cached_tokens": 3193},
            }
        }
        u = oar._map_usage(warm)
        assert u["inputTokens"] == 1315
        assert u["cacheReadInputTokens"] == 3193
        # Fresh + cache-read reconstructs the original prompt total.
        assert u["inputTokens"] + u["cacheReadInputTokens"] == 4508

    def test_map_usage_never_negative_fresh_input(self):
        # Defensive: if cache counts exceed input_tokens, clamp fresh at 0.
        payload = {
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "input_tokens_details": {"cached_tokens": 8, "cache_write_tokens": 6},
            }
        }
        assert oar._map_usage(payload)["inputTokens"] == 0


@pytest.mark.unit
class TestInvocationAndRouting:
    @pytest.fixture
    def client(self):
        c = BedrockClient(region="us-east-2", metrics_enabled=False)
        return c

    def _patch_session(self):
        """Patch get_bedrock_session to provide dummy credentials."""
        fake_session = MagicMock()
        creds = MagicMock()
        creds.get_frozen_credentials.return_value = MagicMock(
            access_key="AKIA",
            secret_key="secret",
            token=None,  # nosec B106 - dummy test credential
        )
        fake_session.get_credentials.return_value = creds
        return patch.object(oar, "get_bedrock_session", return_value=fake_session)

    def test_invoke_model_routes_to_responses_backend(self, client):
        with (
            self._patch_session(),
            patch.object(oar.URLLib3Session, "send") as mock_send,
        ):
            mock_send.return_value = _make_http_response(200, _SAMPLE_RESPONSE)

            result = client.invoke_model(
                model_id="openai.gpt-5.4",
                system_prompt="sys",
                content=[{"text": "hi"}],
            )

        assert (
            result["response"]["output"]["message"]["content"][0]["text"]
            == "Hello world"
        )
        assert "Unspecified/bedrock/openai.gpt-5.4" in result["metering"]

        # Verify SigV4 Authorization header and URL on the prepared request.
        prepared = mock_send.call_args.args[0]
        assert "us-east-2" in prepared.url
        assert prepared.url.endswith("/openai/v1/responses")
        auth = prepared.headers.get("Authorization", "")
        assert "AWS4-HMAC-SHA256" in auth
        assert "bedrock-mantle" in auth  # signing service name in credential scope

    def test_invoke_model_forwards_reasoning_effort(self, client):
        import json as _json

        with (
            self._patch_session(),
            patch.object(oar.URLLib3Session, "send") as mock_send,
        ):
            mock_send.return_value = _make_http_response(200, _SAMPLE_RESPONSE)

            client.invoke_model(
                model_id="openai.gpt-5.5",
                system_prompt="sys",
                content=[{"text": "hi"}],
                reasoning_effort="high",
            )

        prepared = mock_send.call_args.args[0]
        sent_body = _json.loads(prepared.body)
        assert sent_body["reasoning"]["effort"] == "high"

    def test_retry_on_429_then_success(self, client):
        with (
            self._patch_session(),
            patch.object(oar.URLLib3Session, "send") as mock_send,
            patch.object(oar.time, "sleep"),
        ):
            mock_send.side_effect = [
                _make_http_response(429, {"message": "throttled"}),
                _make_http_response(200, _SAMPLE_RESPONSE),
            ]
            result = client.invoke_model(
                model_id="openai.gpt-5.4",
                system_prompt="sys",
                content=[{"text": "hi"}],
            )
        assert mock_send.call_count == 2
        # _SAMPLE_RESPONSE: input_tokens 100 total, cached_tokens 25 → fresh 75.
        assert result["response"]["usage"]["inputTokens"] == 75

    def test_raises_after_max_retries(self, client):
        client.max_retries = 2
        with (
            self._patch_session(),
            patch.object(oar.URLLib3Session, "send") as mock_send,
            patch.object(oar.time, "sleep"),
        ):
            mock_send.return_value = _make_http_response(500, {"message": "boom"})
            with pytest.raises(RuntimeError):
                client.invoke_model(
                    model_id="openai.gpt-5.4",
                    system_prompt="sys",
                    content=[{"text": "hi"}],
                )
        assert mock_send.call_count == 2

    def test_terminal_4xx_not_retried(self, client):
        with (
            self._patch_session(),
            patch.object(oar.URLLib3Session, "send") as mock_send,
            patch.object(oar.time, "sleep"),
        ):
            mock_send.return_value = _make_http_response(400, {"message": "bad"})
            with pytest.raises(RuntimeError):
                client.invoke_model(
                    model_id="openai.gpt-5.4",
                    system_prompt="sys",
                    content=[{"text": "hi"}],
                )
        assert mock_send.call_count == 1


_SSE_STREAM = (
    'data: {"type":"response.created"}\n\n'
    "event: response.output_text.delta\n"
    'data: {"type":"response.output_text.delta","delta":"Hello"}\n\n'
    'data: {"type":"response.output_text.delta","delta":", world"}\n\n'
    'data: {"type":"response.output_text.delta","delta":"!"}\n\n'
    'data: {"type":"response.completed","response":{"usage":{'
    '"input_tokens":12,"output_tokens":5,"total_tokens":17,'
    '"input_tokens_details":{"cached_tokens":4},'
    '"output_tokens_details":{"reasoning_tokens":3}}}}\n\n'
)


def _fake_urllib3_response(status, body_text):
    """Build a fake urllib3 HTTPResponse for the streaming path."""
    resp = MagicMock()
    resp.status = status
    raw = body_text.encode("utf-8")
    # stream(amt) yields byte chunks of size amt (exercises record reassembly).
    resp.stream.side_effect = lambda amt=256, **kw: (
        raw[i : i + amt] for i in range(0, len(raw), amt)
    )
    resp.read.return_value = raw
    return resp


@pytest.mark.unit
class TestSSEParser:
    def test_iter_sse_data_objects_handles_split_chunks(self):
        b = _SSE_STREAM.encode("utf-8")
        chunks = [b[i : i + 7] for i in range(0, len(b), 7)]  # tiny, boundary-splitting
        objs = list(oar._iter_sse_data_objects(iter(chunks)))
        types = [o.get("type") for o in objs]
        assert types == [
            "response.created",
            "response.output_text.delta",
            "response.output_text.delta",
            "response.output_text.delta",
            "response.completed",
        ]
        deltas = [
            o["delta"] for o in objs if o.get("type") == "response.output_text.delta"
        ]
        assert "".join(deltas) == "Hello, world!"

    def test_iter_sse_skips_done_and_blank(self):
        stream = b"data: [DONE]\n\ndata: \n\n"
        assert list(oar._iter_sse_data_objects(iter([stream]))) == []


@pytest.mark.unit
class TestStreamResponsesApi:
    @pytest.fixture
    def client(self):
        return BedrockClient(region="us-east-2", metrics_enabled=False)

    def _patch_signing(self):
        # _sign_request needs credentials; patch the session lookup.
        fake_session = MagicMock()
        creds = MagicMock()
        creds.get_frozen_credentials.return_value = MagicMock(
            access_key="AKIA",
            secret_key="secret",
            token=None,  # nosec B106 - dummy test credential
        )
        fake_session.get_credentials.return_value = creds
        return patch.object(oar, "get_bedrock_session", return_value=fake_session)

    def test_streams_deltas_then_final_metering(self, client):
        fake_resp = _fake_urllib3_response(200, _SSE_STREAM)
        fake_pool = MagicMock()
        fake_pool.request.return_value = fake_resp

        with (
            self._patch_signing(),
            patch("urllib3.PoolManager", return_value=fake_pool),
        ):
            items = list(
                oar.stream_responses_api(
                    client=client,
                    model_id="openai.gpt-5.4",
                    system_prompt="sys",
                    content=[{"text": "hi"}],
                    max_tokens=100,
                    context="ChatWithDocument",
                    reasoning_effort="low",
                )
            )

        # All but the last item are text deltas; last is the metering dict.
        deltas = [i for i in items if isinstance(i, str)]
        final = items[-1]
        assert "".join(deltas) == "Hello, world!"
        assert isinstance(final, dict)
        usage = final["metering"]["ChatWithDocument/bedrock/openai.gpt-5.4"]
        # input_tokens 12 total includes cached 4 → disjoint fresh input 8.
        assert usage["inputTokens"] == 8
        assert usage["outputTokens"] == 5
        assert usage["cacheReadInputTokens"] == 4
        assert usage["cacheWriteInputTokens"] == 0
        assert usage["requests"] == 1
        assert "reasoning_tokens" not in usage
        # stream=true was sent in the request body.
        sent_body = json.loads(fake_pool.request.call_args.kwargs["body"])
        assert sent_body["stream"] is True
        assert sent_body["reasoning"]["effort"] == "low"

    def test_non_200_raises_before_deltas(self, client):
        fake_resp = _fake_urllib3_response(429, '{"message":"slow down"}')
        fake_pool = MagicMock()
        fake_pool.request.return_value = fake_resp

        with (
            self._patch_signing(),
            patch("urllib3.PoolManager", return_value=fake_pool),
        ):
            gen = oar.stream_responses_api(
                client=client,
                model_id="openai.gpt-5.4",
                system_prompt="sys",
                content=[{"text": "hi"}],
                max_tokens=100,
                context="ChatWithDocument",
            )
            with pytest.raises(RuntimeError, match="429"):
                list(gen)
