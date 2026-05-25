# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Property-based tests for Z3 configuration model validation.

Feature: z3-dual-engine-rule-validation, Property 2: Z3 Config Model Validation

Validates: Requirements 3.1, 3.2, 3.3, 3.5
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from pydantic import ValidationError

from idp_common.config.models import (
    RuleValidationConfig,
    Z3RuleTranslatorConfig,
    Z3ValueExtractionConfig,
)


# --- Strategies ---

# Valid model strings: non-empty, up to 256 chars
valid_model_strings = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=256,
)

# Invalid model strings: too long (> 256 chars)
too_long_model_strings = st.text(
    alphabet=st.characters(categories=("L", "N")),
    min_size=257,
    max_size=512,
)

# Valid temperatures: floats in [0.0, 1.0]
valid_temperatures = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Invalid temperatures: floats outside [0.0, 1.0]
invalid_temperatures_below = st.floats(max_value=-0.001, allow_nan=False, allow_infinity=False)
invalid_temperatures_above = st.floats(min_value=1.001, allow_nan=False, allow_infinity=False)

# Valid max_tokens: integers > 0
valid_max_tokens = st.integers(min_value=1, max_value=1_000_000)

# Invalid max_tokens: integers <= 0
invalid_max_tokens = st.integers(max_value=0)

# Valid z3_timeout_ms: integers in (0, 300000]
valid_z3_timeout = st.integers(min_value=1, max_value=300000)

# Invalid z3_timeout_ms: integers <= 0 or > 300000
invalid_z3_timeout_below = st.integers(max_value=0)
invalid_z3_timeout_above = st.integers(min_value=300001, max_value=1_000_000)


# --- Property Tests: Z3RuleTranslatorConfig ---


class TestZ3RuleTranslatorConfigModelField:
    """Property tests for Z3RuleTranslatorConfig.model field validation."""

    @given(model=valid_model_strings)
    @settings(max_examples=100)
    def test_valid_model_strings_accepted(self, model: str):
        """Valid model strings (1-256 chars) are accepted.

        **Validates: Requirements 3.5**
        """
        config = Z3RuleTranslatorConfig(model=model)
        assert config.model == model
        assert 1 <= len(config.model) <= 256

    @given(model=too_long_model_strings)
    @settings(max_examples=100)
    def test_model_strings_exceeding_256_chars_rejected(self, model: str):
        """Model strings exceeding 256 characters are rejected.

        **Validates: Requirements 3.5**
        """
        with pytest.raises(ValidationError) as exc_info:
            Z3RuleTranslatorConfig(model=model)
        assert "model" in str(exc_info.value).lower() or "max_length" in str(exc_info.value).lower()


class TestZ3RuleTranslatorConfigTemperature:
    """Property tests for Z3RuleTranslatorConfig.temperature field validation."""

    @given(temp=valid_temperatures)
    @settings(max_examples=100)
    def test_valid_temperatures_accepted(self, temp: float):
        """Temperatures in [0.0, 1.0] are accepted.

        **Validates: Requirements 3.1, 3.2**
        """
        config = Z3RuleTranslatorConfig(temperature=temp)
        assert 0.0 <= config.temperature <= 1.0

    @given(temp=invalid_temperatures_below)
    @settings(max_examples=100)
    def test_temperatures_below_zero_rejected(self, temp: float):
        """Temperatures below 0.0 are rejected.

        **Validates: Requirements 3.1, 3.2**
        """
        with pytest.raises(ValidationError):
            Z3RuleTranslatorConfig(temperature=temp)

    @given(temp=invalid_temperatures_above)
    @settings(max_examples=100)
    def test_temperatures_above_one_rejected(self, temp: float):
        """Temperatures above 1.0 are rejected.

        **Validates: Requirements 3.1, 3.2**
        """
        with pytest.raises(ValidationError):
            Z3RuleTranslatorConfig(temperature=temp)


class TestZ3RuleTranslatorConfigMaxTokens:
    """Property tests for Z3RuleTranslatorConfig.max_tokens field validation."""

    @given(tokens=valid_max_tokens)
    @settings(max_examples=100)
    def test_positive_max_tokens_accepted(self, tokens: int):
        """max_tokens > 0 are accepted.

        **Validates: Requirements 3.1, 3.2**
        """
        config = Z3RuleTranslatorConfig(max_tokens=tokens)
        assert config.max_tokens == tokens
        assert config.max_tokens > 0

    @given(tokens=invalid_max_tokens)
    @settings(max_examples=100)
    def test_non_positive_max_tokens_rejected(self, tokens: int):
        """max_tokens <= 0 are rejected.

        **Validates: Requirements 3.1, 3.2**
        """
        with pytest.raises(ValidationError):
            Z3RuleTranslatorConfig(max_tokens=tokens)


