# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for idp_common.monitoring.models
"""

from datetime import datetime, timezone

import pytest

from idp_common.monitoring.models import (
    DocumentRecord,
    MonitoringKPIs,
    TimeRange,
    TraceSegment,
)

# ---------------------------------------------------------------------------
# TimeRange
# ---------------------------------------------------------------------------


class TestTimeRange:
    def test_last_n_hours_produces_correct_duration(self):
        tr = TimeRange.last_n_hours(24)
        assert tr.start_time < tr.end_time
        assert tr.duration_hours() == pytest.approx(24.0, abs=0.01)

    def test_last_n_hours_1_hour(self):
        tr = TimeRange.last_n_hours(1)
        assert tr.duration_hours() == pytest.approx(1.0, abs=0.01)

    def test_last_n_hours_strings_are_iso8601(self):
        tr = TimeRange.last_n_hours(6)
        # Both should be parseable ISO 8601 strings ending with 'Z'
        assert tr.start_time.endswith("Z")
        assert tr.end_time.endswith("Z")
        # Should be parseable
        datetime.strptime(tr.start_time, "%Y-%m-%dT%H:%M:%S.%fZ")
        datetime.strptime(tr.end_time, "%Y-%m-%dT%H:%M:%S.%fZ")

    def test_from_datetimes_naive_timestamps(self):
        start = datetime(2026, 1, 1, 0, 0, 0)
        end = datetime(2026, 1, 1, 6, 0, 0)
        tr = TimeRange.from_datetimes(start, end)
        assert tr.duration_hours() == pytest.approx(6.0, abs=0.01)

    def test_from_datetimes_aware_timestamps(self):
        start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        tr = TimeRange.from_datetimes(start, end)
        assert tr.duration_hours() == pytest.approx(12.0, abs=0.01)

    def test_to_datetimes_roundtrip(self):
        tr = TimeRange.last_n_hours(3)
        start, end = tr.to_datetimes()
        assert start.tzinfo is not None
        assert end.tzinfo is not None
        assert (end - start).total_seconds() == pytest.approx(3 * 3600, abs=5)

    def test_start_is_before_end(self):
        tr = TimeRange.last_n_hours(24)
        start, end = tr.to_datetimes()
        assert start < end


# ---------------------------------------------------------------------------
# DocumentRecord
# ---------------------------------------------------------------------------


class TestDocumentRecord:
    def _make_item(self, **overrides):
        base = {
            "PK": "doc#my_doc.pdf",
            "SK": "none",
            "ObjectStatus": "FAILED",
            "InitialEventTime": "2026-03-01T10:00:00Z",
            "StartTime": "2026-03-01T10:00:05Z",
            "CompletionTime": "2026-03-01T10:01:00Z",
            "WorkflowExecutionArn": "arn:aws:states:us-east-1:123:execution:MYSTACK-DocumentProcessingWorkflow:exec-1",
            "TraceId": "1-abc123",
            "NumPages": 5,
            "DocumentClass": "W2",
            "ConfigVersion": "v2",
        }
        base.update(overrides)
        return base

    def test_from_dynamodb_item_parses_object_key(self):
        rec = DocumentRecord.from_dynamodb_item(self._make_item())
        assert rec.object_key == "my_doc.pdf"

    def test_from_dynamodb_item_parses_status(self):
        rec = DocumentRecord.from_dynamodb_item(self._make_item())
        assert rec.status == "FAILED"

    def test_from_dynamodb_item_parses_timestamps(self):
        rec = DocumentRecord.from_dynamodb_item(self._make_item())
        assert rec.queued_time == "2026-03-01T10:00:00Z"
        assert rec.completion_time == "2026-03-01T10:01:00Z"

    def test_from_dynamodb_item_parses_arn(self):
        rec = DocumentRecord.from_dynamodb_item(self._make_item())
        assert "MYSTACK" in rec.workflow_execution_arn

    def test_from_dynamodb_item_parses_trace_id(self):
        rec = DocumentRecord.from_dynamodb_item(self._make_item())
        assert rec.trace_id == "1-abc123"

    def test_from_dynamodb_item_parses_num_pages(self):
        rec = DocumentRecord.from_dynamodb_item(self._make_item())
        assert rec.num_pages == 5

    def test_is_failed(self):
        rec = DocumentRecord.from_dynamodb_item(self._make_item(ObjectStatus="FAILED"))
        assert rec.is_failed() is True
        assert rec.is_completed() is False

    def test_is_completed(self):
        rec = DocumentRecord.from_dynamodb_item(
            self._make_item(ObjectStatus="COMPLETED")
        )
        assert rec.is_completed() is True
        assert rec.is_failed() is False

    def test_is_in_progress(self):
        rec = DocumentRecord.from_dynamodb_item(
            self._make_item(ObjectStatus="IN_PROGRESS")
        )
        assert rec.is_in_progress() is True
        assert rec.is_failed() is False

    def test_raw_preserved(self):
        item = self._make_item()
        rec = DocumentRecord.from_dynamodb_item(item)
        assert rec.raw is item

    def test_unknown_status_fallback(self):
        item = self._make_item()
        del item["ObjectStatus"]
        item["WorkflowStatus"] = "PENDING"
        rec = DocumentRecord.from_dynamodb_item(item)
        assert rec.status == "PENDING"

    def test_missing_status_defaults_to_unknown(self):
        item = self._make_item()
        del item["ObjectStatus"]
        rec = DocumentRecord.from_dynamodb_item(item)
        assert rec.status == "UNKNOWN"

    def test_num_pages_defaults_to_zero_when_missing(self):
        item = self._make_item()
        del item["NumPages"]
        rec = DocumentRecord.from_dynamodb_item(item)
        assert rec.num_pages == 0


# ---------------------------------------------------------------------------
# TraceSegment
# ---------------------------------------------------------------------------


class TestTraceSegment:
    def test_from_xray_document_basic(self):
        doc = {
            "id": "seg-1",
            "name": "my-lambda",
            "start_time": 1000.0,
            "end_time": 1002.5,
            "error": False,
            "fault": False,
        }
        seg = TraceSegment.from_xray_document(doc)
        assert seg.id == "seg-1"
        assert seg.name == "my-lambda"
        assert seg.duration_ms == pytest.approx(2500.0)
        assert seg.has_error is False
        assert seg.has_throttle is False

    def test_from_xray_document_with_error(self):
        doc = {
            "id": "seg-2",
            "name": "failing-lambda",
            "start_time": 1000.0,
            "end_time": 1001.0,
            "error": True,
            "fault": False,
            "cause": {"exceptions": [{"message": "ThrottlingException"}]},
        }
        seg = TraceSegment.from_xray_document(doc)
        assert seg.has_error is True
        assert seg.error_message == "ThrottlingException"

    def test_from_xray_document_with_fault(self):
        doc = {
            "id": "seg-3",
            "name": "broken-lambda",
            "start_time": 1000.0,
            "end_time": 1000.5,
            "error": False,
            "fault": True,
        }
        seg = TraceSegment.from_xray_document(doc)
        assert seg.has_error is True  # fault also sets has_error


# ---------------------------------------------------------------------------
# MonitoringKPIs
# ---------------------------------------------------------------------------


class TestMonitoringKPIs:
    def test_compute_derived_failure_rate(self):
        kpis = MonitoringKPIs(total_documents=100, failed_documents=10)
        kpis.compute_derived()
        assert kpis.failure_rate == pytest.approx(0.1)

    def test_compute_derived_avg_cost(self):
        kpis = MonitoringKPIs(total_documents=10, total_cost=5.0)
        kpis.compute_derived()
        assert kpis.avg_cost_per_document == pytest.approx(0.5)

    def test_compute_derived_zero_documents(self):
        kpis = MonitoringKPIs(total_documents=0, failed_documents=0)
        kpis.compute_derived()
        assert kpis.failure_rate == 0.0
        assert kpis.avg_cost_per_document == 0.0
