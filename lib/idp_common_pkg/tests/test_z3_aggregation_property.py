# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Property-based tests for aggregated results completeness and opacity.

Feature: z3-dual-engine-rule-validation, Property 10: Aggregated Results Completeness and Opacity

For any policy class with N rules processed by mixed engines, the aggregated result
SHALL contain exactly N result entries, and no result entry SHALL contain a field
indicating which engine produced it.

**Validates: Requirements 4.4, 4.8**
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from idp_common.config.schema_constants import (
    X_AWS_IDP_VALIDATION_ENGINE,
)

# --- Strategies ---

# Strategy for engine assignments: "llm", "z3", or absent (None)
engine_assignments = st.sampled_from(["llm", "z3", None])

# Strategy for recommendation values
recommendations = st.sampled_from(["Pass", "Fail", "Information Not Found"])


@st.composite
def policy_class_strategy(draw):
    """Generate a random N-rule policy class with mixed engine assignments.

    Returns a list of rule dicts with unique descriptions and random engines.
    N is between 1 and 15 to cover various sizes.
    """
    num_rules = draw(st.integers(min_value=1, max_value=15))
    rules = []
    for i in range(num_rules):
        suffix = draw(
            st.text(
                alphabet=st.characters(categories=("L", "N")),
                min_size=3,
                max_size=30,
            ).filter(lambda s: s.strip())
        )
        description = f"Rule {i}: {suffix}"
        engine = draw(engine_assignments)
        rules.append({"description": description, "engine": engine})
    return rules


@st.composite
def mixed_engine_policy_class_strategy(draw):
    """Generate a policy class that has at least one Z3 rule and one LLM rule.

    This ensures we test the mixed-engine aggregation scenario.
    """
    # Generate at least 2 rules
    num_rules = draw(st.integers(min_value=2, max_value=15))
    rules = []

    # Ensure at least one Z3 rule
    suffix_z3 = draw(
        st.text(
            alphabet=st.characters(categories=("L", "N")),
            min_size=3,
            max_size=30,
        ).filter(lambda s: s.strip())
    )
    rules.append({"description": f"Rule 0: {suffix_z3}", "engine": "z3"})

    # Ensure at least one LLM rule
    suffix_llm = draw(
        st.text(
            alphabet=st.characters(categories=("L", "N")),
            min_size=3,
            max_size=30,
        ).filter(lambda s: s.strip())
    )
    rules.append({"description": f"Rule 1: {suffix_llm}", "engine": "llm"})

    # Fill remaining rules with random engines
    for i in range(2, num_rules):
        suffix = draw(
            st.text(
                alphabet=st.characters(categories=("L", "N")),
                min_size=3,
                max_size=30,
            ).filter(lambda s: s.strip())
        )
        engine = draw(engine_assignments)
        rules.append({"description": f"Rule {i}: {suffix}", "engine": engine})

    return rules


# --- Helpers ---

# Fields that would expose engine type — these must NOT appear in results
ENGINE_EXPOSING_FIELDS = frozenset(
    [
        "engine",
        "engine_type",
        "validation_engine",
        "x-aws-idp-validation-engine",
        "processed_by",
        "engine_name",
        "validator",
        "validator_type",
    ]
)


def build_config_with_rules(rules):
    """Build a config dict with a policy class containing the given rules."""
    rule_properties = {}
    for i, rule in enumerate(rules):
        prop = {"type": "string", "description": rule["description"]}
        if rule["engine"] is not None:
            prop[X_AWS_IDP_VALIDATION_ENGINE] = rule["engine"]
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


def make_llm_result(rule_description, policy_type):
    """Create a mock LLM engine result (no engine field exposed)."""
    return {
        "rule_type": policy_type,
        "rule": rule_description,
        "recommendation": "Pass",
        "reasoning": "LLM validated this rule successfully.",
        "supporting_pages": [],
    }


def make_z3_result(rule_description, policy_type):
    """Create a mock Z3 engine result (no engine field exposed)."""
    return {
        "rule_type": policy_type,
        "rule": rule_description,
        "recommendation": "Pass",
        "reasoning": "Z3 constraint satisfied.",
        "supporting_pages": [],
    }


# --- Property Tests ---


