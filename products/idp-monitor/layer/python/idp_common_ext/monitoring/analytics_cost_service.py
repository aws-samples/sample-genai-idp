# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Cost and token utilization analytics backed by the Athena ``metering`` table.

Replaces ``DocumentStatsService.get_cost_metrics()`` for analytical (non-real-time)
queries.  Instead of paginating through DynamoDB and recomputing costs in Python,
this service issues a single SQL GROUP BY query to Athena and returns pre-aggregated
results in ~2–5 seconds regardless of dataset size.

Column names match the ``metering`` Glue table schema as defined in
``idp_common/agents/analytics/schema_provider.py``:

    document_id, context, service_api, unit, value, number_of_pages,
    unit_cost, estimated_cost, timestamp, config_version
    Partitioned by: date (YYYY-MM-DD)

Returns ``None`` for all methods when Athena is not configured (graceful
degradation for stacks without a reporting bucket).

Usage::

    from idp_common_ext.monitoring.analytics_cost_service import AnalyticsCostService
    from idp_common_ext.monitoring.analytics_athena_service import AnalyticsAthenaService
    from idp_common_ext.monitoring.models import TimeRange

    svc = AnalyticsCostService()
    tr = TimeRange.last_n_hours(24)

    if svc.is_configured():
        costs = svc.get_cost_metrics(tr)
        tokens = svc.get_token_utilization(tr)
        trends = svc.get_cost_trends(tr, bucket="day")
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from idp_common_ext.monitoring.analytics_athena_service import (
    AnalyticsAthenaService,
    AnalyticsNotConfiguredError,
    AnalyticsQueryError,
)

logger = logging.getLogger(__name__)


def _safe_float(value: Optional[str], default: float = 0.0) -> float:
    """Convert a string value to float, returning *default* on failure."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_int(value: Optional[str], default: int = 0) -> int:
    """Convert a string value to int, returning *default* on failure."""
    if value is None:
        return default
    try:
        return int(float(value))  # handles "1234.0" strings from Athena
    except (ValueError, TypeError):
        return default


class AnalyticsCostService:
    """
    Cost and token utilization analytics from the Athena ``metering`` table.

    All methods return ``None`` when Athena is not configured, so
    ``MonitoringMetricsService`` can fall back to DynamoDB transparently.

    Methods
    -------
    is_configured()
        Returns ``True`` if the underlying Athena service is configured.
    get_cost_metrics(time_range)
        Total cost + token aggregation — same shape as the DynamoDB version.
    get_token_utilization(time_range)
        Token breakdown by model and processing context.
    get_cost_trends(time_range, bucket)
        Time-series cost data bucketed by hour/day/week.
    get_cost_by_config_version(time_range)
        Cost/volume comparison across configuration versions.
    get_model_usage_breakdown(time_range)
        Per-model usage stats including percentage of total cost.
    """

    def __init__(
        self,
        athena_service: Optional[AnalyticsAthenaService] = None,
    ) -> None:
        """
        Args:
            athena_service: Optional pre-built ``AnalyticsAthenaService``.
                            Created automatically from environment variables
                            if omitted.
        """
        self._athena = athena_service or AnalyticsAthenaService()

    # ------------------------------------------------------------------
    # Configuration check
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        """Return ``True`` if Athena is configured and queries can run."""
        return self._athena.is_configured()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _date_range(time_range: Any) -> tuple[str, str]:
        """
        Extract start and end dates (YYYY-MM-DD) from a ``TimeRange``.

        The ``metering`` table is partitioned by ``date``, so we always filter
        on the partition column for performance.
        """
        start_dt, end_dt = time_range.to_datetimes()

        def _to_date(dt: datetime) -> str:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.strftime("%Y-%m-%d")

        return _to_date(start_dt), _to_date(end_dt)

    def _run(self, query: str) -> Optional[List[Dict[str, Any]]]:
        """
        Execute a query, returning ``None`` on configuration or query errors.

        This wrapper converts all ``Analytics*Error`` exceptions into log
        warnings + ``None`` returns so callers never have to handle exceptions.
        """
        try:
            return self._athena.execute_query(query)
        except AnalyticsNotConfiguredError as exc:
            logger.debug("Athena not configured — skipping query: %s", exc)
            return None
        except AnalyticsQueryError as exc:
            logger.warning("Athena query failed: %s", exc)
            return None
        except Exception as exc:
            logger.warning(
                "Unexpected error running Athena query: %s", exc, exc_info=True
            )
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_cost_metrics(self, time_range: Any) -> Optional[Dict[str, Any]]:
        """
        Aggregate cost and token metrics for a time range.

        Returns the same structure as ``DocumentStatsService.get_cost_metrics()``
        so ``MonitoringMetricsService`` can swap sources transparently.

        Args:
            time_range: ``TimeRange`` instance.

        Returns:
            ``{
                "total_input_tokens": int,
                "total_output_tokens": int,
                "total_pages_processed": int,
                "estimated_cost_usd": float,
                "by_model": {
                    "<service_api>": {
                        "input_tokens": int,
                        "output_tokens": int,
                        "cost_usd": float,
                    }
                },
                "document_count": int,
            }``
            or ``None`` if Athena is not configured.
        """
        if not self.is_configured():
            return None

        start_date, end_date = self._date_range(time_range)

        # ── Totals query ──────────────────────────────────────────────
        totals_query = f"""
