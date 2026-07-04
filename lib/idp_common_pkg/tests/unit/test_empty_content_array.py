# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for empty content array handling in LLM response parsing.

Tests the defensive parsing logic that handles cases where LLMs return:
- Empty content arrays []
- Missing content field
- Normal content arrays with data
"""

from idp_common.bedrock.client import BedrockClient


class TestBedrockClientEmptyContent:
    """Test empty content array handling in BedrockClient.extract_text_from_response."""

    def test_extract_text_with_normal_content(self):
        """Normal content array should work as expected."""
        client = BedrockClient()
        response = {
            "output": {
                "message": {"content": [{"text": "This is the classification result"}]}
            }
        }

        result = client.extract_text_from_response(response)
        assert result == "This is the classification result"

    def test_extract_text_with_empty_content_array(self):
        """Empty content array should return empty string."""
        client = BedrockClient()
        response = {"output": {"message": {"content": []}}}

        result = client.extract_text_from_response(response)
        assert result == ""

    def test_extract_text_with_missing_content_field(self):
        """Missing content field should return empty string."""
        client = BedrockClient()
        response = {"output": {"message": {}}}

        result = client.extract_text_from_response(response)
        assert result == ""

    def test_extract_text_with_nested_response(self):
        """Should handle response wrapped in 'response' key."""
        client = BedrockClient()
        response = {
            "response": {
                "output": {"message": {"content": [{"text": "nested response text"}]}}
            }
        }

        result = client.extract_text_from_response(response)
        assert result == "nested response text"

    def test_extract_text_with_none_content(self):
        """Should handle None content gracefully."""
        client = BedrockClient()
        response = {"output": {"message": {"content": None}}}

        result = client.extract_text_from_response(response)
        assert result == ""

    def test_extract_text_with_empty_text_field(self):
        """Should handle content with empty text field."""
        client = BedrockClient()
        response = {"output": {"message": {"content": [{"text": ""}]}}}

        result = client.extract_text_from_response(response)
        assert result == ""

    def test_extract_text_with_missing_text_field(self):
        """Should handle content without text field."""
        client = BedrockClient()
        response = {"output": {"message": {"content": [{"image": "data"}]}}}

        result = client.extract_text_from_response(response)
        assert result == ""

    def test_extract_text_with_multiple_content_items(self):
        """Should concatenate text across all text blocks."""
        client = BedrockClient()
        response = {
            "output": {
                "message": {
                    "content": [
                        {"text": "first item"},
                        {"text": "second item"},
                    ]
                }
            }
        }

        result = client.extract_text_from_response(response)
        assert result == "first itemsecond item"

    def test_extract_text_skips_leading_reasoning_block(self):
        """Reasoning models (Claude Sonnet 5 / 4.6+, extended thinking on) emit a
        reasoningContent block BEFORE the answer text block. The parser must skip
        the reasoning block and return the text, not content[0] (regression: an
        empty string caused every extraction/classification to fail)."""
        client = BedrockClient()
        response = {
            "output": {
                "message": {
                    "content": [
                        {
                            "reasoningContent": {
                                "reasoningText": {"text": "let me think about this"}
                            }
                        },
                        {"text": '{"result": "ok"}'},
                    ]
                }
            }
        }

        result = client.extract_text_from_response(response)
        assert result == '{"result": "ok"}'

    def test_extract_text_reasoning_only_returns_empty(self):
        """A response with only a reasoning block (no text) returns empty string."""
        client = BedrockClient()
        response = {
            "output": {
                "message": {
                    "content": [
                        {"reasoningContent": {"reasoningText": {"text": "thinking"}}}
                    ]
                }
            }
        }

        result = client.extract_text_from_response(response)
        assert result == ""


class TestEmptyContentArrayDetection:
    """Test the logic for detecting and handling empty content arrays."""

    def test_empty_list_detection(self):
        """Test basic empty list detection logic."""
        content = []
        # This is the check pattern used in the fixes
        assert not content or len(content) == 0

    def test_nonempty_list_detection(self):
        """Test that non-empty lists pass the check."""
        content = [{"text": "data"}]
        # Should NOT trigger the empty check
        assert not (not content or len(content) == 0)

    def test_none_detection(self):
        """Test that None triggers the empty check."""
        content = None
        # None should be treated as empty
        # Use .get() with default [] like in the code
        content_array = {} if content is None else content
        result = (
            content_array.get("content", []) if isinstance(content_array, dict) else []
        )
        assert not result or len(result) == 0
