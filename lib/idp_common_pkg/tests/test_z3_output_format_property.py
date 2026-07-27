# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Property-based tests for engine output format invariant.

Feature: z3-dual-engine-rule-validation, Property 4: Engine Output Format Invariant

For any rule processed by either the Z3 engine or the LLM engine, the returned result
SHALL contain a `recommendation` field with a value that is exactly one of "Pass",
"Fail", or "Information Not Found" — no other values are permitted.

**Validates: Requirements 4.2, 4.3**
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from idp_common.config.schema_constants import (
    X_AWS_IDP_VALIDATION_ENGINE,
)

# --- Constants ---

VALID_RECOMMENDATIONS = {"Pass", "Fail", "Information Not Found"}


# --- Strategies ---

# Strategy for random rule descriptions
rule_descriptions = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "Z")),
    min_size=5,
    max_size=100,
).filter(lambda s: s.strip())

# Strategy for random policy type names
policy_types = st.text(
    alphabet=st.characters(categories=("L", "N"), whitelist_characters="-_"),
    min_size=3,
    max_size=40,
).filter(lambda s: s.strip() and s[0].isalpha())

# Strategy for engine assignments: "llm", "z3", or absent (None)
engine_assignments = st.sampled_from(["llm", "z3", None])

# Strategy for valid recommendation values (used by mocked engines)
valid_recommendations = st.sampled_from(["Pass", "Fail", "Information Not Found"])


@st.composite
def rule_list_strategy(draw):
    """Generate a list of rules with unique descriptions and random engine assignments."""
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
        description = f"Rule {i}: {suffix}"
        engine = draw(engine_assignments)
        recommendation = draw(valid_recommendations)
        rules.append(
            {
                "description": description,
                "engine": engine,
                "recommendation": recommendation,
            }
        )
    return rules


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


# --- Property Tests ---


