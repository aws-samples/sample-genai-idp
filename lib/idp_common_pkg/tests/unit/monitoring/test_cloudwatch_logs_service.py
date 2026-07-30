# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for idp_common.monitoring.cloudwatch_logs_service.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from idp_common.monitoring.cloudwatch_logs_service import (
    _build_filter_pattern,
    _extract_function_type,
    _prioritize_log_groups,
    _should_exclude_log_event,
    _truncate_message,
    get_stack_log_groups,
    prioritize_performance_log_groups,
    reset_settings_cache,
    search_by_document_fallback,
    search_log_group,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cw_client(events: list[dict] | None = None, raise_not_found: bool = False):
    """Return a mock boto3 CloudWatch Logs client."""
    client = MagicMock()
    if raise_not_found:
        client.filter_log_events.side_effect = (
            client.exceptions.ResourceNotFoundException(
                {
                    "Error": {
                        "Code": "ResourceNotFoundException",
                        "Message": "Not found",
                    }
                },
                "filter_log_events",
            )
        )
        client.exceptions.ResourceNotFoundException = type(
            "ResourceNotFoundException", (Exception,), {}
        )
    else:
        client.filter_log_events.return_value = {"events": events or []}
    return client


# ---------------------------------------------------------------------------
# _truncate_message
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTruncateMessage:
    def test_short_message_unchanged(self):
        msg = "short error"
        assert _truncate_message(msg, max_length=400) == msg

    def test_long_message_truncated(self):
        msg = "A" * 600
        result = _truncate_message(msg, max_length=400)
        assert result.endswith("... [truncated]")
        assert len(result) == 400 + len("... [truncated]")
        assert result.startswith("A" * 400)

    def test_exact_boundary_not_truncated(self):
        msg = "B" * 400
        assert _truncate_message(msg, max_length=400) == msg

    def test_custom_max_length(self):
        msg = "C" * 200
        result = _truncate_message(msg, max_length=100)
        assert result.endswith("... [truncated]")
        assert result.startswith("C" * 100)


# ---------------------------------------------------------------------------
# _should_exclude_log_event
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestShouldExcludeLogEvent:
    def test_excludes_info_when_error_filter(self):
        assert _should_exclude_log_event("[INFO] all good", "ERROR") is True

    def test_excludes_start_report(self):
        assert _should_exclude_log_event("START RequestId: abc", "ERROR") is True
        assert _should_exclude_log_event("END RequestId: abc", "ERROR") is True
        assert _should_exclude_log_event("REPORT Duration: 100ms", "ERROR") is True

    def test_keeps_error_message(self):
        assert _should_exclude_log_event("[ERROR] extraction failed", "ERROR") is False

    def test_no_filter_keeps_info(self):
        """Without a filter pattern, INFO lines are not excluded."""
        assert _should_exclude_log_event("[INFO] all good", "") is False

    def test_excludes_sample_json_noise(self):
        assert _should_exclude_log_event('data: {"sample_json": true}', "") is True

    def test_long_message_not_excluded(self):
        """Long messages must NOT be excluded — they are truncated instead."""
        long_error = "[ERROR] " + "x" * 2000
        assert _should_exclude_log_event(long_error, "ERROR") is False


# ---------------------------------------------------------------------------
# _build_filter_pattern
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildFilterPattern:
    def test_no_request_id_uses_base(self):
        assert _build_filter_pattern("ERROR") == "ERROR"

    def test_no_request_id_empty_base(self):
        assert _build_filter_pattern("") == ""

    def test_request_id_uses_base_if_present(self):
        assert _build_filter_pattern("WARN", "req-123") == "WARN"

    def test_request_id_defaults_to_error(self):
        assert _build_filter_pattern("", "req-abc") == "ERROR"


