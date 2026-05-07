# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
``idp_common_ext.monitoring`` — IDPMonitor premium monitoring services.

All monitoring services live here in ``idp_common_ext.monitoring`` (premium
``products/idp_common_ext_pkg``).  This package is completely standalone —
it no longer re-exports from ``idp_common.monitoring``.

Public API::

    from idp_common_ext.monitoring import (
        MonitoringMetricsService,
        TimeRange,
        DocumentRecord,
        MonitoringKPIs,
        OperationalDocumentService,
        CloudWatchMetricsService,
        AnalyticsCostService,
        AnalyticsDocumentService,
        AnalyticsEvaluationService,
        AnalyticsAthenaService,
        DashboardService,
        DocumentStatsService,
    )
"""

# ---------------------------------------------------------------------------
# Analytics services (Athena-backed)
# ---------------------------------------------------------------------------
from idp_common_ext.monitoring.analytics_athena_service import (
    AnalyticsAthenaService,
    AnalyticsNotConfiguredError,
    AnalyticsQueryError,
)
from idp_common_ext.monitoring.analytics_cost_service import (
    AnalyticsCostService,
)
from idp_common_ext.monitoring.analytics_document_service import (
    AnalyticsDocumentService,
)
from idp_common_ext.monitoring.analytics_evaluation_service import (
    AnalyticsEvaluationService,
)

# ---------------------------------------------------------------------------
# CloudWatch Logs
# ---------------------------------------------------------------------------
from idp_common_ext.monitoring.cloudwatch_logs_service import (
    get_stack_log_groups,
    prioritize_performance_log_groups,
    search_by_document_fallback,
    search_by_request_ids,
    search_log_group,
    search_stack_wide,
)
from idp_common_ext.monitoring.cloudwatch_logs_service import (
    reset_settings_cache as reset_cw_settings_cache,
)

# ---------------------------------------------------------------------------
# CloudWatch Metrics
# ---------------------------------------------------------------------------
from idp_common_ext.monitoring.cloudwatch_metrics_service import (
    CloudWatchMetricsService,
)

# ---------------------------------------------------------------------------
# Dashboard / unified entry points
# ---------------------------------------------------------------------------
from idp_common_ext.monitoring.dashboard_service import (
    DashboardService,
)

# ---------------------------------------------------------------------------
# Document stats
# ---------------------------------------------------------------------------
from idp_common_ext.monitoring.document_stats_service import (
    DocumentStatsService,
)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
from idp_common_ext.monitoring.models import (
    DocumentRecord,
    LogEvent,
    LogSearchResult,
    MonitoringKPIs,
    TimeRange,
    TraceSegment,
)

# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------
from idp_common_ext.monitoring.monitoring_metrics_service import (
    MonitoringMetricsService,
)

# ---------------------------------------------------------------------------
# Operational / Document services
# ---------------------------------------------------------------------------
from idp_common_ext.monitoring.operational_document_service import (
    OperationalDocumentService,
)

# ---------------------------------------------------------------------------
# Settings cache
# ---------------------------------------------------------------------------
from idp_common_ext.monitoring.settings_cache import (
    SettingsCache,
    get_cloudwatch_log_groups,
    get_setting,
)

# ---------------------------------------------------------------------------
# Stack utilities
# ---------------------------------------------------------------------------
from idp_common_ext.monitoring.stack_utils import (
    extract_stack_name_from_arn,
    get_lambda_function_names,
    get_stack_name,
    get_stack_resources,
    get_state_machine_arn,
)

# ---------------------------------------------------------------------------
# Step Functions
# ---------------------------------------------------------------------------
from idp_common_ext.monitoring.stepfunctions_service import (
    analyze_execution_timeline,
    extract_failure_details,
    get_execution_arn_from_document,
    get_execution_data,
)

# ---------------------------------------------------------------------------
# X-Ray
# ---------------------------------------------------------------------------
from idp_common_ext.monitoring.xray_service import (
    analyze_trace,
    extract_lambda_request_ids,
    get_aws_sdk_call_metrics,
    get_latency_percentiles,
    get_service_performance_summary,
    get_subsegment_details,
    get_throttle_traces,
    get_trace_for_document,
)

__all__ = [
    # Models
    "TimeRange",
    "LogEvent",
    "LogSearchResult",
    "TraceSegment",
    "DocumentRecord",
    "MonitoringKPIs",
    # Settings cache
    "SettingsCache",
    "get_setting",
    "get_cloudwatch_log_groups",
    # CloudWatch Logs
    "get_stack_log_groups",
    "prioritize_performance_log_groups",
    "search_by_document_fallback",
    "search_by_request_ids",
    "search_log_group",
    "search_stack_wide",
    "reset_cw_settings_cache",
    # Stack utilities
    "get_stack_name",
    "extract_stack_name_from_arn",
    "get_stack_resources",
    "get_lambda_function_names",
    "get_state_machine_arn",
    # Step Functions
    "get_execution_arn_from_document",
    "get_execution_data",
    "analyze_execution_timeline",
    "extract_failure_details",
    # X-Ray
    "get_trace_for_document",
    "analyze_trace",
    "get_subsegment_details",
    "extract_lambda_request_ids",
    "get_latency_percentiles",
    "get_throttle_traces",
    "get_aws_sdk_call_metrics",
    "get_service_performance_summary",
    # CloudWatch Metrics
    "CloudWatchMetricsService",
    # Operational / Document services
    "OperationalDocumentService",
    "DocumentStatsService",
    # Analytics services
    "AnalyticsAthenaService",
    "AnalyticsNotConfiguredError",
    "AnalyticsQueryError",
    "AnalyticsCostService",
    "AnalyticsDocumentService",
    "AnalyticsEvaluationService",
    # Unified entry points
    "MonitoringMetricsService",
    "DashboardService",
]
