# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Property-based tests for engine routing correctness.

Feature: z3-dual-engine-rule-validation, Property 3: Engine Routing Correctness

For any policy class containing rules with mixed x-aws-idp-validation-engine values,
the Rule_Validation_Service SHALL route each rule to the engine matching its field value —
rules with "z3" (and a rule_id) to _process_z3_fact_extraction and rules with "llm"
(or absent field) to the LLM engine — with no cross-routing.

**Validates: Requirements 4.1, 2.2, 2.3, 2.4**
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

# Strategy for engine assignments: "llm", "z3", or absent (None)
engine_assignments = st.sampled_from(["llm", "z3", None])


@st.composite
def rule_list_strategy(draw):
    """Generate a list of rules with unique descriptions and random engine assignments.

    Each rule gets a unique description to avoid ambiguity in routing verification.
    Z3 rules always get a rule_id (required for Z3 routing).
    """
    num_rules = draw(st.integers(min_value=1, max_value=10))
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
        "extracted_facts": [],
        "extraction_summary": "LLM fact extraction.",
    }


def make_z3_fact_result(rule_description, policy_type):
    """Create a mock Z3 fact extraction result."""
    return {
        "policy_type": policy_type,
        "rule": rule_description,
        "extracted_facts": [],
        "extraction_summary": "Z3 fact extraction with parameter context.",
    }


# --- Property Tests ---


class TestEngineRoutingCorrectness:
    """Property 3: Engine Routing Correctness.

    For any policy class containing rules with mixed engine assignments,
    each rule is dispatched to the correct engine based on its field value.

    **Validates: Requirements 4.1, 2.2, 2.3, 2.4**
    """

    @given(rules=rule_list_strategy())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_rules_routed_to_correct_engine(self, rules):
        """Each rule is dispatched to the engine matching its x-aws-idp-validation-engine field.

        - Rules with engine="z3" + rule_id → _process_z3_fact_extraction
        - Rules with engine="llm" → _process_rule_question
        - Rules with absent engine field → _process_rule_question (default LLM)

        **Validates: Requirements 4.1, 2.2, 2.3, 2.4**
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

            # Track which engine each rule was dispatched to
            llm_calls = []
            z3_calls = []

            async def mock_process_rule_question(
                rule, user_history, policy_type, config, extraction_results=None
            ):
                llm_calls.append(rule)
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
                z3_calls.append(rule_description)
                return make_z3_fact_result(rule_description, policy_type)

            service._process_rule_question = mock_process_rule_question
            service._process_z3_fact_extraction = mock_process_z3_fact_extraction

            # Execute
            results = await service._process_policy_type(
                policy_type="test-policy",
                user_history="Sample document text",
                config=config,
                extraction_results=None,
            )

            # Verify routing correctness
            expected_z3_rules = [
                r["description"]
                for r in rules
                if r["engine"] == "z3" and r.get("rule_id")
            ]
            expected_llm_rules = [
                r["description"]
                for r in rules
                if r["engine"] != "z3" or not r.get("rule_id")
            ]

            # All Z3 rules should have been dispatched to _process_z3_fact_extraction
            assert sorted(z3_calls) == sorted(expected_z3_rules), (
                f"Z3 routing mismatch: got {sorted(z3_calls)}, "
                f"expected {sorted(expected_z3_rules)}"
            )

            # All LLM rules should have been dispatched to _process_rule_question
            assert sorted(llm_calls) == sorted(expected_llm_rules), (
                f"LLM routing mismatch: got {sorted(llm_calls)}, "
                f"expected {sorted(expected_llm_rules)}"
            )

            # Total results should match total rules
            assert len(results) == len(rules)

    @given(rules=rule_list_strategy())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_no_cross_routing(self, rules):
        """No rule is dispatched to both engines — each goes to exactly one.

        **Validates: Requirements 4.1, 2.2, 2.3**
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

            # Track dispatches
            llm_calls = []
            z3_calls = []

            async def mock_process_rule_question(
                rule, user_history, policy_type, config, extraction_results=None
            ):
                llm_calls.append(rule)
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
                z3_calls.append(rule_description)
                return make_z3_fact_result(rule_description, policy_type)

            service._process_rule_question = mock_process_rule_question
            service._process_z3_fact_extraction = mock_process_z3_fact_extraction

            # Execute
            await service._process_policy_type(
                policy_type="test-policy",
                user_history="Sample document text",
                config=config,
                extraction_results=None,
            )

            # Verify: no rule appears in both call lists (no cross-routing)
            cross_routed = set(llm_calls) & set(z3_calls)
            assert len(cross_routed) == 0, (
                f"Cross-routing detected: rules dispatched to both engines: "
                f"{cross_routed}"
            )

            # Verify: every rule was dispatched to exactly one engine
            all_dispatched = set(llm_calls) | set(z3_calls)
            all_descriptions = set(r["description"] for r in rules)
            assert all_dispatched == all_descriptions, (
                f"Not all rules were dispatched. "
                f"Missing: {all_descriptions - all_dispatched}"
            )