class TestEngineOutputFormatInvariant:
    """Property 4: Engine Output Format Invariant.

    For any rule processed by either the Z3 engine or the LLM engine,
    the returned result SHALL contain a `recommendation` field with a value
    that is exactly one of "Pass", "Fail", or "Information Not Found".

    **Validates: Requirements 4.2, 4.3**
    """

    @given(rules=rule_list_strategy())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_all_results_have_valid_recommendation(self, rules):
        """Every result from both engines has recommendation in the valid set.

        Mocks both engines to return random valid recommendations, then verifies
        the output format invariant holds for all results in the aggregated response.

        **Validates: Requirements 4.2, 4.3**
        """
        config = build_config_with_rules(rules)

        # Build a lookup of expected recommendations per rule description
        recommendation_lookup = {r["description"]: r["recommendation"] for r in rules}

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
                return {
                    "rule_type": policy_type,
                    "rule": rule,
                    "recommendation": recommendation_lookup[rule],
                    "reasoning": "LLM engine result.",
                    "supporting_pages": [],
                }

            async def mock_process_z3_rule(
                rule_description, policy_type, extraction_results, document_text, config
            ):
                return {
                    "rule_type": policy_type,
                    "rule": rule_description,
                    "recommendation": recommendation_lookup[rule_description],
                    "reasoning": "Z3 engine result.",
                    "supporting_pages": [],
                }

            service._process_rule_question = mock_process_rule_question
            service._process_z3_rule = mock_process_z3_rule

            # Execute
            results = await service._process_policy_type(
                policy_type="test-policy",
                user_history="Sample document text for validation.",
                config=config,
                extraction_results=None,
            )

            # Verify: every result has a valid recommendation
            assert len(results) == len(rules)
            for result in results:
                assert "recommendation" in result, (
                    f"Result missing 'recommendation' field: {result}"
                )
                assert result["recommendation"] in VALID_RECOMMENDATIONS, (
                    f"Invalid recommendation value '{result['recommendation']}'. "
                    f"Must be one of {VALID_RECOMMENDATIONS}. "
                    f"Rule: {result.get('rule', 'unknown')}"
                )

    @given(
        rule_desc=rule_descriptions,
        policy_type=policy_types,
        recommendation=valid_recommendations,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_z3_engine_output_format(
        self, rule_desc, policy_type, recommendation
    ):
        """Z3 engine always returns recommendation in the valid set.

        Tests the _process_z3_rule method directly with mocked Z3EngineAdapter
        to verify the output format invariant for Z3 engine results.

        **Validates: Requirements 4.2**
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

            # Mock Z3EngineAdapter.validate_rule to return the given recommendation
            mock_adapter = MagicMock()
            mock_adapter.validate_rule.return_value = {
                "rule_type": policy_type,
                "rule": rule_desc,
                "recommendation": recommendation,
                "reasoning": "Z3 solver determined result.",
                "supporting_pages": [],
            }
            service._z3_adapter = mock_adapter

            # Execute _process_z3_rule directly
            result = await service._process_z3_rule(
                rule_description=rule_desc,
                policy_type=policy_type,
                extraction_results={"key": "value"},
                document_text="Document text content.",
                config={},
            )

            # Verify output format
            assert "recommendation" in result, (
                f"Z3 result missing 'recommendation' field: {result}"
            )
            assert result["recommendation"] in VALID_RECOMMENDATIONS, (
                f"Z3 returned invalid recommendation '{result['recommendation']}'. "
                f"Must be one of {VALID_RECOMMENDATIONS}."
            )

    @given(
        rule_desc=rule_descriptions,
        policy_type=policy_types,
        recommendation=valid_recommendations,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_llm_engine_output_format(
        self, rule_desc, policy_type, recommendation
    ):
        """LLM engine always returns recommendation in the valid set.

        Tests the _process_rule_question method with mocked Bedrock invocation
        to verify the output format invariant for LLM engine results.

        **Validates: Requirements 4.3**
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
            service.token_metrics = {}
            service.metrics_lock = asyncio.Lock()

            # Mock the LLM invocation to return a valid response
            import json

            mock_response_dict = {
                "rule_type": policy_type,
                "rule": rule_desc,
                "recommendation": recommendation,
                "reasoning": "LLM determined result.",
                "supporting_pages": [],
            }
            mock_response_text = json.dumps(mock_response_dict)

            async def mock_invoke_model_async(**kwargs):
                return {
                    "output": {"message": {"content": [{"text": mock_response_text}]}},
                    "metering": {},
                }

            service._invoke_model_async = mock_invoke_model_async

            # Mock _prepare_prompt
            service._prepare_prompt = MagicMock(return_value="mocked prompt")

            # Build a minimal config
            config = {
                "rule_validation": {
                    "fact_extraction": {
                        "model": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
                        "system_prompt": "You are a validator.",
                        "task_prompt": "Validate: {rule}",
                        "temperature": 0.0,
                        "top_k": 50,
                        "top_p": 0.9,
                        "max_tokens": 1024,
                    },
                    "recommendation_options": "Pass, Fail, Information Not Found",
                },
            }

            # Mock bedrock.extract_text_from_response
            with patch(
                "idp_common.rule_validation.service.bedrock.extract_text_from_response",
                return_value=mock_response_text,
            ):
                result = await service._process_rule_question(
                    rule=rule_desc,
                    user_history="Document text content.",
                    policy_type=policy_type,
                    config=config,
                    extraction_results=None,
                )

            # Verify output format
            assert "recommendation" in result, (
                f"LLM result missing 'recommendation' field: {result}"
            )
            assert result["recommendation"] in VALID_RECOMMENDATIONS, (
                f"LLM returned invalid recommendation '{result['recommendation']}'. "
                f"Must be one of {VALID_RECOMMENDATIONS}."
            )

    @given(
        rule_desc=rule_descriptions,
        policy_type=policy_types,
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_z3_error_returns_valid_recommendation(self, rule_desc, policy_type):
        """When Z3 engine encounters an error, it still returns a valid recommendation.

        The error case should return "Information Not Found" which is in the valid set.

        **Validates: Requirements 4.2, 4.3**
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

            # Mock Z3EngineAdapter.validate_rule to raise an exception
            mock_adapter = MagicMock()
            mock_adapter.validate_rule.side_effect = RuntimeError("Z3 solver timeout")
            service._z3_adapter = mock_adapter

            # Execute _process_z3_rule directly (error path)
            result = await service._process_z3_rule(
                rule_description=rule_desc,
                policy_type=policy_type,
                extraction_results={},
                document_text="Document text.",
                config={},
            )

            # Verify: even on error, recommendation is valid
            assert "recommendation" in result, (
                f"Z3 error result missing 'recommendation' field: {result}"
            )
            assert result["recommendation"] in VALID_RECOMMENDATIONS, (
                f"Z3 error returned invalid recommendation '{result['recommendation']}'. "
                f"Must be one of {VALID_RECOMMENDATIONS}."
            )
            # Specifically, errors should return "Information Not Found"
            assert result["recommendation"] == "Information Not Found", (
                f"Z3 error should return 'Information Not Found', "
                f"got '{result['recommendation']}'"
            )
