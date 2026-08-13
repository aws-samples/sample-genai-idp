# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Property-based tests for engine field validation.

Feature: z3-dual-engine-rule-validation, Property 1: Engine Field Validation Rejects Invalid Values

For any string value that is not the case-sensitive literal "llm" or "z3",
when used as the x-aws-idp-validation-engine field during configuration validation,
the system SHALL reject it with a validation error indicating the invalid value
and the set of accepted values.

**Validates: Requirements 2.5, 2.6**
"""

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from idp_common.config.models import IDPConfig
from idp_common.config.schema_constants import (
    VALID_VALIDATION_ENGINES,
    X_AWS_IDP_VALIDATION_ENGINE,
)

# --- Strategies ---

# Generate random strings that are NOT "llm" or "z3"
invalid_engine_strings = st.text(min_size=1, max_size=50).filter(
    lambda s: s not in VALID_VALIDATION_ENGINES
)

# Valid engine values
valid_engine_values = st.sampled_from(sorted(VALID_VALIDATION_ENGINES))


def _make_policy_classes_with_engine(engine_value: str) -> list:
    """Helper to create a policy_classes list with a single rule having the given engine value."""
    return [
        {
            "x-aws-idp-policy-type": "test-policy",
            "rule_properties": {
                "test_rule": {
                    "type": "string",
                    "description": "A test rule",
                    X_AWS_IDP_VALIDATION_ENGINE: engine_value,
                }
            },
        }
    ]


# --- Property Tests ---


class TestEngineFieldValidationRejectsInvalidValues:
    """Property 1: Engine Field Validation Rejects Invalid Values.

    For any string value that is not "llm" or "z3", the system SHALL reject
    it with a validation error indicating the invalid value and accepted values.

    **Validates: Requirements 2.5, 2.6**
    """

    @given(engine_value=invalid_engine_strings)
    @settings(max_examples=100)
    def test_invalid_engine_values_rejected(self, engine_value: str):
        """Any string not in {"llm", "z3"} is rejected with a validation error.

        **Validates: Requirements 2.5, 2.6**
        """
        policy_classes = _make_policy_classes_with_engine(engine_value)

        with pytest.raises(ValidationError) as exc_info:
            IDPConfig(policy_classes=policy_classes)

        error_str = str(exc_info.value)
        # Verify the error message mentions the invalid value
        assert engine_value in error_str
        # Verify the error message mentions accepted values
        assert "llm" in error_str
        assert "z3" in error_str

    @given(engine_value=valid_engine_values)
    @settings(max_examples=100)
    def test_valid_engine_values_accepted(self, engine_value: str):
        """The values "llm" and "z3" are always accepted.

        **Validates: Requirements 2.5, 2.6**
        """
        policy_classes = _make_policy_classes_with_engine(engine_value)

        # Should not raise
        config = IDPConfig(policy_classes=policy_classes)
        assert config.policy_classes == policy_classes


class TestEngineFieldCaseSensitivity:
    """Verify engine field validation is case-sensitive.

    **Validates: Requirements 2.6**
    """

    @given(
        engine_value=st.sampled_from(
            ["LLM", "Llm", "lLm", "Z3", "Z3", "z3 ", " z3", "LLM ", " llm"]
        )
    )
    @settings(max_examples=100)
    def test_case_variants_and_whitespace_rejected(self, engine_value: str):
        """Case variants and whitespace-padded values are rejected (case-sensitive).

        **Validates: Requirements 2.6**
        """
        assume(engine_value not in VALID_VALIDATION_ENGINES)
        policy_classes = _make_policy_classes_with_engine(engine_value)

        with pytest.raises(ValidationError):
            IDPConfig(policy_classes=policy_classes)


class TestEngineFieldAbsenceAccepted:
    """Verify that absent engine field does not trigger validation error.

    **Validates: Requirements 2.5**
    """

    def test_absent_engine_field_accepted(self):
        """When the engine field is absent from a rule, validation passes.

        **Validates: Requirements 2.5**
        """
        policy_classes = [
            {
                "x-aws-idp-policy-type": "test-policy",
                "rule_properties": {
                    "test_rule": {
                        "type": "string",
                        "description": "A test rule without engine field",
                    }
                },
            }
        ]

        # Should not raise
        config = IDPConfig(policy_classes=policy_classes)
        assert config.policy_classes == policy_classes
