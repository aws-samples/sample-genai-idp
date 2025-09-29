# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Orchestrator Agent implementation using Strands framework.

This agent coordinates multiple specialized agents, routing queries to the most
appropriate agent based on the user's request and the capabilities of each agent.
"""

import logging
import os
import types
from typing import Any, Dict, List

import strands
from strands import tool

from ..common.config import load_result_format_description
from ..common.strands_bedrock_model import create_strands_bedrock_model

logger = logging.getLogger(__name__)


def create_orchestrator_agent(
    config: Dict[str, Any],
    session: Any,
    agent_ids: List[str],
    **kwargs,
) -> strands.Agent:
    """
    Create and configure the orchestrator agent with specialized agents as tools.

    Args:
        config: Configuration dictionary
        session: Boto3 session for AWS operations
        agent_ids: List of agent IDs to include as tools in the orchestrator
        **kwargs: Additional arguments

    Returns:
        strands.Agent: Configured orchestrator agent instance
    """

    # Create tool functions for each specialized agent
    tools = []

    # Extract monitoring context to pass to sub-agents
    job_id = kwargs.get("job_id")
    user_id = kwargs.get("user_id")

    for agent_id in agent_ids:
        # Create a unique function name based on the agent ID
        func_name = f"{agent_id.replace('-', '_')}_agent"

        def create_tool_function(aid, fname):
            def tool_func(query: str) -> str:
                try:
                    from ..factory import agent_factory

                    specialized_agent = agent_factory.create_agent(
                        agent_id=aid,
                        config=config,
                        session=session,
                        job_id=job_id,
                        user_id=user_id,
                        **{
                            k: v
                            for k, v in kwargs.items()
                            if k not in ["job_id", "user_id"]
                        },
                    )

                    # Use context manager to properly handle MCP clients
                    with specialized_agent:
                        response = specialized_agent(query)
                    return str(response)

                except Exception as e:
                    logger.error(f"Error in {aid}: {e}")
                    return f"Error processing query with {aid}: {str(e)}"

            new_func = types.FunctionType(
                tool_func.__code__,
                tool_func.__globals__,
                fname,
                tool_func.__defaults__,
                tool_func.__closure__,
            )

            new_func.__doc__ = f"Route query to agent {aid}"
            # Store the original agent_id as a custom attribute
            new_func._original_agent_id = aid
            return tool(new_func)

        # Create the tool function for this specific agent
        tool_func = create_tool_function(agent_id, func_name)
        tools.append(tool_func)

    # Build agent descriptions for system prompt
    agent_descriptions = []
    for tool_func in tools:
        # Get the original agent_id from the function's custom attribute
        agent_id = getattr(tool_func, "_original_agent_id", None)
        if not agent_id:
            raise ValueError(
                f"Tool function {tool_func.__name__} missing _original_agent_id attribute"
            )

        from ..factory import agent_factory

        info = agent_factory._registry[agent_id]
        agent_name = info["agent_name"]
        agent_description = info["agent_description"]
        sample_queries = info["sample_queries"]

        sample_queries_text = ""
        if sample_queries:
            sample_queries_text = f"\nExample queries: {', '.join(sample_queries)}"

        agent_descriptions.append(
            f"- {agent_name}: {agent_description}{sample_queries_text}"
        )

    # Create system prompt with agent descriptions
    agent_names_description_sample_queries = "\n".join(agent_descriptions)

    system_prompt = f"""You are an intelligent orchestrator that routes user queries to specialized agents.

Available specialized agents:
{agent_names_description_sample_queries}

# Role
Your role is to:
1. Analyze the user's query to understand what they're asking for
2. Select the most appropriate specialized agent based on the query content and agent capabilities
3. Route the query to that agent using the corresponding tool
4. Return the agent's response to the user in the result format specified below:

# Result format
Your final response needs to formatted in a specific way for the downstream user to understand it. Here is a description of the result format:
```markdown
{load_result_format_description()}
```

# Guidelines
- Choose the agent whose description and sample queries best match the user's request
- If a query could fit multiple agents, choose the most specific/specialized one
- Always use exactly one agent tool per query
- Pass the user's original query directly to the selected agent
- Return the agent's response without modification

Remember: Your job is to route queries, not to answer them directly. Always use one of the available agent tools.

If the agents response is a json already matching the above result format, return it directly without any modifications or additional interpretation of the results.
"""

    # Get model ID from environment variable
    model_id = os.environ.get(
        "DOCUMENT_ANALYSIS_AGENT_MODEL_ID",
        "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    )

    # Create the orchestrator agent
    model = create_strands_bedrock_model(
        model_id=model_id,
        session=session,
    )

    orchestrator = strands.Agent(
        system_prompt=system_prompt,
        model=model,
        tools=tools,
        callback_handler=None,
    )

    return orchestrator
