# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Base class for IDP MCP tools"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class IDPTool(ABC):
    """Base class for IDP MCP tools"""

    @abstractmethod
    def execute(self, **kwargs) -> Dict[str, Any]:
        """Execute tool logic"""
        pass
