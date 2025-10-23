# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Error Analyzer Agent - Enhanced with modular tools.
"""

import logging
from typing import Any, Dict

import boto3
import strands

from ..common.strands_bedrock_model import create_strands_bedrock_model
from .config import get_error_analyzer_config
from .tools import analyze_errors

logger = logging.getLogger(__name__)


def create_error_analyzer_agent(
    config: Dict[str, Any] = None,
    session: boto3.Session = None,
    pattern_config: Dict[str, Any] = None,
    **kwargs,
) -> strands.Agent:
    """
    Creates configured error analyzer agent with AWS integrations.
    Create the Error Analyzer Agent with modular tools.

    Args:
        config: Legacy configuration (deprecated)
        session: Boto3 session
        pattern_config: Pattern configuration containing agents section
        **kwargs: Additional arguments
    """
    config = get_error_analyzer_config(pattern_config)

    # Create session if not provided
    if session is None:
        session = boto3.Session()

    # Create agent
    tools = [analyze_errors]
    bedrock_model = create_strands_bedrock_model(
        model_id=config["model_id"], boto_session=session
    )

    return strands.Agent(
        tools=tools, system_prompt=config["system_prompt"], model=bedrock_model
    )
