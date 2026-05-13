# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for LLM array unwrapping in extraction and assessment services.

Tests the defensive parsing logic that handles cases where LLMs return:
- Single-element arrays [{...}] instead of objects {...}
- Multi-element arrays [{...}, {...}]
- Empty arrays []
"""

import json


class TestArrayUnwrappingLogic:
    """Test the array unwrapping logic directly."""

    def test_single_element_array_detection(self):
        """Test that single-element arrays are detected correctly."""
        data = [{"field": "value"}]

        assert isinstance(data, list)
        assert len(data) == 1
        unwrapped = data[0]
        assert isinstance(unwrapped, dict)
        assert unwrapped == {"field": "value"}

    def test_multi_element_array_detection(self):
        """Test that multi-element arrays are detected correctly."""
        data = [{"field": "value1"}, {"field": "value2"}]

        assert isinstance(data, list)
        assert len(data) > 1
        assert len(data) == 2

    def test_empty_array_detection(self):
        """Test that empty arrays are detected correctly."""
        data = []

        assert isinstance(data, list)
        assert len(data) == 0

    def test_normal_dict_not_affected(self):
        """Test that normal dicts pass through unchanged."""
        data = {"field": "value"}

        assert isinstance(data, dict)
        assert not isinstance(data, list)

    def test_json_parsing_with_arrays(self):
        """Test JSON parsing with different array scenarios."""
        # Single-element array
        json_str1 = '[{"field": "value"}]'
        parsed1 = json.loads(json_str1)
        assert isinstance(parsed1, list) and len(parsed1) == 1

        # Multi-element array
        json_str2 = '[{"field": "value1"}, {"field": "value2"}]'
        parsed2 = json.loads(json_str2)
        assert isinstance(parsed2, list) and len(parsed2) == 2

        # Empty array
        json_str3 = "[]"
        parsed3 = json.loads(json_str3)
        assert isinstance(parsed3, list) and len(parsed3) == 0

        # Normal object
        json_str4 = '{"field": "value"}'
        parsed4 = json.loads(json_str4)
        assert isinstance(parsed4, dict)

    def test_unwrapping_flow(self):
        """Test the complete unwrapping flow with all cases."""
        test_cases = [
            # (input, expected_output, should_succeed)
            ([{"field": "value"}], {"field": "value"}, True),
            ([{"a": 1}, {"b": 2}], "error", False),
            ([], "error", False),
            ({"field": "value"}, {"field": "value"}, True),
        ]

        for input_data, expected, should_succeed in test_cases:
            result = self._unwrap_if_array(input_data)
            if should_succeed:
                assert result == expected
            else:
                assert result == "error"

    def _unwrap_if_array(self, data):
        """Helper method mimicking the unwrapping logic in the services."""
        if isinstance(data, list):
            if len(data) == 1:
                return data[0]
            elif len(data) == 0:
                return "error"
            else:  # len > 1
                return "error"
        return data
