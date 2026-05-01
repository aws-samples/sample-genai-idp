# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Utility functions for analytics agents.
"""

import logging

logger = logging.getLogger(__name__)

# Global reference to code interpreter tools for cleanup
_code_interpreter_tools_instance = None


def register_code_interpreter_tools(tools_instance):
    """Register the code interpreter tools instance for cleanup."""
    global _code_interpreter_tools_instance
    _code_interpreter_tools_instance = tools_instance


def cleanup_code_interpreter():
    """Clean up the global code interpreter session if it exists."""
    global _code_interpreter_tools_instance
    if _code_interpreter_tools_instance:
        logger.info("Cleaning up code interpreter session...")
        _code_interpreter_tools_instance.cleanup()
        _code_interpreter_tools_instance = None
    else:
        logger.debug("No code interpreter session to clean up")
