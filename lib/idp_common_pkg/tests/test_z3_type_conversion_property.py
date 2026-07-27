# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Property-based tests for Z3 type conversion correctness.

Feature: z3-dual-engine-rule-validation, Property 8: Type Conversion Correctness

For any string representation of a value and a target parameter type (Int, Real, Bool, String),
if the string is a valid representation of that type (e.g., "42" for Int, "3.14" for Real,
"true" for Bool), conversion SHALL succeed and produce the correctly-typed value. If the string
is not a valid representation (e.g., "abc" for Int), conversion SHALL fail and the parameter
SHALL be treated as not extracted.

**Validates: Requirements 6.5, 6.6**
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from idp_common.rule_validation.z3.data_extractor import DataExtractor
from idp_common.rule_validation.z3.exceptions import ExtractionError

# --- Strategies ---

# Valid integer strings
valid_int_strings = st.integers(min_value=-1_000_000, max_value=1_000_000).map(str)

# Valid real/float strings
valid_real_strings = st.floats(
    min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False
).map(str)

# Valid boolean strings (all accepted representations)
valid_bool_true_strings = st.sampled_from(
    ["yes", "Yes", "YES", "true", "True", "TRUE", "1"]
)
valid_bool_false_strings = st.sampled_from(
    ["no", "No", "NO", "false", "False", "FALSE", "0"]
)
valid_bool_strings = st.one_of(valid_bool_true_strings, valid_bool_false_strings)

# Arbitrary strings for String type (any string is valid)
valid_string_values = st.text(min_size=0, max_size=200)

# Invalid integer strings: alphabetic or mixed content that cannot parse as int
invalid_int_strings = st.from_regex(r"[a-zA-Z][a-zA-Z0-9]*", fullmatch=True).filter(
    lambda s: not _is_valid_int(s)
)

# Invalid real strings: alphabetic content that cannot parse as float
invalid_real_strings = st.from_regex(r"[a-zA-Z][a-zA-Z0-9]*", fullmatch=True).filter(
    lambda s: not _is_valid_real(s)
)

# Invalid boolean strings: strings not in the accepted set
invalid_bool_strings = st.text(min_size=2, max_size=20).filter(
    lambda s: (
        s.strip().lower() not in ("yes", "no", "true", "false", "1", "0")
        and len(s.strip()) > 0
    )
)


def _is_valid_int(s: str) -> bool:
    """Check if a string can be parsed as an integer."""
    try:
        int(s.strip())
        return True
    except (ValueError, AttributeError):
        return False


def _is_valid_real(s: str) -> bool:
    """Check if a string can be parsed as a float."""
    try:
        float(s.strip())
        return True
    except (ValueError, AttributeError):
        return False


# --- Test Class ---


