# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Lambda function for AgentCore Gateway MCP tools.
Provides IDP operations through AgentCore Gateway's built-in MCP server.
"""

import json
import logging
import os
from typing import Any, Dict

from tools import get_tool

# Configure logging. Importing idp_common.agents.common.config transitively
# imports strands (via the agents.common package __init__), so a missing/broken
# agents layer would fail THIS module's import and take down every tool with
# Runtime.ImportModuleError. Fall back to stdlib logging so the handler always
# loads; the failure then surfaces per-tool with a diagnosable message.
try:
    from idp_common.agents.common.config import configure_logging

    configure_logging()
except ImportError as _logging_import_error:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    logging.getLogger(__name__).warning(
        f"idp_common agents logging unavailable, using stdlib logging: "
        f"{_logging_import_error}"
    )

# Get logger for this module
logger = logging.getLogger(__name__)

# Version marker for deployment verification
CODE_VERSION = "2024-01-SDK-INTEGRATION-v2"
CODE_UPDATED = "2025-01-09T19:30:00Z"


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Route MCP tool invocations to appropriate handlers"""
    logger.info(f"=== Lambda Handler Started ===")
    logger.info(f"Code Version: {CODE_VERSION}")
    logger.info(f"Code Updated: {CODE_UPDATED}")
    logger.info(f"Received event: {json.dumps(event)}")
    
    # Log context details for debugging
    logger.info(f"Context type: {type(context)}")
    if hasattr(context, 'client_context'):
        logger.info(f"client_context: {context.client_context}")
        if context.client_context:
            custom = getattr(context.client_context, 'custom', {})
            logger.info(f"client_context.custom: {custom}")
    
    # Extract tool name from context (AgentCore Gateway pattern)
    # Format: ${target_name}__${tool_name} or _${tool_name}
    tool_name_full = None
    if hasattr(context, 'client_context') and context.client_context:
        custom = getattr(context.client_context, 'custom', {})
        tool_name_full = custom.get('bedrockAgentCoreToolName')
    
    if not tool_name_full:
        logger.error("No bedrockAgentCoreToolName in context")
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'No tool name in context'})
        }
    
    # Strip target name prefix (handle ___ delimiter)
    if '___' in tool_name_full:
        tool_name = tool_name_full.split('___', 1)[1]
    else:
        tool_name = tool_name_full
    
    # Strip leading underscore if present
    if tool_name.startswith('_'):
        tool_name = tool_name[1:]
    
    logger.info(f"Tool name from context: {tool_name_full} -> {tool_name}")
    
    try:
        logger.info(f"Looking up tool: {tool_name}")
        tool = get_tool(tool_name)
        logger.info(f"Found tool class: {tool.__class__.__name__}")
        logger.info(f"Tool module: {tool.__class__.__module__}")
        
        # Parameters are sent directly as top-level event fields
        logger.info(f"Executing tool: {tool_name} with event: {json.dumps(event)}")
        logger.info(f"Tool execution starting...")
        result = tool.execute(**event)
        logger.info(f"Tool execution completed successfully")
        logger.info(f"Result: {json.dumps(result)[:500]}...")  # Log first 500 chars
        
        return {
            'statusCode': 200,
            'body': json.dumps(result)
        }
    
    except Exception as e:
        logger.error(f"Tool execution failed: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e),
                'tool_name': tool_name
            })
        }