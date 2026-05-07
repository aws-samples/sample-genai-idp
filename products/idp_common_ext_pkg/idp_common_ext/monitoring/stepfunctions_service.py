# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Step Functions service for IDP execution analysis.

Provides reusable functions to retrieve and analyse the processing history
of a document through AWS Step Functions, including a timeline of every step
the document went through and where it failed.

This module is a pure library — it contains no ``@tool`` decorators and makes
no assumptions about agent frameworks.  Agent tool wrappers that call these
functions live in ``agents/error_analyzer/tools/stepfunction_tool.py``.

Usage::

    from idp_common_ext.monitoring.stepfunctions_service import (
        get_execution_arn_from_document,
        get_execution_data,
        analyze_execution_timeline,
        extract_failure_details,
    )

    arn = get_execution_arn_from_document(document_record)
    data = get_execution_data(arn)
    timeline = analyze_execution_timeline(arn)
    failure = extract_failure_details(data["events"])
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import boto3

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level lazy boto3 client cache, keyed by region so that callers passing
# an explicit region always get the correct client, even if a default-region
# client was already initialised first.
# ---------------------------------------------------------------------------
_sf_clients: Dict[Optional[str], Any] = {}


def _get_sf_client(region: Optional[str] = None) -> Any:
    """Return (and lazily create) a per-region Step Functions boto3 client."""
    if region not in _sf_clients:
        _sf_clients[region] = boto3.client("stepfunctions", region_name=region)
    return _sf_clients[region]


# ---------------------------------------------------------------------------
# Event types that indicate a failure in the execution
# ---------------------------------------------------------------------------
_FAILURE_EVENT_TYPES: Set[str] = {
    "TaskFailed",
    "TaskTimedOut",
    "ExecutionFailed",
    "ActivityFailed",
    "LambdaFunctionFailed",
    "LambdaFunctionTimedOut",
}

