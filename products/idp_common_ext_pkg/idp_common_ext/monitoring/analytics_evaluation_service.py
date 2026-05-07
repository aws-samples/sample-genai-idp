# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Accuracy and evaluation analytics backed by the Athena evaluation tables.

Queries the ``document_evaluations``, ``section_evaluations``, and
``attribute_evaluations`` Glue tables that are populated when evaluation jobs
are run against ground-truth baselines.

Column names match the schema defined in
``idp_common/agents/analytics/schema_provider.py``.  All tables are partitioned
by ``date`` (YYYY-MM-DD).

**Important**: These tables are typically empty unless evaluation jobs have been
run separately.  All methods return ``None`` gracefully when:
  - Athena is not configured (no reporting bucket)
  - The evaluation tables contain no rows for the requested time range

Usage::

    from idp_common_ext.monitoring.analytics_evaluation_service import AnalyticsEvaluationService
    from idp_common_ext.monitoring.models import TimeRange

    svc = AnalyticsEvaluationService()
    tr = TimeRange.last_n_hours(720)   # 30 days

    if svc.is_configured():
        summary = svc.get_accuracy_summary(tr)
        by_version = svc.get_accuracy_by_config_version(tr)
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
        return int(float(value))
    except (ValueError, TypeError):
        return default


class AnalyticsEvaluationService:
    """
    Accuracy and evaluation analytics from the Athena evaluation tables.

    All methods return ``None`` when Athena is not configured or evaluation
    tables are empty, so callers can handle the absence of evaluation data
    gracefully.

    Methods
    -------
    is_configured()
        Returns ``True`` if the underlying Athena service is configured.
    get_accuracy_summary(time_range)
        Overall accuracy metrics across all evaluated documents.
    get_accuracy_by_config_version(time_range)
        Accuracy comparison across configuration versions.
    get_confidence_vs_accuracy(time_range)
        Correlation between extraction confidence and match accuracy.
    get_attribute_accuracy_breakdown(section_type, time_range)
        Per-attribute accuracy for a specific document type.
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
        """Extract start and end dates (YYYY-MM-DD) from a ``TimeRange``."""
        start_dt, end_dt = time_range.to_datetimes()

        def _to_date(dt: datetime) -> str:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.strftime("%Y-%m-%d")

        return _to_date(start_dt), _to_date(end_dt)

    def _run(self, query: str) -> Optional[List[Dict[str, Any]]]:
        """
        Execute a query, returning ``None`` on configuration or query errors.

        Converts all ``Analytics*Error`` exceptions into log warnings + ``None``
        returns so callers never have to handle exceptions.
        """
        try:
            return self._athena.execute_query(query)
        except AnalyticsNotConfiguredError as exc:
            logger.debug("Athena not configured — skipping evaluation query: %s", exc)
            return None
        except AnalyticsQueryError as exc:
            logger.warning("Athena evaluation query failed: %s", exc)
            return None
        except Exception as exc:
            logger.warning(
                "Unexpected error running Athena evaluation query: %s",
                exc,
                exc_info=True,
            )
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_accuracy_summary(self, time_range: Any) -> Optional[Dict[str, Any]]:
        """
        Overall accuracy metrics across all evaluated documents.

        Queries ``document_evaluations`` for aggregate scores and
        ``section_evaluations`` for per-document-type breakdown.

        Args:
            time_range: ``TimeRange`` instance.

        Returns:
            ``{
                "avg_accuracy":  float,
                "avg_f1_score":  float,
                "avg_precision": float,
                "avg_recall":    float,
                "document_count": int,
                "by_section_type": {
                    type: {avg_accuracy, avg_f1_score, document_count}
                },
            }``
            or ``None`` if Athena is not configured or no evaluation data exists.
        """
        if not self.is_configured():
            return None

        start_date, end_date = self._date_range(time_range)

        # ── Document-level aggregate ─────────────────────────────────
        doc_query = f"""
SELECT
    COUNT(DISTINCT "document_id")  AS document_count,
    AVG("accuracy")                AS avg_accuracy,
    AVG("f1_score")                AS avg_f1_score,
    AVG("precision")               AS avg_precision,
    AVG("recall")                  AS avg_recall
FROM document_evaluations
WHERE "date" BETWEEN '{start_date}' AND '{end_date}'
""".strip()  # nosec B608

        # ── Per-section-type breakdown ────────────────────────────────
        section_query = f"""
