# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Shared data models for IDP monitoring services.

All monitoring features use these standard structures when passing data around,
ensuring consistent types across the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Explicit set of status values that represent an actively running document.
# Using an allowlist (rather than excluding terminal states) ensures that
# unrecognised values such as "UNKNOWN" or "" are never treated as in-progress.
_IN_PROGRESS_STATUSES: frozenset[str] = frozenset({"IN_PROGRESS", "RUNNING", "STARTED"})


@dataclass
class TimeRange:
    """
    A closed time interval expressed as ISO 8601 UTC strings.

    Example::

        tr = TimeRange.last_n_hours(24)
        print(tr.start_time)  # "2026-03-25T12:00:00.000000Z"
    """

    start_time: str  # ISO 8601, e.g. "2026-03-25T12:00:00.000000Z"
    end_time: str  # ISO 8601

    @classmethod
    def last_n_hours(cls, hours: int = 24) -> "TimeRange":
        """Return a TimeRange covering the last *hours* hours up to now (UTC)."""
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=hours)
        return cls(
            start_time=start.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            end_time=end.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        )

    @classmethod
    def from_datetimes(cls, start: datetime, end: datetime) -> "TimeRange":
        """Create a TimeRange from two datetime objects (converted to UTC)."""
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return cls(
            start_time=start.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            end_time=end.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        )

    def to_datetimes(self) -> tuple[datetime, datetime]:
        """Return (start, end) as timezone-aware datetime objects.

        Accepts timestamps with or without microseconds (e.g. both
        ``"2026-03-25T12:00:00Z"`` and ``"2026-03-25T12:00:00.123456Z"``).
        """

        def _parse(ts: str) -> datetime:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))

        return _parse(self.start_time), _parse(self.end_time)

    def duration_hours(self) -> float:
        """Return the duration of this time range in hours."""
        start, end = self.to_datetimes()
        return (end - start).total_seconds() / 3600


@dataclass
class LogEvent:
    """A single CloudWatch log event."""

    timestamp: str  # ISO 8601
    message: str
    log_group: str
    log_stream: str
    request_id: str = ""


@dataclass
class LogSearchResult:
    """Result of a CloudWatch log search across one or more log groups."""

    events: List[LogEvent] = field(default_factory=list)
    log_groups_searched: List[str] = field(default_factory=list)
    total_events: int = 0
    search_duration_ms: float = 0.0


@dataclass
class TraceSegment:
    """A single segment (or subsegment) within an AWS X-Ray trace."""

    id: str
    name: str
    start_time: float  # Unix epoch seconds
    end_time: float  # Unix epoch seconds
    duration_ms: float
    has_error: bool
    has_throttle: bool
    error_message: str = ""
    origin: str = ""  # e.g. "AWS::Lambda", "AWS::Bedrock"
    subsegments: List["TraceSegment"] = field(default_factory=list)

    @classmethod
    def from_xray_document(cls, doc: Dict[str, Any]) -> "TraceSegment":
        """Parse an X-Ray segment document dict into a TraceSegment."""
        start = doc.get("start_time", 0.0)
        end = doc.get("end_time", 0.0)
        duration_ms = (end - start) * 1000

        # Extract error message from cause block if present
        error_message = ""
        cause = doc.get("cause", {})
        if cause and isinstance(cause, dict):
            exceptions = cause.get("exceptions", [])
            if exceptions:
                error_message = exceptions[0].get("message", "")

        return cls(
            id=doc.get("id", ""),
            name=doc.get("name", ""),
            start_time=start,
            end_time=end,
            duration_ms=round(duration_ms, 1),
            has_error=bool(doc.get("error") or doc.get("fault")),
            has_throttle=bool(doc.get("throttle")),
            error_message=error_message,
            origin=doc.get("origin", ""),
        )


@dataclass
class DocumentRecord:
    """
    Represents a document processing record from the IDP tracking DynamoDB table.

    Field names follow the DynamoDB attribute naming used in the tracking table.
    """

    object_key: str  # S3 object key / document ID
    status: str  # COMPLETED | FAILED | IN_PROGRESS | ABORTED

    # Timestamps (ISO 8601 strings; empty string if not yet set)
    queued_time: str = ""
    start_time: str = ""
    completion_time: str = ""

    # Tracing
    workflow_execution_arn: str = ""
    trace_id: str = ""

    # Processing metadata
    num_pages: int = 0
    document_class: str = ""
    config_version: str = ""

    # Raw DynamoDB item (preserved for downstream access to any field)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dynamodb_item(cls, item: Dict[str, Any]) -> "DocumentRecord":
        """
        Construct a DocumentRecord from a raw DynamoDB tracking table item.

        Handles both camelCase DynamoDB attribute names (ObjectStatus,
        WorkflowExecutionArn, etc.) as stored in the table.
        """
        object_key = item.get("PK", "").replace("doc#", "") or item.get("ObjectKey", "")
        status = item.get("ObjectStatus") or item.get("WorkflowStatus") or "UNKNOWN"

        return cls(
            object_key=object_key,
            status=status,
            queued_time=item.get("InitialEventTime", ""),
            start_time=item.get("StartTime", ""),
            completion_time=item.get("CompletionTime", ""),
            workflow_execution_arn=(
                item.get("WorkflowExecutionArn") or item.get("ExecutionArn", "")
            ),
            trace_id=item.get("TraceId", ""),
            num_pages=int(item.get("NumPages", 0) or 0),
            document_class=item.get("DocumentClass", ""),
            config_version=item.get("ConfigVersion", ""),
            raw=item,
        )

    def is_failed(self) -> bool:
        """Return True if the document processing failed."""
        return self.status == "FAILED"

    def is_completed(self) -> bool:
        """Return True if the document was processed successfully."""
        return self.status == "COMPLETED"

    def is_in_progress(self) -> bool:
        """Return True if the document is currently being processed.

        Uses an explicit allowlist rather than an exclusion list so that
        unrecognised or default status values (e.g. ``"UNKNOWN"``, ``""``)
        are not mistakenly treated as active.
        """
        return self.status in _IN_PROGRESS_STATUSES


@dataclass
class MonitoringKPIs:
    """
    Aggregated key performance indicators for a monitoring time window.

    Used by the Dashboard Service and the UI monitoring page.
    """

    # Volume
    total_documents: int = 0
    total_pages: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    # Status breakdown
    completed_documents: int = 0
    failed_documents: int = 0
    in_progress_documents: int = 0
    aborted_documents: int = 0

    # Cost
    total_cost: float = 0.0
    avg_cost_per_document: float = 0.0

    # Health
    failure_rate: float = 0.0  # 0.0–1.0

    # Configuration
    active_config_count: int = 0

    def compute_derived(self) -> None:
        """Recompute failure_rate and avg_cost_per_document from raw counts.

        avg_cost_per_document is always (re-)assigned inside the
        ``total_documents > 0`` branch so that a subsequent call with
        ``total_cost = 0`` correctly resets it to 0.0 rather than leaving
        a stale non-zero value from a previous computation.
        """
        if self.total_documents > 0:
            self.failure_rate = self.failed_documents / self.total_documents
            self.avg_cost_per_document = (
                self.total_cost / self.total_documents if self.total_cost > 0 else 0.0
            )
        else:
            self.failure_rate = 0.0
            self.avg_cost_per_document = 0.0
