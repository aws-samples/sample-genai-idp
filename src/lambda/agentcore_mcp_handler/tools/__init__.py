# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""MCP Tools for IDP operations"""

import importlib
from typing import Dict, Tuple

from .base import IDPTool

# Tool registry: name -> (module, class). Modules are imported lazily inside
# get_tool so a dependency problem in ONE tool (e.g. the search tool's agent
# stack) surfaces as a per-call error for that tool instead of a
# Runtime.ImportModuleError that takes down every tool in the handler.
TOOLS: Dict[str, Tuple[str, str]] = {
    "search": ("search", "SearchTool"),
    "process": ("batch_run", "BatchRunTool"),
    "reprocess": ("batch_reprocess", "BatchReprocessTool"),
    "status": ("batch_status", "BatchStatusTool"),
    "get_results": ("batch_results", "GetResultsTool"),
}


def get_tool(name: str) -> IDPTool:
    """Get tool instance by name.

    Args:
        name: Registered tool name (e.g. 'search', 'get_results')

    Returns:
        Instantiated tool.

    Raises:
        ValueError: If the tool name is unknown.
        ImportError: If the tool's module (or one of its dependencies) cannot
            be imported — the error names the missing module so packaging
            problems are diagnosable from the tool response.
    """
    entry = TOOLS.get(name)
    if not entry:
        raise ValueError(f"Unknown tool: {name}")
    module_name, class_name = entry
    module = importlib.import_module(f".{module_name}", package=__name__)
    tool_class = getattr(module, class_name)
    return tool_class()