SELECT
    COUNT(DISTINCT "document_id")                                              AS document_count,
    SUM(CASE WHEN "unit" = 'inputTokens'  THEN "value" ELSE 0 END)            AS total_input_tokens,
    SUM(CASE WHEN "unit" = 'outputTokens' THEN "value" ELSE 0 END)            AS total_output_tokens,
    SUM("estimated_cost")                                                      AS total_cost
FROM metering
WHERE "date" BETWEEN '{start_date}' AND '{end_date}'
""".strip()  # nosec B608

        totals_rows = self._run(totals_query)
        if totals_rows is None:
            return None

        totals = totals_rows[0] if totals_rows else {}

        # ── Total pages (correct MAX-per-doc aggregation) ─────────────
        pages_query = f"""
SELECT SUM(max_pages) AS total_pages
FROM (
    SELECT "document_id", MAX("number_of_pages") AS max_pages
    FROM metering
    WHERE "date" BETWEEN '{start_date}' AND '{end_date}'
    GROUP BY "document_id"
)
""".strip()  # nosec B608

        pages_rows = self._run(pages_query)
        total_pages = 0
        if pages_rows:
            total_pages = _safe_int(pages_rows[0].get("total_pages"))

        # ── Per-model breakdown ───────────────────────────────────────
        model_query = f"""
SELECT
    "service_api",
    SUM(CASE WHEN "unit" = 'inputTokens'  THEN "value" ELSE 0 END) AS input_tokens,
    SUM(CASE WHEN "unit" = 'outputTokens' THEN "value" ELSE 0 END) AS output_tokens,
    SUM("estimated_cost")                                           AS cost_usd
FROM metering
WHERE "date" BETWEEN '{start_date}' AND '{end_date}'
  AND "unit" IN ('inputTokens', 'outputTokens')
GROUP BY "service_api"
ORDER BY cost_usd DESC
""".strip()  # nosec B608

        model_rows = self._run(model_query)
        by_model: Dict[str, Any] = {}
        if model_rows:
            for row in model_rows:
                api = row.get("service_api") or "unknown"
                by_model[api] = {
                    "input_tokens": _safe_int(row.get("input_tokens")),
                    "output_tokens": _safe_int(row.get("output_tokens")),
                    "cost_usd": round(_safe_float(row.get("cost_usd")), 6),
                }

        return {
            "total_input_tokens": _safe_int(totals.get("total_input_tokens")),
            "total_output_tokens": _safe_int(totals.get("total_output_tokens")),
            "total_pages_processed": total_pages,
            "estimated_cost_usd": round(_safe_float(totals.get("total_cost")), 6),
            "by_model": by_model,
            "document_count": _safe_int(totals.get("document_count")),
        }

    def get_token_utilization(self, time_range: Any) -> Optional[Dict[str, Any]]:
        """
        Token usage breakdown by model and processing context.

        Args:
            time_range: ``TimeRange`` instance.

        Returns:
            ``{
                "by_model":   {model_id: {input_tokens, output_tokens, total_cost}},
                "by_context": {context:  {input_tokens, output_tokens, total_cost}},
                "totals":     {input_tokens, output_tokens, total_cost},
                "document_count": int,
            }``
            or ``None`` if Athena is not configured.
        """
        if not self.is_configured():
            return None

        start_date, end_date = self._date_range(time_range)

        # ── By model ─────────────────────────────────────────────────
        model_query = f"""
SELECT
    "service_api",
    SUM(CASE WHEN "unit" = 'inputTokens'  THEN "value" ELSE 0 END) AS input_tokens,
    SUM(CASE WHEN "unit" = 'outputTokens' THEN "value" ELSE 0 END) AS output_tokens,
    SUM("estimated_cost")                                           AS total_cost
