# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Document-specific analysis tool.
"""

import logging
from typing import Any, Dict

from strands import tool

from ..config import (
    create_error_response,
    get_config_with_fallback,
    truncate_message,
)
from .cloudwatch_tools import search_document_logs
from .lambda_tools import get_document_context
from .stepfunction_tools import analyze_stepfunction_execution

logger = logging.getLogger(__name__)


def _truncate_log_results(log_results: Dict[str, Any], config: Dict[str, Any]) -> None:
    """
    Applies size constraints to log results to prevent context overflow.
    Applies configured limits to log events and message lengths to ensure
    the response stays within context size constraints.

    Args:
        log_results: Log search results dictionary to truncate
        config: Configuration dictionary with truncation limits
    """
    if not log_results or not log_results.get("results"):
        return

    # Cache config values once
    max_events_per_group = config.get("max_events_per_log_group", 3)
    max_message_length = config.get("max_log_message_length", 200)

    for result in log_results["results"]:
        events = result.get("events", [])
        result["events"] = events[:max_events_per_group]

        for event in result["events"]:
            message = event.get("message", "")
            event["message"] = truncate_message(message, max_message_length)


def _truncate_stepfunction_analysis(
    sf_analysis: Dict[str, Any], config: Dict[str, Any]
) -> None:
    """
    Applies size constraints to Step Function analysis to prevent overflow.
    Applies configured limits to timeline events and error message lengths
    to keep Step Function analysis within context constraints.

    Args:
        sf_analysis: Step Function analysis results to truncate
        config: Configuration dictionary with truncation limits
    """
    if not sf_analysis or sf_analysis.get("error"):
        return

    # Cache config values once
    max_timeline_events = config.get("max_stepfunction_timeline_events", 3)
    max_error_length = config.get("max_stepfunction_error_length", 150)

    timeline_analysis = sf_analysis.get("timeline_analysis", {})
    if "timeline" in timeline_analysis:
        timeline_analysis["timeline"] = timeline_analysis["timeline"][
            :max_timeline_events
        ]

    failure_point = timeline_analysis.get("failure_point")
    if failure_point and "details" in failure_point:
        details = failure_point["details"]
        for key in ["error", "cause"]:
            if key in details:
                details[key] = truncate_message(str(details[key]), max_error_length)


def _truncate_context_data(context: Dict[str, Any], config: Dict[str, Any]) -> None:
    """
    Truncate document context data to prevent overflow.
    Removes large response objects and applies limits to context data
    to optimize memory usage and response size.

    Args:
        context: Document context dictionary to truncate
        config: Configuration dictionary with limits
    """
    if "lookup_function_response" in context:
        del context["lookup_function_response"]


@tool
def analyze_document_failure(
    document_id: str, stack_name: str, max_log_events: int = 5
) -> Dict[str, Any]:
    """
    Perform comprehensive failure analysis for a specific document.
    Combines document context lookup, Step Function execution analysis, and targeted
    log searching to provide detailed insights into document processing failures.

    Args:
        document_id: Document ObjectKey to analyze
        stack_name: CloudFormation stack name
        max_log_events: Maximum log events to include (default: 5)

    Returns:
        Dict containing comprehensive document failure analysis
    """
    try:
        # Get document context via lookup function
        context = get_document_context(document_id, stack_name)

        if not context.get("document_found"):
            return create_error_response(
                context.get("error", "Document not found"),
                analysis_type="document_not_found",
                document_id=document_id,
                document_found=False,
                analysis_summary=f"Document '{document_id}' was not found in the tracking database",
                root_cause="The specified document could not be located in the system's tracking database",
                recommendations=[
                    "Verify the document filename is correct and matches exactly",
                    "Check if the document was successfully uploaded to the system",
                    "Ensure the document processing was initiated",
                    "Contact support if the document should exist in the system",
                ],
            )

        # Extract document details from context
        document_status = context.get("document_status")
        execution_arn = context.get("execution_arn")
        timestamps = context.get("timestamps", {})
        completion_time = timestamps.get("CompletionTime")

        # Analyze Step Function execution if available
        stepfunction_analysis = None
        if execution_arn:
            stepfunction_analysis = analyze_stepfunction_execution(execution_arn)

        # Get configuration with all limits applied
        config = get_config_with_fallback()

        # Use configured values, fallback to parameter if not in config
        configured_log_events = int(config.get("max_log_events", max_log_events))
        configured_log_groups = int(config.get("max_log_groups", 20))

        # Search document-specific logs using configured values
        log_results = search_document_logs(
            document_id=document_id,
            stack_name=stack_name,
            filter_pattern="ERROR",
            max_log_events=configured_log_events,
            max_log_groups=configured_log_groups,
        )

        # Truncate and limit data for context management
        _truncate_log_results(log_results, config)
        _truncate_stepfunction_analysis(stepfunction_analysis, config)
        _truncate_context_data(context, config)

        # Build analysis summary
        analysis_summary = (
            f"Document {document_id} failed with status {document_status}"
        )
        if completion_time:
            analysis_summary += f" at {completion_time}"

        # Add execution context to summary
        if execution_arn:
            analysis_summary += f". Execution: {execution_arn.split(':')[-1]}"

        # Enhance summary with Step Function analysis
        if stepfunction_analysis and not stepfunction_analysis.get("error"):
            sf_summary = stepfunction_analysis.get("analysis_summary", "")
            if sf_summary:
                analysis_summary += f". Workflow: {sf_summary}"

        # Build compact response to avoid context overflow
        response = {
            "analysis_type": "document_specific",
            "document_id": document_id,
            "document_found": True,
            "document_status": document_status,
            "completion_time": completion_time,
            "analysis_summary": analysis_summary,
            "recommendations": [
                "Review Step Function execution timeline for workflow failure points",
                "Check Lambda request IDs for detailed function-level errors",
                "Examine document-specific logs filtered by execution context",
                "Consider reprocessing the document if it was a transient error",
            ],
        }

        # Add optional fields only if they contain meaningful data
        if execution_arn:
            response["execution_arn"] = execution_arn

        if context.get("lambda_request_ids"):
            response["lambda_request_ids"] = context["lambda_request_ids"]

        # Include minimal Step Function data to prioritize logs
        if stepfunction_analysis and not stepfunction_analysis.get("error"):
            response["stepfunction_summary"] = {
                "status": stepfunction_analysis.get("execution_status"),
                "duration_seconds": stepfunction_analysis.get("duration_seconds"),
            }

        if log_results.get("results") and any(
            r.get("events") for r in log_results["results"]
        ):
            # Include all collected log data for comprehensive analysis
            response["log_summary"] = {
                "total_groups_searched": len(log_results.get("results", [])),
                "total_events_found": log_results.get("total_events_found", 0),
                "sample_errors": [
                    e["message"]
                    for r in log_results["results"]
                    for e in r.get("events", [])
                ],
            }

        return response

    except Exception as e:
        logger.error(f"Error analyzing document failure: {e}")
        return create_error_response(str(e))
