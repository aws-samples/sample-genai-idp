# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Configuration type constants.

These constants define the valid configuration types used throughout the system.
Use these instead of hardcoded strings to ensure consistency and type safety.
"""

# Configuration Types
CONFIG_TYPE_SCHEMA = "Schema"
CONFIG_TYPE_CONFIG = "Config"
DEFAULT_VERSION = "default"

# Legacy configuration types (for backward compatibility)
CONFIG_TYPE_DEFAULT = "Default"
CONFIG_TYPE_CUSTOM = "Custom"

# Pricing Configuration Types (mirrors Default/Custom pattern)
CONFIG_TYPE_DEFAULT_PRICING = "DefaultPricing"
CONFIG_TYPE_CUSTOM_PRICING = "CustomPricing"

# All valid configuration types
VALID_CONFIG_TYPES = [
    CONFIG_TYPE_SCHEMA,
    CONFIG_TYPE_CONFIG,
    CONFIG_TYPE_DEFAULT_PRICING,
    CONFIG_TYPE_CUSTOM_PRICING,
    CONFIG_TYPE_DEFAULT,  # Legacy
    CONFIG_TYPE_CUSTOM,   # Legacy
]