# ---------------------------------------------------------------------------
# _extract_function_type
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractFunctionType:
    def test_classification_function(self):
        name = "DEV-P2-EA8-STACK-ClassificationFunction-abc123"
        assert _extract_function_type(name) == "ClassificationFunction"

    def test_queue_processor(self):
        name = "DEV-P2-EA8-QueueProcessor-xyz"
        assert _extract_function_type(name) == "QueueProcessor"

    def test_ocr_function(self):
        name = "DEV-P2-STACK-1H-OCRFunction-EQ6aqm"
        assert _extract_function_type(name) == "OCRFunction"

    def test_empty_string(self):
        assert _extract_function_type("") == ""

    def test_no_known_suffix(self):
        assert _extract_function_type("some-random-name") == ""


# ---------------------------------------------------------------------------
# _prioritize_log_groups
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrioritizeLogGroups:
    _groups = [
        {"name": "/aws/lambda/QueueProcessor"},
        {"name": "/aws/lambda/ClassificationFunction"},
        {"name": "/aws/lambda/ExtractionFunction"},
        {"name": "/aws/lambda/WorkflowTracker"},
    ]

    def test_failed_status_puts_classification_first(self):
        result = _prioritize_log_groups(self._groups, "FAILED")
        names = [g["name"] for g in result]
        assert names.index("/aws/lambda/ClassificationFunction") < names.index(
            "/aws/lambda/QueueProcessor"
        )

    def test_in_progress_status_puts_processor_first(self):
        result = _prioritize_log_groups(self._groups, "IN_PROGRESS")
        names = [g["name"] for g in result]
        assert names.index("/aws/lambda/QueueProcessor") < names.index(
            "/aws/lambda/ClassificationFunction"
        )

    def test_default_status(self):
        result = _prioritize_log_groups(self._groups, None)
        assert len(result) == len(self._groups)

    def test_all_groups_present(self):
        result = _prioritize_log_groups(self._groups, "FAILED")
        assert len(result) == len(self._groups)


# ---------------------------------------------------------------------------
# prioritize_performance_log_groups
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrioritizePerformanceLogGroups:
    def test_processor_first(self):
        groups = [
            {"name": "/aws/lambda/QueueSender"},
            {"name": "/aws/lambda/QueueProcessor"},
            {"name": "/aws/lambda/WorkflowTracker"},
        ]
        result = prioritize_performance_log_groups(groups)
        names = [g["name"] for g in result]
        assert names.index("/aws/lambda/QueueProcessor") < names.index(
            "/aws/lambda/QueueSender"
        )


