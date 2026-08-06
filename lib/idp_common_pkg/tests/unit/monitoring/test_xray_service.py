# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for idp_common.monitoring.xray_service
"""

import json
from unittest.mock import MagicMock, patch

import pytest

import idp_common.monitoring.xray_service as xray_module
from idp_common.monitoring.xray_service import (
    analyze_trace,
    extract_lambda_request_ids,
    get_subsegment_details,
    get_trace_for_document,
)


# ---------------------------------------------------------------------------
# Reset module-level boto3 client/resource cache between tests
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_xray_client():
    """Reset the module-level _xray_client and _dynamodb_resource singletons."""
    xray_module._xray_client = None
    xray_module._dynamodb_resource = None
    yield
    xray_module._xray_client = None
    xray_module._dynamodb_resource = None


# ---------------------------------------------------------------------------
# Shared test data helpers
# ---------------------------------------------------------------------------

_TRACE_ID = "1-abc12345-abcdef123456789012345678"
_DOC_ID = "test_doc.pdf"


def _make_segment_doc(
    name: str = "my-lambda",
    start: float = 1000.0,
    end: float = 1002.0,
    has_error: bool = False,
    subsegments: list = None,
    origin: str = "",
) -> dict:
    doc = {
        "id": f"seg-{name}",
        "name": name,
        "start_time": start,
        "end_time": end,
        "error": has_error,
        "fault": False,
        "origin": origin,
    }
    if subsegments:
        doc["subsegments"] = subsegments
    return doc


def _make_xray_response(segments: list) -> dict:
    return {
        "Traces": [{"Segments": [{"Document": json.dumps(seg)} for seg in segments]}]
    }


# ---------------------------------------------------------------------------
# get_trace_for_document
# ---------------------------------------------------------------------------


class TestGetTraceForDocument:
    def test_returns_trace_from_document_record(self):
        doc_record = {"TraceId": _TRACE_ID}
        result = get_trace_for_document(_DOC_ID, document_record=doc_record)
        assert result is not None
        assert result["trace_id"] == _TRACE_ID
        assert result["source"] == "document_record"

    def test_returns_none_gracefully_when_no_trace(self, monkeypatch):
        monkeypatch.delenv("TRACKING_TABLE_NAME", raising=False)

        mock_xray = MagicMock()
        mock_xray.get_trace_summaries.return_value = {"TraceSummaries": []}

        with patch("idp_common.monitoring.xray_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_xray
            mock_boto3.resource.return_value = MagicMock()
            result = get_trace_for_document(_DOC_ID)

        assert result is None

    def test_falls_back_to_xray_annotation_query(self, monkeypatch):
        monkeypatch.delenv("TRACKING_TABLE_NAME", raising=False)

        mock_xray = MagicMock()
        mock_xray.get_trace_summaries.return_value = {
            "TraceSummaries": [{"Id": _TRACE_ID}]
        }

        with patch("idp_common.monitoring.xray_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_xray
            result = get_trace_for_document(_DOC_ID)

        assert result is not None
        assert result["trace_id"] == _TRACE_ID
        assert result["source"] == "xray_annotation"

    def test_document_record_trace_id_skips_api_calls(self):
        """When document_record has TraceId, no AWS API calls should be made."""
        doc_record = {"TraceId": _TRACE_ID}

        with patch("idp_common.monitoring.xray_service.boto3") as mock_boto3:
            result = get_trace_for_document(_DOC_ID, document_record=doc_record)
            mock_boto3.client.assert_not_called()

        assert result["trace_id"] == _TRACE_ID

    def test_returns_none_when_xray_api_raises(self, monkeypatch):
        monkeypatch.delenv("TRACKING_TABLE_NAME", raising=False)

        mock_xray = MagicMock()
        mock_xray.get_trace_summaries.side_effect = Exception("X-Ray throttled")

        with patch("idp_common.monitoring.xray_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_xray
            result = get_trace_for_document(_DOC_ID)

        assert result is None


# ---------------------------------------------------------------------------
# analyze_trace
# ---------------------------------------------------------------------------


class TestAnalyzeTrace:
    def test_returns_correct_segment_count(self):
        segs = [
            _make_segment_doc("fn-1", 1000, 1002),
            _make_segment_doc("fn-2", 1002, 1005),
        ]
        mock_xray = MagicMock()
        mock_xray.batch_get_traces.return_value = _make_xray_response(segs)

        with patch("idp_common.monitoring.xray_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_xray
            result = analyze_trace(_TRACE_ID)

        assert result["total_segments"] == 2
        assert result["trace_id"] == _TRACE_ID

    def test_detects_error_segments(self):
        segs = [
            _make_segment_doc("good-fn", 1000, 1001, has_error=False),
            _make_segment_doc("bad-fn", 1001, 1002, has_error=True),
        ]
        mock_xray = MagicMock()
        mock_xray.batch_get_traces.return_value = _make_xray_response(segs)

        with patch("idp_common.monitoring.xray_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_xray
            result = analyze_trace(_TRACE_ID)

        assert len(result["error_segments"]) == 1
        assert result["error_segments"][0]["name"] == "bad-fn"
        assert result["has_performance_issues"] is True

    def test_detects_slow_segments(self):
        # 6 seconds > default 5s threshold
        segs = [_make_segment_doc("slow-fn", 1000.0, 1006.0)]
        mock_xray = MagicMock()
        mock_xray.batch_get_traces.return_value = _make_xray_response(segs)

        with patch("idp_common.monitoring.xray_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_xray
            result = analyze_trace(_TRACE_ID)

        assert len(result["slow_segments"]) == 1
        assert result["slow_segments"][0]["duration_ms"] == pytest.approx(6000.0)

    def test_returns_error_dict_when_no_trace_found(self):
        mock_xray = MagicMock()
        mock_xray.batch_get_traces.return_value = {"Traces": []}

        with patch("idp_common.monitoring.xray_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_xray
            result = analyze_trace(_TRACE_ID)

        assert "error" in result
        assert result["total_segments"] == 0

    def test_handles_xray_throttle_gracefully(self):
        mock_xray = MagicMock()
        mock_xray.batch_get_traces.side_effect = Exception("Throttled by X-Ray")

        with patch("idp_common.monitoring.xray_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_xray
            result = analyze_trace(_TRACE_ID)

        # Should return error dict, not raise
        assert "error" in result

    def test_service_timeline_is_sorted_by_start_time(self):
        segs = [
            _make_segment_doc("fn-b", 1002, 1004),
            _make_segment_doc("fn-a", 1000, 1002),
        ]
        mock_xray = MagicMock()
        mock_xray.batch_get_traces.return_value = _make_xray_response(segs)

        with patch("idp_common.monitoring.xray_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_xray
            result = analyze_trace(_TRACE_ID)

        timeline = result["service_timeline"]
        assert timeline[0]["service_name"] == "fn-a"
        assert timeline[1]["service_name"] == "fn-b"

    def test_total_duration_ms_calculated(self):
        segs = [
            _make_segment_doc("fn-1", 1000.0, 1003.5),
        ]
        mock_xray = MagicMock()
        mock_xray.batch_get_traces.return_value = _make_xray_response(segs)

        with patch("idp_common.monitoring.xray_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_xray
            result = analyze_trace(_TRACE_ID)

        assert result["total_duration_ms"] == pytest.approx(3500.0)


# ---------------------------------------------------------------------------
# get_subsegment_details
# ---------------------------------------------------------------------------


class TestGetSubsegmentDetails:
    def _make_seg_with_subsegments(self):
        return {
            "id": "root",
            "name": "root-fn",
            "start_time": 1000.0,
            "end_time": 1005.0,
            "subsegments": [
                {
                    "name": "bedrock-call",
                    "start_time": 1001.0,
                    "end_time": 1003.0,
                    "error": False,
                    "fault": False,
                    "throttle": False,
                    "namespace": "aws",
                    "aws": {"service": "bedrock"},
                    "subsegments": [
                        {
                            "name": "bedrock-invoke",
                            "start_time": 1001.5,
                            "end_time": 1002.5,
                            "error": False,
                            "fault": False,
                            "throttle": False,
                            "namespace": "aws",
                            "aws": {},
                        }
                    ],
                }
            ],
        }

    def test_returns_all_subsegments_recursively(self):
        seg = self._make_seg_with_subsegments()
        mock_xray = MagicMock()
        mock_xray.batch_get_traces.return_value = {
            "Traces": [{"Segments": [{"Document": json.dumps(seg)}]}]
        }

        with patch("idp_common.monitoring.xray_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_xray
            result = get_subsegment_details(_TRACE_ID)

        assert len(result) == 2  # bedrock-call + bedrock-invoke
        names = [s["name"] for s in result]
        assert "bedrock-call" in names
        assert "bedrock-invoke" in names

    def test_filters_by_service_name(self):
        seg = self._make_seg_with_subsegments()
        mock_xray = MagicMock()
        mock_xray.batch_get_traces.return_value = {
            "Traces": [{"Segments": [{"Document": json.dumps(seg)}]}]
        }

        with patch("idp_common.monitoring.xray_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_xray
            result = get_subsegment_details(_TRACE_ID, service_name="bedrock-invoke")

        assert len(result) == 1
        assert result[0]["name"] == "bedrock-invoke"

    def test_sorted_by_start_time(self):
        seg = self._make_seg_with_subsegments()
        mock_xray = MagicMock()
        mock_xray.batch_get_traces.return_value = {
            "Traces": [{"Segments": [{"Document": json.dumps(seg)}]}]
        }

        with patch("idp_common.monitoring.xray_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_xray
            result = get_subsegment_details(_TRACE_ID)

        # bedrock-call starts at 1001.0, bedrock-invoke at 1001.5
        assert result[0]["start_time"] <= result[1]["start_time"]

    def test_returns_empty_list_when_no_trace(self):
        mock_xray = MagicMock()
        mock_xray.batch_get_traces.return_value = {"Traces": []}

        with patch("idp_common.monitoring.xray_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_xray
            result = get_subsegment_details(_TRACE_ID)

        assert result == []


# ---------------------------------------------------------------------------
# extract_lambda_request_ids
# ---------------------------------------------------------------------------


class TestExtractLambdaRequestIds:
    def _make_lambda_segment(
        self,
        name: str = "my-fn",
        origin: str = "AWS::Lambda",
        request_id: str = "req-abc123",
        resource_arn: str = "",
    ) -> dict:
        seg = {
            "name": name,
            "origin": origin,
            "aws": {"request_id": request_id},
        }
        if resource_arn:
            seg["resource_arn"] = resource_arn
        return seg

    def _make_trace_response(self, segments: list) -> dict:
        """Wrap raw segment dicts in the batch_get_traces response shape."""
        return {
            "Traces": [
                {"Segments": [{"Document": json.dumps(seg)} for seg in segments]}
            ]
        }

    def test_returns_function_name_to_request_id_mapping(self):
        seg = self._make_lambda_segment(name="classify-fn", request_id="req-001")
        mock_xray = MagicMock()
        mock_xray.batch_get_traces.return_value = self._make_trace_response([seg])

        with patch("idp_common.monitoring.xray_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_xray
            result = extract_lambda_request_ids(_TRACE_ID)

        assert result == {"classify-fn": "req-001"}

    def test_uses_resource_arn_name_when_present(self):
        """When resource_arn is present the function name is taken from the ARN."""
        seg = self._make_lambda_segment(
            name="arn-name-ignored",
            origin="AWS::Lambda",
            request_id="req-arn",
            resource_arn="arn:aws:lambda:us-east-1:123:function:real-fn-name",
        )
        mock_xray = MagicMock()
        mock_xray.batch_get_traces.return_value = self._make_trace_response([seg])

        with patch("idp_common.monitoring.xray_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_xray
            result = extract_lambda_request_ids(_TRACE_ID)

        assert "real-fn-name" in result
        assert result["real-fn-name"] == "req-arn"

    def test_handles_aws_lambda_function_origin(self):
        """AWS::Lambda::Function origin must also be captured."""
        seg = self._make_lambda_segment(
            name="fn-function-origin",
            origin="AWS::Lambda::Function",
            request_id="req-func",
        )
        mock_xray = MagicMock()
        mock_xray.batch_get_traces.return_value = self._make_trace_response([seg])

        with patch("idp_common.monitoring.xray_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_xray
            result = extract_lambda_request_ids(_TRACE_ID)

        assert "fn-function-origin" in result
        assert result["fn-function-origin"] == "req-func"

    def test_recursively_finds_lambda_in_subsegments(self):
        """Lambda segments nested inside another segment must be found."""
        root = {
            "name": "step-functions",
            "origin": "AWS::StepFunctions",
            "aws": {},
            "subsegments": [
                self._make_lambda_segment(name="nested-fn", request_id="req-nested")
            ],
        }
        mock_xray = MagicMock()
        mock_xray.batch_get_traces.return_value = self._make_trace_response([root])

        with patch("idp_common.monitoring.xray_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_xray
            result = extract_lambda_request_ids(_TRACE_ID)

        assert "nested-fn" in result
        assert result["nested-fn"] == "req-nested"

    def test_skips_entries_with_missing_request_id(self):
        """Segments with an empty request_id must not appear in the result."""
        seg = self._make_lambda_segment(name="fn-no-rid", request_id="")
        mock_xray = MagicMock()
        mock_xray.batch_get_traces.return_value = self._make_trace_response([seg])

        with patch("idp_common.monitoring.xray_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_xray
            result = extract_lambda_request_ids(_TRACE_ID)

        assert result == {}

    def test_returns_empty_dict_when_no_trace_found(self):
        mock_xray = MagicMock()
        mock_xray.batch_get_traces.return_value = {"Traces": []}

        with patch("idp_common.monitoring.xray_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_xray
            result = extract_lambda_request_ids(_TRACE_ID)

        assert result == {}

    def test_returns_empty_dict_when_api_raises(self):
        mock_xray = MagicMock()
        mock_xray.batch_get_traces.side_effect = Exception("X-Ray error")

        with patch("idp_common.monitoring.xray_service.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_xray
            result = extract_lambda_request_ids(_TRACE_ID)

        assert result == {}
