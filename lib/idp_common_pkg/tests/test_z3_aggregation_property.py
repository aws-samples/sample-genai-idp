# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Property-based tests for aggregated results completeness and opacity.

Feature: z3-dual-engine-rule-validation, Property 10: Aggregated Results Completeness and Opacity

For any policy class with N rules processed by mixed engines, the per-section step
SHALL return exactly N result entries, and all entries SHALL have a uniform structure.

**Validates: Requirements 4.4, 4.8**
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from idp_common.config.schema_constants import (
    X_AWS_IDP_RULE_ID,
    X_AWS_IDP_VALIDATION_ENGINE,
)

# --- Strategies ---

engine_assignments = st.sampled_from(["llm", "z3", None])


@st.composite
def policy_class_strategy(draw):
    """Generate a random N-rule policy class with mixed engine assignments."""
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
        rule_id = f"rule_{i}" if engine == "z3" else None
        rules.append({"description": description, "engine": engine, "rule_id": rule_id})
    return rules


@st.composite
def mixed_engine_policy_class_strategy(draw):
    """Generate a policy class that has at least one Z3 rule and one LLM rule."""
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
    rules.append(
        {"description": f"Rule 0: {suffix_z3}", "engine": "z3", "rule_id": "rule_0"}
    )

    # Ensure at least one LLM rule
    suffix_llm = draw(
        st.text(
            alphabet=st.characters(categories=("L", "N")),
            min_size=3,
            max_size=30,
        ).filter(lambda s: s.strip())
    )
    rules.append(
        {"description": f"Rule 1: {suffix_llm}", "engine": "llm", "rule_id": None}
    )

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
        rule_id = f"rule_{i}" if engine == "z3" else None
        rules.append(
            {"description": f"Rule {i}: {suffix}", "engine": engine, "rule_id": rule_id}
        )

    return rules


def build_config_with_rules(rules):
    """Build a config dict with a policy class containing the given rules."""
    rule_properties = {}
    for i, rule in enumerate(rules):
        prop = {"type": "string", "description": rule["description"]}
        if rule["engine"] is not None:
            prop[X_AWS_IDP_VALIDATION_ENGINE] = rule["engine"]
        if rule.get("rule_id"):
            prop[X_AWS_IDP_RULE_ID] = rule["rule_id"]
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
            "token_size": 1000, # nosec B105
            "overlap_percentage": 0.1,
        },
    }


def make_llm_result(rule_description, policy_type):
    """Create a mock LLM engine result."""
    return {
        "policy_type": policy_type,
        "rule": rule_description,
        "extracted_facts": [{"fact": "test", "citation": "1", "relevance": "test"}],
        "extraction_summary": "LLM fact extraction.",
    }


def make_z3_fact_result(rule_description, policy_type):
    """Create a mock Z3 fact extraction result (same format as LLM)."""
    return {
        "policy_type": policy_type,
        "rule": rule_description,
        "extracted_facts": [{"fact": "test", "citation": "1", "relevance": "test"}],
        "extraction_summary": "Z3 fact extraction.",
    }


# --- Property Tests ---


class TestAggregatedResultsCompleteness:
    """Property 10: Aggregated Results Completeness and Opacity.

    For any policy class with N rules, the per-section step SHALL return
    exactly N result entries with uniform structure.

    **Validates: Requirements 4.4, 4.8**
    """

    @given(rules=policy_class_strategy())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_result_count_equals_rule_count(self, rules):
        """Per-section step returns exactly N entries for N rules."""
        config = build_config_with_rules(rules)
        n = len(rules)

        with patch(
            "idp_common.rule_validation.service.RuleValidationService.__init__",
            return_value=None,
        ):
            from idp_common.rule_validation.service import RuleValidationService

            service = RuleValidationService.__new__(RuleValidationService)

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

            async def mock_process_z3_fact_extraction(
                rule_description,
                rule_id,
                policy_type,
                extraction_results,
                document_text,
                config,
                rule_json=None,
            ):
                return make_z3_fact_result(rule_description, policy_type)

            service._process_rule_question = mock_process_rule_question
            service._process_z3_fact_extraction = mock_process_z3_fact_extraction

            results = await service._process_policy_type(
                policy_type="test-policy",
                user_history="Sample document text for validation.",
                config=config,
                extraction_results=None,
            )

            assert len(results) == n, (
                f"Expected exactly {n} results for {n} rules, but got {len(results)}"
            )

    @given(rules=mixed_engine_policy_class_strategy())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_mixed_engine_results_are_uniform(self, rules):
        """Results from mixed engines have the same structure."""
        config = build_config_with_rules(rules)

        with patch(
            "idp_common.rule_validation.service.RuleValidationService.__init__",
            return_value=None,
        ):
            from idp_common.rule_validation.service import RuleValidationService

            service = RuleValidationService.__new__(RuleValidationService)

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

            async def mock_process_z3_fact_extraction(
                rule_description,
                rule_id,
                policy_type,
                extraction_results,
                document_text,
                config,
                rule_json=None,
            ):
                return make_z3_fact_result(rule_description, policy_type)

            service._process_rule_question = mock_process_rule_question
            service._process_z3_fact_extraction = mock_process_z3_fact_extraction

            results = await service._process_policy_type(
                policy_type="test-policy",
                user_history="Sample document text for validation.",
                config=config,
                extraction_results=None,
            )

            # All results have the same set of keys (uniform structure)
            if results:
                first_keys = set(results[0].keys())
                for i, result in enumerate(results[1:], start=1):
                    result_keys = set(result.keys())
                    assert result_keys == first_keys, (
                        f"Result entry {i} has different keys than entry 0. "
                        f"Entry 0 keys: {first_keys}, Entry {i} keys: {result_keys}."
                    )

    @given(rules=mixed_engine_policy_class_strategy())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_every_rule_has_corresponding_result(self, rules):
        """Every rule in the policy class has a corresponding result entry."""
        config = build_config_with_rules(rules)

        with patch(
            "idp_common.rule_validation.service.RuleValidationService.__init__",
            return_value=None,
        ):
            from idp_common.rule_validation.service import RuleValidationService

            service = RuleValidationService.__new__(RuleValidationService)

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

            async def mock_process_z3_fact_extraction(
                rule_description,
                rule_id,
                policy_type,
                extraction_results,
                document_text,
                config,
                rule_json=None,
            ):
                return make_z3_fact_result(rule_description, policy_type)

            service._process_rule_question = mock_process_rule_question
            service._process_z3_fact_extraction = mock_process_z3_fact_extraction

            results = await service._process_policy_type(
                policy_type="test-policy",
                user_history="Sample document text for validation.",
                config=config,
                extraction_results=None,
            )

            result_rules = {r["rule"] for r in results}
            expected_rules = {r["description"] for r in rules}

            assert result_rules == expected_rules, (
                f"Not all rules have corresponding results. "
                f"Missing: {expected_rules - result_rules}. "
                f"Extra: {result_rules - expected_rules}."
            )
