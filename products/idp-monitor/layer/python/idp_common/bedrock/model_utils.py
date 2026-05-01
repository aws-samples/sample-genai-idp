# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Utility functions for Bedrock model ID handling.

This module provides utilities for parsing model IDs and extracting
service tier information from model ID suffixes.
"""

import logging
from typing import Optional, Tuple

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