# Mapping from event type to the key that holds failure detail in the event dict
_FAILURE_DETAIL_KEYS: Dict[str, str] = {
    "TaskFailed": "taskFailedEventDetails",
    "TaskTimedOut": "taskTimedOutEventDetails",
    "ExecutionFailed": "executionFailedEventDetails",
    "ActivityFailed": "activityFailedEventDetails",
    "LambdaFunctionFailed": "lambdaFunctionFailedEventDetails",
    "LambdaFunctionTimedOut": "lambdaFunctionTimedOutEventDetails",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_execution_arn_from_document(
    doc_record: Any,
) -> str:
    """
    Extract the Step Functions execution ARN from a DynamoDB document record.

    Accepts either a plain ``dict`` (raw DynamoDB item) or a
    :class:`~idp_common.monitoring.models.DocumentRecord` dataclass.

    Args:
        doc_record: DynamoDB document record dict or ``DocumentRecord``.

    Returns:
        Execution ARN string, or ``""`` if not available.
    """
    if isinstance(doc_record, dict):
        return (
            doc_record.get("WorkflowExecutionArn", "")
            or doc_record.get("ExecutionArn", "")
            or doc_record.get("workflow_execution_arn", "")
            or ""
        )
    # Handle DocumentRecord dataclass (or any object with the attribute)
    return (
        getattr(doc_record, "workflow_execution_arn", "")
        or getattr(doc_record, "WorkflowExecutionArn", "")
        or ""
    )


def get_execution_data(
    execution_arn: str,
    region: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Fetch full Step Functions execution history for a given execution ARN.

    Paginates through the ``get_execution_history`` API to retrieve all events.

    Args:
        execution_arn: Full ARN of the Step Functions execution.
        region:        AWS region name.  Defaults to the region inferred by
                       boto3 from the environment.

    Returns:
        ``{
            "execution_arn": str,
            "status": str,      # SUCCEEDED | FAILED | RUNNING | ABORTED | TIMED_OUT
            "start_date": str,  # ISO 8601 or ""
            "stop_date": str,   # ISO 8601 or ""
            "events": list,     # Raw execution history events (timestamps serialised)
            "input": str,       # Execution input JSON string
        }``
    """
    sf = _get_sf_client(region)
    result: Dict[str, Any] = {
        "execution_arn": execution_arn,
        "status": "UNKNOWN",
        "start_date": "",
        "stop_date": "",
        "events": [],
        "input": "",
    }

    try:
        desc = sf.describe_execution(executionArn=execution_arn)
        result["status"] = desc.get("status", "UNKNOWN")

        start = desc.get("startDate")
        stop = desc.get("stopDate")
        result["start_date"] = _serialize_datetime(start)
        result["stop_date"] = _serialize_datetime(stop)
        result["input"] = desc.get("input", "")

        # Paginate execution history
        paginator = sf.get_paginator("get_execution_history")
        events: List[Dict[str, Any]] = []
        for page in paginator.paginate(
            executionArn=execution_arn,
            includeExecutionData=True,
        ):
            events.extend(page.get("events", []))

        # Serialise all timestamp fields so the result is JSON-safe
        for event in events:
            ts = event.get("timestamp")
            if ts is not None and not isinstance(ts, str):
                event["timestamp"] = _serialize_datetime(ts)

        result["events"] = events

    except sf.exceptions.ExecutionDoesNotExist:
        # Use a distinct status so callers can tell "not found" from a
        # transient API error (which leaves status as "UNKNOWN").
        logger.warning("Execution not found: %s", execution_arn)
        result["status"] = "NOT_FOUND"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to get execution data for %s: %s", execution_arn, exc)

    return result


def analyze_execution_timeline(
    execution_arn: str,
    max_events: int = 200,
    region: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Analyse a Step Functions execution and produce a structured timeline.

    Returns the sequence of states with their durations, identifying which
    state failed and extracting the error details.

    Args:
        execution_arn: Full ARN of the Step Functions execution.
        max_events:    Maximum history events to process (default: 200).
        region:        AWS region name.

    Returns:
        ``{
            "execution_arn": str,
            "overall_status": str,
            "total_duration_ms": float,
            "states": [
                {
                    "name": str,
                    "status": str,       # SUCCEEDED | FAILED
                    "start_time": str,
                    "end_time": str,
                    "duration_ms": float,
                    "is_failure": bool,
                }
            ],
            "failed_state": str,
            "failure_details": dict,
        }``
    """
    exec_data = get_execution_data(execution_arn, region=region)
    all_events: List[Dict[str, Any]] = exec_data.get("events", [])
    if len(all_events) > max_events:
        logger.warning(
            "Execution %s has %d events; truncating to %d for timeline analysis. "
            "Increase max_events to avoid missing failure details.",
            execution_arn,
            len(all_events),
            max_events,
        )
    events = all_events[:max_events]

    timeline: Dict[str, Any] = {
        "execution_arn": execution_arn,
        "overall_status": exec_data.get("status", "UNKNOWN"),
        "total_duration_ms": 0.0,
        "states": [],
        "failed_state": "",
        "failure_details": {},
    }

    state_starts: Dict[str, str] = {}  # state_name → start_timestamp
    states: List[Dict[str, Any]] = []

    for event in events:
        event_type: str = event.get("type", "")
        timestamp: str = event.get("timestamp", "")

        if event_type == "TaskStateEntered":
            state_name = event.get("stateEnteredEventDetails", {}).get("name", "")
            if state_name:
                state_starts[state_name] = timestamp
            continue

        # --- State-completion and failure events that produce a timeline entry ---
        if event_type == "TaskStateExited":
            state_name = event.get("stateExitedEventDetails", {}).get("name", "")
            is_failure = False
            status = "SUCCEEDED"

        elif event_type in ("TaskFailed", "TaskTimedOut"):
            # Task-level failures do not carry stateExitedEventDetails — look
            # back to the most recently entered state to get the name.
            state_name = list(state_starts.keys())[-1] if state_starts else "Unknown"
            is_failure = True
            status = "FAILED"

        elif event_type == "ExecutionFailed":
            state_name = event.get("stateExitedEventDetails", {}).get("name", "")
            if not state_name:
                # Attribute failure to the last known entered state
                state_name = (
                    list(state_starts.keys())[-1] if state_starts else "Unknown"
                )
            is_failure = True
            status = "FAILED"

        else:
            # Ignore all other event types (ExecutionStarted, LambdaScheduled, etc.)
            continue

        start = state_starts.get(state_name, "")
        duration_ms = _compute_duration_ms(start, timestamp)

        states.append(
            {
                "name": state_name,
                "status": status,
                "start_time": start,
                "end_time": timestamp,
                "duration_ms": round(duration_ms, 1),
                "is_failure": is_failure,
            }
        )

        if is_failure and not timeline["failed_state"]:
            timeline["failed_state"] = state_name

    timeline["states"] = states
    timeline["failure_details"] = extract_failure_details(events)

    # Total execution duration
    start_date = exec_data.get("start_date", "")
    stop_date = exec_data.get("stop_date", "")
    if start_date and stop_date:
        timeline["total_duration_ms"] = round(
            _compute_duration_ms(start_date, stop_date), 1
        )

    return timeline


def extract_failure_details(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Parse Step Functions execution history events to extract failure information.

    Handles all six failure event types:
    ``TaskFailed``, ``TaskTimedOut``, ``ExecutionFailed``,
    ``ActivityFailed``, ``LambdaFunctionFailed``, ``LambdaFunctionTimedOut``.

    Args:
        events: List of raw execution history event dicts (timestamps may be
                strings or ``datetime`` objects).

    Returns:
        ``{
            "error": str,        # Error type (e.g. "ThrottlingException")
            "cause": str,        # Error cause message (may be a JSON string)
            "failed_state": str, # Name of the state that failed
            "event_type": str,   # The Step Functions event type
        }``
        All fields are empty strings if no failure event is found.
    """
    result: Dict[str, Any] = {
        "error": "",
        "cause": "",
        "failed_state": "",
        "event_type": "",
    }

    # Walk in reverse to find the most recent failure event
    for event in reversed(events):
        event_type: str = event.get("type", "")
        if event_type not in _FAILURE_EVENT_TYPES:
            continue

        result["event_type"] = event_type

        detail_key = _FAILURE_DETAIL_KEYS.get(event_type, "")
        details: Dict[str, Any] = event.get(detail_key, {}) if detail_key else {}

        result["error"] = details.get("error", "") or details.get("Error", "") or ""
        result["cause"] = details.get("cause", "") or details.get("Cause", "") or ""

        # Trace back to find which state was entered before this failure
        event_id: int = event.get("id", 0)
        for prior in reversed(events):
            if (
                prior.get("id", 0) < event_id
                and prior.get("type") == "TaskStateEntered"
            ):
                result["failed_state"] = prior.get("stateEnteredEventDetails", {}).get(
                    "name", ""
                )
                break

        break  # Use the most recent failure only

    return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _serialize_datetime(dt: Any) -> str:
    """Convert a datetime object (or None) to an ISO 8601 string."""
    if dt is None:
        return ""
    if isinstance(dt, str):
        return dt
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return str(dt)


def _compute_duration_ms(start: str, end: str) -> float:
    """
    Compute the duration in milliseconds between two ISO 8601 timestamp strings.

    Returns 0.0 if either string is empty or unparseable.
    """
    if not start or not end:
        return 0.0
    try:
        t0 = datetime.fromisoformat(start.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return (t1 - t0).total_seconds() * 1000
    except (ValueError, TypeError) as exc:
        logger.debug(
            "Could not compute duration between '%s' and '%s': %s", start, end, exc
        )
        return 0.0