class TestTypeConversionCorrectness:
    """
    Property 8: Type Conversion Correctness

    For any string representation of a value and a target parameter type,
    if the string is a valid representation of that type, conversion SHALL succeed
    and produce the correctly-typed value. If the string is not a valid representation,
    conversion SHALL fail and the parameter SHALL be treated as not extracted.

    **Validates: Requirements 6.5, 6.6**
    """

    def setup_method(self):
        """Create a fresh DataExtractor for each test."""
        self.extractor = DataExtractor()

    # --- Valid Int Conversions ---

    @given(value_str=valid_int_strings)
    @settings(max_examples=100)
    def test_valid_int_strings_convert_correctly(self, value_str: str):
        """Valid integer strings convert to int type with correct value.

        **Validates: Requirements 6.5**
        """
        result = self.extractor._convert_type(value_str, "Int")
        assert isinstance(result, int)
        assert result == int(value_str.strip())

    # --- Valid Real Conversions ---

    @given(value_str=valid_real_strings)
    @settings(max_examples=100)
    def test_valid_real_strings_convert_correctly(self, value_str: str):
        """Valid float strings convert to float type with correct value.

        **Validates: Requirements 6.5**
        """
        result = self.extractor._convert_type(value_str, "Real")
        assert isinstance(result, float)
        assert result == float(value_str.strip())

    # --- Valid Bool Conversions ---

    @given(value_str=valid_bool_true_strings)
    @settings(max_examples=100)
    def test_valid_bool_true_strings_convert_to_true(self, value_str: str):
        """Valid boolean true strings ('yes', 'true', '1') convert to True.

        **Validates: Requirements 6.5**
        """
        result = self.extractor._convert_type(value_str, "Bool")
        assert isinstance(result, bool)
        assert result is True

    @given(value_str=valid_bool_false_strings)
    @settings(max_examples=100)
    def test_valid_bool_false_strings_convert_to_false(self, value_str: str):
        """Valid boolean false strings ('no', 'false', '0') convert to False.

        **Validates: Requirements 6.5**
        """
        result = self.extractor._convert_type(value_str, "Bool")
        assert isinstance(result, bool)
        assert result is False

    # --- Valid String Conversions ---

    @given(value_str=valid_string_values)
    @settings(max_examples=100)
    def test_string_type_preserves_value_exactly(self, value_str: str):
        """String type preserves the exact input value without modification.

        **Validates: Requirements 6.5**
        """
        result = self.extractor._convert_type(value_str, "String")
        assert isinstance(result, str)
        assert result == value_str

    # --- Invalid Int Conversions ---

    @given(value_str=invalid_int_strings)
    @settings(max_examples=100)
    def test_invalid_int_strings_raise_extraction_error(self, value_str: str):
        """Non-numeric strings fail conversion to Int with ExtractionError.

        **Validates: Requirements 6.6**
        """
        with pytest.raises(ExtractionError) as exc_info:
            self.extractor._convert_type(value_str, "Int")
        assert "Type conversion failed" in exc_info.value.message

    # --- Invalid Real Conversions ---

    @given(value_str=invalid_real_strings)
    @settings(max_examples=100)
    def test_invalid_real_strings_raise_extraction_error(self, value_str: str):
        """Non-numeric strings fail conversion to Real with ExtractionError.

        **Validates: Requirements 6.6**
        """
        with pytest.raises(ExtractionError) as exc_info:
            self.extractor._convert_type(value_str, "Real")
        assert "Type conversion failed" in exc_info.value.message

    # --- Invalid Bool Conversions ---

    @given(value_str=invalid_bool_strings)
    @settings(max_examples=100)
    def test_invalid_bool_strings_raise_extraction_error(self, value_str: str):
        """Strings not in accepted bool set fail conversion with ExtractionError.

        **Validates: Requirements 6.6**
        """
        with pytest.raises(ExtractionError) as exc_info:
            self.extractor._convert_type(value_str, "Bool")
        assert "Type conversion failed" in exc_info.value.message

    # --- Empty String Handling ---

    def test_empty_string_fails_int_conversion(self):
        """Empty string cannot be converted to Int.

        **Validates: Requirements 6.6**
        """
        with pytest.raises(ExtractionError):
            self.extractor._convert_type("", "Int")

    def test_empty_string_fails_real_conversion(self):
        """Empty string cannot be converted to Real.

        **Validates: Requirements 6.6**
        """
        with pytest.raises(ExtractionError):
            self.extractor._convert_type("", "Real")

    def test_whitespace_only_fails_int_conversion(self):
        """Whitespace-only string cannot be converted to Int.

        **Validates: Requirements 6.6**
        """
        with pytest.raises(ExtractionError):
            self.extractor._convert_type("   ", "Int")

    def test_whitespace_only_fails_real_conversion(self):
        """Whitespace-only string cannot be converted to Real.

        **Validates: Requirements 6.6**
        """
        with pytest.raises(ExtractionError):
            self.extractor._convert_type("   ", "Real")

    # --- Numeric Type Passthrough ---

    @given(value=st.integers(min_value=-1_000_000, max_value=1_000_000))
    @settings(max_examples=100)
    def test_int_values_pass_through_for_int_type(self, value: int):
        """Integer values pass through directly when target type is Int.

        **Validates: Requirements 6.5**
        """
        result = self.extractor._convert_type(value, "Int")
        assert isinstance(result, int)
        assert result == value

    @given(
        value=st.floats(
            min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False
        )
    )
    @settings(max_examples=100)
    def test_numeric_values_convert_to_real(self, value: float):
        """Numeric values (int or float) convert to float for Real type.

        **Validates: Requirements 6.5**
        """
        result = self.extractor._convert_type(value, "Real")
        assert isinstance(result, float)
        assert result == float(value)

    # --- None Handling ---

    def test_none_value_returns_none_for_all_types(self):
        """None values pass through as None regardless of target type.

        **Validates: Requirements 6.5**
        """
        for type_name in ("Int", "Real", "Bool", "String"):
            result = self.extractor._convert_type(None, type_name)
            assert result is None

    # --- Integer with whitespace ---

    @given(value=st.integers(min_value=-1_000_000, max_value=1_000_000))
    @settings(max_examples=100)
    def test_int_strings_with_whitespace_convert_correctly(self, value: int):
        """Integer strings with leading/trailing whitespace still convert correctly.

        **Validates: Requirements 6.5**
        """
        value_str = f"  {value}  "
        result = self.extractor._convert_type(value_str, "Int")
        assert isinstance(result, int)
        assert result == value

    # --- Bool with whitespace ---

    @given(value_str=valid_bool_strings)
    @settings(max_examples=100)
    def test_bool_strings_with_whitespace_convert_correctly(self, value_str: str):
        """Boolean strings with leading/trailing whitespace still convert correctly.

        **Validates: Requirements 6.5**
        """
        padded = f"  {value_str}  "
        result = self.extractor._convert_type(padded, "Bool")
        assert isinstance(result, bool)
