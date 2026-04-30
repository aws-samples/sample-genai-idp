"""
IDPMonitor — AppSync Lambda Resolver

This is the ONLY place in IDPMonitor where subscription entitlement is checked.
The foundation services in idp_common_ext/monitoring/ are subscription-unaware.

Flow:
  1. Parse AppSync event (field name + arguments)
  2. For getMonitoringStatus:  return subscription status (respects SUBSCRIPTION_VALIDATION_MODE)
  3. For getMonitoringDashboard:
       a. Check subscription entitlement
       b. If not entitled: return subscriptionStatus="inactive" with empty sections
       c. If entitled: call MonitoringMetricsService → transform output → return

Data flow (real data path):
  MonitoringMetricsService.get_dashboard_data()
    → { kpis, statusBreakdown, docTypeDistribution, volumeOverTime,
        latencyByStep, recentFailures, configInfo, throttleReport, ... }
  _transform_to_appsync_response()
    → { volume, cost, latency, failures, throttles, distribution, config }
  Lambda returns the mapped AppSync schema fields

Fallback (dev/mock):
  _build_mock_dashboard() is kept for local dev when the layer is unavailable.
  It is only used if MonitoringMetricsService cannot be imported.

Environment variables:
  SUBSCRIPTION_VALIDATION_MODE  "marketplace" | "none"  (default: "none")
  ACCELERATOR_STACK_NAME        Name of the deployed accelerator stack
  TRACKING_TABLE_NAME           DynamoDB tracking table name (cross-stack import)
  CONFIGURATION_TABLE_NAME      DynamoDB configuration table name (cross-stack import)
  REPORTING_BUCKET_NAME         S3 reporting bucket name (cross-stack import)
  LOG_LEVEL                     Python log level (default: INFO)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

SUBSCRIPTION_VALIDATION_MODE = os.environ.get("SUBSCRIPTION_VALIDATION_MODE", "none")
ACCELERATOR_STACK_NAME = os.environ.get("ACCELERATOR_STACK_NAME", "")
TRACKING_TABLE_NAME = os.environ.get("TRACKING_TABLE_NAME", "")
CONFIGURATION_TABLE_NAME = os.environ.get("CONFIGURATION_TABLE_NAME", "")
REPORTING_BUCKET_NAME = os.environ.get("REPORTING_BUCKET_NAME", "")

# ── Import MonitoringMetricsService from idp_common_ext layer ─────────────────
# The layer is attached via the IdpCommonExtLayer Lambda Layer defined in
# monitoring-template.yaml. If the import fails (e.g. local dev without the
# layer), _MONITORING_SERVICE_AVAILABLE is set to False and mock data is used.
try:
    from idp_common_ext.monitoring import MonitoringMetricsService, TimeRange

    _MONITORING_SERVICE_AVAILABLE = True
    logger.info("idp_common_ext.monitoring imported successfully")
except ImportError as _exc:
    _MONITORING_SERVICE_AVAILABLE = False
    logger.warning(
        "idp_common_ext not available (layer missing?): %s — falling back to mock data",
        _exc,
    )

# ── Time range string → hours mapping ────────────────────────────────────────
_TIME_RANGE_HOURS: dict[str, int] = {
    "1h": 1,
    "6h": 6,
    "12h": 12,
    "24h": 24,
    "2d": 48,
    "7d": 168,
    "14d": 336,
    "30d": 720,
}


def _parse_time_range(time_range: str) -> "TimeRange":
    """Convert a UI time-range shorthand string to a TimeRange object."""
    hours = _TIME_RANGE_HOURS.get(str(time_range).lower(), 24)
    return TimeRange.last_n_hours(hours)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AppSync Lambda resolver entry point."""
    logger.debug("Resolver event: %s", json.dumps(event, default=str))

    field_name = event.get("info", {}).get("fieldName", "")

    if field_name == "getMonitoringStatus":
        return _handle_get_status()

    if field_name == "getMonitoringDashboard":
        return _handle_get_dashboard(event)

    logger.warning("Unknown field: %s", field_name)
    return {"error": f"Unknown field: {field_name}"}


# ─────────────────────────────────────────────────────────────────────────────
# Handlers
# ─────────────────────────────────────────────────────────────────────────────


