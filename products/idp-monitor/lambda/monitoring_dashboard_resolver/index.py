"""
IDPMonitor — AppSync Lambda Resolver

Flow:
  1. Parse AppSync event (field name + arguments)
  2. For getMonitoringStatus:  return subscription status
  3. For getMonitoringDashboard:
       a. Check subscription entitlement
       b. If not entitled: return subscriptionStatus="inactive" with empty sections
       c. If entitled: call MonitoringMetricsService → transform output → return
       d. If service unavailable or fails: return empty/zero data (NO mock data)

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
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Force handler to also log to stdout for CloudWatch visibility
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

SUBSCRIPTION_VALIDATION_MODE = os.environ.get("SUBSCRIPTION_VALIDATION_MODE", "none")
ACCELERATOR_STACK_NAME = os.environ.get("ACCELERATOR_STACK_NAME", "")
TRACKING_TABLE_NAME = os.environ.get("TRACKING_TABLE_NAME", "")
CONFIGURATION_TABLE_NAME = os.environ.get("CONFIGURATION_TABLE_NAME", "")
REPORTING_BUCKET_NAME = os.environ.get("REPORTING_BUCKET_NAME", "")

# ── Import MonitoringMetricsService from idp_common_ext layer ─────────────────
try:
    from idp_common_ext.monitoring import MonitoringMetricsService, TimeRange

    _MONITORING_SERVICE_AVAILABLE = True
    logger.info(
        "✓ idp_common_ext.monitoring imported successfully. "
        "MonitoringMetricsService is available."
    )
except ImportError as _exc:
    _MONITORING_SERVICE_AVAILABLE = False
    logger.warning(
        "✗ idp_common_ext NOT available (layer missing?): %s — "
        "Will return empty data (no mock fallback).",
        _exc,
    )

# Log environment configuration at cold start
logger.info(
    "Lambda cold start — env config: "
    "SUBSCRIPTION_VALIDATION_MODE=%s, "
    "ACCELERATOR_STACK_NAME=%s, "
    "TRACKING_TABLE_NAME=%s, "
    "CONFIGURATION_TABLE_NAME=%s, "
    "REPORTING_BUCKET_NAME=%s, "
    "MONITORING_SERVICE_AVAILABLE=%s",
    SUBSCRIPTION_VALIDATION_MODE,
    ACCELERATOR_STACK_NAME,
    TRACKING_TABLE_NAME or "(not set)",
    CONFIGURATION_TABLE_NAME or "(not set)",
    REPORTING_BUCKET_NAME or "(not set)",
    _MONITORING_SERVICE_AVAILABLE,
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
    logger.info(">>> Resolver invoked. Event: %s", json.dumps(event, default=str))

    field_name = event.get("info", {}).get("fieldName", "")
    logger.info("Field name: %s", field_name)

    if field_name == "getMonitoringStatus":
        result = _handle_get_status()
        logger.info(
            "<<< getMonitoringStatus response: %s", json.dumps(result, default=str)
        )
        return result

    if field_name == "getMonitoringDashboard":
        result = _handle_get_dashboard(event)
        # Log a summary (not the full payload which can be large)
        logger.info(
            "<<< getMonitoringDashboard response summary: "
            "subscriptionStatus=%s, hasVolume=%s, hasLatency=%s, "
            "hasFailures=%s, errorCount=%d",
            result.get("subscriptionStatus"),
            result.get("volume") is not None,
            result.get("latency") is not None,
            result.get("failures") is not None,
            len(result.get("errors") or []),
        )
        return result

    logger.warning("Unknown field: %s", field_name)
    return {"error": f"Unknown field: {field_name}"}


# ─────────────────────────────────────────────────────────────────────────────
# Handlers
# ─────────────────────────────────────────────────────────────────────────────


def _handle_get_status() -> dict[str, Any]:
    """Lightweight subscription status check."""
    status = _check_entitlement()
    logger.info("getMonitoringStatus: entitlement=%s", status)
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

    logger.info(
        "getMonitoringDashboard: time_range=%s, sections=%s, startTime=%s, endTime=%s",
        time_range,
        sections,
        start_time,
        end_time,
    )

    # ── Step 1: Check subscription entitlement ──────────────────────────────
    entitled = _check_entitlement() == "active"
    logger.info("Entitlement check: entitled=%s", entitled)

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
        logger.info(
            "Fetching REAL monitoring data via MonitoringMetricsService "
            "(time_range=%s, sections=%s)",
            time_range,
            sections,
        )
        try:
            tr = _parse_time_range(time_range)
            logger.info("Parsed TimeRange: %s", tr)

            svc = MonitoringMetricsService()
            logger.info("MonitoringMetricsService instantiated successfully")

            raw = svc.get_dashboard_data(
                time_range=tr,
                include_sections=sections,
            )
            logger.info(
                "MonitoringMetricsService.get_dashboard_data() returned keys: %s",
                list(raw.keys()) if raw else "(None)",
            )

            dashboard = _transform_to_appsync_response(raw, time_range)
            # Supplement missing data directly from DynamoDB if needed
            dashboard = _supplement_from_dynamodb(dashboard, time_range)
            logger.info("Transform complete — dashboard sections populated")

        except Exception as exc:  # noqa: BLE001
            logger.error(
                "MonitoringMetricsService FAILED: %s — returning empty data (NO mock)",
                exc,
                exc_info=True,
            )
            section_errors.append(
                {
                    "section": "all",
                    "message": f"MonitoringMetricsService error: {exc}",
                    "code": type(exc).__name__,
                }
            )
            dashboard = _build_empty_dashboard(time_range)
    else:
        # Layer unavailable — return empty data
        logger.warning(
            "MonitoringMetricsService NOT available (layer import failed). "
            "Returning EMPTY dashboard data. "
            "Ensure the idp_common_ext Lambda Layer is attached to this function."
        )
        section_errors.append(
            {
                "section": "all",
                "message": (
                    "Monitoring service layer (idp_common_ext) is not available. "
                    "Please check Lambda layer configuration."
                ),
                "code": "LayerUnavailable",
            }
        )
        dashboard = _build_empty_dashboard(time_range)

    logger.info(
        "Dashboard response assembled: time_range=%s, sections=%s, "
        "errors=%d, volume_total=%s",
        time_range,
        sections,
        len(section_errors),
        dashboard.get("volume", {}).get("totalDocuments")
        if dashboard.get("volume")
        else "N/A",
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
# ─────────────────────────────────────────────────────────────────────────────


def _transform_to_appsync_response(
    raw: dict[str, Any],
    time_range: str,
) -> dict[str, Any]:
    """Transform MonitoringMetricsService normalized output to AppSync AWSJSON fields."""
    kpis = raw.get("kpis") or {}
    status = raw.get("statusBreakdown") or {}
    volume_over_time = raw.get("volumeOverTime") or []

    logger.info(
        "Transform input — kpis: %s",
        json.dumps(kpis, default=str),
    )
    logger.info(
        "Transform input — statusBreakdown: %s, volumeOverTime count: %d, "
        "docTypeDistribution: %s, configInfo: %s",
        json.dumps(status, default=str),
        len(volume_over_time),
        json.dumps(raw.get("docTypeDistribution") or [], default=str),
        json.dumps(raw.get("configInfo") or {}, default=str),
    )

    # ── volume ───────────────────────────────────────────────────────────────
    total_docs = kpis.get("totalDocs", 0)
    success_count = status.get("successCount", 0)
    failure_count = status.get("failureCount", 0)
    pending_count = status.get("pendingCount", 0)
    success_rate = kpis.get("successRate", 0.0)

    time_series = [
        {
            "timestamp": bucket.get("date", ""),
            "completed": bucket.get("completed", 0),
            "failed": bucket.get("failed", 0),
            "total": bucket.get("count", 0),
        }
        for bucket in volume_over_time
    ]

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
        "perModelBreakdown": raw.get("modelUsage") or [],
        "historicalTrend": raw.get("costTrends") or [],
        "tokenUtilization": raw.get("tokenUtilization"),
    }

    # ── latency ───────────────────────────────────────────────────────────────
    latency_raw = raw.get("latencyByStep") or {}
    latency = _transform_latency(latency_raw)

    # ── failures ──────────────────────────────────────────────────────────────
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
                "failedAt": (
                    f.get("timestamp")
                    or f.get("failedAt")
                    or f.get("CompletionTime")
                    or f.get("WorkflowStartTime")
                    or f.get("createdAt")
                    or ""
                ),
                "errorMessage": f.get("errorMessage", ""),
                "errorCode": "",
                "stage": f.get("stage", ""),
            }
            for f in failures_list
        ],
    }

    # ── throttles ─────────────────────────────────────────────────────────────
    throttle_raw = raw.get("throttleReport") or {}
    throttles = _transform_throttles(throttle_raw, kpis)

    # ── distribution ──────────────────────────────────────────────────────────
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
    # configVersionDistribution is array of {name, value} showing which versions
    # were actually used to process documents
    config_version_dist = raw.get("configVersionDistribution") or []
    config = {
        "versionDistribution": [
            {
                "version": item.get("name", ""),
                "documentCount": item.get("value", 0),
            }
            for item in config_version_dist
        ],
        "totalVersions": len(config_version_dist),
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
    """Transform X-Ray service performance summary into the UI latency format."""

    def _ms(val: Any) -> int:
        if val is None:
            return 0
        try:
            f = float(val)
            return int(f * 1000) if f < 1000 else int(f)
        except (TypeError, ValueError):
            return 0

    overall = latency_raw.get("overall") or latency_raw
    p50 = _ms(overall.get("p50_ms") or overall.get("p50") or overall.get("median_ms"))
    p90 = _ms(overall.get("p90_ms") or overall.get("p90"))
    p99 = _ms(overall.get("p99_ms") or overall.get("p99"))
    sample_count = int(overall.get("sample_count") or overall.get("count") or 0)

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
    """Transform CloudWatchMetricsService throttle report into the UI throttles format."""
    total_events = int(
        kpis.get("throttleEvents", 0) or throttle_raw.get("total_events", 0) or 0
    )

    def _extract_service(key: str) -> dict[str, Any]:
        val = throttle_raw.get(key) or throttle_raw.get(key.replace("_", "")) or {}
        count = int(val.get("count", 0) if isinstance(val, dict) else val or 0)
        severity = "ok" if count == 0 else ("warning" if count < 10 else "critical")
        return {"count": count, "severity": severity, "threshold": 10}

    lambda_t = _extract_service("lambda")
    bedrock_t = _extract_service("bedrock")
    textract_t = _extract_service("textract")
    dynamodb_t = _extract_service("dynamodb")

    severity_order = {"ok": 0, "warning": 1, "critical": 2}
    max_severity = max(
        [
            lambda_t["severity"],
            bedrock_t["severity"],
            textract_t["severity"],
            dynamodb_t["severity"],
        ],
        key=lambda s: severity_order.get(s, 0),
        default="ok",
    )

    return {
        "overallSeverity": max_severity,
        "totalEvents": total_events,
        "lambdaThrottles": lambda_t,
        "bedrockThrottles": bedrock_t,
        "textractThrottles": textract_t,
        "dynamodbThrottles": dynamodb_t,
        "sqsMessageAge": {"count": 0, "severity": "ok", "threshold": 300},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Subscription check
# ─────────────────────────────────────────────────────────────────────────────


def _check_entitlement() -> str:
    """Returns "active" | "inactive" | "unknown"."""
    if SUBSCRIPTION_VALIDATION_MODE == "none":
        logger.debug("Subscription validation disabled — returning active")
        return "active"

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
# Helper: identify infrastructure-level stage names (not pipeline steps)
# ─────────────────────────────────────────────────────────────────────────────

_INFRA_PATTERNS = (
    "s3",
    "sqs",
    "dynamodb",
    "stepfunctions",
    "appsync-api",
    "amazonaws.com",
    "Table-",
    "Queue-",
    "Bucket-",
)


def _is_infrastructure_stage(name: str) -> bool:
    """Return True if stage name looks like an AWS infra service, not a pipeline step."""
    lower = name.lower()
    return any(p.lower() in lower for p in _INFRA_PATTERNS)


# ─────────────────────────────────────────────────────────────────────────────
# Supplement missing data from DynamoDB tracking table
# ─────────────────────────────────────────────────────────────────────────────


def _supplement_from_dynamodb(
    dashboard: dict[str, Any], time_range: str
) -> dict[str, Any]:
    """
    Fill in missing data (pages, tokens, doc types, config, timeSeries, latency)
    by scanning the DynamoDB tracking table directly.
    """
    volume = dashboard.get("volume") or {}
    cost = dashboard.get("cost") or {}
    distribution = dashboard.get("distribution") or {}
    config = dashboard.get("config") or {}
    latency = dashboard.get("latency") or {}

    # Check if data needs supplementing
    needs_pages = volume.get("totalPages", 0) == 0
    needs_tokens = cost.get("totalTokens", 0) == 0
    needs_dist = not distribution.get("classes")
    needs_config = not config.get("activeVersion")
    needs_timeline = all(
        b.get("total", 0) == 0 and b.get("completed", 0) == 0
        for b in (volume.get("timeSeries") or [])
    )
    needs_latency = not latency.get("perStage") or all(
        s.get("p50Ms", 0) == 0 and s.get("p90Ms", 0) == 0
        for s in latency.get("perStage", [])
    )

    if not (
        needs_pages
        or needs_tokens
        or needs_dist
        or needs_config
        or needs_timeline
        or needs_latency
    ):
        logger.info("All data complete — no DynamoDB supplement needed")
        return dashboard

    logger.info(
        "Supplementing data from DynamoDB: needs_pages=%s, needs_tokens=%s, "
        "needs_dist=%s, needs_config=%s",
        needs_pages,
        needs_tokens,
        needs_dist,
        needs_config,
    )

    try:
        from collections import defaultdict  # noqa: PLC0415
        from decimal import Decimal  # noqa: PLC0415

        import boto3  # noqa: PLC0415

        dynamodb = boto3.resource("dynamodb")

        # ── Supplement pages, tokens, doc types from tracking table ────────
        if TRACKING_TABLE_NAME and (needs_pages or needs_tokens or needs_dist):
            table = dynamodb.Table(TRACKING_TABLE_NAME)
            total_pages = 0
            total_input_tokens = 0
            total_output_tokens = 0
            doc_type_counts: dict[str, int] = defaultdict(int)

            # Scan tracking table (limited to recent docs)
            scan_params: dict[str, Any] = {
                "FilterExpression": "ItemType = :doc",
                "ExpressionAttributeValues": {":doc": "document"},
                "ProjectionExpression": "PageCount, Metering, Sections, Pages",
                "Limit": 1000,
            }
            response = table.scan(**scan_params)
            items = response.get("Items", [])

            for item in items:
                # Pages
                page_count = item.get("PageCount", 0)
                if isinstance(page_count, Decimal):
                    page_count = int(page_count)
                total_pages += page_count

                # Doc types from Sections
                sections = item.get("Sections", [])
                if sections and isinstance(sections, list):
                    first_section = sections[0] if sections else {}
                    if isinstance(first_section, dict):
                        cls = first_section.get("Class", "")
                        if cls:
                            doc_type_counts[cls] += 1
                elif not sections:
                    # Try from Pages
                    pages = item.get("Pages", [])
                    if pages and isinstance(pages, list):
                        first_page = pages[0] if pages else {}
                        if isinstance(first_page, dict):
                            cls = first_page.get("Class", "")
                            if cls:
                                doc_type_counts[cls] += 1

                # Tokens from Metering
                metering = item.get("Metering", {})
                if isinstance(metering, dict):
                    for step_name, step_data in metering.items():
                        if isinstance(step_data, dict):
                            inp = step_data.get("inputTokens", 0)
                            out = step_data.get("outputTokens", 0)
                            if isinstance(inp, Decimal):
                                inp = int(inp)
                            if isinstance(out, Decimal):
                                out = int(out)
                            total_input_tokens += inp
                            total_output_tokens += out

            logger.info(
                "DynamoDB supplement results: total_pages=%d, input_tokens=%d, "
                "output_tokens=%d, doc_types=%s",
                total_pages,
                total_input_tokens,
                total_output_tokens,
                dict(doc_type_counts),
            )

            # Update volume with pages
            if needs_pages and total_pages > 0:
                volume["totalPages"] = total_pages

            # Update cost with tokens
            if needs_tokens and (total_input_tokens > 0 or total_output_tokens > 0):
                cost["totalInputTokens"] = total_input_tokens
                cost["totalOutputTokens"] = total_output_tokens
                cost["totalTokens"] = total_input_tokens + total_output_tokens
                # Estimate cost (rough: $0.003/1K input, $0.015/1K output for Claude)
                est_cost = (
                    total_input_tokens * 0.003 + total_output_tokens * 0.015
                ) / 1000
                cost["estimatedCostUsd"] = round(est_cost, 6)
                total_docs = volume.get("totalDocuments", 1) or 1
                cost["avgCostPerDoc"] = round(est_cost / total_docs, 6)

            # Update distribution
            if needs_dist and doc_type_counts:
                total_classified = sum(doc_type_counts.values())
                classes = []
                for name, count in sorted(
                    doc_type_counts.items(), key=lambda x: x[1], reverse=True
                ):
                    classes.append(
                        {
                            "className": name,
                            "count": count,
                            "percentage": round((count / total_classified) * 100, 1),
                        }
                    )
                distribution["classes"] = classes
                distribution["totalDocuments"] = volume.get(
                    "totalDocuments", total_classified
                )

        # ── Supplement config from configuration table ─────────────────────
        if CONFIGURATION_TABLE_NAME and needs_config:
            try:
                config_table = dynamodb.Table(CONFIGURATION_TABLE_NAME)
                # Table uses IsActive (boolean) and Configuration (partition key)
                from boto3.dynamodb.conditions import Attr  # noqa: PLC0415

                response = config_table.scan(
                    FilterExpression=Attr("IsActive").eq(True),
                    Limit=10,
                )
                items = response.get("Items", [])
                if items:
                    active_item = items[0]
                    # Configuration key is like "Config#default"
                    cfg_key = active_item.get("Configuration", "")
                    version_name = (
                        cfg_key.replace("Config#", "")
                        if cfg_key.startswith("Config#")
                        else cfg_key
                    )
                    config["activeVersion"] = version_name
                    config["documentClassCount"] = len(items)  # All active configs

                # Get all configuration names (document classes)
                response = config_table.scan(
                    FilterExpression=Attr("Configuration").begins_with("Config#"),
                    ProjectionExpression="Configuration, DocumentType, #n",
                    ExpressionAttributeNames={"#n": "Name"},
                )
                all_configs = response.get("Items", [])
                config["documentClassCount"] = len(all_configs)

                # Extract document class names from configurations
                doc_classes = []
                for cfg_item in all_configs:
                    # Try DocumentType first, then Name, then parse from Configuration key
                    doc_type = (
                        cfg_item.get("DocumentType") or cfg_item.get("Name") or ""
                    )
                    if not doc_type:
                        cfg_k = cfg_item.get("Configuration", "")
                        doc_type = (
                            cfg_k.replace("Config#", "")
                            if cfg_k.startswith("Config#")
                            else cfg_k
                        )
                    if doc_type:
                        doc_classes.append(doc_type)
                config["documentClasses"] = doc_classes
                logger.info("Config document classes: %s", doc_classes)
            except Exception as exc:
                logger.warning("Config table supplement failed: %s", exc)

        # ── Supplement per-version document counts ─────────────────────────
        # Count documents processed during each version's active period
        # by matching document completion timestamps to version deploy windows.
        version_history = config.get("versionHistory") or []
        if TRACKING_TABLE_NAME and version_history:
            try:
                from datetime import timedelta  # noqa: PLC0415

                table = dynamodb.Table(TRACKING_TABLE_NAME)
                response = table.scan(
                    FilterExpression="ItemType = :doc",
                    ExpressionAttributeValues={":doc": "document"},
                    ProjectionExpression="CompletionTime, WorkflowStartTime",
                    Limit=2000,
                )
                doc_items = response.get("Items", [])

                # Parse version deploy dates and sort descending
                version_windows = []
                for v in version_history:
                    created = v.get("createdAt", "")
                    ts = None
                    if created:
                        try:
                            ts = datetime.fromisoformat(
                                str(created).replace("Z", "+00:00")
                            )
                        except (ValueError, TypeError):
                            pass
                    version_windows.append(
                        {"version": v.get("version", ""), "deployedAt": ts, "count": 0}
                    )

                # Sort by deploy time descending (most recent first)
                version_windows.sort(
                    key=lambda x: (
                        x["deployedAt"] or datetime.min.replace(tzinfo=timezone.utc)
                    ),
                    reverse=True,
                )

                # For each document, find which version window it belongs to
                for item in doc_items:
                    ts_str = item.get("CompletionTime") or item.get(
                        "WorkflowStartTime", ""
                    )
                    if not ts_str:
                        continue
                    try:
                        doc_ts = datetime.fromisoformat(
                            str(ts_str).replace("Z", "+00:00")
                        )
                    except (ValueError, TypeError):
                        continue

                    # Find the version that was active when this doc was processed
                    assigned = False
                    for vw in version_windows:
                        if vw["deployedAt"] and doc_ts >= vw["deployedAt"]:
                            vw["count"] += 1
                            assigned = True
                            break
                    # If doc is older than all versions, assign to oldest
                    if not assigned and version_windows:
                        version_windows[-1]["count"] += 1

                # Write counts back to version_history
                version_count_map = {
                    vw["version"]: vw["count"] for vw in version_windows
                }
                for v in version_history:
                    v["documentCount"] = version_count_map.get(v.get("version", ""), 0)

                config["versionHistory"] = version_history
                logger.info(
                    "Per-version doc counts: %s",
                    {vw["version"]: vw["count"] for vw in version_windows},
                )
            except Exception as exc:
                logger.warning("Per-version document count supplement failed: %s", exc)

        # ── Supplement timeSeries from tracking table ──────────────────────
        # Fields: CompletionTime, WorkflowStartTime, ObjectStatus/WorkflowStatus
        if TRACKING_TABLE_NAME and needs_timeline:
            try:
                from datetime import timedelta  # noqa: PLC0415

                table = dynamodb.Table(TRACKING_TABLE_NAME)
                range_hours = _TIME_RANGE_HOURS.get(str(time_range).lower(), 24)
                now = datetime.now(timezone.utc)
                start = now - timedelta(hours=range_hours)

                # Scan for completion timestamps
                response = table.scan(
                    FilterExpression="ItemType = :doc",
                    ExpressionAttributeValues={":doc": "document"},
                    ProjectionExpression="CompletionTime, WorkflowStartTime, ObjectStatus, WorkflowStatus",
                    Limit=1000,
                )
                items = response.get("Items", [])

                # Bucket documents by hour
                bucket_size = max(1, range_hours // 24) if range_hours > 24 else 1
                num_buckets = min(24, range_hours)
                buckets: dict[str, dict[str, int]] = {}

                for i in range(num_buckets):
                    bucket_time = start + timedelta(hours=i * bucket_size)
                    bucket_key = bucket_time.strftime("%Y-%m-%dT%H:00:00+00:00")
                    buckets[bucket_key] = {"completed": 0, "failed": 0, "total": 0}

                for item in items:
                    ts_str = item.get("CompletionTime") or item.get(
                        "WorkflowStartTime", ""
                    )
                    status = item.get("ObjectStatus") or item.get("WorkflowStatus", "")
                    if not ts_str:
                        continue
                    try:
                        if "T" in str(ts_str):
                            ts = datetime.fromisoformat(
                                str(ts_str).replace("Z", "+00:00")
                            )
                        else:
                            continue
                        if ts < start:
                            continue
                        # Find matching bucket
                        bucket_idx = min(
                            int((ts - start).total_seconds() / (bucket_size * 3600)),
                            num_buckets - 1,
                        )
                        bucket_time = start + timedelta(hours=bucket_idx * bucket_size)
                        bucket_key = bucket_time.strftime("%Y-%m-%dT%H:00:00+00:00")
                        if bucket_key in buckets:
                            buckets[bucket_key]["total"] += 1
                            if status in (
                                "COMPLETED",
                                "SUCCEEDED",
                                "completed",
                                "success",
                            ):
                                buckets[bucket_key]["completed"] += 1
                            elif status in ("FAILED", "ERROR", "failed", "error"):
                                buckets[bucket_key]["failed"] += 1
                            else:
                                buckets[bucket_key]["completed"] += 1
                    except (ValueError, TypeError):
                        continue

                # Build time series from buckets
                time_series = [
                    {"timestamp": k, **v} for k, v in sorted(buckets.items())
                ]
                if any(b["total"] > 0 for b in time_series):
                    volume["timeSeries"] = time_series
                    logger.info(
                        "TimeSeries supplement: %d buckets with data",
                        sum(1 for b in time_series if b["total"] > 0),
                    )
            except Exception as exc:
                logger.warning("TimeSeries supplement failed: %s", exc)

        # ── Supplement latency from Metering data ─────────────────────────
        # Metering keys format: "Step/lambda/duration" → {"gb_seconds": "12.7"}
        # gb_seconds ≈ duration_seconds (assuming ~1GB memory), so *1000 = ms
        if TRACKING_TABLE_NAME and needs_latency:
            try:
                table = dynamodb.Table(TRACKING_TABLE_NAME)
                response = table.scan(
                    FilterExpression="ItemType = :doc",
                    ExpressionAttributeValues={":doc": "document"},
                    ProjectionExpression="Metering",
                    Limit=200,
                )
                items = response.get("Items", [])

                # Aggregate latency by pipeline step from Metering
                step_latencies: dict[str, list[int]] = defaultdict(list)
                for item in items:
                    metering = item.get("Metering", {})
                    if not isinstance(metering, dict):
                        continue
                    for key, step_data in metering.items():
                        if not isinstance(step_data, dict):
                            continue
                        # Only process duration entries (e.g., "OCR/lambda/duration")
                        if "/lambda/duration" not in key and "/duration" not in key:
                            continue
                        # Extract step name: "OCR/lambda/duration" → "OCR"
                        step_name = key.split("/")[0]
                        # gb_seconds → approximate ms (gb_seconds * 1000)
                        gb_sec = step_data.get("gb_seconds", 0)
                        if isinstance(gb_sec, Decimal):
                            gb_sec = float(gb_sec)
                        elif isinstance(gb_sec, str):
                            try:
                                gb_sec = float(gb_sec)
                            except ValueError:
                                gb_sec = 0.0
                        duration_ms = int(float(gb_sec) * 1000)
                        if duration_ms > 0:
                            step_latencies[step_name].append(duration_ms)

                if step_latencies:
                    per_stage = []
                    all_durations = []
                    for step_name, durations in sorted(step_latencies.items()):
                        durations.sort()
                        n = len(durations)
                        p50 = durations[n // 2] if n > 0 else 0
                        p90 = durations[int(n * 0.9)] if n > 1 else p50
                        p99 = durations[int(n * 0.99)] if n > 2 else p90
                        per_stage.append(
                            {
                                "stageName": step_name,
                                "p50Ms": p50,
                                "p90Ms": p90,
                                "p99Ms": p99,
                            }
                        )
                        all_durations.extend(durations)

                    all_durations.sort()
                    n_all = len(all_durations)
                    latency["perStage"] = per_stage
                    latency["p50Ms"] = all_durations[n_all // 2] if n_all > 0 else 0
                    latency["p90Ms"] = (
                        all_durations[int(n_all * 0.9)] if n_all > 1 else 0
                    )
                    latency["p99Ms"] = (
                        all_durations[int(n_all * 0.99)] if n_all > 2 else 0
                    )
                    latency["sampleCount"] = n_all
                    logger.info(
                        "Latency supplement: %d steps, %d samples",
                        len(per_stage),
                        n_all,
                    )
            except Exception as exc:
                logger.warning("Latency supplement failed: %s", exc)

    except Exception as exc:  # noqa: BLE001
        logger.warning("DynamoDB supplement failed: %s", exc)

    dashboard["volume"] = volume
    dashboard["cost"] = cost
    dashboard["distribution"] = distribution
    dashboard["config"] = config
    dashboard["latency"] = latency
    return dashboard


# ─────────────────────────────────────────────────────────────────────────────
# Empty dashboard — returned when service is unavailable or fails
# NO MOCK DATA — just zeros and empty arrays
# ─────────────────────────────────────────────────────────────────────────────


def _build_empty_dashboard(time_range: str) -> dict[str, Any]:
    """
    Returns an empty/zero-valued dashboard payload.
    Used when MonitoringMetricsService is not available or throws an error.
    The UI will display zero values or "no data" states.
    """
    now = datetime.now(timezone.utc)

    volume = {
        "totalDocuments": 0,
        "completedDocuments": 0,
        "failedDocuments": 0,
        "inProgressDocuments": 0,
        "successRate": 0.0,
        "throughputPerHour": 0.0,
        "totalPages": 0,
        "timeRange": time_range,
        "startTime": now.isoformat(),
        "endTime": now.isoformat(),
        "statusBreakdown": {
            "completed": 0,
            "failed": 0,
            "inProgress": 0,
            "queued": 0,
        },
        "timeSeries": [],
    }

    cost = {
        "totalInputTokens": 0,
        "totalOutputTokens": 0,
        "totalTokens": 0,
        "estimatedCostUsd": 0.0,
        "avgCostPerDoc": 0.0,
        "dataSource": "none",
        "perModelBreakdown": [],
        "historicalTrend": [],
        "tokenUtilization": None,
    }

    latency = {
        "p50Ms": 0,
        "p90Ms": 0,
        "p99Ms": 0,
        "sampleCount": 0,
        "xRayEnabled": False,
        "perStage": [],
    }

    failures = {
        "totalFailures": 0,
        "hasMore": False,
        "recentFailures": [],
    }

    throttles = {
        "overallSeverity": "ok",
        "totalEvents": 0,
        "lambdaThrottles": {"count": 0, "severity": "ok", "threshold": 10},
        "bedrockThrottles": {"count": 0, "severity": "ok", "threshold": 10},
        "textractThrottles": {"count": 0, "severity": "ok", "threshold": 10},
        "dynamodbThrottles": {"count": 0, "severity": "ok", "threshold": 10},
        "sqsMessageAge": {"count": 0, "severity": "ok", "threshold": 300},
    }

    distribution = {
        "totalDocuments": 0,
        "classificationLevel": "document",
        "classes": [],
    }

    config = {
        "activeVersion": "",
        "documentClassCount": 0,
        "documentClasses": [],
        "versionHistory": [],
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
