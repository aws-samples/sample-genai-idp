# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for BedrockClient service_tier functionality with model ID suffixes."""

from unittest.mock import MagicMock

import pytest

from idp_common.bedrock.client import BedrockClient


@pytest.mark.unit
class TestBedrockClientServiceTier:
    """Test service tier parameter handling in BedrockClient."""

    @pytest.fixture
    def mock_bedrock_response(self):
        """Mock Bedrock API response."""
        return {
            "output": {"message": {"content": [{"text": "test response"}]}},
            "usage": {
                "inputTokens": 100,
                "outputTokens": 50,
                "totalTokens": 150,
            },
        }

    @pytest.fixture
    def bedrock_client(self):
        """Create BedrockClient instance with mocked boto3 client."""
        client = BedrockClient(region="us-west-2", metrics_enabled=False)
        client._client = MagicMock()
        return client

    def test_model_id_with_flex_suffix(self, bedrock_client, mock_bedrock_response):
        """Test model ID with :flex suffix extracts tier and uses base model."""
        bedrock_client._client.converse.return_value = mock_bedrock_response

        bedrock_client.invoke_model(
            model_id="us.amazon.nova-2-lite-v1:0:flex",
            system_prompt="test",
            content=[{"text": "test"}],
        )

        call_args = bedrock_client._client.converse.call_args
        assert call_args.kwargs["modelId"] == "us.amazon.nova-2-lite-v1:0"
        assert call_args.kwargs["serviceTier"] == {"type": "flex"}

    def test_model_id_with_priority_suffix(self, bedrock_client, mock_bedrock_response):
        """Test model ID with :priority suffix extracts tier and uses base model."""
        bedrock_client._client.converse.return_value = mock_bedrock_response

        bedrock_client.invoke_model(
            model_id="us.amazon.nova-2-lite-v1:0:priority",
            system_prompt="test",
            content=[{"text": "test"}],
        )

        call_args = bedrock_client._client.converse.call_args
        assert call_args.kwargs["modelId"] == "us.amazon.nova-2-lite-v1:0"
        assert call_args.kwargs["serviceTier"] == {"type": "priority"}

    def test_model_id_without_suffix(self, bedrock_client, mock_bedrock_response):
        """Test model ID without suffix uses standard tier (no serviceTier param)."""
        bedrock_client._client.converse.return_value = mock_bedrock_response

        bedrock_client.invoke_model(
            model_id="us.amazon.nova-pro-v1:0",
            system_prompt="test",
            content=[{"text": "test"}],
        )

        call_args = bedrock_client._client.converse.call_args
        assert call_args.kwargs["modelId"] == "us.amazon.nova-pro-v1:0"
        assert "serviceTier" not in call_args.kwargs

    def test_service_tier_parameter_fallback(
        self, bedrock_client, mock_bedrock_response
    ):
        """Test service_tier parameter still works as fallback."""
        bedrock_client._client.converse.return_value = mock_bedrock_response

        bedrock_client.invoke_model(
            model_id="us.amazon.nova-pro-v1:0",
            system_prompt="test",
            content=[{"text": "test"}],
            service_tier="flex",
        )

        call_args = bedrock_client._client.converse.call_args
        assert call_args.kwargs["modelId"] == "us.amazon.nova-pro-v1:0"
        assert call_args.kwargs["serviceTier"] == {"type": "flex"}

    def test_suffix_takes_precedence_over_parameter(
        self, bedrock_client, mock_bedrock_response
    ):
        """Test model ID suffix takes precedence over service_tier parameter."""
        bedrock_client._client.converse.return_value = mock_bedrock_response

        bedrock_client.invoke_model(
            model_id="us.amazon.nova-2-lite-v1:0:priority",
            system_prompt="test",
            content=[{"text": "test"}],
            service_tier="flex",
        )

        call_args = bedrock_client._client.converse.call_args
        assert call_args.kwargs["modelId"] == "us.amazon.nova-2-lite-v1:0"
        assert call_args.kwargs["serviceTier"] == {"type": "priority"}

    def test_global_model_with_flex(self, bedrock_client, mock_bedrock_response):
        """Test global model ID with flex suffix."""
        bedrock_client._client.converse.return_value = mock_bedrock_response

        bedrock_client.invoke_model(
            model_id="global.amazon.nova-2-lite-v1:0:flex",
            system_prompt="test",
            content=[{"text": "test"}],
        )

        call_args = bedrock_client._client.converse.call_args
        assert call_args.kwargs["modelId"] == "global.amazon.nova-2-lite-v1:0"
        assert call_args.kwargs["serviceTier"] == {"type": "flex"}

    def test_standard_normalized_to_default(
        self, bedrock_client, mock_bedrock_response
    ):
        """Test 'standard' service_tier parameter normalized to 'default'."""
        bedrock_client._client.converse.return_value = mock_bedrock_response

        bedrock_client.invoke_model(
            model_id="us.amazon.nova-pro-v1:0",
            system_prompt="test",
            content=[{"text": "test"}],
            service_tier="standard",
        )

        call_args = bedrock_client._client.converse.call_args
        assert call_args.kwargs["serviceTier"] == {"type": "default"}
