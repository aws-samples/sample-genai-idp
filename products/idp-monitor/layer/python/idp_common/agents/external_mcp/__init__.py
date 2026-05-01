# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
External MCP Agent module.
"""

from .agent import create_external_mcp_agent
from .config import get_external_mcp_config

__all__ = ["create_external_mcp_agent", "get_external_mcp_config"]
