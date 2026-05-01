# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Helper function for creating BedrockModel instances with automatic guardrail support and retry logic.
"""

import logging
import os

from botocore.config import Config
from strands.models import BedrockModel

logger = logging.getLogger(__name__)


def create_strands_bedrock_model(
    model_id: str, boto_session=None, **kwargs
) -> BedrockModel:
    """
    Create a BedrockModel with automatic guardrail configuration and retry logic.

    This function creates a BedrockModel with:
    - Automatic retry configuration with exponential backoff (adaptive mode)
    - Guardrail support from environment variables
    - Configurable timeouts for connection and read operations

    The retry configuration handles Bedrock transient errors including:
    - serviceUnavailableException
    - ThrottlingException
    - ModelThrottledException
    - And other transient errors

    Args:
        model_id: The Bedrock model ID to use
        boto_session: Optional boto3 session
        **kwargs: Additional arguments to pass to BedrockModel

    Returns:
        BedrockModel instance with guardrails and retry logic applied

    Environment Variables:
        GUARDRAIL_ID_AND_VERSION: Format "guardrail_id:version" for guardrail configuration
        BEDROCK_MAX_RETRIES: Maximum retry attempts (default: 5)
        BEDROCK_CONNECT_TIMEOUT: Connection timeout in seconds (default: 10)
        BEDROCK_READ_TIMEOUT: Read timeout in seconds (default: 300)
    """
    # Get retry configuration from environment
    max_retries = int(os.environ.get("BEDROCK_MAX_RETRIES", "5"))
    connect_timeout = float(os.environ.get("BEDROCK_CONNECT_TIMEOUT", "10.0"))
    read_timeout = float(os.environ.get("BEDROCK_READ_TIMEOUT", "300.0"))

    # Configure boto3 retry behavior with exponential backoff
    # This applies to all Bedrock API calls made through this model
    boto_config = Config(
        retries={
            "max_attempts": max_retries,
            "mode": "adaptive",  # Uses exponential backoff with adaptive retry mode
        },
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
    )

    logger.debug(
        "Creating BedrockModel with retry configuration",
        extra={
            "model_id": model_id,
            "max_retries": max_retries,
            "connect_timeout": connect_timeout,
            "read_timeout": read_timeout,
        },
    )

    # Apply boto config to kwargs if not already provided
    if "boto_client_config" not in kwargs:
        kwargs["boto_client_config"] = boto_config

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
                logger.debug(
                    "Guardrails enabled for BedrockModel",
                    extra={"guardrail_id": guardrail_id},
                )
        except ValueError:
            logger.warning(
                "Invalid GUARDRAIL_ID_AND_VERSION format, continuing without guardrails"
            )

    return BedrockModel(model_id=model_id, boto_session=boto_session, **kwargs)
