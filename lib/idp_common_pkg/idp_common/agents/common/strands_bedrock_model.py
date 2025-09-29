# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Helper function for creating BedrockModel instances with automatic guardrail support.
"""

import os

from strands.models import BedrockModel


def create_strands_bedrock_model(
    model_id: str, boto_session=None, **kwargs
) -> BedrockModel:
    """
    Create a BedrockModel with automatic guardrail configuration from environment.

    Args:
        model_id: The Bedrock model ID to use
        boto_session: Optional boto3 session
        **kwargs: Additional arguments to pass to BedrockModel

    Returns:
        BedrockModel instance with guardrails applied if configured
    """
    # Get guardrail configuration from environment if available
    guardrail_env = os.environ.get("GUARDRAIL_ID_AND_VERSION", "")
    if guardrail_env:
        try:
            guardrail_id, guardrail_version = guardrail_env.split(":")
            if guardrail_id and guardrail_version:
                kwargs.update(
                    {
                        "guardrail_id": guardrail_id,
                        "guardrail_version": guardrail_version,
                        "guardrail_trace": "enabled",
                    }
                )
        except ValueError:
            pass  # Invalid format, continue without guardrails

    return BedrockModel(model_id=model_id, boto_session=boto_session, **kwargs)
