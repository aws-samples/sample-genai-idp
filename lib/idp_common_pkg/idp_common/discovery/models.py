# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Pydantic models for rule discovery output.

These models define the structured output schema used by the agentic rule discovery
to extract rules from policy documents. The models ensure that the LLM output
conforms to the expected format consumed by RuleValidationService.

Usage:
    from idp_common.discovery.models import RuleDiscoveryOutput

    # Used with agentic_idp.structured_output()
    result, response = structured_output(
        model_id="global.anthropic.claude-sonnet-4-6",
        data_format=RuleDiscoveryOutput,
        prompt=...,
    )

    # Convert to rule_classes format
    rules = [rc.model_dump(mode="json", by_alias=True) for rc in result.rule_classes]
"""

from pydantic import BaseModel, Field


class RuleProperty(BaseModel):
    """A single rule extracted from the policy document."""

    description: str = Field(
        ...,
        description=(
            "Yes/no validation question or checkable statement for this rule. "
            "Should be phrased as a question that can be evaluated against a transaction document."
        ),
    )
    page: str = Field(
        default="",
        description="Page number or section reference where the rule was found in the policy document.",
    )


class PolicyRuleClass(BaseModel):
    """
    A rule class containing multiple related rules.

    Compatible with RuleValidationService which reads:
    - x-aws-idp-rule-type: rule category identifier
    - rule_properties[*].description: individual rule questions to evaluate
    """

    x_aws_idp_rule_type: str = Field(
        alias="x-aws-idp-rule-type",
        default="policy_rules",
        description="Rule category identifier (e.g., 'billing_rules', 'eligibility_rules')",
    )
    description: str = Field(
        default="Rules extracted from the policy document",
        description="Description of this rule category",
    )
    rule_properties: dict[str, RuleProperty] = Field(
        ...,
        description=(
            "Map of descriptive snake_case rule names to rule definitions. "
            "Keys should be descriptive names like 'bundled_services_not_separate', "
            "NOT generic names like 'rule_1'."
        ),
    )

    model_config = {"populate_by_name": True}


class RuleDiscoveryOutput(BaseModel):
    """
    Complete output from agentic rule discovery.

    Contains a list of rule classes, each with multiple individual rules.
    This is the Pydantic model used as data_format for structured_output().
    """

    rule_classes: list[PolicyRuleClass] = Field(
        min_length=1,
        description="List of rule class objects extracted from the policy document. Must contain at least one rule class.",
    )
