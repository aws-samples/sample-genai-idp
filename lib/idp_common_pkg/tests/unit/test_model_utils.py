# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for model_utils module."""

import pytest
from idp_common.bedrock.model_utils import get_model_max_output_tokens, parse_model_id


@pytest.mark.unit
class TestParseModelId:
    """Test model ID parsing functionality."""

    def test_parse_model_without_suffix(self):
        """Test parsing model ID without service tier suffix."""
        base_id, tier = parse_model_id("us.amazon.nova-2-lite-v1:0")
        assert base_id == "us.amazon.nova-2-lite-v1:0"
        assert tier is None

    def test_parse_model_with_flex_suffix(self):
        """Test parsing model ID with flex suffix."""
        base_id, tier = parse_model_id("us.amazon.nova-2-lite-v1:0:flex")
        assert base_id == "us.amazon.nova-2-lite-v1:0"
        assert tier == "flex"

    def test_parse_model_with_priority_suffix(self):
        """Test parsing model ID with priority suffix."""
        base_id, tier = parse_model_id("us.amazon.nova-2-lite-v1:0:priority")
        assert base_id == "us.amazon.nova-2-lite-v1:0"
        assert tier == "priority"

    def test_parse_model_with_uppercase_suffix(self):
        """Test parsing model ID with uppercase suffix."""
        base_id, tier = parse_model_id("us.amazon.nova-2-lite-v1:0:FLEX")
        assert base_id == "us.amazon.nova-2-lite-v1:0"
        assert tier == "flex"

    def test_parse_model_with_invalid_suffix(self):
        """Test parsing model ID with invalid suffix."""
        base_id, tier = parse_model_id("us.amazon.nova-2-lite-v1:0:invalid")
        assert base_id == "us.amazon.nova-2-lite-v1:0:invalid"
        assert tier is None

    def test_parse_empty_string(self):
        """Test parsing empty string."""
        base_id, tier = parse_model_id("")
        assert base_id == ""
        assert tier is None

    def test_parse_none(self):
        """Test parsing None."""
        base_id, tier = parse_model_id(None)
        assert base_id is None
        assert tier is None

    def test_parse_model_with_1m_and_tier(self):
        """Test parsing model ID with both 1m and tier suffix."""
        # This should not happen in practice, but test behavior
        base_id, tier = parse_model_id("us.anthropic.claude-3-5-haiku:1m:flex")
        assert base_id == "us.anthropic.claude-3-5-haiku:1m"
        assert tier == "flex"

    def test_parse_global_model_with_flex(self):
        """Test parsing global model with flex suffix."""
        base_id, tier = parse_model_id("global.amazon.nova-2-lite-v1:0:flex")
        assert base_id == "global.amazon.nova-2-lite-v1:0"
        assert tier == "flex"

    def test_parse_global_model_with_priority(self):
        """Test parsing global model with priority suffix."""
        base_id, tier = parse_model_id("global.amazon.nova-2-lite-v1:0:priority")
        assert base_id == "global.amazon.nova-2-lite-v1:0"
        assert tier == "priority"


