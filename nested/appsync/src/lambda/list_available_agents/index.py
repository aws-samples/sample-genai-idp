# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Lambda function to list all available agents.
"""

import json
import logging
import os

from idp_common.agents.factory import agent_factory
from idp_common.utils.log_sanitizer import sanitize_event_for_logging

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def handler(event, context):
    """
    List all available agents from the factory.
    
    Args:
        event: The event dict from AppSync
        context: The Lambda context
        
    Returns:
        List of available agents with metadata
    """
    logger.info(f"Received event: {json.dumps(sanitize_event_for_logging(event))}")
    
    try:
        # Get list of available agents from factory
        available_agents = agent_factory.list_available_agents()
        
        logger.info(f"Found {len(available_agents)} available agents")
        return available_agents
        
    except Exception as e:
        error_msg = f"Error listing available agents: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)
