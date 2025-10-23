# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
System-wide analysis tool.
"""

import logging
from typing import Any, Dict, List

from strands import tool

from ..config import (
    create_error_response,
    create_success_response,
    get_config_with_fallback,
    safe_int_conversion,
    truncate_message,
)
from .cloudwatch_tools import search_stack_logs
from .dynamodb_tools import get_tracking_table_name, query_tracking_table

logger = logging.getLogger(__name__)


def _get_prioritized_error_patterns() -> List[tuple[str, int]]:
    """
    Get prioritized error patterns for multi-pattern log searching.
    Returns error patterns ordered by criticality with associated event limits
    to optimize log search efficiency and focus on most important errors.

    Returns:
        List of tuples containing (pattern, max_events) pairs
    """
    return [
        ("ERROR", 5),  # Most critical, get 5 events
        ("Exception", 3),  # Important, get 3 events
        ("ValidationException", 2),  # Specific validation issues
        ("Failed", 2),  # General failures
        ("Timeout", 1),  # Performance issues
    ]


def _filter_and_deduplicate_events(
    events: List[Dict], config: Dict[str, Any]
) -> List[Dict]:
    """
    Filter and deduplicate log events to reduce noise and context size.
    Removes duplicate error signatures and applies message length limits
    to keep only unique, meaningful error events within context constraints.

    Args:
        events: List of log event dictionaries
        config: Configuration dictionary with limits

    Returns:
        List of filtered and deduplicated events
    """
    import re

    max_message_length = config.get("max_log_message_length", 200)
    seen_messages = set()
    filtered = []

    for event in events:
        message = event.get("message", "")
        # Extract error signature (remove timestamps, request IDs, etc.)
        error_signature = re.sub(r"\d{4}-\d{2}-\d{2}.*?Z", "", message)
        error_signature = re.sub(r"RequestId: [a-f0-9-]+", "", error_signature)

        if error_signature not in seen_messages and len(filtered) < 10:
            seen_messages.add(error_signature)
            truncated_message = truncate_message(message, max_message_length)

            filtered.append(
                {
                    "timestamp": event["timestamp"],
                    "message": truncated_message,
                    "log_stream": event.get("log_stream", "")[:50],
                }
            )

    return filtered


def _categorize_errors(log_events: List[Dict]) -> Dict[str, List[Dict]]:
    """
    Categorize log events by error type for pattern analysis.
    Groups error events into categories based on message content to identify
    common failure patterns and system issues.

    Args:
        log_events: List of log event dictionaries

    Returns:
        Dict mapping category names to lists of categorized events
    """
    categories = {
        "validation_errors": [],
        "processing_errors": [],
        "system_errors": [],
        "timeout_errors": [],
        "access_errors": [],
    }

    for event in log_events:
        message = event.get("message", "").lower()
        if "validation" in message or "invalid" in message:
            categories["validation_errors"].append(event)
        elif "timeout" in message:
            categories["timeout_errors"].append(event)
        elif "access" in message or "denied" in message:
            categories["access_errors"].append(event)
        elif "exception" in message or "error" in message:
            categories["processing_errors"].append(event)
        else:
            categories["system_errors"].append(event)

    return categories


def _generate_error_summary(
    categories: Dict, failed_documents: List, total_estimate: int
) -> str:
    """
    Generate comprehensive error summary with categorized insights.
    Creates a human-readable summary of error analysis results including
    total counts, failed documents, and error category breakdown.

    Args:
        categories: Dict of categorized errors
        failed_documents: List of failed document records
        total_estimate: Estimated total error count

    Returns:
        Formatted summary string
    """
    total_errors = sum(len(errors) for errors in categories.values())

    if total_errors == 0:
        return "No processing errors found in the specified time range"

    summary_parts = [
        f"Found {total_estimate} total errors across {len(failed_documents)} failed documents"
    ]

    # Add category breakdown
    for category, errors in categories.items():
        if errors:
            category_name = category.replace("_", " ")
            summary_parts.append(f"{len(errors)} {category_name}")

    return ". ".join(summary_parts)


@tool
def analyze_recent_system_errors(
    time_range_hours: int, stack_name: str, max_log_events: int = 5
) -> Dict[str, Any]:
    """
    Perform comprehensive system-wide error analysis with multi-pattern detection.
    Analyzes recent system errors across all components using multiple search patterns,
    categorizes errors by type, and provides insights into system health and failure patterns.

    Args:
        time_range_hours: Hours to look back for analysis
        stack_name: CloudFormation stack name
        max_log_events: Maximum log events to include in response

    Returns:
        Dict containing comprehensive system error analysis results
    """
    try:
        # Get configuration with all limits applied
        config = get_config_with_fallback()

        # Cache frequently used config values
        max_timeline_events = config.get("max_stepfunction_timeline_events", 3)
        max_message_length = config.get("max_log_message_length", 200)

        # Ensure parameters are integers using safe conversion
        time_range_hours = safe_int_conversion(time_range_hours)
        # Use configured max_log_events, fallback to parameter if not in config
        max_log_events = safe_int_conversion(
            config.get("max_log_events", max_log_events)
        )

        # Get tracking table name
        tracking_info = get_tracking_table_name()
        if not tracking_info.get("tracking_table_found"):
            return create_error_response("TrackingTable not found")

        # Query for recent documents and filter for failures
        error_records = query_tracking_table(hours_back=time_range_hours, limit=50)

        recent_failures = []

        # Filter for failed documents from the query results
        for item in error_records.get("items", []):
            status = item.get("Status") or item.get("ObjectStatus")
            if status == "FAILED":
                recent_failures.append(
                    {
                        "document_id": item.get("ObjectKey"),
                        "status": status,
                        "completion_time": item.get("CompletionTime"),
                        "error_message": item.get("ErrorMessage"),
                    }
                )

        # Step 1: Quick scan to estimate error volume
        initial_scan = search_stack_logs(
            filter_pattern="ERROR",
            hours_back=int(time_range_hours),
            max_log_events=5,
            max_log_groups=5,
        )

        total_errors_estimate = initial_scan.get("total_events_found", 0)

        # Step 2: Multi-pattern error search with limits
        error_summary = {}
        all_log_events = []
        total_events_collected = 0

        for pattern, max_events in _get_prioritized_error_patterns():
            if total_events_collected >= int(max_log_events):
                break

            results = search_stack_logs(
                filter_pattern=pattern,
                hours_back=int(time_range_hours),
                max_log_events=min(
                    max_events, int(max_log_events) - total_events_collected
                ),
                max_log_groups=10,
            )

            if results.get("total_events_found", 0) > 0:
                # Collect events from all log groups
                pattern_events = []
                for result in results.get("results", []):
                    pattern_events.extend(result.get("events", []))

                # Filter and deduplicate
                filtered_events = _filter_and_deduplicate_events(pattern_events, config)

                error_summary[pattern] = {
                    "count": results.get("total_events_found", 0),
                    "sample_events": filtered_events,
                }
                all_log_events.extend(filtered_events)
                total_events_collected += len(filtered_events)

        # Step 3: Categorize errors
        categorized_errors = _categorize_errors(all_log_events)

        # Step 4: Generate compact summary
        analysis_summary = _generate_error_summary(
            categorized_errors, recent_failures, total_errors_estimate
        )

        return create_success_response(
            {
                "analysis_type": "system_wide",
                "time_range_hours": time_range_hours,
                "total_errors_estimate": total_errors_estimate,
                "recent_failures_count": len(recent_failures),
                "recent_failures": recent_failures[:max_timeline_events],
                "error_categories": {
                    category: {
                        "count": len(errors),
                        "sample": truncate_message(
                            errors[0]["message"], max_message_length
                        )
                        if errors
                        else None,
                    }
                    for category, errors in categorized_errors.items()
                    if errors
                },
                "error_summary": error_summary,
                "analysis_summary": analysis_summary,
                "context_management": {
                    "events_collected": total_events_collected,
                    "max_events_limit": max_log_events,
                },
                "recommendations": [
                    "Review error categories to identify patterns",
                    "Check recent failed documents for common issues",
                    "Monitor system-wide error trends over time",
                    "Consider scaling resources if timeout errors are frequent",
                ],
            }
        )

    except Exception as e:
        logger.error(f"Error in system-wide analysis: {e}")
        return create_error_response(str(e))
