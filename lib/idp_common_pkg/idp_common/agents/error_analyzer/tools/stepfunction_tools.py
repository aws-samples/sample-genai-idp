# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Step Function tools for document-specific workflow execution analysis.
"""

import logging
from typing import Any, Dict, List, Optional

import boto3
from strands import tool

from ..config import (
    create_error_response,
    create_success_response,
    get_config_with_fallback,
)

logger = logging.getLogger(__name__)


def _extract_failure_details(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Failure parser: Extracts detailed error information from Step Function events.

    Extract detailed failure information from Step Function execution events.

    Parses different types of failure events to extract error messages, causes,
    and resource information for comprehensive failure analysis.

    Args:
        event: Step Function execution event dictionary

    Returns:
        Dict containing failure details or None if event is not a failure
    """
    event_type = event.get("type", "")

    failure_events = [
        "ExecutionFailed",
        "TaskFailed",
        "LambdaFunctionFailed",
        "TaskTimedOut",
        "ExecutionTimedOut",
    ]

    if event_type not in failure_events:
        return None

    details = {}

    # Extract error details based on event type
    if event_type == "ExecutionFailed":
        failure_detail = event.get("executionFailedEventDetails", {})
        details = {
            "error": failure_detail.get("error", "Unknown execution error"),
            "cause": failure_detail.get("cause", "No cause provided"),
        }
    elif event_type == "TaskFailed":
        failure_detail = event.get("taskFailedEventDetails", {})
        details = {
            "error": failure_detail.get("error", "Unknown task error"),
            "cause": failure_detail.get("cause", "No cause provided"),
            "resource": failure_detail.get("resource", "Unknown resource"),
        }
    elif event_type == "LambdaFunctionFailed":
        failure_detail = event.get("lambdaFunctionFailedEventDetails", {})
        details = {
            "error": failure_detail.get("error", "Lambda function failed"),
            "cause": failure_detail.get("cause", "No cause provided"),
        }
    elif "TimedOut" in event_type:
        timeout_detail = event.get("executionTimedOutEventDetails") or event.get(
            "taskTimedOutEventDetails", {}
        )
        details = {
            "error": f"{event_type.replace('EventDetails', '')}",
            "cause": timeout_detail.get("cause", "Execution exceeded timeout limit"),
        }

    return details


def _analyze_execution_timeline(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze Step Function execution timeline to identify failure patterns and state transitions.
    Processes execution events chronologically to build a timeline of state transitions
    and identify the exact point of failure with context.

    Args:
        events: List of Step Function execution events

    Returns:
        Dict containing timeline analysis, failure point, and state information
    """
    if not events:
        return {"error": "No execution events available"}

    # Cache config values once
    config = get_config_with_fallback()
    max_timeline_events = config.get("max_stepfunction_timeline_events", 3)

    timeline = []
    failure_point = None
    last_successful_state = None

    for event in events:
        timestamp = event.get("timestamp")
        event_type = event.get("type", "")

        # Track state transitions
        if event_type == "StateEntered":
            state_name = event.get("stateEnteredEventDetails", {}).get(
                "name", "Unknown"
            )
            timeline.append(
                {
                    "timestamp": timestamp,
                    "event": f"Entered state: {state_name}",
                    "state": state_name,
                }
            )
            last_successful_state = state_name

        elif event_type == "StateExited":
            state_name = event.get("stateExitedEventDetails", {}).get("name", "Unknown")
            timeline.append(
                {
                    "timestamp": timestamp,
                    "event": f"Exited state: {state_name}",
                    "state": state_name,
                }
            )

        # Identify failure point
        failure_details = _extract_failure_details(event)
        if failure_details and not failure_point:
            failure_point = {
                "timestamp": timestamp,
                "event_type": event_type,
                "state": last_successful_state,
                "details": failure_details,
            }

    return {
        "timeline": timeline[-max_timeline_events:],
        "failure_point": failure_point,
        "last_successful_state": last_successful_state,
    }


@tool
def analyze_stepfunction_execution(execution_arn: str) -> Dict[str, Any]:
    """
    Analyze Step Function execution to identify workflow failures and state transitions.
    Retrieves execution history and performs comprehensive analysis to identify failure points,
    state transitions, and execution patterns for document processing workflows.

    Args:
        execution_arn: Step Function execution ARN from document context

    Returns:
        Dict containing execution analysis, timeline, and failure details
    """
    try:
        if not execution_arn:
            return create_error_response("No execution ARN provided")

        stepfunctions_client = boto3.client("stepfunctions")

        # Get execution details
        execution_response = stepfunctions_client.describe_execution(
            executionArn=execution_arn
        )

        # Get execution history
        history_response = stepfunctions_client.get_execution_history(
            executionArn=execution_arn,
            maxResults=100,
            reverseOrder=True,  # Most recent events first
        )

        events = history_response.get("events", [])

        # Analyze timeline and failures
        timeline_analysis = _analyze_execution_timeline(events)

        # Extract execution metadata
        execution_status = execution_response.get("status", "UNKNOWN")
        start_date = execution_response.get("startDate")
        stop_date = execution_response.get("stopDate")

        # Calculate execution duration
        duration_seconds = None
        if start_date and stop_date:
            duration_seconds = (stop_date - start_date).total_seconds()

        # Build analysis summary
        analysis_summary = f"Step Function execution {execution_status}"
        if timeline_analysis.get("failure_point"):
            failure_point = timeline_analysis["failure_point"]
            analysis_summary += f" at state '{failure_point.get('state', 'Unknown')}'"
            if failure_point.get("details", {}).get("error"):
                analysis_summary += f": {failure_point['details']['error']}"

        return create_success_response(
            {
                "execution_status": execution_status,
                "duration_seconds": duration_seconds,
                "timeline_analysis": timeline_analysis,
                "analysis_summary": analysis_summary,
                "recommendations": [
                    "Check the failure point state for specific error details",
                    "Review Lambda function logs if failure occurred in Lambda task",
                    "Verify input data format if failure occurred early in workflow",
                    "Consider timeout adjustments if execution timed out",
                ],
            }
        )

    except Exception as e:
        logger.error(f"Error analyzing Step Function execution {execution_arn}: {e}")
        return create_error_response(str(e))