@pytest.mark.unit
class TestGetModelMaxOutputTokens:
    """Test model max output token detection."""

    def test_claude4_models_return_64k(self):
        """Claude 4 models that cap at 64,000 output tokens: Sonnet 4.0/4.5,
        Haiku 4.5, and Opus 4.0/4.1/4.5. (Sonnet 4.6 and Opus 4.6 are 128K —
        see test_claude46_models_return_128k.)"""
        # Sonnet 4.0
        assert (
            get_model_max_output_tokens("us.anthropic.claude-sonnet-4-20250514-v1:0")
            == 64_000
        )
        # Sonnet 4.5
        assert (
            get_model_max_output_tokens("us.anthropic.claude-sonnet-4-5-20250929-v1:0")
            == 64_000
        )
        # Haiku 4.5
        assert (
            get_model_max_output_tokens("us.anthropic.claude-haiku-4-5-20251001-v1:0")
            == 64_000
        )
        # Opus 4.5
        assert (
            get_model_max_output_tokens("us.anthropic.claude-opus-4-5-20250514-v1:0")
            == 64_000
        )

    def test_claude46_models_return_128k(self):
        """Sonnet 4.6 and Opus 4.6 support 128,000 output tokens (like Opus 4.7/4.8),
        including the :1m extended-context variants. Regression: the generic
        'claude-(opus|sonnet|haiku)-4' catch-all previously mis-capped these at 64K."""
        assert get_model_max_output_tokens("us.anthropic.claude-sonnet-4-6") == 128_000
        assert (
            get_model_max_output_tokens("us.anthropic.claude-sonnet-4-6:1m") == 128_000
        )
        assert get_model_max_output_tokens("eu.anthropic.claude-sonnet-4-6") == 128_000
        assert get_model_max_output_tokens("us.anthropic.claude-opus-4-6") == 128_000
        assert (
            get_model_max_output_tokens("us.anthropic.claude-opus-4-6-v1:1m") == 128_000
        )

    def test_claude_opus_47_48_return_128k(self):
        """Opus 4.7 and 4.8 support 128,000 output tokens, incl. :1m variants."""
        assert get_model_max_output_tokens("us.anthropic.claude-opus-4-7") == 128_000
        assert get_model_max_output_tokens("us.anthropic.claude-opus-4-7:1m") == 128_000
        assert get_model_max_output_tokens("us.anthropic.claude-opus-4-8") == 128_000
        assert get_model_max_output_tokens("us.anthropic.claude-opus-4-8:1m") == 128_000

    def test_claude3_models_return_8k(self):
        """Test Claude 3 models return 8,192 max tokens."""
        assert (
            get_model_max_output_tokens("us.anthropic.claude-3-haiku-20240307-v1:0")
            == 8_192
        )
        assert (
            get_model_max_output_tokens("us.anthropic.claude-3-5-sonnet-20241022-v2:0")
            == 8_192
        )
        assert (
            get_model_max_output_tokens("eu.anthropic.claude-3-5-sonnet-20241022-v2:0")
            == 8_192
        )

    def test_nova_models_return_10k(self):
        """Test Amazon Nova models return 10,000 max tokens."""
        assert get_model_max_output_tokens("us.amazon.nova-lite-v1:0") == 10_000
        assert get_model_max_output_tokens("us.amazon.nova-pro-v1:0") == 10_000
        assert get_model_max_output_tokens("us.amazon.nova-premier-v1:0") == 10_000
        assert get_model_max_output_tokens("us.amazon.nova-micro-v1:0") == 10_000

    def test_nova2_models_return_10k(self):
        """Test Amazon Nova 2 models return 10,000 max tokens."""
        assert get_model_max_output_tokens("us.amazon.nova-2-lite-v1:0") == 10_000
        assert get_model_max_output_tokens("eu.amazon.nova-2-lite-v1:0") == 10_000
        assert get_model_max_output_tokens("global.amazon.nova-2-lite-v1:0") == 10_000

    def test_openai_gpt5_models_return_128k(self):
        """Test OpenAI GPT-5.x models return 128,000 max tokens."""
        assert get_model_max_output_tokens("openai.gpt-5.4") == 128_000
        assert get_model_max_output_tokens("openai.gpt-5.5") == 128_000

    def test_unknown_model_raises_error(self):
        """Test unknown models raise ValueError instead of returning default."""
        with pytest.raises(ValueError, match="Unsupported model ID"):
            get_model_max_output_tokens("unknown.model.id")

        with pytest.raises(ValueError, match="Unsupported model ID"):
            get_model_max_output_tokens("us.meta.llama-3-70b-instruct-v1:0")

    def test_case_insensitive(self):
        """Test model ID matching is case insensitive."""
        assert (
            get_model_max_output_tokens("US.ANTHROPIC.CLAUDE-SONNET-4-20250514-V1:0")
            == 64_000
        )
        assert get_model_max_output_tokens("US.AMAZON.NOVA-LITE-V1:0") == 10_000
        assert (
            get_model_max_output_tokens("US.ANTHROPIC.CLAUDE-3-HAIKU-20240307-V1:0")
            == 8_192
        )

    def test_extended_context_1m_suffix(self):
        """Test that :1m extended context suffix doesn't change output token limit."""
        # Claude 4 with :1m suffix should still be 64K output (Sonnet, Haiku)
        assert (
            get_model_max_output_tokens("us.anthropic.claude-sonnet-4-20250514-v1:0:1m")
            == 64_000
        )
        # The :1m increases INPUT context window, not output tokens

    def test_opus_4_7_returns_128k(self):
        """Test Claude Opus 4.7 returns 128,000 max tokens."""
        assert (
            get_model_max_output_tokens("us.anthropic.claude-opus-4-7-20250514-v1:0")
            == 128_000
        )
        assert (
            get_model_max_output_tokens("global.anthropic.claude-opus-4-7") == 128_000
        )
        # With :1m suffix
        assert (
            get_model_max_output_tokens("us.anthropic.claude-opus-4-7-20250514-v1:0:1m")
            == 128_000
        )

    def test_opus_4_8_returns_128k(self):
        """Test Claude Opus 4.8 returns 128,000 max tokens."""
        assert (
            get_model_max_output_tokens("us.anthropic.claude-opus-4-8-20251201-v1:0")
            == 128_000
        )
        assert (
            get_model_max_output_tokens("global.anthropic.claude-opus-4-8") == 128_000
        )
        # With :1m suffix
        assert get_model_max_output_tokens("us.anthropic.claude-opus-4-8:1m") == 128_000

    def test_sonnet_5_returns_128k(self):
        """Claude Sonnet 5 returns 128,000 max tokens (1M context), incl. :1m.
        Sonnet 5 does NOT match the claude-(opus|sonnet|haiku)-4 catch-all, so it
        needs its own model_config_limits entry."""
        assert get_model_max_output_tokens("us.anthropic.claude-sonnet-5") == 128_000
        assert get_model_max_output_tokens("us.anthropic.claude-sonnet-5:1m") == 128_000
        assert (
            get_model_max_output_tokens("global.anthropic.claude-sonnet-5") == 128_000
        )

    def test_older_opus_versions_return_64k(self):
        """Claude Opus 4.5 returns 64,000 max tokens. (Opus 4.6 is 128K — see
        test_claude46_models_return_128k.)"""
        assert (
            get_model_max_output_tokens("us.anthropic.claude-opus-4-5-20250514-v1:0")
            == 64_000
        )
