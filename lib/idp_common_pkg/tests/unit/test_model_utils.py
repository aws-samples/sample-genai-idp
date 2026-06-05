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
        """Test Claude 4 Sonnet/Haiku and older Opus versions return 64,000 max tokens."""
        # Sonnet 4.x
        assert (
            get_model_max_output_tokens("us.anthropic.claude-sonnet-4-20250514-v1:0")
            == 64_000
        )
        assert get_model_max_output_tokens("eu.anthropic.claude-sonnet-4-6") == 64_000
        # Haiku 4.x
        assert (
            get_model_max_output_tokens("us.anthropic.claude-haiku-4-5-20251001-v1:0")
            == 64_000
        )
        # Older Opus versions (4.5, 4.6)
        assert (
            get_model_max_output_tokens("us.anthropic.claude-opus-4-5-20250514-v1:0")
            == 64_000
        )
        assert (
            get_model_max_output_tokens("us.anthropic.claude-opus-4-6-20250514-v1:0")
            == 64_000
        )

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

    def test_older_opus_versions_return_64k(self):
        """Test Claude Opus 4.5/4.6 return 64,000 max tokens."""
        assert (
            get_model_max_output_tokens("us.anthropic.claude-opus-4-5-20250514-v1:0")
            == 64_000
        )
        assert (
            get_model_max_output_tokens("us.anthropic.claude-opus-4-6-20250514-v1:0")
            == 64_000
        )