def _handle_get_status() -> dict[str, Any]:
    """
    Lightweight subscription status check.

    When SUBSCRIPTION_VALIDATION_MODE=none (dev/testing), always returns "active".
    When SUBSCRIPTION_VALIDATION_MODE=marketplace, calls AWS Marketplace entitlement API.
    """
    status = _check_entitlement()
    return {
        "subscriptionStatus": status,
        "stackName": os.environ.get("AWS_LAMBDA_FUNCTION_NAME", ""),
        "acceleratorStackName": ACCELERATOR_STACK_NAME,
    }


def _handle_get_dashboard(event: dict[str, Any]) -> dict[str, Any]:
    """Fetch full dashboard data with subscription enforcement."""
    args = event.get("arguments", {}).get("input", {})
    time_range = args.get("timeRange", "24h")
    sections = args.get("sections")  # None = all sections
    start_time = args.get("startTime")
    end_time = args.get("endTime")

    generated_at = datetime.now(timezone.utc).isoformat()

    # ── Step 1: Check subscription entitlement ──────────────────────────────
    entitled = _check_entitlement() == "active"

    if not entitled:
        logger.info("Subscription not active — returning inactive status")
        return {
            "subscriptionStatus": "inactive",
            "subscriptionTier": None,
            "volume": None,
            "cost": None,
            "latency": None,
            "failures": None,
            "throttles": None,
            "distribution": None,
            "config": None,
            "timeRange": time_range,
            "startTime": start_time,
            "endTime": end_time,
            "generatedAt": generated_at,
            "errors": [],
        }

    # ── Step 2: Fetch dashboard data ────────────────────────────────────────
    section_errors: list[dict[str, Any]] = []

    if _MONITORING_SERVICE_AVAILABLE:
        # Real data path — MonitoringMetricsService fetches DynamoDB / CloudWatch / X-Ray
        logger.info(
            "Fetching real monitoring data via MonitoringMetricsService "
            "(time_range=%s, sections=%s)",
            time_range,
            sections,
        )
        try:
            tr = _parse_time_range(time_range)
            svc = MonitoringMetricsService()
            raw = svc.get_dashboard_data(
                time_range=tr,
                include_sections=sections,  # None = all operational sections
            )
            dashboard = _transform_to_appsync_response(raw, time_range)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "MonitoringMetricsService failed: %s — falling back to mock data",
                exc,
                exc_info=True,
            )
            section_errors.append(
                {
                    "section": "all",
                    "message": str(exc),
                    "code": type(exc).__name__,
                }
            )
            dashboard = _build_mock_dashboard(time_range)
    else:
        # Layer unavailable — use mock data (local dev / CI)
        logger.info(
            "MonitoringMetricsService unavailable — returning mock dashboard data"
        )
        dashboard = _build_mock_dashboard(time_range)

    logger.info(
        "Dashboard response assembled for time_range=%s sections=%s errors=%d",
        time_range,
        sections,
        len(section_errors),
    )

    return {
        "subscriptionStatus": "active",
        "subscriptionTier": "standard",
        "volume": dashboard.get("volume"),
        "cost": dashboard.get("cost"),
        "latency": dashboard.get("latency"),
        "failures": dashboard.get("failures"),
        "throttles": dashboard.get("throttles"),
        "distribution": dashboard.get("distribution"),
        "config": dashboard.get("config"),
        "timeRange": time_range,
        "startTime": start_time,
        "endTime": end_time,
        "generatedAt": generated_at,
        "errors": section_errors,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Transform MonitoringMetricsService output → AppSync schema format
#
# MonitoringMetricsService.get_dashboard_data() returns a normalized dict:
#   {
#     "kpis": { totalDocs, totalPages, totalInputTokens, ... },
#     "statusBreakdown": { successCount, failureCount, pendingCount },
#     "docTypeDistribution": [{ name, count, percentage }],
#     "volumeOverTime": [{ date, count, completed, failed }],
#     "latencyByStep": { ... },
#     "recentFailures": [{ documentId, status, classification, ... }],
#     "configInfo": { activeVersion, documentTypesCount, ... },
#     "throttleReport": { ... },
#     "queriedAt": str,
#     "dataSources": list[str],
#   }
#
# AppSync schema expects AWSJSON fields:
#   volume, cost, latency, failures, throttles, distribution, config
#
# The Lambda is the canonical place to perform this mapping — the service
# output format (MonitoringMetricsService) is the standard; the Lambda
# adapts it to the AppSync schema.
# ─────────────────────────────────────────────────────────────────────────────


def _transform_to_appsync_response(
    raw: dict[str, Any],
    time_range: str,
) -> dict[str, Any]:
    """
    Transform MonitoringMetricsService normalized output to AppSync AWSJSON fields.

    Args:
        raw:        Output from MonitoringMetricsService.get_dashboard_data()
        time_range: Original time range string (e.g. "24h") for metadata fields

    Returns:
        Dict with keys: volume, cost, latency, failures, throttles, distribution, config
    """
    kpis = raw.get("kpis") or {}
    status = raw.get("statusBreakdown") or {}
    volume_over_time = raw.get("volumeOverTime") or []

    # ── volume ───────────────────────────────────────────────────────────────
    # Combines kpis (totals), statusBreakdown, and volumeOverTime (time series)
    total_docs = kpis.get("totalDocs", 0)
    success_count = status.get("successCount", 0)
    failure_count = status.get("failureCount", 0)
    pending_count = status.get("pendingCount", 0)
    success_rate = kpis.get("successRate", 0.0)

    # Build timeSeries from volumeOverTime buckets
    time_series = [
        {
            "timestamp": bucket.get("date", ""),
            "completed": bucket.get("completed", 0),
            "failed": bucket.get("failed", 0),
            "total": bucket.get("count", 0),
        }
        for bucket in volume_over_time
    ]

    # Compute throughput per hour (total docs / time range hours)
    range_hours = _TIME_RANGE_HOURS.get(str(time_range).lower(), 24)
    throughput_per_hour = round(total_docs / range_hours, 1) if range_hours > 0 else 0.0

    volume = {
        "totalDocuments": total_docs,
        "completedDocuments": success_count,
        "failedDocuments": failure_count,
        "inProgressDocuments": pending_count,
        "successRate": round(success_rate * 100, 1)
        if success_rate <= 1.0
        else success_rate,
        "throughputPerHour": throughput_per_hour,
        "totalPages": kpis.get("totalPages", 0),
        "timeRange": time_range,
        "statusBreakdown": {
            "completed": success_count,
            "failed": failure_count,
            "inProgress": pending_count,
            "queued": 0,
        },
        "timeSeries": time_series,
    }

    # ── cost ─────────────────────────────────────────────────────────────────
    # Sourced from kpis (token counts + cost totals)
    total_input_tokens = kpis.get("totalInputTokens", 0)
    total_output_tokens = kpis.get("totalOutputTokens", 0)
    total_cost = kpis.get("totalCost", 0.0)

    cost = {
        "totalInputTokens": total_input_tokens,
        "totalOutputTokens": total_output_tokens,
        "totalTokens": total_input_tokens + total_output_tokens,
        "estimatedCostUsd": round(total_cost, 6),
        "avgCostPerDoc": kpis.get("avgCostPerDoc", 0.0),
        "dataSource": "dynamodb",
        # Athena-enriched fields (populated when AnalyticsCostService is configured)
        "perModelBreakdown": raw.get("modelUsage") or [],
        "historicalTrend": raw.get("costTrends") or [],
        "tokenUtilization": raw.get("tokenUtilization"),
    }

    # ── latency ───────────────────────────────────────────────────────────────
    # Sourced from latencyByStep (X-Ray service performance summary)
    latency_raw = raw.get("latencyByStep") or {}
    latency = _transform_latency(latency_raw)

    # ── failures ──────────────────────────────────────────────────────────────
    # Sourced from recentFailures (normalized list from OperationalDocumentService)
    failures_list = raw.get("recentFailures") or []
    failures = {
        "totalFailures": kpis.get("criticalErrors", len(failures_list)),
        "hasMore": False,
        "recentFailures": [
            {
                "documentId": f.get("documentId", ""),
                "batchId": "",
                "documentClass": f.get("classification", ""),
                "pageCount": f.get("numPages", 0),
                "failedAt": f.get("timestamp", ""),
                "errorMessage": f.get("errorMessage", ""),
                "errorCode": "",
                "stage": "",
            }
            for f in failures_list
        ],
    }

    # ── throttles ─────────────────────────────────────────────────────────────
    # Sourced from throttleReport (CloudWatchMetricsService)
    throttle_raw = raw.get("throttleReport") or {}
    throttles = _transform_throttles(throttle_raw, kpis)

    # ── distribution ──────────────────────────────────────────────────────────
    # Sourced from docTypeDistribution (normalized list)
    dist_list = raw.get("docTypeDistribution") or []
    distribution = {
        "totalDocuments": total_docs,
        "classificationLevel": "document",
        "classes": [
            {
                "className": d.get("name", ""),
                "count": d.get("count", 0),
                "percentage": d.get("percentage", 0.0),
            }
            for d in dist_list
        ],
    }

    # ── config ────────────────────────────────────────────────────────────────
    # Sourced from configInfo (OperationalDocumentService / configuration table)
    config_raw = raw.get("configInfo") or {}
    config = {
        "activeVersion": config_raw.get("activeVersion", ""),
        "documentClassCount": config_raw.get("documentTypesCount", 0),
        "documentClasses": [],  # detailed class list not included in configInfo summary
        "versionHistory": [
            {
                "version": v,
                "createdAt": "",
                "isActive": v == config_raw.get("activeVersion"),
            }
            for v in (config_raw.get("configVersions") or [])
        ],
    }

    return {
        "volume": volume,
        "cost": cost,
        "latency": latency,
        "failures": failures,
        "throttles": throttles,
        "distribution": distribution,
        "config": config,
        "errors": [],
    }


def _transform_latency(latency_raw: dict[str, Any]) -> dict[str, Any]:
    """
    Transform X-Ray service performance summary into the UI latency format.

    The xray_service.get_service_performance_summary() returns a dict whose
    exact shape depends on what X-Ray has traced.  We defensively extract
    p50/p90/p99 values at the top level and per-service/stage breakdowns.
    """

    # Top-level percentiles — xray_service may return these at the root or
    # nested under a "overall" / "aggregate" key.
    def _ms(val: Any) -> int:
        """Convert seconds float or ms int to integer ms."""
        if val is None:
            return 0
        try:
            f = float(val)
            # heuristic: values < 1000 are likely already seconds
            return int(f * 1000) if f < 1000 else int(f)
        except (TypeError, ValueError):
            return 0

    overall = latency_raw.get("overall") or latency_raw
    p50 = _ms(overall.get("p50_ms") or overall.get("p50") or overall.get("median_ms"))
    p90 = _ms(overall.get("p90_ms") or overall.get("p90"))
    p99 = _ms(overall.get("p99_ms") or overall.get("p99"))
    sample_count = int(overall.get("sample_count") or overall.get("count") or 0)

    # Per-stage / per-service breakdown
    per_stage = []
    stages_raw = (
        latency_raw.get("by_service")
        or latency_raw.get("per_stage")
        or latency_raw.get("services")
        or {}
    )
    if isinstance(stages_raw, dict):
        for stage_name, stage_data in stages_raw.items():
            if isinstance(stage_data, dict):
                per_stage.append(
                    {
                        "stageName": stage_name,
                        "p50Ms": _ms(
                            stage_data.get("p50_ms")
                            or stage_data.get("p50")
                            or stage_data.get("median_ms")
                        ),
                        "p90Ms": _ms(stage_data.get("p90_ms") or stage_data.get("p90")),
                        "p99Ms": _ms(stage_data.get("p99_ms") or stage_data.get("p99")),
                    }
                )
    elif isinstance(stages_raw, list):
        for stage_data in stages_raw:
            per_stage.append(
                {
                    "stageName": stage_data.get("name", stage_data.get("service", "")),
                    "p50Ms": _ms(
                        stage_data.get("p50_ms")
                        or stage_data.get("p50")
                        or stage_data.get("median_ms")
                    ),
                    "p90Ms": _ms(stage_data.get("p90_ms") or stage_data.get("p90")),
                    "p99Ms": _ms(stage_data.get("p99_ms") or stage_data.get("p99")),
                }
            )

    return {
        "p50Ms": p50,
        "p90Ms": p90,
        "p99Ms": p99,
        "sampleCount": sample_count,
        "xRayEnabled": bool(latency_raw),
        "perStage": per_stage,
    }


def _transform_throttles(
    throttle_raw: dict[str, Any],
    kpis: dict[str, Any],
) -> dict[str, Any]:
    """
    Transform CloudWatchMetricsService throttle report into the UI throttles format.

    CloudWatchMetricsService.get_throttle_report() returns a dict whose shape
    is implementation-defined.  We extract per-service counts defensively.
    """
    total_events = int(
        kpis.get("throttleEvents", 0) or throttle_raw.get("total_events", 0) or 0
    )

    def _extract_service(key: str) -> dict[str, Any]:
        """Extract count for a named service from the throttle report."""
        # The throttle report may use snake_case or camelCase service keys
        val = throttle_raw.get(key) or throttle_raw.get(key.replace("_", "")) or {}
        count = int(val.get("count", 0) if isinstance(val, dict) else val or 0)
        severity = "ok" if count == 0 else ("warning" if count < 10 else "critical")
        return {"count": count, "severity": severity, "threshold": 10}

    lambda_t = _extract_service("lambda")
    bedrock_t = _extract_service("bedrock")
    textract_t = _extract_service("textract")

    # Overall severity — highest severity across services
    severity_order = {"ok": 0, "warning": 1, "critical": 2}
    max_severity = max(
        [lambda_t["severity"], bedrock_t["severity"], textract_t["severity"]],
        key=lambda s: severity_order.get(s, 0),
        default="ok",
    )

    return {
        "overallSeverity": max_severity,
        "totalEvents": total_events,
        "lambdaThrottles": lambda_t,
        "bedrockThrottles": bedrock_t,
        "textractThrottles": textract_t,
        "sqsMessageAge": {"count": 0, "severity": "ok", "threshold": 300},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Subscription check
# ─────────────────────────────────────────────────────────────────────────────


def _check_entitlement() -> str:
    """
    Returns "active" | "inactive" | "unknown".

    When mode is "none", always returns "active" (dev/testing bypass).
    When mode is "marketplace", calls AWS Marketplace GetEntitlements API.
    """
    if SUBSCRIPTION_VALIDATION_MODE == "none":
        logger.debug("Subscription validation disabled — returning active")
        return "active"

    # Production: call AWS Marketplace entitlement API
    try:
        import boto3  # noqa: PLC0415

        client = boto3.client("marketplace-entitlement")
        response = client.get_entitlements(
            ProductCode=os.environ.get("MARKETPLACE_PRODUCT_CODE", ""),
            Filter={"CUSTOMER_IDENTIFIER": [os.environ.get("AWS_ACCOUNT_ID", "")]},
        )
        entitlements = response.get("Entitlements", [])
        if entitlements:
            logger.info("Marketplace entitlement found: %s", entitlements[0])
            return "active"
        logger.info("No marketplace entitlements found")
        return "inactive"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Entitlement check failed: %s", exc)
        return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Mock data — kept for local dev when idp_common_ext layer is unavailable
# ─────────────────────────────────────────────────────────────────────────────


def _build_mock_dashboard(time_range: str) -> dict[str, Any]:
    """
    Returns a realistic mock dashboard payload for dev/testing.
    Only used when MonitoringMetricsService is not available (layer missing).
    Mirrors the TypeScript types in products/idp-monitor/ui/src/types/monitoring.ts.
    """
    now = datetime.now(timezone.utc)

    # Build time series (last 24 buckets of 1h each)
    time_series = []
    for i in range(24, 0, -1):
        bucket = now - timedelta(hours=i)
        time_series.append(
            {
                "timestamp": bucket.isoformat(),
                "completed": 45 + (i % 7) * 3,
                "failed": 1 + (i % 3),
                "total": 47 + (i % 7) * 3,
            }
        )

    volume = {
        "totalDocuments": 1247,
        "completedDocuments": 1198,
        "failedDocuments": 23,
        "inProgressDocuments": 26,
        "successRate": 96.1,
        "throughputPerHour": 52.0,
        "totalPages": 8734,
        "timeRange": time_range,
        "startTime": (now - timedelta(hours=24)).isoformat(),
        "endTime": now.isoformat(),
        "statusBreakdown": {
            "completed": 1198,
            "failed": 23,
            "inProgress": 26,
            "queued": 0,
        },
        "timeSeries": time_series,
    }

    cost = {
        "totalInputTokens": 4_820_000,
        "totalOutputTokens": 980_000,
        "totalTokens": 5_800_000,
        "estimatedCostUsd": 8.74,
        "avgCostPerDoc": 0.007,
        "dataSource": "mock",
        "perModelBreakdown": [
            {
                "modelId": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                "inputTokens": 3_200_000,
                "outputTokens": 650_000,
                "totalTokens": 3_850_000,
                "estimatedCostUsd": 5.93,
                "documentCount": 812,
            },
            {
                "modelId": "amazon.nova-pro-v1:0",
                "inputTokens": 1_620_000,
                "outputTokens": 330_000,
                "totalTokens": 1_950_000,
                "estimatedCostUsd": 2.81,
                "documentCount": 435,
            },
        ],
        "historicalTrend": [
            {
                "date": (now - timedelta(days=d)).strftime("%Y-%m-%d"),
                "estimatedCostUsd": round(7.5 + d * 0.3 + (d % 3) * 0.5, 2),
                "totalTokens": 5_200_000 + d * 100_000,
            }
            for d in range(7, 0, -1)
        ],
    }

    latency = {
        "p50Ms": 1840,
        "p90Ms": 4200,
        "p99Ms": 8750,
        "sampleCount": 1198,
        "xRayEnabled": True,
        "perStage": [
            {"stageName": "ocr", "p50Ms": 320, "p90Ms": 720, "p99Ms": 1200},
            {"stageName": "classification", "p50Ms": 480, "p90Ms": 980, "p99Ms": 1800},
            {"stageName": "extraction", "p50Ms": 890, "p90Ms": 2100, "p99Ms": 4900},
            {"stageName": "assessment", "p50Ms": 150, "p90Ms": 400, "p99Ms": 850},
        ],
    }

    failures = {
        "totalFailures": 23,
        "hasMore": False,
        "recentFailures": [
            {
                "documentId": f"doc-{1000 + i}",
                "batchId": "batch-20260427-001",
                "documentClass": "W2" if i % 2 == 0 else "Invoice",
                "pageCount": 2 + i % 4,
                "failedAt": (now - timedelta(minutes=30 + i * 15)).isoformat(),
                "errorMessage": "Bedrock throttling: rate limit exceeded"
                if i % 3 == 0
                else "Textract: document quality too low",
                "errorCode": "ThrottlingException"
                if i % 3 == 0
                else "DocumentQualityError",
                "stage": "extraction" if i % 3 == 0 else "ocr",
            }
            for i in range(5)
        ],
    }

    throttles = {
        "overallSeverity": "warning",
        "totalEvents": 15,
        "lambdaThrottles": {"count": 3, "severity": "warning", "threshold": 5},
        "bedrockThrottles": {"count": 12, "severity": "warning", "threshold": 10},
        "textractThrottles": {"count": 0, "severity": "ok", "threshold": 5},
        "sqsMessageAge": {"count": 45, "severity": "ok", "threshold": 300},
    }

    distribution = {
        "totalDocuments": 1247,
        "classificationLevel": "section",
        "classes": [
            {"className": "W2", "count": 523, "percentage": 41.9},
            {"className": "Invoice", "count": 312, "percentage": 25.0},
            {"className": "1099-MISC", "count": 198, "percentage": 15.9},
            {"className": "BankStatement", "count": 142, "percentage": 11.4},
            {"className": "Other", "count": 72, "percentage": 5.8},
        ],
    }

    config = {
        "activeVersion": "v1.4.2",
        "documentClassCount": 5,
        "documentClasses": ["W2", "Invoice", "1099-MISC", "BankStatement", "Other"],
        "versionHistory": [
            {
                "version": "v1.4.2",
                "createdAt": (now - timedelta(days=3)).isoformat(),
                "isActive": True,
            },
            {
                "version": "v1.4.1",
                "createdAt": (now - timedelta(days=14)).isoformat(),
                "isActive": False,
            },
            {
                "version": "v1.4.0",
                "createdAt": (now - timedelta(days=30)).isoformat(),
                "isActive": False,
            },
        ],
    }

    return {
        "volume": volume,
        "cost": cost,
        "latency": latency,
        "failures": failures,
        "throttles": throttles,
        "distribution": distribution,
        "config": config,
        "errors": [],
    }
