# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Real-time document status and volume metrics from DynamoDB.

``OperationalDocumentService`` handles **operational** (live) queries only:
document status counts, volume metrics, recent failures, document type
distribution, and configuration info.  It reads from DynamoDB and is suited
for queries that require up-to-the-minute accuracy.

**For historical cost/token analytics use** ``AnalyticsCostService`` instead.
That service queries the Athena ``metering`` table and is 10–30× faster for
large datasets, supports long-range historical queries, and provides GROUP BY
aggregations that are not practical with DynamoDB.

This class is a refactored version of ``DocumentStatsService`` with the
``get_cost_metrics()`` method removed (migrated to ``AnalyticsCostService``).
The old name is preserved as a backward-compatible alias in
``document_stats_service.py``.

Usage::

    from idp_common_ext.monitoring import OperationalDocumentService, TimeRange

    svc = OperationalDocumentService()
    tr = TimeRange.last_n_hours(1)

    volume   = svc.get_volume_metrics(tr)
    failures = svc.get_recent_failures(tr, limit=20)
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from typing import Any, Dict, List, Optional

from idp_common.dynamodb.service import DocumentDynamoDBService
from idp_common.models import Status

logger = logging.getLogger(__name__)


class OperationalDocumentService:
    """
    Real-time document status and volume metrics from DynamoDB.

    Provides operational (live) queries:

    * :meth:`get_volume_metrics`            — totals, success rate, throughput
    * :meth:`get_status_breakdown`          — counts by individual status value
    * :meth:`get_document_type_distribution`— counts by document class
    * :meth:`get_volume_over_time`          — time-bucketed volume for charts
    * :meth:`get_recent_failures`           — list of recently failed documents
    * :meth:`get_active_config_info`        — active config version + doc classes

    For cost/token analytics see :class:`~idp_common.monitoring.analytics_cost_service.AnalyticsCostService`.
    """

    def __init__(
        self,
        dynamodb_service: Optional[DocumentDynamoDBService] = None,
        table_name: Optional[str] = None,
    ) -> None:
        """
        Args:
            dynamodb_service: Optional pre-built ``DocumentDynamoDBService``.
                              Created from ``TRACKING_TABLE_NAME`` env var if omitted.
            table_name:       Explicit DynamoDB table name (overrides env var).
        """
        if dynamodb_service is not None:
            self._db = dynamodb_service
        else:
            resolved_table = table_name or os.environ.get("TRACKING_TABLE_NAME", "")
            self._db = DocumentDynamoDBService(table_name=resolved_table or None)

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _fetch_all_documents(
        self,
        start_date_time: Optional[str],
        end_date_time: Optional[str],
        page_limit: int = 500,
        max_pages: int = 40,
    ) -> List[Any]:
        """
        Exhaustively paginate through ``list_documents`` and return all results.

        Args:
            start_date_time: ISO 8601 start filter (may be None).
            end_date_time:   ISO 8601 end filter (may be None).
            page_limit:      Items per DynamoDB page.
            max_pages:       Safety cap to avoid runaway pagination (default
                             caps at 20,000 documents).

        Returns:
            Flat list of ``Document`` objects.
        """
        all_docs: List[Any] = []
        next_token = None
        pages_fetched = 0

        while pages_fetched < max_pages:
            response = self._db.list_documents(
                start_date_time=start_date_time,
                end_date_time=end_date_time,
                limit=page_limit,
                exclusive_start_key=next_token,
            )
            page_docs = response.get("Documents", [])
            all_docs.extend(page_docs)

            next_token = response.get("nextToken")
            pages_fetched += 1

            if not next_token:
                break

        if pages_fetched == max_pages and next_token:
            logger.warning(
                "Reached max pagination limit (%d pages); results may be incomplete",
                max_pages,
            )

        return all_docs

    # -------------------------------------------------------------------------
    # Volume metrics
    # -------------------------------------------------------------------------

    def get_volume_metrics(
        self,
        time_range: Any,  # TimeRange
    ) -> Dict[str, Any]:
        """
        Return document volume metrics for the given time range.

        Args:
            time_range: ``TimeRange`` instance.

        Returns:
            ``{
                "total_documents": int,
                "completed": int,
                "failed": int,
                "processing": int,
                "queued": int,
                "success_rate": float,     # 0.0 – 1.0
                "failure_rate": float,
                "time_range_hours": float,
                "throughput_per_hour": float,
            }``
        """
        docs = self._fetch_all_documents(
            start_date_time=time_range.start_time,
            end_date_time=time_range.end_time,
        )

        _in_progress = {
            Status.RUNNING,
            Status.OCR,
            Status.CLASSIFYING,
            Status.EXTRACTING,
            Status.ASSESSING,
            Status.POSTPROCESSING,
            Status.SUMMARIZING,
            Status.RULE_VALIDATION,
            Status.RULE_VALIDATION_ORCHESTRATOR,
            Status.EVALUATING,
            Status.HITL_IN_PROGRESS,
        }
        completed = sum(1 for d in docs if d.status == Status.COMPLETED)
        failed = sum(1 for d in docs if d.status == Status.FAILED)
        processing = sum(1 for d in docs if d.status in _in_progress)
        queued = sum(1 for d in docs if d.status == Status.QUEUED)
        total = len(docs)

        hours = time_range.duration_hours() or 1.0
        success_rate = completed / total if total else 0.0
        failure_rate = failed / total if total else 0.0
        throughput = total / hours

        return {
            "total_documents": total,
            "completed": completed,
            "failed": failed,
            "processing": processing,
            "queued": queued,
            "success_rate": round(success_rate, 4),
            "failure_rate": round(failure_rate, 4),
            "time_range_hours": hours,
            "throughput_per_hour": round(throughput, 2),
        }

    # -------------------------------------------------------------------------
    # Status breakdown
    # -------------------------------------------------------------------------

    def get_status_breakdown(
        self,
        time_range: Any,
    ) -> Dict[str, Any]:
        """
        Return a count of documents in each status within the time range.

        Returns:
            ``{
                "by_status": {"COMPLETED": N, "FAILED": N, ...},
                "total": int,
            }``
        """
        docs = self._fetch_all_documents(
            start_date_time=time_range.start_time,
            end_date_time=time_range.end_time,
        )

        by_status: Dict[str, int] = defaultdict(int)
        for doc in docs:
            status_value = (
                doc.status.value if hasattr(doc.status, "value") else str(doc.status)
            )
            by_status[status_value] += 1

        return {
            "by_status": dict(by_status),
            "total": len(docs),
        }

    # -------------------------------------------------------------------------
    # Document type distribution
    # -------------------------------------------------------------------------

    def get_document_type_distribution(
        self,
        time_range: Any,
    ) -> Dict[str, Any]:
        """
        Return a breakdown of documents by their classified document type.

        Document type is derived from the ``classification`` field of the
        *first* section in each document.

        Returns:
            ``{
                "by_type": {"InvoiceDocument": N, "W2": N, ...},
                "total": int,
                "unclassified": int,
            }``
        """
        docs = self._fetch_all_documents(
            start_date_time=time_range.start_time,
            end_date_time=time_range.end_time,
        )

        by_type: Dict[str, int] = defaultdict(int)
        unclassified = 0
        for doc in docs:
            classification = None
            # Primary: section-level classification (Class field in Sections[])
            if doc.sections:
                classification = doc.sections[0].classification or None
            # Fallback: page-level classification (Class field in Pages[])
            if not classification and doc.pages:
                first_page = next(iter(doc.pages.values()), None)
                if first_page:
                    classification = getattr(first_page, "classification", None) or None
            if not classification:
                unclassified += 1
            else:
                by_type[classification] += 1

        return {
            "by_type": dict(by_type),
            "total": len(docs),
            "unclassified": unclassified,
        }

    def get_config_version_distribution(
        self,
        time_range: Any,
    ) -> Dict[str, Any]:
        """
        Return a breakdown of documents by the config version they were processed with.

        Returns:
            ``{
                "by_version": {"v1.0": N, "v1.1": N, ...},
                "total": int,
                "no_version": int,
            }``
        """
        docs = self._fetch_all_documents(
            start_date_time=time_range.start_time,
            end_date_time=time_range.end_time,
        )

        by_version: Dict[str, int] = defaultdict(int)
        no_version = 0
        for doc in docs:
            config_version = getattr(doc, "config_version", None)
            if not config_version:
                no_version += 1
            else:
                by_version[config_version] += 1

        return {
            "by_version": dict(by_version),
            "total": len(docs),
            "no_version": no_version,
        }

    # -------------------------------------------------------------------------
    # Volume over time (time-series bucketing)
    # -------------------------------------------------------------------------

    def get_volume_over_time(
        self,
        time_range: Any,
        bucket_hours: int = 1,
    ) -> Dict[str, Any]:
        """
        Bucket document volumes into time intervals for time-series charting.

        Args:
            time_range:   ``TimeRange`` instance.
            bucket_hours: Width of each bucket in hours (default 1).

        Returns:
            ``{
                "buckets": [
                    {
                        "start": str,     # ISO 8601
                        "end": str,
                        "total": int,
                        "completed": int,
                        "failed": int,
                    }
                ],
                "bucket_hours": int,
            }``
        """
        from datetime import datetime, timedelta, timezone

        docs = self._fetch_all_documents(
            start_date_time=time_range.start_time,
            end_date_time=time_range.end_time,
        )

        start_dt, end_dt = time_range.to_datetimes()
        bucket_delta = timedelta(hours=bucket_hours)
        buckets: List[Dict[str, Any]] = []

        current = start_dt
        while current < end_dt:
            bucket_end = min(current + bucket_delta, end_dt)
            bucket_start_iso = current.isoformat()
            bucket_end_iso = bucket_end.isoformat()

            total = 0
            completed = 0
            failed = 0
            for doc in docs:
                doc_time_str = (
                    doc.queued_time
                    or doc.start_time
                    or getattr(doc, "initial_event_time", None)
                )
                if not doc_time_str:
                    continue
                try:
                    doc_time_str_clean = doc_time_str.replace("Z", "+00:00")
                    doc_dt = datetime.fromisoformat(doc_time_str_clean)
                    if doc_dt.tzinfo is None:
                        doc_dt = doc_dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                if current <= doc_dt < bucket_end:
                    total += 1
                    if doc.status == Status.COMPLETED:
                        completed += 1
                    elif doc.status == Status.FAILED:
                        failed += 1

            buckets.append(
                {
                    "start": bucket_start_iso,
                    "end": bucket_end_iso,
                    "total": total,
                    "completed": completed,
                    "failed": failed,
                }
            )
            current = bucket_end

        return {"buckets": buckets, "bucket_hours": bucket_hours}

    # -------------------------------------------------------------------------
    # Recent failures
    # -------------------------------------------------------------------------

    def get_recent_failures(
        self,
        time_range: Any,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """
        Return a list of recently failed documents within the time range.

        Args:
            time_range: ``TimeRange`` instance.
            limit:      Maximum number of failed documents to return (default 10).

        Returns:
            ``{
                "failures": [
                    {
                        "document_id": str,
                        "status": str,
                        "classification": str | None,
                        "timestamp": str,          # completion_time or start_time
                        "num_pages": int,
                        "error_message": str | None,
                        "stage": str | None,
                    }
                ],
                "total_failed": int,
                "limit": int,
            }``
        """
        docs = self._fetch_all_documents(
            start_date_time=time_range.start_time,
            end_date_time=time_range.end_time,
        )

        failed_docs = [d for d in docs if d.status == Status.FAILED]

        def _doc_timestamp(doc: Any) -> str:
            # Prefer completion_time (when failure occurred), fall back to others
            return (
                getattr(doc, "completion_time", "")
                or getattr(doc, "queued_time", "")
                or getattr(doc, "start_time", "")
                or ""
            )

        failed_docs.sort(key=_doc_timestamp, reverse=True)
        total_failed = len(failed_docs)
        failed_docs = failed_docs[:limit]

        # ── Enrich failed docs with full attributes from base table ──────
        # The GSI (TypeDateIndex) does NOT project Metering, Sections, Pages,
        # or Errors. Do a follow-up GetItem for each failed doc to get full data.
        enriched_docs = []
        for doc in failed_docs:
            object_key = getattr(doc, "input_key", None) or getattr(doc, "id", None)
            if object_key:
                try:
                    full_doc = self._db.get_document(object_key)
                    if full_doc:
                        enriched_docs.append(full_doc)
                        continue
                except Exception as e:
                    logger.debug("Failed to enrich doc %s: %s", object_key, e)
            enriched_docs.append(doc)
        failed_docs = enriched_docs

        failures = []
        for doc in failed_docs:
            classification = None
            if doc.sections:
                classification = doc.sections[0].classification

            # ── Extract error message from multiple sources ──────────────
            error_message = None
            # 1. Check doc.errors list (List[str]) — primary error source
            errors_list = getattr(doc, "errors", None)
            if errors_list and isinstance(errors_list, list) and len(errors_list) > 0:
                error_message = "; ".join(str(e) for e in errors_list if e)
            # 2. Check metering dict for error_message or error key
            if not error_message and isinstance(getattr(doc, "metering", None), dict):
                error_message = (
                    doc.metering.get("error_message")
                    or doc.metering.get("error")
                    or None
                )
            # 3. Check metering dict keys for step-level errors
            if not error_message and isinstance(getattr(doc, "metering", None), dict):
                for key, val in doc.metering.items():
                    if isinstance(val, dict) and val.get("error"):
                        error_message = val["error"]
                        break
            # 4. Check top-level error_message attribute (some models)
            if not error_message:
                top_level = getattr(doc, "error_message", None)
                if isinstance(top_level, str) and top_level:
                    error_message = top_level
            # 5. Check raw DynamoDB item for common error fields
            if not error_message:
                raw = getattr(doc, "raw", None) or {}
                error_message = (
                    raw.get("ErrorMessage")
                    or raw.get("Error")
                    or raw.get("FailureReason")
                    or raw.get("StepFunctionError")
                    or None
                )
            # ── Extract failed stage from metering or metadata ───────────
            stage = None
            # 1. Check metadata dict for failed_step / stage info
            metadata = getattr(doc, "metadata", None) or {}
            if isinstance(metadata, dict):
                stage = (
                    metadata.get("failed_step") or metadata.get("failed_stage") or None
                )
            # 2. Try to infer from metering keys (last step with duration = failure point)
            if stage is None and isinstance(getattr(doc, "metering", None), dict):
                # First check for explicit error entries
                for key, val in doc.metering.items():
                    if isinstance(val, dict) and val.get("error"):
                        stage = key.split("/")[0]
                        break
                # If no error entry, the last metering key is likely the failed step
                if stage is None and doc.metering:
                    last_step = None
                    for key in doc.metering.keys():
                        step_name = key.split("/")[0]
                        if step_name and step_name not in ("total",):
                            last_step = step_name
                    stage = last_step
            # 3. Check raw DynamoDB item if available
            if stage is None:
                raw = getattr(doc, "raw", None) or {}
                if isinstance(raw, dict):
                    stage = raw.get("FailedStep") or raw.get("FailedStage") or None

            # 6. Fallback: generate descriptive error message from context
            if not error_message and stage:
                error_message = f"Processing failed during {stage} step"
            elif not error_message:
                error_message = "Processing failed (no error details available)"

            # ── Determine best timestamp (when the failure occurred) ─────
            timestamp = (
                getattr(doc, "completion_time", "")
                or getattr(doc, "queued_time", "")
                or getattr(doc, "start_time", "")
                or None
            )
            # Also check raw item for CompletionTime
            if not timestamp:
                timestamp = (
                    raw.get("CompletionTime") or raw.get("WorkflowStartTime") or None
                )

            failures.append(
                {
                    "document_id": getattr(doc, "id", None)
                    or getattr(doc, "document_id", None)
                    or getattr(doc, "pk", None),
                    "status": doc.status.value
                    if hasattr(doc.status, "value")
                    else str(doc.status),
                    "classification": classification,
                    "timestamp": timestamp,
                    "num_pages": doc.num_pages or 0,
                    "error_message": error_message,
                    "stage": stage,
                    "config_version": getattr(doc, "config_version", None),
                }
            )

        return {
            "failures": failures,
            "total_failed": total_failed,
            "limit": limit,
        }

    # -------------------------------------------------------------------------
    # Active config info
    # -------------------------------------------------------------------------

    def get_active_config_info(self) -> Dict[str, Any]:
        """
        Return metadata about the currently active IDP configuration.

        Returns:
            ``{
                "active_version": str | None,
                "document_class_count": int,
                "versions_available": int,
                "versions": [{"version": str, "description": str, ...}],
            }``
        """
        try:
            from idp_common.config import ConfigurationManager

            mgr = ConfigurationManager()
            versions = mgr.list_config_versions()
            config = mgr.get_merged_configuration(version="")  # active version

            doc_class_count = 0
            active_version = None
            if config:
                active_version = getattr(config, "version", None)
                classification_cfg = getattr(config, "classification", None)
                if classification_cfg:
                    classes = getattr(classification_cfg, "document_classes", [])
                    doc_class_count = len(classes) if classes else 0

            return {
                "active_version": active_version,
                "document_class_count": doc_class_count,
                "versions_available": len(versions) if versions else 0,
                "versions": versions or [],
            }
        except Exception as exc:
            logger.warning("Failed to retrieve active config info: %s", exc)
            return {
                "active_version": None,
                "document_class_count": 0,
                "versions_available": 0,
                "versions": [],
            }
