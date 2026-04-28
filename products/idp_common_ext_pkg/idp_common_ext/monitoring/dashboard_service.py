# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Backward-compatibility shim for DashboardService.

The canonical implementation has been renamed to
:class:`~idp_common.monitoring.MonitoringMetricsService` in
``monitoring_metrics_service.py``.

This module re-exports ``MonitoringMetricsService`` under the legacy
``DashboardService`` name so that existing code and tests that import
``DashboardService`` continue to work without modification.

New code should import ``MonitoringMetricsService`` directly::

    from idp_common_ext.monitoring import MonitoringMetricsService
"""

from idp_common_ext.monitoring.monitoring_metrics_service import MonitoringMetricsService

# Legacy alias — do not use in new code
DashboardService = MonitoringMetricsService

__all__ = ["DashboardService", "MonitoringMetricsService"]
