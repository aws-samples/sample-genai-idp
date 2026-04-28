"""
IDPMonitor — AppSync Lambda Resolver

This is the ONLY place in IDPMonitor where subscription entitlement is checked.
The foundation services in idp_common/monitoring/ are subscription-unaware.

Flow:
  1. Parse AppSync event (field name + arguments)
  2. For getMonitoringStatus:  return subscription status (respects SUBSCRIPTION_VALIDATION_MODE)
  3. For getMonitoringDashboard:
       a. Check subscription entitlement
       b. If not entitled: return subscriptionStatus="inactive" with empty sections
       c. If entitled: call MonitoringMetricsService (or return mock data in dev mode)

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

# ── Lazy imports (available via Lambda layer) ─────────────────────────────────
# Uncomment when idp_common layer is attached:
# from idp_common_ext.monitoring.monitoring_metrics_service import MonitoringMetricsService
# from idp_common.subscription.license_checker import LicenseChecker


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
    if SUBSCRIPTION_VALIDATION_MODE == "none":
        # Dev/testing mode — return realistic mock data so the UI renders fully
        logger.info("Dev mode — returning mock dashboard data")
        dashboard = _build_mock_dashboard(time_range)
    else:
        # Production mode — call MonitoringMetricsService
        # TODO: Uncomment when idp_common layer is attached
        # service = MonitoringMetricsService(
        #     tracking_table=TRACKING_TABLE_NAME,
        #     config_table=CONFIGURATION_TABLE_NAME,
        #     reporting_bucket=REPORTING_BUCKET_NAME,
        #     stack_name=ACCELERATOR_STACK_NAME,
        #     time_range=time_range,
        #     start_time=start_time,
        #     end_time=end_time,
        # )
        # dashboard = service.get_dashboard_data(sections=sections)
        dashboard = _build_mock_dashboard(
            time_range
        )  # placeholder until service is ready

    logger.info(
        "Dashboard data fetched for time_range=%s sections=%s", time_range, sections
    )

    return {
        "subscriptionStatus": "active",
        "subscriptionTier": "standard",
        "volume": json.dumps(dashboard["volume"]),
        "cost": json.dumps(dashboard["cost"]),
        "latency": json.dumps(dashboard["latency"]),
        "failures": json.dumps(dashboard["failures"]),
        "throttles": json.dumps(dashboard["throttles"]),
        "distribution": json.dumps(dashboard["distribution"]),
        "config": json.dumps(dashboard["config"]),
        "timeRange": time_range,
        "startTime": start_time,
        "endTime": end_time,
        "generatedAt": generated_at,
        "errors": [],
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
# Mock data — realistic sample dashboard data for dev/testing
# ─────────────────────────────────────────────────────────────────────────────


def _build_mock_dashboard(time_range: str) -> dict[str, Any]:
    """
    Returns a realistic mock dashboard payload for dev/testing.
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
        "dataSource": "dynamodb",
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