SELECT
    "section_type",
    COUNT(DISTINCT "document_id")  AS document_count,
    AVG("accuracy")                AS avg_accuracy,
    AVG("f1_score")                AS avg_f1_score,
    AVG("precision")               AS avg_precision,
    AVG("recall")                  AS avg_recall
FROM section_evaluations
WHERE "date" BETWEEN '{start_date}' AND '{end_date}'
GROUP BY "section_type"
ORDER BY avg_accuracy DESC
""".strip()  # nosec B608

        doc_rows = self._run(doc_query)
        section_rows = self._run(section_query)

        if doc_rows is None:
            return None

        d = doc_rows[0] if doc_rows else {}
        doc_count = _safe_int(d.get("document_count"))

        # Return None if no evaluation data exists for this time range
        if doc_count == 0:
            return None

        by_section_type: Dict[str, Any] = {}
        if section_rows:
            for row in section_rows:
                stype = row.get("section_type") or "unknown"
                by_section_type[stype] = {
                    "avg_accuracy": round(_safe_float(row.get("avg_accuracy")), 4),
                    "avg_f1_score": round(_safe_float(row.get("avg_f1_score")), 4),
                    "avg_precision": round(_safe_float(row.get("avg_precision")), 4),
                    "avg_recall": round(_safe_float(row.get("avg_recall")), 4),
                    "document_count": _safe_int(row.get("document_count")),
                }

        return {
            "avg_accuracy": round(_safe_float(d.get("avg_accuracy")), 4),
            "avg_f1_score": round(_safe_float(d.get("avg_f1_score")), 4),
            "avg_precision": round(_safe_float(d.get("avg_precision")), 4),
            "avg_recall": round(_safe_float(d.get("avg_recall")), 4),
            "document_count": doc_count,
            "by_section_type": by_section_type,
        }

    def get_accuracy_by_config_version(
        self,
        time_range: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        Accuracy comparison across configuration versions.

        Useful for A/B testing configuration changes — compare accuracy before
        and after a config update.

        Args:
            time_range: ``TimeRange`` instance.

        Returns:
            ``{
                "by_version": {
                    version: {
                        avg_accuracy, avg_f1_score, avg_weighted_score,
                        document_count
                    }
                }
            }``
            or ``None`` if Athena is not configured or no evaluation data exists.
        """
        if not self.is_configured():
            return None

        start_date, end_date = self._date_range(time_range)

        query = f"""
SELECT
    "config_version",
    COUNT(DISTINCT "document_id")    AS document_count,
    AVG("accuracy")                  AS avg_accuracy,
    AVG("f1_score")                  AS avg_f1_score,
    AVG("weighted_overall_score")    AS avg_weighted_score,
    AVG("precision")                 AS avg_precision,
    AVG("recall")                    AS avg_recall
FROM document_evaluations
WHERE "date" BETWEEN '{start_date}' AND '{end_date}'
GROUP BY "config_version"
ORDER BY avg_f1_score DESC
""".strip()  # nosec B608

        rows = self._run(query)
        if rows is None:
            return None

        by_version: Dict[str, Any] = {}
        for row in rows:
            version = row.get("config_version") or "default"
            by_version[version] = {
                "document_count": _safe_int(row.get("document_count")),
                "avg_accuracy": round(_safe_float(row.get("avg_accuracy")), 4),
                "avg_f1_score": round(_safe_float(row.get("avg_f1_score")), 4),
                "avg_weighted_score": round(
                    _safe_float(row.get("avg_weighted_score")), 4
                ),
                "avg_precision": round(_safe_float(row.get("avg_precision")), 4),
                "avg_recall": round(_safe_float(row.get("avg_recall")), 4),
            }

        return {"by_version": by_version} if by_version else None

    def get_confidence_vs_accuracy(
        self,
        time_range: Any,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Correlation between extraction confidence scores and match accuracy.

        Groups attribute evaluations by confidence band to show how well
        high-confidence extractions actually perform.

        Args:
            time_range: ``TimeRange`` instance.

        Returns:
            ``[{
                "confidence_band": str,   # e.g. "High (>0.9)"
                "accuracy_rate":  float,
                "attribute_count": int,
            }, ...]``
            ordered from High to Low confidence, or ``None`` if not configured.
        """
        if not self.is_configured():
            return None

        start_date, end_date = self._date_range(time_range)

        query = f"""
SELECT
    CASE
        WHEN TRY(CAST("confidence" AS double)) IS NULL THEN 'Unknown'
        WHEN CAST("confidence" AS double) >= 0.9 THEN 'High (>=0.9)'
        WHEN CAST("confidence" AS double) >= 0.7 THEN 'Medium (0.7-0.9)'
        ELSE 'Low (<0.7)'
    END                                          AS confidence_band,
    AVG(CASE WHEN "matched" = 'true' THEN 1.0 ELSE 0.0 END) AS accuracy_rate,
    COUNT(*)                                     AS attribute_count
FROM attribute_evaluations
WHERE "date" BETWEEN '{start_date}' AND '{end_date}'
GROUP BY 1
ORDER BY AVG(CASE WHEN "matched" = 'true' THEN 1.0 ELSE 0.0 END) DESC
""".strip()  # nosec B608

        rows = self._run(query)
        if rows is None:
            return None

        # Define display order
        band_order = {
            "High (>=0.9)": 0,
            "Medium (0.7-0.9)": 1,
            "Low (<0.7)": 2,
            "Unknown": 3,
        }

        result = []
        for row in rows:
            band = row.get("confidence_band") or "Unknown"
            result.append(
                {
                    "confidence_band": band,
                    "accuracy_rate": round(_safe_float(row.get("accuracy_rate")), 4),
                    "attribute_count": _safe_int(row.get("attribute_count")),
                }
            )

        result.sort(key=lambda x: band_order.get(x["confidence_band"], 99))
        return result if result else None

    def get_attribute_accuracy_breakdown(
        self,
        section_type: str,
        time_range: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        Per-attribute accuracy for a specific document type.

        Shows which fields are extracted accurately and which are problematic,
        useful for targeted configuration tuning.

        Args:
            section_type: Document type / section type to query
                          (e.g. ``"invoice"``, ``"w2"``).
            time_range:   ``TimeRange`` instance.

        Returns:
            ``{
                "section_type": str,
                "document_count": int,
                "attributes": [
                    {
                        "attribute_name": str,
                        "accuracy_rate":  float,   # fraction matched
                        "avg_score":      float,
                        "total_count":    int,
                        "matched_count":  int,
                    }, ...
                ]
            }``
            sorted by accuracy_rate ascending (worst-performing fields first),
            or ``None`` if Athena is not configured or no data exists.
        """
        if not self.is_configured():
            return None

        start_date, end_date = self._date_range(time_range)

        query = f"""
SELECT
    "attribute_name",
    AVG(CASE WHEN "matched" = 'true' THEN 1.0 ELSE 0.0 END) AS accuracy_rate,
    AVG(TRY(CAST("score" AS double)))                        AS avg_score,
    COUNT(*)                                                 AS total_count,
    SUM(CASE WHEN "matched" = 'true' THEN 1 ELSE 0 END)     AS matched_count
FROM attribute_evaluations
WHERE "date" BETWEEN '{start_date}' AND '{end_date}'
  AND LOWER("section_type") = LOWER('{section_type}')
GROUP BY "attribute_name"
ORDER BY accuracy_rate ASC
""".strip()  # nosec B608

        # Also get document count for this section type
        doc_count_query = f"""
SELECT COUNT(DISTINCT "document_id") AS document_count
FROM section_evaluations
WHERE "date" BETWEEN '{start_date}' AND '{end_date}'
  AND LOWER("section_type") = LOWER('{section_type}')
""".strip()  # nosec B608

        attr_rows = self._run(query)
        doc_count_rows = self._run(doc_count_query)

        if attr_rows is None:
            return None

        doc_count = 0
        if doc_count_rows:
            doc_count = _safe_int(doc_count_rows[0].get("document_count"))

        attributes = []
        for row in attr_rows:
            attributes.append(
                {
                    "attribute_name": row.get("attribute_name") or "unknown",
                    "accuracy_rate": round(_safe_float(row.get("accuracy_rate")), 4),
                    "avg_score": round(_safe_float(row.get("avg_score")), 4),
                    "total_count": _safe_int(row.get("total_count")),
                    "matched_count": _safe_int(row.get("matched_count")),
                }
            )

        return {
            "section_type": section_type,
            "document_count": doc_count,
            "attributes": attributes,
        }
