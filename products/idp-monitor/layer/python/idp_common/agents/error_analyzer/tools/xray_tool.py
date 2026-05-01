# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
X-Ray tools for tracing analysis and performance monitoring.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import boto3
from strands import tool

from ..config import (
    create_error_response,
    get_ea_param,
)

logger = logging.getLogger(__name__)

# Default X-Ray service graph look-back window (hours).
# Overridden at runtime by ErrorAnalyzerParameters.xray_analysis_hours (max 6).
_DEFAULT_XRAY_ANALYSIS_HOURS = 3


@tool
def analyze_document_trace(document_id: str) -> Dict[str, Any]:
    """
    Analyze document trace to identify performance issues and errors in processing workflow.

    Retrieves and analyzes X-Ray trace data for a document, providing detailed performance
    metrics, error analysis, and service timeline information.

    Use this tool to:
    - Analyze document processing performance
    - Identify errors and bottlenecks in document workflow
    - Get detailed service timeline and execution flow
    - Troubleshoot specific document processing issues

    Example usage:
    - "Analyze document trace for report.pdf"
    - "Check trace performance for lending_package.pdf"
    - "Show me the service timeline for document ABC123"
    - "Find bottlenecks in document processing trace"

    Args:
        document_id: The document ID to analyze (e.g., "report.pdf", "lending_package.pdf")

    Returns:
        Dict with keys:
        - document_id (str): The analyzed document identifier
        - trace_id (str): X-Ray trace ID if found
        - trace_found (bool): Whether trace data was located
        - detailed_analysis (dict): Performance and error analysis if trace found
        - service_timeline (list): Chronological service execution timeline if trace found
        - recommendations (list): Actionable troubleshooting recommendations
    """
    try:
        if not document_id:
            return create_error_response("No document ID provided")

        xray_client = boto3.client("xray")

        # Find trace ID for the document
        xray_trace_id = _find_trace_id_for_document(document_id, xray_client)
        if not xray_trace_id:
            return _create_trace_not_found_response(document_id)

        # Get and analyze trace data
        segments = _get_trace_segments(xray_client, xray_trace_id)
        if not segments:
            return create_error_response(
                f"Could not retrieve trace details for {xray_trace_id}"
            )

        # Analyze segments and build response
        detailed_analysis = _analyze_trace_segments(segments)
        service_timeline = _build_service_timeline(segments)

        return _build_trace_analysis_response(
            document_id=document_id,
            trace_id=xray_trace_id,
            trace_found=True,
            detailed_analysis=detailed_analysis,
            service_timeline=service_timeline,
        )

    except Exception as e:
        logger.error(f"Error analyzing document trace for {document_id}: {e}")
        return create_error_response(str(e))


@tool
def analyze_system_performance(
    stack_name: str = "", hours_back: int = 1
) -> Dict[str, Any]:
    """
    Analyze system performance issues focusing on stack-specific traces first, then general infrastructure.

    Intelligently identifies performance bottlenecks by prioritizing stack-specific analysis
    when stack information is available, otherwise performs general infrastructure analysis.

    Use this tool to:
    - Identify recent performance issues in the system
    - Find stack-specific errors and bottlenecks
    - Analyze service dependencies and error patterns
    - Troubleshoot system-wide performance degradation

    Example usage:
    - "Analyze system performance for the last 2 hours"
    - "Check performance issues for stack MyStack"
    - "Find system bottlenecks and slow services"
    - "Analyze infrastructure performance problems"

    Args:
        stack_name: CloudFormation stack name to focus analysis (optional)
        hours_back: Hours to look back for analysis (default: 1)

    Returns:
        Dict with keys:
        - analysis_type (str): "stack_focused" or "infrastructure_wide"
        - stack_name (str): Stack analyzed (if provided)
        - traces_found (int): Number of traces analyzed
        - services_found (int): Number of services analyzed
        - performance_issues (dict): Detailed performance analysis
        - recommendations (list): Actionable recommendations
    """
    try:
        # hours_back already has proper default
        xray_client = boto3.client("xray")

        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours_back)

        # Try stack-specific analysis first if stack_name provided
        if stack_name:
            stack_analysis = _analyze_stack_traces(
                xray_client, stack_name, start_time, end_time
            )
            if stack_analysis.get("traces_found", 0) > 0:
                # Get service map for additional context
                service_analysis = _analyze_service_performance(
                    xray_client, start_time, end_time
                )

                return _build_performance_analysis_response(
                    analysis_type="stack_focused",
                    stack_name=stack_name,
                    traces_found=stack_analysis["traces_found"],
                    services_found=service_analysis.get("services_found", 0),
                    performance_issues={
                        "stack_traces": stack_analysis,
                        "service_map": service_analysis,
                    },
                    recommendations=_generate_recommendations(
                        stack_analysis, service_analysis
                    ),
                )

        # Fallback to general infrastructure analysis
        service_analysis = _analyze_service_performance(
            xray_client, start_time, end_time
        )

        return _build_performance_analysis_response(
            analysis_type="infrastructure_wide",
            stack_name=stack_name if stack_name else "not_provided",
            traces_found=0,
            services_found=service_analysis.get("services_found", 0),
            performance_issues={"service_map": service_analysis},
            recommendations=_generate_recommendations(None, service_analysis),
        )

    except Exception as e:
        logger.error(f"Error in system performance analysis: {e}")
        return create_error_response(str(e))


