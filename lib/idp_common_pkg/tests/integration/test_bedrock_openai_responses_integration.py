# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Integration tests for OpenAI GPT-5.x via the bedrock-mantle Responses API.

These make REAL calls to the ``bedrock-mantle`` endpoint and require:
  - AWS credentials with ``bedrock-mantle:CreateInference`` permission
  - Access to the OpenAI models in the target region(s):
      * GPT-5.4: us-east-1, us-east-2, us-west-2, us-gov-west-1
      * GPT-5.5: us-east-1, us-east-2
      * GPT-5.6 Sol: us-east-1, us-east-2
      * GPT-5.6 Terra/Luna: us-east-1, us-east-2, us-west-2

Like all integration tests in this package they are excluded from the default
run (``addopts = -m "not integration"`` in pytest.ini) and only execute with::

    pytest -m integration tests/integration/test_bedrock_openai_responses_integration.py

A test that hits an access/availability error (no model access, wrong region)
is skipped rather than failed, so the suite stays green where the models are
not enabled.
"""

import io

import pytest

from idp_common.bedrock.client import BedrockClient

# Errors that mean "the model/endpoint isn't available to this account/region"
# rather than a real defect — used to skip instead of fail.
_AVAILABILITY_MARKERS = (
    "AccessDenied",
    "could not be found",
    "not found",
    "not authorized",
    "403",
    "404",
    "ResourceNotFound",
    "ValidationException",
)


def _skip_if_unavailable(exc: Exception) -> None:
    msg = str(exc)
    if any(marker.lower() in msg.lower() for marker in _AVAILABILITY_MARKERS):
        pytest.skip(
            f"OpenAI Responses model not available in this account/region: {msg}"
        )
    raise exc


def _make_png(text: str) -> bytes:
    """Render a tiny PNG containing the given text for the multimodal test."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (260, 80), "white")
    ImageDraw.Draw(img).text((10, 30), text, fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.integration
class TestOpenAIResponsesIntegration:
    """Real end-to-end calls validating the bedrock-mantle backend."""

    @pytest.fixture
    def client(self):
        # us-west-2 supports GPT-5.4 in-region; GPT-5.5 falls back to us-east-1.
        return BedrockClient(region="us-west-2", metrics_enabled=False)

    def test_gpt_5_4_text(self, client):
        """GPT-5.4 text request returns a correct answer and parsed usage."""
        try:
            result = client.invoke_model(
                model_id="openai.gpt-5.4",
                system_prompt="You are terse. Reply with only the number.",
                content=[{"text": "What is 17 times 23?"}],
                max_tokens=2000,
                context="IntegrationTest",
                reasoning_effort="low",
            )
        except Exception as e:  # noqa: BLE001 - intentional skip-or-reraise
            _skip_if_unavailable(e)

        text = client.extract_text_from_response(result)
        assert "391" in text

        # Contract: converse-shaped response + metering with the exact unit keys.
        usage = result["response"]["usage"]
        for key in (
            "inputTokens",
            "outputTokens",
            "totalTokens",
            "cacheReadInputTokens",
            "cacheWriteInputTokens",
        ):
            assert key in usage
        assert usage["inputTokens"] > 0
        assert usage["outputTokens"] > 0

        metering = result["metering"]["IntegrationTest/bedrock/openai.gpt-5.4"]
        assert metering["requests"] == 1
        assert metering["inputTokens"] == usage["inputTokens"]

    def test_gpt_5_4_multimodal_image(self, client):
        """GPT-5.4 reads text from an image (input_image translation path)."""
        png = _make_png("INVOICE NO: CAT-42")
        try:
            result = client.invoke_model(
                model_id="openai.gpt-5.4",
                system_prompt="You read text from images. Reply with only the invoice number.",
                content=[
                    {"text": "What is the invoice number in this image?"},
                    {"image": {"format": "png", "source": {"bytes": png}}},
                ],
                max_tokens=2000,
                context="IntegrationTest",
                reasoning_effort="low",
            )
        except Exception as e:  # noqa: BLE001
            _skip_if_unavailable(e)

        text = client.extract_text_from_response(result)
        assert "CAT-42" in text

    def test_gpt_5_5_cross_region_fallback(self, client):
        """GPT-5.5 (us-east-1/us-east-2) is reachable from a us-west-2 client."""
        try:
            result = client.invoke_model(
                model_id="openai.gpt-5.5",
                system_prompt="Reply with one word.",
                content=[{"text": "What color is a clear daytime sky?"}],
                max_tokens=2000,
                context="IntegrationTest",
            )
        except Exception as e:  # noqa: BLE001
            _skip_if_unavailable(e)

        text = client.extract_text_from_response(client_result := result)
        assert text.strip() != ""
        assert client_result["response"]["usage"]["outputTokens"] > 0

    def test_reasoning_effort_high_accepted(self, client):
        """A high reasoning effort is accepted end-to-end."""
        try:
            result = client.invoke_model(
                model_id="openai.gpt-5.4",
                system_prompt="Reply with one short sentence.",
                content=[{"text": "Name one benefit of unit tests."}],
                max_tokens=4000,
                context="IntegrationTest",
                reasoning_effort="high",
            )
        except Exception as e:  # noqa: BLE001
            _skip_if_unavailable(e)

        assert client.extract_text_from_response(result).strip() != ""

    def test_gpt_5_6_terra_explicit_cache(self, client):
        """GPT-5.6 Terra accepts an explicit prompt-cache breakpoint end-to-end.

        Sends a <<CACHEPOINT>> marker (translated to prompt_cache_breakpoint) and
        asserts the call succeeds and reports cache metering keys.
        """
        try:
            result = client.invoke_model(
                model_id="openai.gpt-5.6-terra",
                system_prompt="Reply with one word.",
                content=[
                    {"text": "Static reusable context. <<CACHEPOINT>>"},
                    {"text": "What color is a clear daytime sky?"},
                ],
                max_tokens=2000,
                context="IntegrationTest",
            )
        except Exception as e:  # noqa: BLE001
            _skip_if_unavailable(e)

        assert client.extract_text_from_response(result).strip() != ""
        usage = result["response"]["usage"]
        assert "cacheReadInputTokens" in usage
        assert "cacheWriteInputTokens" in usage
