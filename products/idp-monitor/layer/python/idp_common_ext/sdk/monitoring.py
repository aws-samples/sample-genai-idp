# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
IDPMonitor SDK plugin — ``client.monitoring`` namespace.

Registered via the ``idp_sdk.plugins`` entry point in ``setup.py``.
The open-source ``IDPClient._load_plugins()`` calls ``register(client, stack_name)``
here at init time — setting ``client.monitoring = MonitoringOperations(stack_name)``.

Usage (after ``idp_common_ext`` is installed)::

    from idp_sdk import IDPClient

    client = IDPClient(stack_name="my-idp-stack")
    dashboard = client.monitoring.get_dashboard(hours=24)
    failures  = client.monitoring.get_recent_failures(hours=6)
    costs     = client.monitoring.get_cost_metrics(hours=24)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from idp_common_ext.monitoring import MonitoringMetricsService, TimeRange

logger = logging.getLogger(__name__)


class MonitoringOperations:
    """
    Provides programmatic access to all IDPMonitor metrics.

    Instantiated per ``IDPClient`` instance via plugin discovery.
    All methods call ``MonitoringMetricsService`` directly using the
    customer's IAM context — no subscription check here (gating is
    handled by the Lambda resolver in the UI path).
    """

    def __init__(self, stack_name: str) -> None:
        self._stack_name = stack_name
        self._svc: Optional[MonitoringMetricsService] = None

    def _get_service(self) -> MonitoringMetricsService:
        """Lazy-initialize the monitoring service (avoids import overhead at startup)."""
        if self._svc is None:
            self._svc = MonitoringMetricsService()
        return self._svc

    # ------------------------------------------------------------------
    # Core dashboard methods
    # ------------------------------------------------------------------

    def get_dashboard(
        self,
        hours: int = 24,
        doc_prefix: Optional[str] = None,
        include_latency: bool = True,
        include_throttles: bool = True,
    ) -> Dict[str, Any]:
        """
        Return full dashboard data (all sections).

        Args:
            hours:             Time range in hours (default: 24).
            doc_prefix:        Optional S3 key prefix to scope DynamoDB queries.
            include_latency:   Include X-Ray latency section (slightly slower).
            include_throttles: Include CloudWatch throttles section.

        Returns:
            Normalized dashboard dict — same shape as AppSync response.
        """
        sections = [
            "volume",
            "status",
            "doc_types",
            "timeline",
            "failures",
            "config",
            "costs",
        ]
        if include_latency:
            sections.append("latency")
        if include_throttles:
            sections.append("throttles")

        tr = TimeRange.last_n_hours(hours)
        return self._get_service().get_dashboard_data(
            time_range=tr,
            doc_prefix=doc_prefix,
            include_sections=sections,
        )

    def get_volume_metrics(
        self,
        hours: int = 24,
        doc_prefix: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return volume and status breakdown only (fast — DynamoDB only)."""
        tr = TimeRange.last_n_hours(hours)
        return self._get_service().get_dashboard_data(
            time_range=tr,
            doc_prefix=doc_prefix,
            include_sections=["volume", "status", "doc_types", "timeline"],
        )

    def get_cost_metrics(
        self,
        hours: int = 24,
        doc_prefix: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Return cost and token metrics.

        Auto-routes to Athena when configured; falls back to DynamoDB otherwise.
        """
        tr = TimeRange.last_n_hours(hours)
        return self._get_service().get_dashboard_data(
            time_range=tr,
            doc_prefix=doc_prefix,
            include_sections=["costs"],
        )

    def get_recent_failures(
        self,
        hours: int = 24,
        doc_prefix: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return recently failed documents with error details."""
        tr = TimeRange.last_n_hours(hours)
        return self._get_service().get_dashboard_data(
            time_range=tr,
            doc_prefix=doc_prefix,
            include_sections=["failures"],
        )

    def get_throttle_report(self, hours: int = 1) -> Dict[str, Any]:
        """Return CloudWatch throttle report with severity badges."""
        tr = TimeRange.last_n_hours(hours)
        return self._get_service().get_dashboard_data(
            time_range=tr,
            include_sections=["throttles"],
        )

    def get_latency_metrics(self, hours: int = 1) -> Dict[str, Any]:
        """Return X-Ray latency percentiles (P50/P90/P99) by pipeline stage."""
        tr = TimeRange.last_n_hours(hours)
        return self._get_service().get_dashboard_data(
            time_range=tr,
            include_sections=["latency"],
        )

    def get_config_info(self) -> Dict[str, Any]:
        """Return active config version and document type count."""
        tr = TimeRange.last_n_hours(24)
        return self._get_service().get_dashboard_data(
            time_range=tr,
            include_sections=["config"],
        )

    # ------------------------------------------------------------------
    # Analytics methods (Athena-backed — return None when not configured)
    # ------------------------------------------------------------------

    def get_token_utilization(self, hours: int = 24) -> Optional[Dict[str, Any]]:
        """
        Token usage breakdown by model and processing context (Athena only).

        Returns ``None`` when Athena is not configured.
        """
        tr = TimeRange.last_n_hours(hours)
        result = self._get_service().get_dashboard_data(
            time_range=tr,
            include_sections=["token_usage"],
        )
        return result.get("tokenUtilization")

    def get_cost_trends(
        self,
        hours: int = 168,
        bucket: str = "day",
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Cost time-series data (Athena only).

        Args:
            hours:  Time range in hours (default: 168 = 7 days).
            bucket: Granularity — ``"hour"`` | ``"day"`` | ``"week"``.

        Returns ``None`` when Athena is not configured.
        """
        tr = TimeRange.last_n_hours(hours)
        result = self._get_service().get_dashboard_data(
            time_range=tr,
            include_sections=["cost_trends"],
        )
        return result.get("costTrends")

    def get_cost_by_config_version(self, hours: int = 720) -> Optional[Dict[str, Any]]:
        """
        Cost and document volume per config version (Athena only).

        Returns ``None`` when Athena is not configured.
        """
        tr = TimeRange.last_n_hours(hours)
        result = self._get_service().get_dashboard_data(
            time_range=tr,
            include_sections=["cost_by_version"],
        )
        return result.get("costByVersion")

    def get_model_usage(self, hours: int = 24) -> Optional[Dict[str, Any]]:
        """
        Per-model cost breakdown and usage statistics (Athena only).

        Returns ``None`` when Athena is not configured.
        """
        tr = TimeRange.last_n_hours(hours)
        result = self._get_service().get_dashboard_data(
            time_range=tr,
            include_sections=["model_usage"],
        )
        return result.get("modelUsage")


# ---------------------------------------------------------------------------
# Entry point called by open-source plugin discovery
# ---------------------------------------------------------------------------


def register(client: Any, stack_name: str) -> None:
    """
    Entry point called by ``IDPClient._load_plugins()``.

    Sets ``client.monitoring = MonitoringOperations(stack_name)``.
    """
    client.monitoring = MonitoringOperations(stack_name)
    logger.debug(
        "IDPMonitor SDK plugin registered: client.monitoring set for stack '%s'",
        stack_name,
    )
