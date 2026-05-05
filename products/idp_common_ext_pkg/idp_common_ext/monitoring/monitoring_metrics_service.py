# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
MonitoringMetricsService — unified monitoring data orchestrator.

Runs data fetches in parallel across DynamoDB, CloudWatch, X-Ray, and (when
configured) Athena to assemble a single normalized monitoring snapshot.

The service is the single source of truth for monitoring data format — all
consumers (Lambda resolver for UI, SDK for CLI/programmatic access) call this
service directly and receive the same standardized data shape.

Data source routing
-------------------
``costs``
    Routes to :class:`AnalyticsCostService` (Athena) when Athena is configured,
    falls back to :class:`OperationalDocumentService` (DynamoDB) otherwise.
    This is transparent to callers — the output shape is identical either way.

``token_usage``
    Athena only (``AnalyticsCostService.get_token_utilization``).
    Returns ``None`` when Athena is not configured.

``cost_trends``
    Athena only (``AnalyticsCostService.get_cost_trends``).
    Returns ``None`` when Athena is not configured.

``cost_by_version``
    Athena only (``AnalyticsCostService.get_cost_by_config_version``).
    Returns ``None`` when Athena is not configured.

``model_usage``
    Athena only (``AnalyticsCostService.get_model_usage_breakdown``).
    Returns ``None`` when Athena is not configured.

All other sections (``volume``, ``status``, ``doc_types``, ``timeline``,
``failures``, ``config``, ``throttles``, ``latency``) are operational and
always read from DynamoDB / CloudWatch / X-Ray.

Usage::

    from idp_common_ext.monitoring import MonitoringMetricsService, TimeRange

    svc = MonitoringMetricsService()
    tr = TimeRange.last_n_hours(24)

    result = svc.get_dashboard_data(
        time_range=tr,
        doc_prefix=None,
        include_sections=["volume", "costs", "latency"],
    )
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from idp_common_ext.monitoring.analytics_cost_service import AnalyticsCostService
from idp_common_ext.monitoring.analytics_document_service import (
    AnalyticsDocumentService,
)
from idp_common_ext.monitoring.cloudwatch_metrics_service import (
    CloudWatchMetricsService,
)
from idp_common_ext.monitoring.models import TimeRange
from idp_common_ext.monitoring.operational_document_service import (
    OperationalDocumentService,
)
from idp_common_ext.monitoring.xray_service import get_service_performance_summary

logger = logging.getLogger(__name__)

# All section names recognised by the service
_ALL_SECTIONS = frozenset(
    [
        # Operational — DynamoDB / CloudWatch / X-Ray
        "volume",
        "status",
        "doc_types",
        "timeline",
        "failures",
        "config",
        "throttles",
        "latency",
        # Cost — routes to Athena if configured, DynamoDB fallback
        "costs",
        # Analytics — Athena only (None when not configured)
        "token_usage",
        "cost_trends",
        "cost_by_version",
        "model_usage",
    ]
)


