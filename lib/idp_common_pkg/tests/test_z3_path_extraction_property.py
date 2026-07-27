# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Property-based tests for path-based extraction correctness.

Feature: z3-dual-engine-rule-validation, Property 7: Path-Based Extraction Correctness

Validates: Requirements 6.1, 6.2
"""

from hypothesis import assume, given, settings
from hypothesis import strategies as st
from idp_common.rule_validation.z3.data_extractor import DataExtractor

# --- Strategies ---

# Leaf values that can appear in nested dictionaries
leaf_values = st.one_of(
    st.integers(min_value=-10000, max_value=10000),
    st.floats(min_value=-10000, max_value=10000, allow_nan=False, allow_infinity=False),
    st.text(
        min_size=0, max_size=50, alphabet=st.characters(categories=("L", "N", "P"))
    ),
    st.booleans(),
    st.none(),
)

# Valid dictionary keys (non-empty strings without dots to avoid path ambiguity)
valid_keys = st.text(
    alphabet=st.characters(categories=("L", "N"), whitelist_characters="_-"),
    min_size=1,
    max_size=20,
).filter(lambda s: "." not in s and len(s.strip()) > 0)


# Strategy to generate nested dictionaries with known paths
@st.composite
def nested_dict_with_path(draw):
    """
    Generate a nested dictionary and a valid dot-notation path that resolves to a value.

    Returns a tuple of (nested_dict, path, expected_value).
    """
    # Decide depth (1 to 5 levels)
    depth = draw(st.integers(min_value=1, max_value=5))

    # Generate keys for each level
    keys = [draw(valid_keys) for _ in range(depth)]

    # Generate the leaf value
    value = draw(leaf_values)

    # Build the nested dictionary from inside out
    nested = value
    for key in reversed(keys):
        nested = {key: nested}

    # Add some sibling keys at various levels to make the dict more realistic
    current = nested
    for i, key in enumerate(keys[:-1]):
        # Add 0-2 sibling keys at this level
        num_siblings = draw(st.integers(min_value=0, max_value=2))
        for _ in range(num_siblings):
            sibling_key = draw(valid_keys)
            if sibling_key != key:
                current[sibling_key] = draw(leaf_values)
        current = current[key]

    # Build the dot-notation path
    path = ".".join(keys)

    return nested, path, value


@st.composite
def nested_dict_with_invalid_path(draw):
    """
    Generate a nested dictionary and an invalid dot-notation path that does NOT resolve.

    Returns a tuple of (nested_dict, invalid_path).
    """
    # Generate a base nested dict
    depth = draw(st.integers(min_value=1, max_value=4))
    keys = [draw(valid_keys) for _ in range(depth)]
    value = draw(leaf_values)

    nested = value
    for key in reversed(keys):
        nested = {key: nested}

    # Generate an invalid path by using a key that doesn't exist
    invalid_key = draw(valid_keys)
    # Ensure the invalid key is different from the actual keys
    assume(invalid_key not in keys)

    # Strategy 1: Replace one of the path components with a non-existent key
    strategy = draw(st.integers(min_value=0, max_value=2))

    if strategy == 0:
        # Completely wrong first key
        invalid_path = (
            invalid_key + "." + ".".join(keys[1:]) if len(keys) > 1 else invalid_key
        )
    elif strategy == 1:
        # Valid prefix but wrong last key
        if len(keys) > 1:
            invalid_path = ".".join(keys[:-1]) + "." + invalid_key
        else:
            invalid_path = invalid_key
    else:
        # Path that goes deeper than the dict
        invalid_path = ".".join(keys) + "." + invalid_key

    return nested, invalid_path


@st.composite
def path_through_non_dict(draw):
    """
    Generate a dictionary where the path tries to traverse through a non-dict value.

    Returns a tuple of (nested_dict, invalid_path).
    """
    # Create a dict where an intermediate value is not a dict
    key1 = draw(valid_keys)
    key2 = draw(valid_keys)
    assume(key1 != key2)

    # The value at key1 is a leaf (not a dict), so key1.key2 should fail
    leaf = draw(
        st.one_of(
            st.integers(min_value=-100, max_value=100),
            st.text(min_size=1, max_size=20),
            st.booleans(),
        )
    )

    nested = {key1: leaf}
    invalid_path = f"{key1}.{key2}"

    return nested, invalid_path


# --- Property Tests ---


class TestPathBasedExtractionValidPaths:
    """Property tests for valid path-based extraction.

    **Validates: Requirements 6.1**
    """

    @given(data=nested_dict_with_path())
    @settings(max_examples=100)
    def test_valid_path_returns_correct_value(self, data):
        """For any nested dictionary and a valid dot-notation path that resolves to a value,
        the DataExtractor's path-based lookup SHALL return the value at that path.

        **Validates: Requirements 6.1**
        """
        nested_dict, path, expected_value = data
        extractor = DataExtractor()

        result = extractor._extract_path(nested_dict, path)

        assert result == expected_value, (
            f"Expected value {expected_value!r} at path '{path}', got {result!r}"
        )

    @given(data=nested_dict_with_path())
    @settings(max_examples=100)
    def test_valid_path_extraction_is_deterministic(self, data):
        """Extracting the same path from the same dict always returns the same value.

        **Validates: Requirements 6.1**
        """
        nested_dict, path, expected_value = data
        extractor = DataExtractor()

        result1 = extractor._extract_path(nested_dict, path)
        result2 = extractor._extract_path(nested_dict, path)

        assert result1 == result2, (
            f"Non-deterministic extraction: first={result1!r}, second={result2!r}"
        )


class TestPathBasedExtractionInvalidPaths:
    """Property tests for invalid path-based extraction.

    **Validates: Requirements 6.2**
    """

    @given(data=nested_dict_with_invalid_path())
    @settings(max_examples=100)
    def test_invalid_path_returns_none(self, data):
        """For paths that do not resolve in the nested dictionary,
        the DataExtractor's path-based lookup SHALL return None.

        **Validates: Requirements 6.2**
        """
        nested_dict, invalid_path = data
        extractor = DataExtractor()

        result = extractor._extract_path(nested_dict, invalid_path)

        assert result is None, (
            f"Expected None for invalid path '{invalid_path}', got {result!r}"
        )

    @given(data=path_through_non_dict())
    @settings(max_examples=100)
    def test_path_through_non_dict_returns_none(self, data):
        """For paths that try to traverse through a non-dict value,
        the DataExtractor's path-based lookup SHALL return None.

        **Validates: Requirements 6.2**
        """
        nested_dict, invalid_path = data
        extractor = DataExtractor()

        result = extractor._extract_path(nested_dict, invalid_path)

        assert result is None, (
            f"Expected None for path '{invalid_path}' through non-dict, got {result!r}"
        )

    @given(key=valid_keys)
    @settings(max_examples=100)
    def test_path_in_empty_dict_returns_none(self, key):
        """For any path in an empty dictionary, extraction SHALL return None.

        **Validates: Requirements 6.2**
        """
        extractor = DataExtractor()

        result = extractor._extract_path({}, key)

        assert result is None, (
            f"Expected None for path '{key}' in empty dict, got {result!r}"
        )


class TestPathBasedExtractionEdgeCases:
    """Property tests for edge cases in path-based extraction.

    **Validates: Requirements 6.1, 6.2**
    """

    @given(key=valid_keys, value=leaf_values)
    @settings(max_examples=100)
    def test_single_level_path_returns_value(self, key, value):
        """A single-component path (no dots) correctly retrieves top-level values.

        **Validates: Requirements 6.1**
        """
        data = {key: value}
        extractor = DataExtractor()

        result = extractor._extract_path(data, key)

        assert result == value, (
            f"Expected {value!r} for single-level path '{key}', got {result!r}"
        )

    @given(data=nested_dict_with_path())
    @settings(max_examples=100)
    def test_cache_does_not_affect_correctness(self, data):
        """Caching does not affect the correctness of path extraction.

        **Validates: Requirements 6.1**
        """
        nested_dict, path, expected_value = data
        extractor = DataExtractor()

        # First call populates cache
        result1 = extractor._extract_path(nested_dict, path)
        # Second call uses cache
        result2 = extractor._extract_path(nested_dict, path)
        # Clear cache and extract again
        extractor.clear_cache()
        result3 = extractor._extract_path(nested_dict, path)

        assert result1 == expected_value
        assert result2 == expected_value
        assert result3 == expected_value