def _build_performance_analysis_response(
    analysis_type: str,
    stack_name: str,
    traces_found: int,
    services_found: int,
    performance_issues: Dict[str, Any],
    recommendations: List[str],
) -> Dict[str, Any]:
    """
    Build unified performance analysis response with logging.
    """
    response: Dict[str, Any] = {
        "analysis_type": analysis_type,
        "stack_name": stack_name,
        "traces_found": traces_found,
        "services_found": services_found,
        "performance_issues": performance_issues,
        "recommendations": recommendations,
    }

    logger.info(f"System performance analysis response: {response}")
    return response


def _find_trace_id_for_document(document_id: str, xray_client) -> Optional[str]:
    """
    Find X-Ray trace ID for a document using DynamoDB lookup or X-Ray annotation query.
    """
    # Try DynamoDB first
    trace_id = _get_trace_id_from_dynamodb(document_id)
    if trace_id:
        return trace_id

    # Fallback to X-Ray annotation query
    return _get_trace_id_from_xray_annotations(document_id, xray_client)


def _get_trace_id_from_dynamodb(document_id: str) -> Optional[str]:
    """
    Get trace ID from DynamoDB tracking table.
    """
    tracking_table_name = os.environ.get("TRACKING_TABLE_NAME")
    if not tracking_table_name:
        return None

    try:
        dynamodb = boto3.resource("dynamodb")
        tracking_table = dynamodb.Table(tracking_table_name)  # type: ignore[attr-defined]

        response = tracking_table.get_item(
            Key={"PK": f"doc#{document_id}", "SK": "none"}
        )

        if "Item" in response:
            trace_id = response["Item"].get("TraceId")
            logger.info(f"TraceId: {trace_id} for document {document_id}")
            return trace_id

    except Exception as e:
        logger.warning(f"Could not retrieve trace_id from DynamoDB: {e}")

    return None


def _get_trace_id_from_xray_annotations(document_id: str, xray_client) -> Optional[str]:
    """
    Get trace ID using X-Ray annotation query.
    """
    logger.info(f"Searching X-Ray traces by annotation for document {document_id}")

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=24)

    response = xray_client.get_trace_summaries(
        StartTime=start_time,
        EndTime=end_time,
        FilterExpression=f'annotation.document_id = "{document_id}"',
    )

    traces = response.get("TraceSummaries", [])
    if traces:
        trace_id = traces[0].get("Id")
        logger.info(f"Found trace_id {trace_id} via annotation query")
        return trace_id

    return None


def _get_trace_segments(xray_client, trace_id: str) -> List[Dict[str, Any]]:
    """
    Get trace segments from X-Ray.
    """
    logger.info(f"Attempting to get trace details for trace_id: {trace_id}")

    segments_response = xray_client.batch_get_traces(TraceIds=[trace_id])
    logger.debug(f"X-Ray batch_get_traces response: {segments_response}")

    if not segments_response.get("Traces"):
        return []

    trace_data = segments_response["Traces"][0]
    return trace_data.get("Segments", [])


