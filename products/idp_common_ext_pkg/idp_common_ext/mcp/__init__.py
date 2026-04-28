# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
``idp_common_ext.mcp`` — MCP plugin package for IDPMonitor.

The ``register(server)`` function in ``monitoring.py`` is called automatically
by the open-source ``idp_mcp_connector`` plugin discovery hook when this package
is installed.  It adds 7 monitoring tools to the MCP server.

This sub-package is NOT imported directly by consumers — it is discovered via
the ``idp_mcp.plugins`` entry point registered in ``setup.py``.
"""