FROM metering
WHERE "date" BETWEEN '{start_date}' AND '{end_date}'
  AND "unit" IN ('inputTokens', 'outputTokens')
GROUP BY "service_api"
ORDER BY total_cost DESC
""".strip()  # nosec B608

        # ── By context ───────────────────────────────────────────────
        context_query = f"""
SELECT
    "context",
    SUM(CASE WHEN "unit" = 'inputTokens'  THEN "value" ELSE 0 END) AS input_tokens,
    SUM(CASE WHEN "unit" = 'outputTokens' THEN "value" ELSE 0 END) AS output_tokens,
    SUM("estimated_cost")                                           AS total_cost
FROM metering
WHERE "date" BETWEEN '{start_date}' AND '{end_date}'
  AND "unit" IN ('inputTokens', 'outputTokens')
GROUP BY "context"
ORDER BY total_cost DESC
""".strip()  # nosec B608

        # ── Totals ────────────────────────────────────────────────────
        totals_query = f"""
SELECT
    COUNT(DISTINCT "document_id")                                              AS document_count,
    SUM(CASE WHEN "unit" = 'inputTokens'  THEN "value" ELSE 0 END)            AS input_tokens,
    SUM(CASE WHEN "unit" = 'outputTokens' THEN "value" ELSE 0 END)            AS output_tokens,
    SUM("estimated_cost")                                                      AS total_cost
FROM metering
WHERE "date" BETWEEN '{start_date}' AND '{end_date}'
  AND "unit" IN ('inputTokens', 'outputTokens')
