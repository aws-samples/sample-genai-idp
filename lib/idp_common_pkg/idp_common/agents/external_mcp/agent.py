# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
External MCP Agent implementation using Strands framework.
"""

import logging
import os
from typing import Any, Dict

import boto3
from mcp.client.streamable_http import streamablehttp_client
from strands import Agent
from strands.tools.mcp import MCPClient

from ..common.oauth_auth import get_cognito_bearer_token
from ..common.strands_bedrock_model import create_strands_bedrock_model

logger = logging.getLogger(__name__)


def create_external_mcp_agent(
    config: Dict[str, Any] = None,
    session: boto3.Session = None,
    model_id: str = None,
    mcp_server_config: Dict[str, Any] = None,
    **kwargs,
) -> Agent:
    """
    Create External MCP Agent that connects to external MCP servers.

    Args:
        config: Configuration dictionary (ignored - MCP agent uses its own config)
        session: Boto3 session for AWS operations. If None, creates default session
        model_id: Model ID to use. If None, reads from DOCUMENT_ANALYSIS_AGENT_MODEL_ID environment variable
        mcp_server_config: Individual MCP server configuration dict (required)
        **kwargs: Additional arguments (job_id, user_id, etc.)

    Returns:
        Agent: Configured Strands agent instance with MCP tools

    Raises:
        Exception: If authentication or MCP connection fails
    """
    if mcp_server_config is None:
        raise Exception("mcp_server_config is required")

    # Get session if not provided
    if session is None:
        session = boto3.Session()

    logger.info("Creating External MCP Agent with provided server configuration")

    # Validate required fields
    required_fields = [
        "mcp_url",
        "cognito_user_pool_id",
        "cognito_client_id",
        "cognito_username",
        "cognito_password",
    ]
    missing_fields = [
        field for field in required_fields if field not in mcp_server_config
    ]
    if missing_fields:
        error_msg = f"MCP server config missing required fields: {missing_fields}"
        logger.error(error_msg)
        raise Exception(error_msg)

    # Get bearer token from Cognito
    try:
        bearer_token = get_cognito_bearer_token(
            user_pool_id=mcp_server_config["cognito_user_pool_id"],
            client_id=mcp_server_config["cognito_client_id"],
            username=mcp_server_config["cognito_username"],
            password=mcp_server_config["cognito_password"],
            session=session,
        )
        logger.info("Successfully obtained bearer token for MCP authentication")
    except Exception as e:
        error_msg = f"Failed to get bearer token: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)

    # Create MCP client with authentication headers
    mcp_url = mcp_server_config["mcp_url"]
    headers = {
        "authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
    }

    try:
        # Create MCP client
        mcp_client = MCPClient(lambda: streamablehttp_client(mcp_url, headers))

        # Discover tools and create dynamic description within MCP context
        with mcp_client:
            tools = mcp_client.list_tools_sync()

            # Get actual tool names from the MCPAgentTool objects
            tool_names = []
            for tool in tools:
                if hasattr(tool, "tool_name"):
                    tool_names.append(tool.tool_name)
                elif hasattr(tool, "mcp_tool") and hasattr(tool.mcp_tool, "name"):
                    tool_names.append(tool.mcp_tool.name)
                else:
                    raise Exception(
                        f"Unable to extract tool name from MCP tool: {tool}"
                    )

            # Create dynamic description based on available tools
            if tool_names:
                tool_list = ", ".join(tool_names)
                dynamic_description = f"Agent which has access to an external MCP server. The tools available are: {tool_list}."
            else:
                dynamic_description = "Agent which has access to an external MCP server, but no tools were discovered at creation time."

            logger.info(f"Discovered {len(tools)} MCP tools: {tool_names}")

            # Get model ID from parameter or environment variable
            if model_id is None:
                model_id = os.environ.get("DOCUMENT_ANALYSIS_AGENT_MODEL_ID")
                if not model_id:
                    error_msg = (
                        "DOCUMENT_ANALYSIS_AGENT_MODEL_ID environment variable not set"
                    )
                    logger.error(error_msg)
                    raise Exception(error_msg)

            # Create Bedrock model
            bedrock_model = create_strands_bedrock_model(
                model_id=model_id, boto_session=session
            )

            # Create system prompt
            system_prompt = f"""
            You are an AI agent that has access to external tools via MCP (Model Context Protocol).
            
            {dynamic_description}
            
            Use the available tools to help answer user questions. When using tools, provide clear explanations of what you're doing and what the results mean.
            
            If a tool fails or returns an error, explain the issue to the user and suggest alternatives if possible.
            """

            # Create Strands agent with MCP tools
            strands_agent = Agent(
                tools=tools, system_prompt=system_prompt, model=bedrock_model
            )

        # Return the Strands agent - the MCP client will be managed by IDPAgent
        logger.info("External MCP Agent created successfully")
        return strands_agent, mcp_client

    except Exception as e:
        error_msg = f"Failed to connect to MCP server at {mcp_url}: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)