class TestAggregatedResultsCompleteness:
    """Property 10: Aggregated Results Completeness and Opacity.

    For any policy class with N rules processed by mixed engines, the aggregated
    result SHALL contain exactly N result entries, and no result entry SHALL contain
    a field indicating which engine produced it.

    **Validates: Requirements 4.4, 4.8**
    """

    @given(rules=policy_class_strategy())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_result_count_equals_rule_count(self, rules):
        """Aggregated result contains exactly N entries for N rules.

        For any policy class with N rules, regardless of engine assignment,
        the service must return exactly N result entries — one per rule.

        **Validates: Requirements 4.4, 4.8**
        """
        config = build_config_with_rules(rules)
        n = len(rules)

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
            service.timing_metrics = {"criteria_processing_time": []}

            async def mock_process_rule_question(
                rule, user_history, policy_type, config, extraction_results=None
            ):
                return make_llm_result(rule, policy_type)

            async def mock_process_z3_rule_with_fallback(
                rule_description, policy_type, extraction_results, document_text, config
            ):
                return make_z3_result(rule_description, policy_type)

            service._process_rule_question = mock_process_rule_question
            service._process_z3_rule_with_fallback = mock_process_z3_rule_with_fallback

            # Execute
            results = await service._process_policy_type(
                policy_type="test-policy",
                user_history="Sample document text for validation.",
                config=config,
                extraction_results=None,
            )

            # Verify: exactly N results for N rules
            assert len(results) == n, (
                f"Expected exactly {n} results for {n} rules, but got {len(results)}"
            )

    @given(rules=policy_class_strategy())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_no_result_exposes_engine_type(self, rules):
        """No result entry contains a field that exposes which engine processed it.

        The aggregated results must be opaque — a consumer cannot determine
        whether a result came from the Z3 engine or the LLM engine by
        inspecting the result fields.

        **Validates: Requirements 4.4, 4.8**
        """
        config = build_config_with_rules(rules)

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
            service.timing_metrics = {"criteria_processing_time": []}

            async def mock_process_rule_question(
                rule, user_history, policy_type, config, extraction_results=None
            ):
                return make_llm_result(rule, policy_type)

            async def mock_process_z3_rule_with_fallback(
                rule_description, policy_type, extraction_results, document_text, config
            ):
                return make_z3_result(rule_description, policy_type)

            service._process_rule_question = mock_process_rule_question
            service._process_z3_rule_with_fallback = mock_process_z3_rule_with_fallback

            # Execute
            results = await service._process_policy_type(
                policy_type="test-policy",
                user_history="Sample document text for validation.",
                config=config,
                extraction_results=None,
            )

            # Verify: no result entry exposes engine type
            for i, result in enumerate(results):
                for field in ENGINE_EXPOSING_FIELDS:
                    assert field not in result, (
                        f"Result entry {i} exposes engine type via field '{field}'. "
                        f"Result keys: {list(result.keys())}. "
                        f"The aggregated results must be engine-opaque."
                    )

    @given(rules=mixed_engine_policy_class_strategy())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_mixed_engine_results_are_uniform(self, rules):
        """Results from mixed engines have the same structure — no engine-specific fields.

        When a policy class has both Z3 and LLM rules, all result entries
        must have the same set of keys, ensuring uniformity and opacity.

        **Validates: Requirements 4.4, 4.8**
        """
        config = build_config_with_rules(rules)

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
            service.timing_metrics = {"criteria_processing_time": []}

            async def mock_process_rule_question(
                rule, user_history, policy_type, config, extraction_results=None
            ):
                return make_llm_result(rule, policy_type)

            async def mock_process_z3_rule_with_fallback(
                rule_description, policy_type, extraction_results, document_text, config
            ):
                return make_z3_result(rule_description, policy_type)

            service._process_rule_question = mock_process_rule_question
            service._process_z3_rule_with_fallback = mock_process_z3_rule_with_fallback

            # Execute
            results = await service._process_policy_type(
                policy_type="test-policy",
                user_history="Sample document text for validation.",
                config=config,
                extraction_results=None,
            )

            # Verify: all results have the same set of keys (uniform structure)
            if results:
                first_keys = set(results[0].keys())
                for i, result in enumerate(results[1:], start=1):
                    result_keys = set(result.keys())
                    assert result_keys == first_keys, (
                        f"Result entry {i} has different keys than entry 0. "
                        f"Entry 0 keys: {first_keys}, Entry {i} keys: {result_keys}. "
                        f"All results must have uniform structure regardless of engine."
                    )

            # Also verify no engine-exposing fields
            for i, result in enumerate(results):
                for field in ENGINE_EXPOSING_FIELDS:
                    assert field not in result, (
                        f"Result entry {i} exposes engine type via field '{field}'."
                    )

    @given(rules=mixed_engine_policy_class_strategy())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_every_rule_has_corresponding_result(self, rules):
        """Every rule in the policy class has a corresponding result entry.

        The aggregated results must cover all rules — no rule is dropped
        during aggregation regardless of which engine processed it.

        **Validates: Requirements 4.4, 4.8**
        """
        config = build_config_with_rules(rules)

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
            service.timing_metrics = {"criteria_processing_time": []}

            async def mock_process_rule_question(
                rule, user_history, policy_type, config, extraction_results=None
            ):
                return make_llm_result(rule, policy_type)

            async def mock_process_z3_rule_with_fallback(
                rule_description, policy_type, extraction_results, document_text, config
            ):
                return make_z3_result(rule_description, policy_type)

            service._process_rule_question = mock_process_rule_question
            service._process_z3_rule_with_fallback = mock_process_z3_rule_with_fallback

            # Execute
            results = await service._process_policy_type(
                policy_type="test-policy",
                user_history="Sample document text for validation.",
                config=config,
                extraction_results=None,
            )

            # Verify: every rule description appears in the results
            result_rules = {r["rule"] for r in results}
            expected_rules = {r["description"] for r in rules}

            assert result_rules == expected_rules, (
                f"Not all rules have corresponding results. "
                f"Missing: {expected_rules - result_rules}. "
                f"Extra: {result_rules - expected_rules}."
            )
