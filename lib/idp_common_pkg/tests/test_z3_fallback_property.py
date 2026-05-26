# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Property-based tests for Z3-to-LLM fallback on error.

Feature: z3-dual-engine-rule-validation, Property 5: Z3-to-LLM Fallback on Error

For any rule assigned to the Z3 engine that encounters a translation, extraction,
or solver error, the service SHALL log a warning, then re-process that rule using
the LLM engine as a fallback. The final result for that rule SHALL be the LLM
engine's output (not "Information Not Found"), unless the LLM engine also fails.

**Validates: Requirements 4.5**
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from idp_common.config.schema_constants import (
    X_AWS_IDP_VALIDATION_ENGINE,
    VALIDATION_ENGINE_Z3,
)


# --- Strategies ---

# Strategy for random rule descriptions
rule_description_strategy = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "Z")),
    min_size=5,
    max_size=100,
).filter(lambda s: s.strip())

# Strategy for Z3 error reasoning messages
z3_error_reasoning_strategy = st.sampled_from([
    "Z3 engine error: TranslationError - Failed to translate rule to SMT-LIB",
    "Z3 engine error: ExtractionError - Could not extract parameter values",
    "Z3 engine error: ValidationError - Constraint parsing failed",
    "Z3 engine error: Solver timeout exceeded",
    "Z3 engine error: ValidationSystemError - General system failure",
    "Z3 engine error: Invalid RuleJSON structure",
])

# Strategy for LLM recommendation outcomes (Pass or Fail — valid LLM results)
llm_recommendation_strategy = st.sampled_from(["Pass", "Fail"])

# Strategy for policy type names
policy_type_strategy = st.text(
    alphabet=st.characters(categories=("L", "N")),
    min_size=3,
    max_size=30,
).filter(lambda s: s.strip())


@st.composite
def z3_failing_rules_strategy(draw):
    """Generate a list of rules assigned to Z3 that will raise errors.

    Each rule has a unique description and a Z3 error reasoning message.
    """
    num_rules = draw(st.integers(min_value=1, max_value=8))
    rules = []
    for i in range(num_rules):
        suffix = draw(
            st.text(
                alphabet=st.characters(categories=("L", "N")),
                min_size=3,
                max_size=30,
            ).filter(lambda s: s.strip())
        )
        description = f"Z3Rule {i}: {suffix}"
        error_reasoning = draw(z3_error_reasoning_strategy)
        llm_recommendation = draw(llm_recommendation_strategy)
        rules.append({
            "description": description,
            "error_reasoning": error_reasoning,
            "llm_recommendation": llm_recommendation,
        })
    return rules


# --- Helper Functions ---


def build_config_with_z3_rules(rules):
    """Build a config dict with a policy class containing Z3-assigned rules.

    Args:
        rules: List of dicts with "description" key.

    Returns:
        A config dict suitable for RuleValidationService._process_z3_rule_with_fallback.
    """
    rule_properties = {}
    for i, rule in enumerate(rules):
        prop = {
            "type": "string",
            "description": rule["description"],
            X_AWS_IDP_VALIDATION_ENGINE: VALIDATION_ENGINE_Z3,
        }
        rule_properties[f"rule_{i}"] = prop

    return {
        "policy_classes": [
            {
                "x-aws-idp-policy-type": "test-policy",
                "rule_properties": rule_properties,
            }
        ],
        "rule_validation": {
            "fact_extraction": {
                "model": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
            },
            "semaphore": 5,
            "max_chunk_size": 4000,
            "token_size": 1000,
            "overlap_percentage": 0.1,
        },
    }


# --- Property Tests ---


