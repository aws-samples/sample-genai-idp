# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Utility functions for Bedrock model ID handling.

This module provides utilities for parsing model IDs and extracting
service tier information from model ID suffixes.
"""

import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

import yaml

logger = logging.getLogger(__name__)


def parse_model_id(model_id: str) -> Tuple[str, Optional[str]]:
    """
    Parse a model ID to extract the base model ID and service tier.

    Model IDs can include an optional service tier suffix in the format:
    <base-model-id>[:<service-tier>]

    Examples:
        >>> parse_model_id("us.amazon.nova-2-lite-v1:0")
        ("us.amazon.nova-2-lite-v1:0", None)

        >>> parse_model_id("us.amazon.nova-2-lite-v1:0:flex")
        ("us.amazon.nova-2-lite-v1:0", "flex")

        >>> parse_model_id("us.amazon.nova-2-lite-v1:0:priority")
        ("us.amazon.nova-2-lite-v1:0", "priority")

    Args:
        model_id: The model ID string, potentially with service tier suffix

    Returns:
        Tuple of (base_model_id, service_tier) where service_tier is None
        if no valid tier suffix is present
    """
    if not model_id:
        return model_id, None

    # Split on colons
    parts = model_id.split(":")

    # If only 1 or 2 parts, no tier suffix
    if len(parts) <= 2:
        return model_id, None

    # Check if last part is a valid service tier
    potential_tier = parts[-1].lower().strip()
    valid_tiers = ["flex", "priority"]

    if potential_tier in valid_tiers:
        # Reconstruct base model ID without the tier suffix
        base_model_id = ":".join(parts[:-1])
        return base_model_id, potential_tier

    # Last part is not a valid tier, return as-is
    return model_id, None


@lru_cache(maxsize=1)
def _load_model_limits() -> list[dict]:
    """
    Load model limits from model_config_limits.yaml.

    Returns:
        List of model limit entries with pattern and max_output_tokens.

    Raises:
        FileNotFoundError: If model_config_limits.yaml cannot be found.
        ValueError: If the YAML file is malformed or missing required fields.
    """
    # Resolution order. The file is BUNDLED into the package
    # (idp_common/config/model_config_limits.yaml) so it resolves at runtime in
    # Lambda, notebooks, and pip installs — the same pattern as system_defaults.
    # The repo-root config_library/ copy is the source of truth for editing and
    # is used as a dev/publish-time fallback.
    limit_paths = [
        # 1. Bundled in-package copy (sibling of this file's config package).
        Path(__file__).parent.parent / "config" / "model_config_limits.yaml",
        # 2. Development / publish: repo-root config_library/ (5 parents up).
        Path(__file__).parent.parent.parent.parent.parent
        / "config_library"
        / "model_config_limits.yaml",
        # 3. Fallback: IDP_PROJECT_ROOT or current working directory.
        Path(os.environ.get("IDP_PROJECT_ROOT", "."))
        / "config_library"
        / "model_config_limits.yaml",
    ]

    limit_file = None
    for path in limit_paths:
        if path.exists():
            limit_file = path
            break

    if not limit_file:
        raise FileNotFoundError(
            "model_config_limits.yaml not found. "
            "Ensure idp-cli is run from repository root or set IDP_PROJECT_ROOT environment variable. "
            f"Searched paths: {[str(p) for p in limit_paths]}"
        )

    try:
        with open(limit_file) as f:
            config = yaml.safe_load(f)

        if not config or "model_limits" not in config:
            raise ValueError(
                f"model_config_limits.yaml is missing 'model_limits' key: {limit_file}"
            )

        model_limits = config.get("model_limits", [])
        logger.debug(
            "Loaded %d model limit patterns from model_config_limits.yaml",
            len(model_limits),
        )
        return model_limits

    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse model_config_limits.yaml: {e}") from e


def get_model_max_output_tokens(model_id: str) -> int:
    """
    Get the maximum output tokens supported by a Bedrock model.

    This function determines model-specific maximum token limits by loading
    patterns from config_library/model_config_limits.yaml. Patterns are matched
    in order (first match wins). There is no AWS API that exposes the per-model
    output limit, so this file is the source of truth; an unmatched model raises
    ValueError (callers can fall back to parse_max_tokens_limit_from_error on a
    Bedrock over-limit ValidationException to self-heal a missing entry).

    Token Limits by Model Family (from model_config_limits.yaml):
        - Claude Sonnet 5 / Opus 4.6-4.8 / Sonnet 4.6: 128,000 tokens
        - Other Claude 4.x models: 64,000 tokens
        - Claude 3.x models: 8,192 tokens
        - Amazon Nova models: 10,000 tokens
        - OpenAI GPT-5.x: 128,000 tokens

    Args:
        model_id: Bedrock model identifier (e.g., "us.anthropic.claude-sonnet-4-20250514-v1:0")

    Returns:
        Maximum output tokens supported by the model

    Raises:
        FileNotFoundError: If model_config_limits.yaml cannot be found
        ValueError: If model_config_limits.yaml is malformed
        RuntimeError: If no pattern matches the model_id (should never happen with ".*" catch-all)

    Examples:
        >>> get_model_max_output_tokens("us.anthropic.claude-sonnet-4-20250514-v1:0")
        64000
        >>> get_model_max_output_tokens("us.amazon.nova-lite-v1:0")
        10000
        >>> get_model_max_output_tokens("us.anthropic.claude-3-haiku-20240307-v1:0")
        8192
    """
    model_id_lower = model_id.lower()

    # Load from config file (raises if file not found or malformed)
    model_limits = _load_model_limits()

    # Match against patterns in order (first match wins)
    for limit_entry in model_limits:
        pattern = limit_entry.get("pattern", "")
        max_tokens = limit_entry.get("max_output_tokens")

        if not pattern or max_tokens is None:
            logger.warning(
                "Skipping malformed model limit entry",
                extra={"entry": limit_entry},
            )
            continue

        if re.search(pattern, model_id_lower):
            logger.debug(
                "Matched model limit pattern",
                extra={
                    "model_id": model_id,
                    "pattern": pattern,
                    "max_output_tokens": max_tokens,
                },
            )
            return max_tokens

    # No pattern matched - unknown/unsupported model
    raise ValueError(
        f"Unsupported model ID: {model_id}. "
        f"No max_tokens limit defined in model_config_limits.yaml. "
        f"Supported model families: Claude 4.x, Claude 3.x, Amazon Nova. "
        f"To add this model, run scripts/discover_model_limits.py to test its actual limits."
    )


# Bedrock's ValidationException for an over-limit maxTokens request states the
# real cap in the message. There is no AWS API that exposes the per-model output
# limit, so this error text is the authoritative source we fall back to when
# model_config_limits.yaml is missing/stale for a model. Two observed formats:
#   Claude: "max_tokens: 999999 > 128000, which is the maximum allowed number of
#            output tokens for anthropic.claude-sonnet-5"
#   Nova:   "The maximum tokens you requested exceeds the model limit of 10000."
_MAX_TOKENS_LIMIT_PATTERNS = (
    re.compile(r">\s*(\d+)\s*,\s*which is the maximum", re.IGNORECASE),
    re.compile(r"model limit of\s*(\d+)", re.IGNORECASE),
)


def parse_max_tokens_limit_from_error(message: str) -> Optional[int]:
    """Extract the true max-output-tokens limit from a Bedrock ValidationException.

    Returns the limit as an int when the message matches a known over-limit
    format, otherwise None (the error is unrelated to max_tokens).
    """
    if not message:
        return None
    for pattern in _MAX_TOKENS_LIMIT_PATTERNS:
        m = pattern.search(message)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None
    return None
