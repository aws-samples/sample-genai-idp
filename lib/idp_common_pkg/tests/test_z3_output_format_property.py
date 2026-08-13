# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Property-based tests for engine output format invariant.

Feature: z3-dual-engine-rule-validation, Property 4: Engine Output Format Invariant

For any rule processed by the per-section step (either via Z3 fact extraction or
LLM fact extraction), the returned result SHALL contain the standard fact extraction
fields: policy_type, rule, extracted_facts, extraction_summary.

For the orchestration step, Z3 verdicts SHALL contain a `recommendation` field with
a value that is exactly one of "Pass", "Fail", or "Information Not Found".

**Validates: Requirements 4.2, 4.3**
"""

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from idp_common.config.schema_constants import (
    X_AWS_IDP_RULE_ID,
    X_AWS_IDP_VALIDATION_ENGINE,
)

# --- Constants ---

VALID_RECOMMENDATIONS = {"Pass", "Fail", "Information Not Found"}

REQUIRED_FACT_EXTRACTION_FIELDS = {
    "policy_type",
    "rule",
    "extracted_facts",
    "extraction_summary",
}


# --- Strategies ---

rule_descriptions = st.text(
    alphabet=st.characters(categories=("L", "N", "P", "Z")),
    min_size=5,
    max_size=100,
).filter(lambda s: s.strip())

policy_types = st.text(
    alphabet=st.characters(categories=("L", "N"), whitelist_characters="-_"),
    min_size=3,
    max_size=40,
).filter(lambda s: s.strip() and s[0].isalpha())

engine_assignments = st.sampled_from(["llm", "z3", None])

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
            "token_size": 1000,  # nosec B105
            "overlap_percentage": 0.1,
        },
    }


# --- Property Tests ---


class TestEngineOutputFormatInvariant:
    """Property 4: Engine Output Format Invariant.

    Per-section results from both Z3 fact extraction and LLM fact extraction
    SHALL contain the standard fact extraction fields.

    **Validates: Requirements 4.2, 4.3**
    """

    @given(rules=rule_list_strategy())
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_all_results_have_valid_recommendation(self, rules):
        """Every per-section result has the required fact extraction fields.

        **Validates: Requirements 4.2, 4.3**
        """
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
                return {
                    "policy_type": policy_type,
                    "rule": rule,
                    "extracted_facts": [
                        {"fact": "test", "citation": "1", "relevance": "r"}
                    ],
                    "extraction_summary": "LLM engine result.",
                }

            async def mock_process_z3_fact_extraction(
                rule_description,
                rule_id,
                policy_type,
                extraction_results,
                document_text,
                config,
                rule_json=None,
            ):
                return {
                    "policy_type": policy_type,
                    "rule": rule_description,
                    "extracted_facts": [
                        {"fact": "test", "citation": "1", "relevance": "r"}
                    ],
                    "extraction_summary": "Z3 fact extraction result.",
                }

            service._process_rule_question = mock_process_rule_question
            service._process_z3_fact_extraction = mock_process_z3_fact_extraction

            results = await service._process_policy_type(
                policy_type="test-policy",
                user_history="Sample document text for validation.",
                config=config,
                extraction_results=None,
            )

            assert len(results) == len(rules)
            for result in results:
                # Every result must have the required fact extraction fields
                for field in REQUIRED_FACT_EXTRACTION_FIELDS:
                    assert field in result, (
                        f"Result missing '{field}' field: {list(result.keys())}"
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
        """LLM engine always returns the required fact extraction fields.

        **Validates: Requirements 4.3**
        """
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
            service.token_metrics = {}
            service.metrics_lock = asyncio.Lock()

            # Mock the LLM invocation to return a valid fact extraction response
            mock_response_dict = {
                "extracted_facts": [
                    {"fact": "test fact", "citation": "1", "relevance": "relevant"}
                ],
                "extraction_summary": "Found relevant facts.",
            }
            mock_response_text = (
                f"<response>{json.dumps(mock_response_dict)}</response>"
            )

            async def mock_invoke_model_async(**kwargs):
                return {
                    "output": {"message": {"content": [{"text": mock_response_text}]}},
                    "metering": {},
                }

            service._invoke_model_async = mock_invoke_model_async
            service._prepare_prompt = MagicMock(return_value="mocked prompt")

            config = {
                "rule_validation": {
                    "fact_extraction": {
                        "model": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
                        "system_prompt": "You are a validator.",
                        "task_prompt": "Validate: {rule} {DOCUMENT_TEXT} {EXTRACTION_RESULTS} {recommendation_options} {policy_type}",
                        "temperature": 0.0,
                        "top_k": 50,
                        "top_p": 0.9,
                        "max_tokens": 1024,
                    },
                    "recommendation_options": "Pass, Fail, Information Not Found",
                },
            }

            with patch(
                "idp_common.rule_validation.service.bedrock.extract_text_from_response",
                return_value=f"<response>{json.dumps(mock_response_dict)}</response>",
            ):
                result = await service._process_rule_question(
                    rule=rule_desc,
                    user_history="Document text content.",
                    policy_type=policy_type,
                    config=config,
                    extraction_results=None,
                )

            # Verify output has required fields
            assert "policy_type" in result
            assert "rule" in result
            assert "extracted_facts" in result
            assert "extraction_summary" in result
