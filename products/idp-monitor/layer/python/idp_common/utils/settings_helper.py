"""
Settings helper for runtime configuration via SSM Parameter Store.

Provides cached access to stack settings stored in SSM, enabling
Lambda functions to retrieve configuration values without deployment-time
dependencies on other nested stacks.
"""

import json
import os
import time
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

# Module-level cache
_settings_cache: Optional[Dict[str, Any]] = None
_cache_timestamp: float = 0
_CACHE_TTL_SECONDS = 300  # 5 minute cache

ssm_client = boto3.client("ssm")


def get_settings(
    parameter_name: Optional[str] = None, force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Get settings from SSM Parameter Store with caching.

    Args:
        parameter_name: SSM parameter name. Defaults to SETTINGS_PARAMETER env var.
        force_refresh: If True, bypass cache and fetch fresh values.

    Returns:
        Dict containing settings key-value pairs.

    Raises:
        ValueError: If parameter_name not provided and SETTINGS_PARAMETER not set.
        ClientError: If SSM parameter cannot be retrieved.

    Example:
        >>> settings = get_settings()
        >>> state_machine_arn = settings.get('StateMachineArn')
    """
    global _settings_cache, _cache_timestamp

    param_name = parameter_name or os.environ.get("SETTINGS_PARAMETER")
    if not param_name:
        raise ValueError(
            "Settings parameter name not provided and SETTINGS_PARAMETER "
            "environment variable not set"
        )

    current_time = time.time()
    cache_valid = (
        _settings_cache is not None
        and not force_refresh
        and (current_time - _cache_timestamp) < _CACHE_TTL_SECONDS
    )

    if cache_valid:
        return _settings_cache  # type: ignore[return-value]

    try:
        response = ssm_client.get_parameter(Name=param_name)
        _settings_cache = json.loads(response["Parameter"]["Value"])
        _cache_timestamp = current_time
        return _settings_cache
    except ClientError as e:
        # If parameter doesn't exist yet (during initial deployment), return empty dict
        if e.response["Error"]["Code"] == "ParameterNotFound":
            return {}
        raise


def get_setting(
    key: str, default: Any = None, parameter_name: Optional[str] = None
) -> Any:
    """
    Get a specific setting value.

    Args:
        key: The setting key to retrieve.
        default: Default value if key not found.
        parameter_name: SSM parameter name (optional).

    Returns:
        The setting value, or default if not found.

    Example:
        >>> state_machine_arn = get_setting('StateMachineArn')
        >>> kb_id = get_setting('KnowledgeBaseId', default='')
    """
    settings = get_settings(parameter_name=parameter_name)
    return settings.get(key, default)


def clear_cache() -> None:
    """Clear the settings cache. Useful for testing."""
    global _settings_cache, _cache_timestamp
    _settings_cache = None
    _cache_timestamp = 0
