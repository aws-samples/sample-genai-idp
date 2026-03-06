# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""MCP Tools for IDP operations"""

from typing import Dict, Type
from .base import IDPTool
from .search import SearchTool
from .batch_run import BatchRunTool
from .batch_reprocess import BatchReprocessTool
from .batch_status import BatchStatusTool
from .batch_results import GetResultsTool

# Tool registry
TOOLS: Dict[str, Type[IDPTool]] = {
    "search": SearchTool,
    "process": BatchRunTool,
    "reprocess": BatchReprocessTool,
    "status": BatchStatusTool,
    "get_results": GetResultsTool,
}


def get_tool(name: str) -> IDPTool:
    """Get tool instance by name"""
    tool_class = TOOLS.get(name)
    if not tool_class:
        raise ValueError(f"Unknown tool: {name}")
    return tool_class()