""".strip()  # nosec B608

        model_rows = self._run(model_query)
        context_rows = self._run(context_query)
        totals_rows = self._run(totals_query)

        if model_rows is None or context_rows is None or totals_rows is None:
            return None

        by_model: Dict[str, Any] = {}
        for row in model_rows:
            api = row.get("service_api") or "unknown"
            by_model[api] = {
                "input_tokens": _safe_int(row.get("input_tokens")),
                "output_tokens": _safe_int(row.get("output_tokens")),
                "total_cost": round(_safe_float(row.get("total_cost")), 6),
            }

        by_context: Dict[str, Any] = {}
        for row in context_rows:
            ctx = row.get("context") or "unknown"
            by_context[ctx] = {
                "input_tokens": _safe_int(row.get("input_tokens")),
                "output_tokens": _safe_int(row.get("output_tokens")),
                "total_cost": round(_safe_float(row.get("total_cost")), 6),
            }

        t = totals_rows[0] if totals_rows else {}
        totals = {
            "input_tokens": _safe_int(t.get("input_tokens")),
            "output_tokens": _safe_int(t.get("output_tokens")),
            "total_cost": round(_safe_float(t.get("total_cost")), 6),
        }

        return {
            "by_model": by_model,
            "by_context": by_context,
            "totals": totals,
            "document_count": _safe_int(t.get("document_count")),
        }

    def get_cost_trends(
        self,
        time_range: Any,
        bucket: str = "day",
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Time-series cost data for charting.

        Args:
            time_range: ``TimeRange`` instance.
            bucket:     Bucket granularity — ``"hour"``, ``"day"`` (default),
                        or ``"week"``.

        Returns:
            ``[{"date": str, "total_cost": float, "document_count": int,
               "input_tokens": int, "output_tokens": int}, ...]``
            or ``None`` if Athena is not configured.
        """
        if not self.is_configured():
            return None

        start_date, end_date = self._date_range(time_range)

        # Metering is partitioned by date (YYYY-MM-DD) — we bucket accordingly.
        # For hour buckets we use date_trunc on the timestamp column; for day
        # we use the partition column directly (faster, no full-column scan).
        if bucket == "hour":
            group_expr = "date_format(\"timestamp\", '%Y-%m-%d %H:00')"
        elif bucket == "week":
            group_expr = (
                "date_format(date_trunc('week', CAST(\"date\" AS date)), '%Y-%m-%d')"
            )
        else:  # "day"
            group_expr = '"date"'

        query = f"""
SELECT
    {group_expr}                                                               AS bucket_date,
    COUNT(DISTINCT "document_id")                                              AS document_count,
    SUM("estimated_cost")                                                      AS total_cost,
    SUM(CASE WHEN "unit" = 'inputTokens'  THEN "value" ELSE 0 END)            AS input_tokens,
    SUM(CASE WHEN "unit" = 'outputTokens' THEN "value" ELSE 0 END)            AS output_tokens
FROM metering
WHERE "date" BETWEEN '{start_date}' AND '{end_date}'
GROUP BY {group_expr}
ORDER BY bucket_date
""".strip()  # nosec B608

        rows = self._run(query)
        if rows is None:
            return None

        result = []
        for row in rows:
            result.append(
                {
                    "date": row.get("bucket_date", ""),
                    "total_cost": round(_safe_float(row.get("total_cost")), 6),
                    "document_count": _safe_int(row.get("document_count")),
                    "input_tokens": _safe_int(row.get("input_tokens")),
                    "output_tokens": _safe_int(row.get("output_tokens")),
                }
            )
        return result

    def get_cost_by_config_version(
        self,
        time_range: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        Cost and volume comparison across configuration versions.

        Useful for evaluating the cost impact of configuration changes.

        Args:
            time_range: ``TimeRange`` instance.

        Returns:
            ``{"by_version": {version: {total_cost, document_count,
               avg_cost_per_doc, input_tokens, output_tokens}}}``
            or ``None`` if Athena is not configured.
        """
        if not self.is_configured():
            return None

        start_date, end_date = self._date_range(time_range)

        query = f"""
SELECT
    "config_version",
    COUNT(DISTINCT "document_id")                                              AS document_count,
    SUM("estimated_cost")                                                      AS total_cost,
    SUM("estimated_cost") / NULLIF(COUNT(DISTINCT "document_id"), 0)          AS avg_cost_per_doc,
    SUM(CASE WHEN "unit" = 'inputTokens'  THEN "value" ELSE 0 END)            AS input_tokens,
    SUM(CASE WHEN "unit" = 'outputTokens' THEN "value" ELSE 0 END)            AS output_tokens
FROM metering
WHERE "date" BETWEEN '{start_date}' AND '{end_date}'
GROUP BY "config_version"
ORDER BY total_cost DESC
""".strip()  # nosec B608

        rows = self._run(query)
        if rows is None:
            return None

        by_version: Dict[str, Any] = {}
        for row in rows:
            version = row.get("config_version") or "default"
            by_version[version] = {
                "total_cost": round(_safe_float(row.get("total_cost")), 6),
                "document_count": _safe_int(row.get("document_count")),
                "avg_cost_per_doc": round(_safe_float(row.get("avg_cost_per_doc")), 6),
                "input_tokens": _safe_int(row.get("input_tokens")),
                "output_tokens": _safe_int(row.get("output_tokens")),
            }

        return {"by_version": by_version}

    def get_model_usage_breakdown(
        self,
        time_range: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        Which models are used, how much, and what they cost.

        Includes each model's percentage contribution to total cost for easy
        identification of the most expensive processing steps.

        Args:
            time_range: ``TimeRange`` instance.

        Returns:
            ``{"models": [{model_id, total_calls, input_tokens, output_tokens,
               cost, pct_of_total_cost}]}``
            or ``None`` if Athena is not configured.
        """
        if not self.is_configured():
            return None

        start_date, end_date = self._date_range(time_range)

        query = f"""
SELECT
    "service_api",
    COUNT(DISTINCT "document_id")                                              AS total_calls,
    SUM(CASE WHEN "unit" = 'inputTokens'  THEN "value" ELSE 0 END)            AS input_tokens,
    SUM(CASE WHEN "unit" = 'outputTokens' THEN "value" ELSE 0 END)            AS output_tokens,
    SUM("estimated_cost")                                                      AS cost,
    SUM("estimated_cost") * 100.0
        / NULLIF(SUM(SUM("estimated_cost")) OVER (), 0)                        AS pct_of_total_cost
FROM metering
WHERE "date" BETWEEN '{start_date}' AND '{end_date}'
GROUP BY "service_api"
ORDER BY cost DESC
""".strip()  # nosec B608

        rows = self._run(query)
        if rows is None:
            return None

        models = []
        for row in rows:
            models.append(
                {
                    "model_id": row.get("service_api") or "unknown",
                    "total_calls": _safe_int(row.get("total_calls")),
                    "input_tokens": _safe_int(row.get("input_tokens")),
                    "output_tokens": _safe_int(row.get("output_tokens")),
                    "cost": round(_safe_float(row.get("cost")), 6),
                    "pct_of_total_cost": round(
                        _safe_float(row.get("pct_of_total_cost")), 2
                    ),
                }
            )

        return {"models": models}
