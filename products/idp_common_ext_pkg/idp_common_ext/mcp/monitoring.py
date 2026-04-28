# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
IDPMonitor MCP plugin — 7 monitoring tools.

Registered via the ``idp_mcp.plugins`` entry point in ``setup.py``.
The open-source ``idp_mcp_connector`` calls ``register(server)`` here
at startup — adding 7 monitoring tools to the MCP server when
``idp_common_ext`` is installed.

Tools exposed:

    monitoring_dashboard    Full dashboard data for all sections
    monitoring_volume       Document volume and status breakdown
    monitoring_costs        Cost and token metrics (auto-Athena)
    monitoring_failures     Recently failed documents with error details
    monitoring_throttles    AWS service throttle counts and severity
    monitoring_performance  X-Ray P50/P90/P99 latency by pipeline stage
    monitoring_config       Active config version and document types

All tools accept ``stack_name`` and ``hours`` parameters.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _get_ops(stack_name: Optional[str]) -> Any:
    """Return a MonitoringOperations instance for the given stack."""
    from idp_common_ext.sdk.monitoring import MonitoringOperations

    resolved = stack_name or os.environ.get("STACK_NAME", "")
    if not resolved:
        raise ValueError(
            "stack_name is required. Pass it as a tool argument or set the STACK_NAME env var."
        )
    return MonitoringOperations(resolved)


# ---------------------------------------------------------------------------
# Entry point called by open-source plugin discovery
# ---------------------------------------------------------------------------


def register(server: Any) -> None:
    """
    Entry point called by the open-source MCP connector's plugin discovery.

    Registers 7 monitoring tools on the MCP ``server`` instance.
    The server object is expected to expose a ``tool()`` decorator
    (following the MCP connector pattern in ``lib/idp_mcp_connector_pkg/``).
    """

    @server.tool()
    def monitoring_dashboard(
        stack_name: Optional[str] = None,
        hours: int = 24,
        doc_prefix: Optional[str] = None,
    ) -> dict:
        """
        Return full monitoring dashboard data (all sections).

        Args:
            stack_name:  IDP Accelerator stack name (falls back to STACK_NAME env var).
            hours:       Time range in hours (default: 24).
            doc_prefix:  Optional S3 key prefix filter.
        """
        return _get_ops(stack_name).get_dashboard(hours=hours, doc_prefix=doc_prefix)

    @server.tool()
    def monitoring_volume(
        stack_name: Optional[str] = None,
        hours: int = 24,
        doc_prefix: Optional[str] = None,
    ) -> dict:
        """
        Return document volume and status breakdown.

        Args:
            stack_name:  IDP Accelerator stack name.
            hours:       Time range in hours (default: 24).
            doc_prefix:  Optional S3 key prefix filter.
        """
        return _get_ops(stack_name).get_volume_metrics(
            hours=hours, doc_prefix=doc_prefix
        )

    @server.tool()
    def monitoring_costs(
        stack_name: Optional[str] = None,
        hours: int = 24,
        doc_prefix: Optional[str] = None,
    ) -> dict:
        """
        Return cost and token metrics (auto-routes to Athena when configured).

        Args:
            stack_name:  IDP Accelerator stack name.
            hours:       Time range in hours (default: 24).
            doc_prefix:  Optional S3 key prefix filter.
        """
        return _get_ops(stack_name).get_cost_metrics(hours=hours, doc_prefix=doc_prefix)

    @server.tool()
    def monitoring_failures(
        stack_name: Optional[str] = None,
        hours: int = 24,
        doc_prefix: Optional[str] = None,
    ) -> dict:
        """
        Return recently failed documents with error details.

        Args:
            stack_name:  IDP Accelerator stack name.
            hours:       Time range in hours (default: 24).
            doc_prefix:  Optional S3 key prefix filter.
        """
        return _get_ops(stack_name).get_recent_failures(
            hours=hours, doc_prefix=doc_prefix
        )

    @server.tool()
    def monitoring_throttles(
        stack_name: Optional[str] = None,
        hours: int = 1,
    ) -> dict:
        """
        Return AWS service throttle counts and severity badges.

        Args:
            stack_name:  IDP Accelerator stack name.
            hours:       Time range in hours (default: 1).
        """
        return _get_ops(stack_name).get_throttle_report(hours=hours)

    @server.tool()
    def monitoring_performance(
        stack_name: Optional[str] = None,
        hours: int = 1,
    ) -> dict:
        """
        Return X-Ray latency percentiles (P50/P90/P99) by pipeline stage.

        Args:
            stack_name:  IDP Accelerator stack name.
            hours:       Time range in hours (default: 1).
        """
        return _get_ops(stack_name).get_latency_metrics(hours=hours)

    @server.tool()
    def monitoring_config(
        stack_name: Optional[str] = None,
    ) -> dict:
        """
        Return active IDP config version and document type list.

        Args:
            stack_name:  IDP Accelerator stack name.
        """
        return _get_ops(stack_name).get_config_info()

    logger.debug("IDPMonitor MCP plugin registered: 7 monitoring tools added")
