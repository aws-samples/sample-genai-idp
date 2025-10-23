# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Configuration management for error analyzer agents.
"""

import logging
from typing import Any, Dict, List

from ..common.config import configure_logging, get_environment_config

logger = logging.getLogger(__name__)


def get_error_analyzer_config(pattern_config: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Builds complete error analyzer configuration from environment and patterns.
    Get error analyzer configuration with defaults and overrides.

    Returns:
        Dict containing complete error analyzer configuration
    """
    from ... import get_config

    # Start with base environment and context limits
    config = get_environment_config(["CLOUDWATCH_LOG_GROUP_PREFIX", "AWS_STACK_NAME"])
    config.update(get_context_limits())

    # Load and apply agent configuration
    full_config = get_config()
    agent_config = full_config.get("agents", {}).get("error_analyzer", {})

    if not agent_config:
        raise ValueError("error_analyzer configuration not found")

    # Apply agent settings with defaults
    config.update(
        {
            "model_id": agent_config.get(
                "model_id", "anthropic.claude-3-sonnet-20240229-v1:0"
            ),
            "system_prompt": agent_config.get("system_prompt"),
            "error_patterns": get_default_error_patterns(),
            "aws_capabilities": get_aws_service_capabilities(),
        }
    )

    # Apply parameters with type conversion
    params = agent_config.get("parameters", {})
    config["max_log_events"] = safe_int_conversion(params.get("max_log_events"), 5)
    config["time_range_hours_default"] = safe_int_conversion(
        params.get("time_range_hours_default"), 24
    )

    # Apply UI overrides for context limits - UI config takes precedence
    if pattern_config and "max_log_events" in pattern_config:
        config["max_log_events"] = safe_int_conversion(
            pattern_config["max_log_events"], config["max_log_events"]
        )

    # Validate required fields
    if not config.get("system_prompt"):
        raise ValueError("system_prompt is required")

    configure_logging(
        log_level=config.get("log_level"),
        strands_log_level=config.get("strands_log_level"),
    )

    return config


def get_default_error_patterns() -> List[str]:
    """Returns standard error patterns for CloudWatch log filtering."""
    return [
        "ERROR",
        "CRITICAL",
        "FATAL",
        "Exception",
        "Traceback",
        "Failed",
        "Timeout",
        "AccessDenied",
        "ThrottlingException",
    ]


def get_context_limits() -> Dict[str, int]:
    """Returns default resource and context size constraints."""
    return {
        "max_log_events": 5,
        "max_log_message_length": 400,
        "max_events_per_log_group": 5,
        "max_log_groups": 20,
        "max_stepfunction_timeline_events": 3,
        "max_stepfunction_error_length": 200,
        "time_range_hours_default": 24,
    }


def get_aws_service_capabilities() -> Dict[str, Any]:
    """Returns AWS service integration metadata and descriptions."""
    return {
        "cloudwatch_logs": {
            "description": "CloudWatch Logs integration for error analysis",
            "capabilities": [
                "search_log_events",
                "get_log_groups",
                "filter_log_events",
            ],
            "implementation": "Native AWS SDK integration",
        },
        "dynamodb": {
            "description": "DynamoDB integration for document tracking",
            "capabilities": ["scan_table", "query_table", "get_item"],
            "implementation": "Native AWS SDK integration",
        },
        "benefits": [
            "No external dependencies",
            "Native Lambda integration",
            "Optimal performance",
        ],
    }


# Utility functions
def decimal_to_float(obj: Any) -> Any:
    """Recursively converts DynamoDB Decimal objects to JSON-compatible floats."""
    if hasattr(obj, "__class__") and obj.__class__.__name__ == "Decimal":
        return float(obj)
    elif isinstance(obj, dict):
        return {k: decimal_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [decimal_to_float(v) for v in obj]
    return obj


def create_error_response(error: str, **kwargs) -> Dict[str, Any]:
    """Creates standardized error response with consistent format."""
    response = {"error": str(error), "success": False}
    response.update(kwargs)
    return response


def create_success_response(data: Dict[str, Any]) -> Dict[str, Any]:
    """Creates standardized success response with consistent format."""
    response = {"success": True}
    response.update(data)
    return response


def safe_int_conversion(value: Any, default: int = 0) -> int:
    """Safely converts values to integers with fallback handling."""
    try:
        return int(float(value)) if value is not None else default
    except (ValueError, TypeError):
        return default


def truncate_message(message: str, max_length: int = 200) -> str:
    """Truncates messages to specified length with ellipsis indicator."""
    if len(message) <= max_length:
        return message
    return message[:max_length] + "... [truncated]"


def get_config_with_fallback() -> Dict[str, Any]:
    """Gets error analyzer config with graceful fallback to defaults."""
    try:
        return get_error_analyzer_config()
    except Exception as e:
        logger.warning(f"Failed to load config, using defaults: {e}")
        return get_context_limits()
