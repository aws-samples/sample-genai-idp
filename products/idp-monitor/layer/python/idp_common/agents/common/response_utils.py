# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Utility functions for parsing and handling agent responses.
"""

import json
import logging
import re
from typing import Any, Dict

logger = logging.getLogger(__name__)


def extract_json_from_markdown(response: str) -> str:
    """
    Extract JSON content from markdown code blocks.

    The LLM often returns JSON wrapped in markdown code blocks like:
    ```json
    {"key": "value"}
    ```

    This function extracts the JSON content between the code block markers.

    Args:
        response: The raw response string from the LLM

    Returns:
        The extracted JSON string, or the original response if no code blocks found
    """
    # Pattern to match ```json ... ``` or ``` ... ``` code blocks
    json_pattern = r"```(?:json)?\s*\n?(.*?)\n?```"

    match = re.search(json_pattern, response, re.DOTALL | re.IGNORECASE)
    if match:
        extracted_json = match.group(1).strip()
        logger.debug(
            f"Extracted JSON from markdown code block: {extracted_json[:100]}..."
        )
        return extracted_json

    # If no code blocks found, return the original response
    logger.debug("No markdown code blocks found, returning original response")
    return response.strip()


def parse_agent_response(response) -> Dict[str, Any]:
    """
    Parse the agent response, handling Strands AgentResult objects.

    Args:
        response: The response from the Strands agent (AgentResult)

    Returns:
        Parsed JSON response as a dictionary

    Raises:
        ValueError: If the response is not a valid AgentResult
    """
    # Check if response is a Strands AgentResult
    if not hasattr(response, "__str__"):
        raise ValueError(f"Expected Strands AgentResult, got {type(response)}")

    # Convert AgentResult to string using its __str__ method
    response_str = str(response)
    logger.debug(f"Processing AgentResult as string: {response_str[:100]}...")

    # Check if response looks like JSON before trying to parse
    response_str = response_str.strip()
    if not (response_str.startswith("{") or response_str.startswith("```")):
        logger.debug("Response doesn't appear to be JSON, returning as text")
        return {"responseType": "text", "content": response_str}

    # Extract JSON from markdown code blocks if present
    json_str = extract_json_from_markdown(response_str)

    try:
        parsed_response = json.loads(json_str)
        logger.debug(
            f"Successfully parsed JSON response with type: {parsed_response.get('responseType', 'unknown')}"
        )
        return parsed_response
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse as JSON, returning as text: {e}")
        return {"responseType": "text", "content": response_str}