def _build_service_timeline(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build chronological service timeline from trace segments.
    """
    service_timeline = []

    for segment in segments:
        segment_doc = _parse_segment_document(segment.get("Document", {}))
        if not segment_doc:
            continue

        service_timeline.append(
            {
                "service_name": segment_doc.get("name"),
                "start_time": segment_doc.get("start_time"),
                "end_time": segment_doc.get("end_time"),
                "duration_ms": (
                    segment_doc.get("end_time", 0) - segment_doc.get("start_time", 0)
                )
                * 1000,
                "has_error": bool(segment_doc.get("error") or segment_doc.get("fault")),
                "annotations": segment_doc.get("annotations", {}),
            }
        )

    return sorted(service_timeline, key=lambda x: x.get("start_time", 0))


def _create_trace_not_found_response(document_id: str) -> Dict[str, Any]:
    """
    Create response when no trace is found for the document.
    """
    return _build_trace_analysis_response(
        document_id=document_id,
        trace_found=False,
        message="No X-Ray traces found for this document",
        recommendations=[
            "Verify document was processed recently (within 24 hours)",
            "Check if X-Ray tracing is enabled for all Lambda functions",
            "Ensure document ID is correct",
        ],
    )


def _build_trace_analysis_response(
    document_id: str,
    trace_found: bool,
    trace_id: Optional[str] = None,
    detailed_analysis: Optional[Dict[str, Any]] = None,
    service_timeline: Optional[List[Dict[str, Any]]] = None,
    message: Optional[str] = None,
    recommendations: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Build unified trace analysis response with logging.
    """
    response: Dict[str, Any] = {
        "document_id": document_id,
        "trace_found": trace_found,
    }

    if trace_id:
        response["trace_id"] = trace_id
    if detailed_analysis:
        response["detailed_analysis"] = detailed_analysis
    if service_timeline:
        response["service_timeline"] = service_timeline
    if message:
        response["message"] = message
    if not trace_found:
        response["traces_found"] = 0

    response["recommendations"] = recommendations or [
        "Review error segments for specific failure causes",
        "Check slow segments for performance optimization",
        "Analyze service timeline for bottlenecks",
    ]

    logger.info(f"X-Ray trace analysis response for {document_id}: {response}")
    return response


def extract_lambda_request_ids(xray_trace_id: str) -> Dict[str, str]:
    """
    Extract Lambda request IDs from X-Ray trace.

    Args:
        xray_trace_id: X-Ray trace ID

    Returns:
        Dict mapping Lambda function names to their CloudWatch request IDs
    """
    logger.info(f"Extracting Lambda request IDs from X-Ray trace: {xray_trace_id}")
    xray_client = boto3.client("xray")

    try:
        response = xray_client.batch_get_traces(TraceIds=[xray_trace_id])

        traces = response.get("Traces", [])
        if not traces:
            logger.warning(f"No traces found for trace ID: {xray_trace_id}")
            return {}

        lambda_executions = []
        for trace in traces:
            segments = trace.get("Segments", [])
            logger.info(
                f"Processing {len(segments)} segments for trace {xray_trace_id}"
            )

            for segment in segments:
                try:
                    segment_doc = json.loads(segment["Document"])
                    parsed_executions = _parse_segment_for_lambda(segment_doc)
                    lambda_executions.extend(parsed_executions)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse segment document: {e}")
                    continue

        logger.debug(f"Total Lambda executions found: {lambda_executions}")

        # Convert to function_name -> request_id mapping
        lambda_function_to_request_id_map = {}
        for execution in lambda_executions:
            if execution["request_id"]:
                lambda_function_to_request_id_map[execution["function_name"]] = (
                    execution["request_id"]
                )

        logger.info(
            f"Lambda function to request ID mapping: {lambda_function_to_request_id_map}"
        )
        return lambda_function_to_request_id_map

    except Exception as e:
        logger.error(f"Error extracting Lambda request IDs from {xray_trace_id}: {e}")
        return {}


def _extract_trace_summary(trace: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract key information from X-Ray trace summary.

    Args:
        trace: X-Ray trace summary dictionary

    Returns:
        Dict containing extracted trace information
    """
    return {
        "trace_id": trace.get("Id"),
        "duration": trace.get("Duration", 0),
        "response_time": trace.get("ResponseTime", 0),
        "has_error": trace.get("HasError", False),
        "has_fault": trace.get("HasFault", False),
        "has_throttle": trace.get("HasThrottle", False),
        "service_ids": [service.get("Name") for service in trace.get("ServiceIds", [])],
    }


def _parse_segment_document(segment_doc: Any) -> Dict[str, Any]:
    """
    Parse segment document from string or dict format.

    Args:
        segment_doc: Segment document (string or dict)

    Returns:
        Parsed segment document as dict
    """
    if isinstance(segment_doc, str):
        import json

        try:
            return json.loads(segment_doc)
        except json.JSONDecodeError:
            return {}
    return segment_doc or {}


def _analyze_trace_segments(segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze X-Ray trace segments to identify performance bottlenecks.

    Args:
        segments: List of X-Ray trace segments

    Returns:
        Dict containing segment analysis
    """
    if not segments:
        return {"error": "No trace segments available"}

    total_duration = 0
    error_segments = []
    slow_segments = []

    slow_threshold = get_ea_param("xray_slow_segment_threshold_ms", 5000)

    for segment in segments:
        segment_doc = _parse_segment_document(segment.get("Document", {}))
        if not segment_doc:
            continue

        duration = segment_doc.get("end_time", 0) - segment_doc.get("start_time", 0)
        total_duration += duration

        # Check for errors
        if segment_doc.get("error") or segment_doc.get("fault"):
            error_segments.append(
                {
                    "id": segment_doc.get("id"),
                    "name": segment_doc.get("name"),
                    "error": segment_doc.get("error"),
                    "fault": segment_doc.get("fault"),
                    "cause": segment_doc.get("cause", {}).get("exceptions", []),
                }
            )

        # Check for slow segments
        if duration * 1000 > slow_threshold:  # Convert to ms
            slow_segments.append(
                {
                    "id": segment_doc.get("id"),
                    "name": segment_doc.get("name"),
                    "duration_ms": duration * 1000,
                    "service": segment_doc.get("service", {}).get("name"),
                }
            )

    return {
        "total_segments": len(segments),
        "total_duration_ms": total_duration * 1000,
        "error_segments": error_segments,
        "slow_segments": slow_segments,
        "has_performance_issues": len(slow_segments) > 0 or len(error_segments) > 0,
    }


def _parse_segment_for_lambda(segment: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Recursively parse segment for Lambda executions.

    Args:
        segment: X-Ray segment document

    Returns:
        List of Lambda execution details
    """
    lambda_executions = []

    if segment.get("origin") == "AWS::Lambda":
        aws_info = segment.get("aws", {})
        function_name = segment.get("name", "Unknown")

        if "resource_arn" in segment:
            function_name = segment["resource_arn"].split(":")[-1]

        request_id = aws_info.get("request_id")
        lambda_executions.append(
            {
                "function_name": function_name,
                "request_id": request_id,
            }
        )

    # Recursively check subsegments
    subsegments = segment.get("subsegments", [])

    for subsegment in subsegments:
        lambda_executions.extend(_parse_segment_for_lambda(subsegment))

    return lambda_executions


def _analyze_stack_traces(
    xray_client, stack_name: str, start_time: datetime, end_time: datetime
) -> Dict[str, Any]:
    """
    Analyze X-Ray traces for a specific stack.
    """
    try:
        response = xray_client.get_trace_summaries(
            StartTime=start_time,
            EndTime=end_time,
            FilterExpression=f'annotation.stack_name = "{stack_name}"',
        )

        traces = response.get("TraceSummaries", [])

        if not traces:
            return {"traces_found": 0, "message": "No traces found for stack"}

        # Analyze trace summaries
        total_errors = sum(1 for trace in traces if trace.get("HasError"))
        total_faults = sum(1 for trace in traces if trace.get("HasFault"))
        total_throttles = sum(1 for trace in traces if trace.get("HasThrottle"))

        service_names = set()
        for trace in traces:
            for service in trace.get("ServiceIds", []):
                service_names.add(service.get("Name"))

        return {
            "traces_found": len(traces),
            "total_errors": total_errors,
            "total_faults": total_faults,
            "total_throttles": total_throttles,
            "services_involved": list(service_names),
            "error_rate": total_errors / len(traces) if traces else 0,
        }

    except Exception as e:
        logger.error(f"Error analyzing stack traces: {e}")
        return {"traces_found": 0, "error": str(e)}


def _analyze_service_performance(
    xray_client, start_time: datetime, end_time: datetime
) -> Dict[str, Any]:
    """
    Analyze X-Ray service map for performance issues.
    """
    try:
        # Resolve configurable X-Ray analysis hours from IDPConfig (cap at 6)
        xray_hours = min(
            get_ea_param("xray_analysis_hours", _DEFAULT_XRAY_ANALYSIS_HOURS),
            6,  # hard cap per X-Ray API constraint
        )

        # Clamp the time window to the configured maximum
        time_diff = end_time - start_time
        if time_diff > timedelta(hours=xray_hours):
            start_time = end_time - timedelta(hours=xray_hours)
            logger.info(
                "Time range limited to %d hours for X-Ray service graph analysis",
                xray_hours,
            )

        response = xray_client.get_service_graph(StartTime=start_time, EndTime=end_time)
        services = response.get("Services", [])

        if not services:
            return {"services_found": 0, "message": "No service map data available"}

        error_rate_threshold = get_ea_param("xray_error_rate_threshold", 0.05)
        response_time_threshold = get_ea_param("xray_response_time_threshold_ms", 10000)

        service_analysis = []
        high_error_services = []
        slow_services = []

        for service in services:
            service_stats = service.get("SummaryStatistics", {})
            error_rate = service_stats.get("ErrorStatistics", {}).get("ErrorRate", 0)
            response_time = service_stats.get("ResponseTimeHistogram", {}).get(
                "TotalTime", 0
            )
            request_count = service_stats.get("RequestCount", 0)

            analysis = {
                "name": service.get("Name"),
                "type": service.get("Type"),
                "request_count": request_count,
                "error_rate": error_rate,
                "response_time_ms": response_time * 1000,
                "edges": len(service.get("Edges", [])),
            }

            service_analysis.append(analysis)

            if error_rate > error_rate_threshold:
                high_error_services.append(analysis["name"])
            if response_time * 1000 > response_time_threshold:
                slow_services.append(analysis["name"])

        return {
            "services_found": len(services),
            "service_analysis": service_analysis,
            "high_error_services": high_error_services,
            "slow_services": slow_services,
        }

    except Exception as e:
        logger.error(f"Error analyzing service performance: {e}")
        return {"services_found": 0, "error": str(e)}


def _generate_recommendations(
    stack_analysis: Optional[Dict[str, Any]], service_analysis: Optional[Dict[str, Any]]
) -> List[str]:
    """
    Generate actionable recommendations based on analysis results.
    """
    recommendations = []

    if stack_analysis and stack_analysis.get("traces_found", 0) > 0:
        if stack_analysis.get("total_errors", 0) > 0:
            recommendations.append(
                "Review stack-specific error traces for failure patterns"
            )
        if stack_analysis.get("total_throttles", 0) > 0:
            recommendations.append(
                "Check stack services for throttling and capacity issues"
            )

    if service_analysis and service_analysis.get("services_found", 0) > 0:
        if service_analysis.get("high_error_services"):
            recommendations.append(
                f"Investigate high-error services: {', '.join(service_analysis['high_error_services'][:3])}"
            )
        if service_analysis.get("slow_services"):
            recommendations.append(
                f"Optimize slow services: {', '.join(service_analysis['slow_services'][:3])}"
            )

    if not recommendations:
        recommendations = [
            "Ensure X-Ray tracing is enabled for all services",
            "Check if services have been active in the time window",
            "Verify X-Ray daemon configuration",
        ]

    return recommendations