# --- Property Tests: Z3ValueExtractionConfig ---


class TestZ3ValueExtractionConfigModelField:
    """Property tests for Z3ValueExtractionConfig.model field validation."""

    @given(model=valid_model_strings)
    @settings(max_examples=100)
    def test_valid_model_strings_accepted(self, model: str):
        """Valid model strings (1-256 chars) are accepted.

        **Validates: Requirements 3.5**
        """
        config = Z3ValueExtractionConfig(model=model)
        assert config.model == model
        assert 1 <= len(config.model) <= 256

    @given(model=too_long_model_strings)
    @settings(max_examples=100)
    def test_model_strings_exceeding_256_chars_rejected(self, model: str):
        """Model strings exceeding 256 characters are rejected.

        **Validates: Requirements 3.5**
        """
        with pytest.raises(ValidationError) as exc_info:
            Z3ValueExtractionConfig(model=model)
        assert "model" in str(exc_info.value).lower() or "max_length" in str(exc_info.value).lower()


class TestZ3ValueExtractionConfigTemperature:
    """Property tests for Z3ValueExtractionConfig.temperature field validation."""

    @given(temp=valid_temperatures)
    @settings(max_examples=100)
    def test_valid_temperatures_accepted(self, temp: float):
        """Temperatures in [0.0, 1.0] are accepted.

        **Validates: Requirements 3.1, 3.2**
        """
        config = Z3ValueExtractionConfig(temperature=temp)
        assert 0.0 <= config.temperature <= 1.0

    @given(temp=invalid_temperatures_below)
    @settings(max_examples=100)
    def test_temperatures_below_zero_rejected(self, temp: float):
        """Temperatures below 0.0 are rejected.

        **Validates: Requirements 3.1, 3.2**
        """
        with pytest.raises(ValidationError):
            Z3ValueExtractionConfig(temperature=temp)

    @given(temp=invalid_temperatures_above)
    @settings(max_examples=100)
    def test_temperatures_above_one_rejected(self, temp: float):
        """Temperatures above 1.0 are rejected.

        **Validates: Requirements 3.1, 3.2**
        """
        with pytest.raises(ValidationError):
            Z3ValueExtractionConfig(temperature=temp)


class TestZ3ValueExtractionConfigMaxTokens:
    """Property tests for Z3ValueExtractionConfig.max_tokens field validation."""

    @given(tokens=valid_max_tokens)
    @settings(max_examples=100)
    def test_positive_max_tokens_accepted(self, tokens: int):
        """max_tokens > 0 are accepted.

        **Validates: Requirements 3.1, 3.2**
        """
        config = Z3ValueExtractionConfig(max_tokens=tokens)
        assert config.max_tokens == tokens
        assert config.max_tokens > 0

    @given(tokens=invalid_max_tokens)
    @settings(max_examples=100)
    def test_non_positive_max_tokens_rejected(self, tokens: int):
        """max_tokens <= 0 are rejected.

        **Validates: Requirements 3.1, 3.2**
        """
        with pytest.raises(ValidationError):
            Z3ValueExtractionConfig(max_tokens=tokens)


# --- Property Tests: RuleValidationConfig.z3_timeout_ms ---


class TestZ3TimeoutMs:
    """Property tests for RuleValidationConfig.z3_timeout_ms field validation."""

    @given(timeout=valid_z3_timeout)
    @settings(max_examples=100)
    def test_valid_timeout_values_accepted(self, timeout: int):
        """z3_timeout_ms in (0, 300000] are accepted.

        **Validates: Requirements 3.3**
        """
        config = RuleValidationConfig(z3_timeout_ms=timeout)
        assert config.z3_timeout_ms == timeout
        assert 1 <= config.z3_timeout_ms <= 300000

    @given(timeout=invalid_z3_timeout_below)
    @settings(max_examples=100)
    def test_timeout_zero_or_below_rejected(self, timeout: int):
        """z3_timeout_ms <= 0 are rejected.

        **Validates: Requirements 3.3**
        """
        with pytest.raises(ValidationError):
            RuleValidationConfig(z3_timeout_ms=timeout)

    @given(timeout=invalid_z3_timeout_above)
    @settings(max_examples=100)
    def test_timeout_above_300000_rejected(self, timeout: int):
        """z3_timeout_ms > 300000 are rejected.

        **Validates: Requirements 3.3**
        """
        with pytest.raises(ValidationError):
            RuleValidationConfig(z3_timeout_ms=timeout)