# ---------------------------------------------------------------------------
# search_log_group
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchLogGroup:
    def test_returns_events(self):
        raw_events = [
            {
                "message": "[ERROR] extraction failed",
                "timestamp": int(datetime.now().timestamp() * 1000),
                "logStreamName": "stream-1",
            }
        ]
        with patch("idp_common.monitoring.cloudwatch_logs_service.boto3") as mock_boto3:
            mock_client = _make_cw_client(events=raw_events)
            mock_boto3.client.return_value = mock_client

            result = search_log_group(
                log_group_name="/aws/lambda/test",
                filter_pattern="ERROR",
                max_events=5,
            )

        assert result["events_found"] == 1
        assert "[ERROR]" in result["events"][0]["message"]

    def test_truncates_long_message(self):
        long_message = "[ERROR] " + "x" * 1000
        raw_events = [
            {
                "message": long_message,
                "timestamp": int(datetime.now().timestamp() * 1000),
                "logStreamName": "stream-1",
            }
        ]
        with patch("idp_common.monitoring.cloudwatch_logs_service.boto3") as mock_boto3:
            mock_client = _make_cw_client(events=raw_events)
            mock_boto3.client.return_value = mock_client

            result = search_log_group(
                log_group_name="/aws/lambda/test",
                filter_pattern="ERROR",
                max_events=5,
                log_message_max_length=400,
            )

        assert result["events_found"] == 1
        msg = result["events"][0]["message"]
        assert msg.endswith("... [truncated]")
        assert len(msg) == 400 + len("... [truncated]")

    def test_not_found_returns_empty(self):
        with patch("idp_common.monitoring.cloudwatch_logs_service.boto3") as mock_boto3:
            mock_client = MagicMock()
            exc_type = type("ResourceNotFoundException", (Exception,), {})
            mock_client.exceptions.ResourceNotFoundException = exc_type
            mock_client.filter_log_events.side_effect = exc_type("not found")
            mock_boto3.client.return_value = mock_client

            result = search_log_group("/aws/lambda/missing", max_events=5)

        assert result["events_found"] == 0
        assert result["events"] == []

    def test_filters_info_noise_when_error_filter(self):
        raw_events = [
            {
                "message": "[INFO] all good",
                "timestamp": int(datetime.now().timestamp() * 1000),
                "logStreamName": "stream",
            },
            {
                "message": "[ERROR] bad thing",
                "timestamp": int(datetime.now().timestamp() * 1000),
                "logStreamName": "stream",
            },
        ]
        with patch("idp_common.monitoring.cloudwatch_logs_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = _make_cw_client(events=raw_events)
            result = search_log_group("/g", filter_pattern="ERROR", max_events=10)

        assert result["events_found"] == 1
        assert "[ERROR]" in result["events"][0]["message"]


# ---------------------------------------------------------------------------
# get_stack_log_groups (SSM integration)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetStackLogGroups:
    def test_returns_groups_from_settings(self):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.return_value = {
            "Parameter": {
                "Value": '{"CloudWatchLogGroups": "/aws/lambda/A,/aws/lambda/B"}'
            }
        }
        import os

        with patch.dict(os.environ, {"SETTINGS_PARAMETER_NAME": "test-param"}):
            reset_settings_cache(ttl_seconds=300, ssm_client=mock_ssm)
            groups = get_stack_log_groups()

        assert len(groups) == 2
        names = [g["name"] for g in groups]
        assert "/aws/lambda/A" in names
        assert "/aws/lambda/B" in names

    def test_returns_empty_when_no_settings(self):
        mock_ssm = MagicMock()
        mock_ssm.get_parameter.side_effect = Exception("not found")
        import os

        with patch.dict(os.environ, {"SETTINGS_PARAMETER_NAME": "test-param"}):
            reset_settings_cache(ttl_seconds=300, ssm_client=mock_ssm)
            groups = get_stack_log_groups()

        assert groups == []


# ---------------------------------------------------------------------------
# search_by_document_fallback
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchByDocumentFallback:
    def test_finds_error_events(self):
        raw_events = [
            {
                "message": "[ERROR] failed to process report-pdf",
                "timestamp": int(datetime.now().timestamp() * 1000),
                "logStreamName": "stream",
            }
        ]
        groups = [{"name": "/aws/lambda/ExtractionFunction"}]
        time_window = {
            "start_time": datetime.now() - timedelta(hours=1),
            "end_time": datetime.now(),
        }

        with patch("idp_common.monitoring.cloudwatch_logs_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = _make_cw_client(events=raw_events)
            result = search_by_document_fallback(
                document_id="report.pdf",
                groups_to_search=groups,
                time_window=time_window,
                max_log_events=5,
            )

        assert result["total_events"] == 1
        assert result["search_method_used"] == "document_specific_fallback"

    def test_skips_non_error_events(self):
        raw_events = [
            {
                "message": "Processing report-pdf successfully",
                "timestamp": int(datetime.now().timestamp() * 1000),
                "logStreamName": "stream",
            }
        ]
        groups = [{"name": "/aws/lambda/ExtractionFunction"}]
        time_window = {
            "start_time": datetime.now() - timedelta(hours=1),
            "end_time": datetime.now(),
        }

        with patch("idp_common.monitoring.cloudwatch_logs_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = _make_cw_client(events=raw_events)
            result = search_by_document_fallback(
                document_id="report.pdf",
                groups_to_search=groups,
                time_window=time_window,
                max_log_events=5,
            )

        assert result["total_events"] == 0
        assert result["search_method_used"] == "none"