class TestZ3ToLLMFallbackOnError:
    """Property 5: Z3-to-LLM Fallback on Error.

    For any rule assigned to the Z3 engine that encounters a translation,
    extraction, or solver error, the service SHALL log a warning, then
    re-process that rule using the LLM engine as a fallback. The final
    result for that rule SHALL be the LLM engine's output (not
    "Information Not Found"), unless the LLM engine also fails.

    **Validates: Requirements 4.5**
    """

    @given(
        rule_description=rule_description_strategy,
        error_reasoning=z3_error_reasoning_strategy,
        llm_recommendation=llm_recommendation_strategy,
        policy_type=policy_type_strategy,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_z3_error_triggers_llm_fallback(
        self, rule_description, error_reasoning, llm_recommendation, policy_type
    ):
        """When Z3 returns "Information Not Found", the service falls back to LLM.

        The final result should be the LLM engine's output, not the Z3 error result.

        **Validates: Requirements 4.5**
        """
        with patch(
            "idp_common.rule_validation.service.RuleValidationService.__init__",
            return_value=None,
        ):
            from idp_common.rule_validation.service import RuleValidationService

            service = RuleValidationService.__new__(RuleValidationService)

            # Set up minimal required attributes
            service.config = MagicMock()
            service.config.rule_validation.semaphore = 5
            service.region = "us-east-1"
            service._semaphore = asyncio.Semaphore(5)
            service._z3_adapter = MagicMock()
            service.token_metrics = {}
            service.metrics_lock = asyncio.Lock()

            # Mock _process_z3_rule to return "Information Not Found" (Z3 failure)
            z3_error_result = {
                "rule_type": policy_type,
                "rule": rule_description,
                "recommendation": "Information Not Found",
                "reasoning": error_reasoning,
                "supporting_pages": [],
                "_z3_error": True,
            }

            async def mock_process_z3_rule(
                rule_description, policy_type, extraction_results, document_text, config
            ):
                return z3_error_result

            service._process_z3_rule = mock_process_z3_rule

            # Mock _process_rule_question to return a valid LLM result
            llm_result = {
                "policy_type": policy_type,
                "rule": rule_description,
                "recommendation": llm_recommendation,
                "reasoning": "LLM engine validated this rule successfully.",
                "supporting_pages": [],
            }

            async def mock_process_rule_question(
                rule, user_history, policy_type, config, extraction_results=None
            ):
                return llm_result

            service._process_rule_question = mock_process_rule_question

            # Execute the fallback method
            config = build_config_with_z3_rules([{"description": rule_description}])
            result = await service._process_z3_rule_with_fallback(
                rule_description=rule_description,
                policy_type=policy_type,
                extraction_results={},
                document_text="Sample document text for testing.",
                config=config,
            )

            # Verify: the final result is the LLM output, NOT the Z3 error
            assert result["recommendation"] != "Information Not Found", (
                f"Fallback failed: result still has Z3 error recommendation "
                f"'Information Not Found' instead of LLM result '{llm_recommendation}'"
            )
            assert result["recommendation"] == llm_recommendation, (
                f"Expected LLM recommendation '{llm_recommendation}', "
                f"got '{result['recommendation']}'"
            )
            assert result == llm_result, (
                f"Final result should be the LLM result, got: {result}"
            )

    @given(rules=z3_failing_rules_strategy())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_multiple_z3_failures_all_fallback_to_llm(self, rules):
        """When multiple Z3 rules fail, each one independently falls back to LLM.

        Every rule that Z3 fails on should get re-processed by LLM, and the
        final results should all be LLM outputs (not "Information Not Found").

        **Validates: Requirements 4.5**
        """
        with patch(
            "idp_common.rule_validation.service.RuleValidationService.__init__",
            return_value=None,
        ):
            from idp_common.rule_validation.service import RuleValidationService

            service = RuleValidationService.__new__(RuleValidationService)

            # Set up minimal required attributes
            service.config = MagicMock()
            service.config.rule_validation.semaphore = 5
            service.region = "us-east-1"
            service._semaphore = asyncio.Semaphore(5)
            service._z3_adapter = MagicMock()
            service.token_metrics = {}
            service.metrics_lock = asyncio.Lock()

            # Track calls to verify fallback happens for each rule
            z3_calls = []
            llm_calls = []

            # Map rule descriptions to their expected LLM recommendations
            expected_llm_results = {}
            for rule in rules:
                expected_llm_results[rule["description"]] = rule["llm_recommendation"]

            async def mock_process_z3_rule(
                rule_description, policy_type, extraction_results, document_text, config
            ):
                z3_calls.append(rule_description)
                # Find the matching rule's error reasoning
                matching_rule = next(
                    r for r in rules if r["description"] == rule_description
                )
                return {
                    "rule_type": policy_type,
                    "rule": rule_description,
                    "recommendation": "Information Not Found",
                    "reasoning": matching_rule["error_reasoning"],
                    "supporting_pages": [],
                    "_z3_error": True,
                }

            async def mock_process_rule_question(
                rule, user_history, policy_type, config, extraction_results=None
            ):
                llm_calls.append(rule)
                return {
                    "policy_type": policy_type,
                    "rule": rule,
                    "recommendation": expected_llm_results[rule],
                    "reasoning": "LLM engine validated this rule.",
                    "supporting_pages": [],
                }

            service._process_z3_rule = mock_process_z3_rule
            service._process_rule_question = mock_process_rule_question

            # Execute fallback for each rule
            config = build_config_with_z3_rules(rules)
            results = []
            for rule in rules:
                result = await service._process_z3_rule_with_fallback(
                    rule_description=rule["description"],
                    policy_type="test-policy",
                    extraction_results={},
                    document_text="Sample document text.",
                    config=config,
                )
                results.append(result)

            # Verify: Z3 was called for every rule
            assert len(z3_calls) == len(rules), (
                f"Expected Z3 to be called {len(rules)} times, "
                f"but was called {len(z3_calls)} times"
            )

            # Verify: LLM fallback was called for every rule (since all Z3 calls fail)
            assert len(llm_calls) == len(rules), (
                f"Expected LLM fallback to be called {len(rules)} times, "
                f"but was called {len(llm_calls)} times"
            )

            # Verify: no result has "Information Not Found" (all fell back to LLM)
            for i, result in enumerate(results):
                assert result["recommendation"] != "Information Not Found", (
                    f"Rule {i} ('{rules[i]['description'][:40]}...') still has "
                    f"'Information Not Found' after fallback — LLM result not used"
                )
                assert result["recommendation"] == rules[i]["llm_recommendation"], (
                    f"Rule {i} expected recommendation "
                    f"'{rules[i]['llm_recommendation']}', "
                    f"got '{result['recommendation']}'"
                )

    @given(
        rule_description=rule_description_strategy,
        policy_type=policy_type_strategy,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_z3_success_does_not_trigger_fallback(
        self, rule_description, policy_type
    ):
        """When Z3 succeeds (returns "Pass" or "Fail"), no LLM fallback occurs.

        The Z3 result should be returned directly without invoking the LLM engine.

        **Validates: Requirements 4.5**
        """
        with patch(
            "idp_common.rule_validation.service.RuleValidationService.__init__",
            return_value=None,
        ):
            from idp_common.rule_validation.service import RuleValidationService

            service = RuleValidationService.__new__(RuleValidationService)

            # Set up minimal required attributes
            service.config = MagicMock()
            service.config.rule_validation.semaphore = 5
            service.region = "us-east-1"
            service._semaphore = asyncio.Semaphore(5)
            service._z3_adapter = MagicMock()
            service.token_metrics = {}
            service.metrics_lock = asyncio.Lock()

            # Mock _process_z3_rule to return a successful result
            z3_success_result = {
                "rule_type": policy_type,
                "rule": rule_description,
                "recommendation": "Pass",
                "reasoning": "Z3 solver determined rule is satisfied.",
                "supporting_pages": [],
            }

            async def mock_process_z3_rule(
                rule_description, policy_type, extraction_results, document_text, config
            ):
                return z3_success_result

            service._process_z3_rule = mock_process_z3_rule

            # Mock _process_rule_question — should NOT be called
            llm_called = []

            async def mock_process_rule_question(
                rule, user_history, policy_type, config, extraction_results=None
            ):
                llm_called.append(rule)
                return {
                    "policy_type": policy_type,
                    "rule": rule,
                    "recommendation": "Fail",
                    "reasoning": "LLM should not have been called.",
                    "supporting_pages": [],
                }

            service._process_rule_question = mock_process_rule_question

            # Execute
            config = build_config_with_z3_rules([{"description": rule_description}])
            result = await service._process_z3_rule_with_fallback(
                rule_description=rule_description,
                policy_type=policy_type,
                extraction_results={},
                document_text="Sample document text.",
                config=config,
            )

            # Verify: Z3 result is returned directly
            assert result == z3_success_result, (
                f"Expected Z3 success result, got: {result}"
            )

            # Verify: LLM was NOT called (no fallback needed)
            assert len(llm_called) == 0, (
                f"LLM engine was called {len(llm_called)} times when Z3 succeeded — "
                f"fallback should not trigger on Z3 success"
            )

    @given(
        rule_description=rule_description_strategy,
        error_reasoning=z3_error_reasoning_strategy,
        policy_type=policy_type_strategy,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_llm_fallback_failure_returns_llm_error(
        self, rule_description, error_reasoning, policy_type
    ):
        """When both Z3 and LLM fail, the LLM error result is returned (not Z3's).

        If the LLM engine also fails after Z3 fallback, the final result should
        be the LLM's error result (which may also be "Information Not Found"),
        not the original Z3 error.

        **Validates: Requirements 4.5**
        """
        with patch(
            "idp_common.rule_validation.service.RuleValidationService.__init__",
            return_value=None,
        ):
            from idp_common.rule_validation.service import RuleValidationService

            service = RuleValidationService.__new__(RuleValidationService)

            # Set up minimal required attributes
            service.config = MagicMock()
            service.config.rule_validation.semaphore = 5
            service.region = "us-east-1"
            service._semaphore = asyncio.Semaphore(5)
            service._z3_adapter = MagicMock()
            service.token_metrics = {}
            service.metrics_lock = asyncio.Lock()

            # Mock _process_z3_rule to return "Information Not Found" (Z3 failure)
            async def mock_process_z3_rule(
                rule_description, policy_type, extraction_results, document_text, config
            ):
                return {
                    "rule_type": policy_type,
                    "rule": rule_description,
                    "recommendation": "Information Not Found",
                    "reasoning": error_reasoning,
                    "supporting_pages": [],
                    "_z3_error": True,
                }

            service._process_z3_rule = mock_process_z3_rule

            # Mock _process_rule_question to also fail (LLM error)
            llm_error_result = {
                "policy_type": policy_type,
                "rule": rule_description,
                "recommendation": "Information Not Found",
                "reasoning": "Error during processing: Bedrock invocation failed",
                "supporting_pages": [],
            }

            async def mock_process_rule_question(
                rule, user_history, policy_type, config, extraction_results=None
            ):
                return llm_error_result

            service._process_rule_question = mock_process_rule_question

            # Execute
            config = build_config_with_z3_rules([{"description": rule_description}])
            result = await service._process_z3_rule_with_fallback(
                rule_description=rule_description,
                policy_type=policy_type,
                extraction_results={},
                document_text="Sample document text.",
                config=config,
            )

            # Verify: the LLM error result is returned (not the Z3 error)
            assert result == llm_error_result, (
                f"Expected LLM error result to be returned when both engines fail. "
                f"Got: {result}"
            )
            # The reasoning should be from LLM, not Z3
            assert result["reasoning"] != error_reasoning, (
                f"Result reasoning should be from LLM fallback, not Z3 error. "
                f"Got Z3 reasoning: '{error_reasoning}'"
            )