class MonitoringMetricsService:
    """
    Orchestrates parallel data fetching across monitoring services and returns
    a unified, normalized monitoring snapshot.

    All consumers — the Lambda resolver (UI path) and the SDK (CLI/programmatic
    path) — call this service directly.  The normalized output format uses
    camelCase keys and flat arrays so no per-consumer transformation is needed.

    Backward compatibility:
        The constructor still accepts ``document_stats_service`` as a keyword
        argument so existing code that passes a pre-built ``DocumentStatsService``
        continues to work.  The argument is treated as an
        ``OperationalDocumentService`` (they share the same interface).
    """

    def __init__(
        self,
        document_stats_service: Optional[OperationalDocumentService] = None,
        cloudwatch_metrics_service: Optional[CloudWatchMetricsService] = None,
        # New parameters — analytics services (optional)
        operational_service: Optional[OperationalDocumentService] = None,
        analytics_cost_service: Optional[AnalyticsCostService] = None,
        analytics_document_service: Optional[AnalyticsDocumentService] = None,
        analytics_eval_service: Optional[Any] = None,  # AnalyticsEvaluationService
    ) -> None:
        """
        Args:
            document_stats_service:      Legacy param — an ``OperationalDocumentService``
                                         (or old ``DocumentStatsService``).  Used when
                                         ``operational_service`` is not provided.
            cloudwatch_metrics_service:  Optional pre-built CloudWatch service.
            operational_service:         Optional pre-built ``OperationalDocumentService``.
                                         Takes precedence over ``document_stats_service``.
            analytics_cost_service:      Optional pre-built ``AnalyticsCostService``.
                                         When provided and configured, cost/token sections
                                         are served from Athena instead of DynamoDB.
            analytics_document_service:  Optional pre-built ``AnalyticsDocumentService``.
                                         When provided and configured, volume/timeline/
                                         doc_types/config sections are served from Athena
                                         instead of DynamoDB.
            analytics_eval_service:      Optional pre-built ``AnalyticsEvaluationService``.
                                         Reserved for future evaluation sections.
        """
        # Resolve operational service — prefer explicit operational_service,
        # then legacy document_stats_service, then auto-create.
        self._operational = (
            operational_service
            or document_stats_service
            or OperationalDocumentService()
        )
        self._cw_metrics = cloudwatch_metrics_service or CloudWatchMetricsService()
        # Analytics services — auto-create if not provided.
        # AnalyticsCostService.is_configured() gates actual Athena calls.
        self._analytics_cost = analytics_cost_service or AnalyticsCostService()
        self._analytics_doc = analytics_document_service or AnalyticsDocumentService()
        self._analytics_eval = analytics_eval_service  # optional, not auto-created

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def get_dashboard_data(
        self,
        time_range: TimeRange,
        doc_prefix: Optional[str] = None,
        include_sections: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Fetch monitoring data for the requested sections and return a normalized
        response that all consumers can use directly without transformation.

        Args:
            time_range:        Time window to query.
            doc_prefix:        Optional S3 key prefix to scope DynamoDB queries.
            include_sections:  List of section names to fetch.  When ``None``
                               or empty, **all operational sections** are fetched
                               (analytics sections are opt-in via explicit names).
                               Valid names: ``volume``, ``status``, ``costs``,
                               ``doc_types``, ``timeline``, ``failures``,
                               ``config``, ``throttles``, ``latency``,
                               ``token_usage``, ``cost_trends``,
                               ``cost_by_version``, ``model_usage``.

        Returns:
            Normalized dict (all consumers use this format directly)::

                {
                    "kpis": {
                        "totalDocs":         int,
                        "totalPages":        int,
                        "totalInputTokens":  int,
                        "totalOutputTokens": int,
                        "totalCost":         float,
                        "avgCostPerDoc":     float,
                        "successRate":       float,   # 0.0–1.0
                        "failureRate":       float,
                        "criticalErrors":    int,
                        "throttleEvents":    int,
                    } | None,
                    "statusBreakdown": {
                        "successCount":  int,
                        "failureCount":  int,
                        "pendingCount":  int,
                    } | None,
                    "docTypeDistribution": [...],
                    "volumeOverTime":      [...],
                    "latencyByStep":       dict | None,
                    "recentFailures":      [...],
                    "configInfo":          dict | None,
                    "throttleReport":      dict | None,
                    "tokenUtilization":    dict | None,   # Athena only
                    "costTrends":          list | None,   # Athena only
                    "costByVersion":       dict | None,   # Athena only
                    "modelUsage":          dict | None,   # Athena only
                    "queriedAt":           str,           # ISO 8601
                    "dataSources":         list[str],
                }
        """
        # Normalise include_sections — None / empty means all operational sections
        # (analytics sections are opt-in)
        if not include_sections:
            sections = set(_ALL_SECTIONS) - {
                "token_usage",
                "cost_trends",
                "cost_by_version",
                "model_usage",
            }
        else:
            sections = set(s.lower() for s in include_sections)

        # Build task map: section_name → callable (no-arg lambdas)
        tasks: Dict[str, Any] = {}

        # ── Operational sections — route to Athena when configured ────
        if "volume" in sections:
            if self._analytics_doc.is_configured():
                logger.debug(
                    "volume section: routing to Athena AnalyticsDocumentService"
                )
                tasks["volume"] = lambda: self._analytics_doc.get_volume_metrics(
                    time_range
                )
            else:
                tasks["volume"] = lambda: self._operational.get_volume_metrics(
                    time_range
                )

        if "status" in sections:
            # Status breakdown (COMPLETED/FAILED/PENDING) requires DynamoDB
            # because metering only has completed documents.
            tasks["status"] = lambda: self._operational.get_status_breakdown(time_range)

        if "doc_types" in sections:
            if self._analytics_doc.is_configured():
                logger.debug(
                    "doc_types section: routing to Athena AnalyticsDocumentService"
                )
                tasks["doc_types"] = lambda: (
                    self._analytics_doc.get_document_type_distribution(time_range)
                )
            else:
                tasks["doc_types"] = lambda: (
                    self._operational.get_document_type_distribution(time_range)
                )

        if "timeline" in sections:
            if self._analytics_doc.is_configured():
                logger.debug(
                    "timeline section: routing to Athena AnalyticsDocumentService"
                )
                tasks["timeline"] = lambda: self._analytics_doc.get_volume_over_time(
                    time_range
                )
            else:
                tasks["timeline"] = lambda: self._operational.get_volume_over_time(
                    time_range
                )

        if "failures" in sections:
            # Recent failures require DynamoDB (error messages not in Athena)
            tasks["failures"] = lambda: self._operational.get_recent_failures(
                time_range
            )

        if "config" in sections:
            if self._analytics_doc.is_configured():
                logger.debug(
                    "config section: routing to Athena AnalyticsDocumentService"
                )
                tasks["config"] = lambda: (
                    self._analytics_doc.get_config_version_distribution(time_range)
                )
            else:
                tasks["config"] = lambda: (
                    self._operational.get_config_version_distribution(time_range)
                )

        if "throttles" in sections:
            tasks["throttles"] = lambda: self._cw_metrics.get_throttle_report(
                services=["bedrock", "textract", "lambda"],
                time_range=time_range,
            )

        if "latency" in sections:
            _start, _end = time_range.to_datetimes()
            tasks["latency"] = lambda s=_start, e=_end: get_service_performance_summary(
                start_time=s,
                end_time=e,
            )

        # ── Cost section — routes to Athena if configured, DynamoDB fallback ──
        if "costs" in sections:
            if self._analytics_cost.is_configured():
                logger.debug("costs section: routing to Athena AnalyticsCostService")
                tasks["costs"] = lambda: self._analytics_cost.get_cost_metrics(
                    time_range
                )
            else:
                logger.debug(
                    "costs section: Athena not configured, falling back to DynamoDB"
                )
                tasks["costs"] = lambda: (
                    self._operational.get_cost_metrics(time_range)
                    if hasattr(self._operational, "get_cost_metrics")
                    else None
                )

        # ── Analytics sections — Athena only ─────────────────────────
        if "token_usage" in sections:
            tasks["token_usage"] = lambda: self._analytics_cost.get_token_utilization(
                time_range
            )

        if "cost_trends" in sections:
            tasks["cost_trends"] = lambda: self._analytics_cost.get_cost_trends(
                time_range
            )

        if "cost_by_version" in sections:
            tasks["cost_by_version"] = lambda: (
                self._analytics_cost.get_cost_by_config_version(time_range)
            )

        if "model_usage" in sections:
            tasks["model_usage"] = lambda: (
                self._analytics_cost.get_model_usage_breakdown(time_range)
            )

        # Execute tasks in parallel
        results: Dict[str, Any] = {}
        data_sources: List[str] = []

        with ThreadPoolExecutor(max_workers=min(len(tasks), 8)) as executor:
            future_to_key = {executor.submit(fn): key for key, fn in tasks.items()}
            for future in as_completed(future_to_key):
                key = future_to_key[future]
                try:
                    results[key] = future.result()
                    data_sources.append(key)
                    logger.debug("Fetched section '%s' successfully", key)
                except Exception as exc:
                    logger.warning(
                        "Failed to fetch section '%s': %s", key, exc, exc_info=True
                    )
                    results[key] = None

        return self._normalize_response(results, data_sources)

    # -------------------------------------------------------------------------
    # Private: normalize raw section results into the standard format
    # -------------------------------------------------------------------------

    def _normalize_response(
        self,
        results: Dict[str, Any],
        data_sources: List[str],
    ) -> Dict[str, Any]:
        """
        Transform raw section results into the standardized consumer format.

        This is the single place where internal snake_case / nested structures
        are converted to camelCase flat structures.  All consumers (Lambda
        resolver and SDK) receive this format directly.
        """
        return {
            "kpis": self._normalize_kpis(
                volume=results.get("volume"),
                costs=results.get("costs"),
                throttle=results.get("throttles"),
            ),
            "statusBreakdown": self._normalize_status_breakdown(results.get("status")),
            "configVersionDistribution": self._normalize_config_version_distribution(
                results.get("config")
            ),
            "docTypeDistribution": self._normalize_doc_type_distribution(
                results.get("doc_types")
            ),
            "volumeOverTime": self._normalize_volume_over_time(results.get("timeline")),
            "latencyByStep": results.get("latency"),
            "recentFailures": self._normalize_recent_failures(results.get("failures")),
            "throttleReport": results.get("throttles"),
            # Analytics sections (None when Athena not configured)
            "tokenUtilization": results.get("token_usage"),
            "costTrends": results.get("cost_trends"),
            "costByVersion": results.get("cost_by_version"),
            "modelUsage": results.get("model_usage"),
            "queriedAt": datetime.now(tz=timezone.utc).isoformat(),
            "dataSources": sorted(data_sources),
        }

    @staticmethod
    def _normalize_kpis(
        volume: Optional[Dict[str, Any]],
        costs: Optional[Dict[str, Any]],
        throttle: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Merge volume metrics and cost metrics into a single unified KPIs dict.

        Accepts cost data from either source (Athena or DynamoDB) since both
        return the same field names.

        Internal format (volume):
            {"total_documents": int, "completed": int, "failed": int,
             "success_rate": float, "failure_rate": float, ...}

        Internal format (costs — same whether from Athena or DynamoDB):
            {"total_input_tokens": int, "total_output_tokens": int,
             "total_pages_processed": int, "estimated_cost_usd": float,
             "document_count": int, ...}

        Normalized output:
            {"totalDocs": int, "totalPages": int, "totalInputTokens": int,
             "totalOutputTokens": int, "totalCost": float, "avgCostPerDoc": float,
             "successRate": float, "failureRate": float,
             "criticalErrors": int, "throttleEvents": int}
        """
        if volume is None and costs is None:
            return None

        v = volume or {}
        c = costs or {}

        total_docs = v.get("total_documents", 0)
        failed = v.get("failed", 0)
        estimated_cost = c.get("estimated_cost_usd", 0.0)
        doc_count = c.get("document_count", total_docs) or total_docs

        avg_cost = round(estimated_cost / doc_count, 6) if doc_count else 0.0

        throttle_events = 0
        if throttle and isinstance(throttle, dict):
            throttle_events = throttle.get("total_events", 0) or 0

        return {
            "totalDocs": total_docs,
            "totalPages": c.get("total_pages_processed", 0),
            "totalInputTokens": c.get("total_input_tokens", 0),
            "totalOutputTokens": c.get("total_output_tokens", 0),
            "totalCost": round(estimated_cost, 6),
            "avgCostPerDoc": avg_cost,
            "successRate": v.get("success_rate", 0.0),
            "failureRate": v.get("failure_rate", 0.0),
            "criticalErrors": failed,
            "throttleEvents": throttle_events,
        }

    @staticmethod
    def _normalize_status_breakdown(
        status: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Convert internal status breakdown to flat consumer format.

        Internal format:
            {"by_status": {"COMPLETED": 140, "FAILED": 5, ...}, "total": 150}

        Normalized output:
            {"successCount": 140, "failureCount": 5, "pendingCount": 5}
        """
        if status is None:
            return None

        by_status = status.get("by_status", {}) or {}

        success_count = by_status.get("COMPLETED", 0)
        failure_count = by_status.get("FAILED", 0)
        pending_count = sum(
            count
            for state, count in by_status.items()
            if state not in ("COMPLETED", "FAILED")
        )

        return {
            "successCount": success_count,
            "failureCount": failure_count,
            "pendingCount": pending_count,
        }

    @staticmethod
    def _normalize_doc_type_distribution(
        doc_types: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Convert internal doc type dict to flat array for charting.

        Internal format:
            {"by_type": {"InvoiceDocument": 50, "W2": 100}, "total": 150,
             "unclassified": 0}

        Normalized output (sorted by count descending):
            [{"name": "W2", "count": 100, "percentage": 66.7}, ...]
        """
        if doc_types is None:
            return []

        by_type = doc_types.get("by_type", {}) or {}
        total = doc_types.get("total", 0) or sum(by_type.values()) or 1

        result = []
        for name, count in by_type.items():
            result.append(
                {
                    "name": name,
                    "count": count,
                    "percentage": round((count / total) * 100, 1) if total else 0.0,
                }
            )

        result.sort(key=lambda x: x["count"], reverse=True)
        return result

    @staticmethod
    def _normalize_volume_over_time(
        timeline: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Extract buckets from nested timeline dict into a flat array.

        Internal format:
            {"buckets": [{"start": str, "end": str, "total": int,
                          "completed": int, "failed": int}],
             "bucket_hours": int}

        Normalized output:
            [{"date": str, "count": int, "completed": int, "failed": int}, ...]
        """
        if timeline is None:
            return []

        buckets = timeline.get("buckets", []) or []
        result = []
        for bucket in buckets:
            result.append(
                {
                    "date": bucket.get("start", ""),
                    "count": bucket.get("total", 0),
                    "completed": bucket.get("completed", 0),
                    "failed": bucket.get("failed", 0),
                }
            )
        return result

    @staticmethod
    def _normalize_recent_failures(
        failures: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Extract failure list from nested dict into a flat array with camelCase keys.

        Internal format:
            {"failures": [{"document_id": str, "status": str, ...}],
             "total_failed": int, "limit": int}

        Normalized output:
            [{"documentId": str, "status": str, "classification": str,
              "timestamp": str, "numPages": int, "errorMessage": str}, ...]
        """
        if failures is None:
            return []

        raw_list = failures.get("failures", []) or []
        result = []
        for item in raw_list:
            result.append(
                {
                    "documentId": item.get("document_id"),
                    "status": item.get("status", ""),
                    "classification": item.get("classification"),
                    "timestamp": item.get("timestamp"),
                    "numPages": item.get("num_pages", 0),
                    "errorMessage": item.get("error_message"),
                }
            )
        return result

    @staticmethod
    def _normalize_config_version_distribution(
        config: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Convert internal config version dict to flat array for charting.

        Internal format:
            {"by_version": {"v1.0": 50, "v1.1": 100}, "total": 150,
             "no_version": 0}

        Normalized output:
            [
                {"name": "v1.0", "value": 50},
                {"name": "v1.1", "value": 100},
                {"name": "No Version", "value": 0}
            ]
        """
        if not config:
            return []

        by_version = config.get("by_version", {}) or {}
        no_version = config.get("no_version", 0)

        result = [{"name": k, "value": v} for k, v in by_version.items()]

        if no_version > 0:
            result.append({"name": "No Version", "value": no_version})

        return result
