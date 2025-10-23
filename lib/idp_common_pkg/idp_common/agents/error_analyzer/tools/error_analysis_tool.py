# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unified analysis tool for intelligent error routing.
"""

import logging
import os
import re
from typing import Any, Dict, Tuple

from strands import tool

from ..config import (
    create_error_response,
    get_config_with_fallback,
    safe_int_conversion,
)
from .document_analysis_tool import analyze_document_failure
from .general_analysis_tool import analyze_recent_system_errors

logger = logging.getLogger(__name__)


def _classify_query_intent(query: str) -> Tuple[str, str]:
    """
    Classify user query to determine appropriate analysis approach.
    Analyzes query text to distinguish between document-specific analysis requests
    and general system-wide error analysis requests using pattern matching.

    Args:
        query: User query string to classify

    Returns:
        Tuple of (intent_type, document_id) where intent_type is either
        'document_specific' or 'general_analysis'
    """
    # Document-specific patterns - require colon immediately after keyword
    specific_doc_patterns = [
        r"document:\s*([^\s]+)",  # "document: filename.pdf"
        r"file:\s*([^\s]+)",  # "file: report.docx"
        r"ObjectKey:\s*([^\s]+)",  # "ObjectKey: path/file.pdf"
    ]

    # Check for specific document patterns first
    for pattern in specific_doc_patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            document_id = match.group(1).strip()
            return ("document_specific", document_id)

    # If no specific document pattern found, it's general analysis
    return ("general_analysis", "")


@tool
def analyze_errors(query: str, time_range_hours: int = 1) -> Dict[str, Any]:
    """
    Intelligent error analysis with automatic query classification and routing.
    Primary entry point for error analysis that automatically determines whether to perform
    document-specific analysis or system-wide analysis based on query patterns.

    Document-specific examples:
    - "document: lending_package.pdf"
    General analysis examples:
    - "Find failure for document processing"

    Args:
        query: User query describing the analysis request
        time_range_hours: Hours to look back for analysis (default: 1, uses config default)

    Returns:
        Dict containing analysis results appropriate to the query type
    """
    try:
        stack_name = os.environ.get("AWS_STACK_NAME", "")
        if not stack_name:
            return create_error_response(
                "AWS_STACK_NAME not configured", analysis_summary="Configuration error"
            )

        config = get_config_with_fallback()
        max_log_events = safe_int_conversion(config.get("max_log_events", 5))
        time_range_default = safe_int_conversion(
            config.get("time_range_hours_default", 24)
        )

        # Use config default if parameter is default value
        time_range_hours = safe_int_conversion(time_range_hours, 1)
        if time_range_hours == 1:  # Default parameter value
            time_range_hours = time_range_default

        # Enhanced query classification
        intent, document_id = _classify_query_intent(query)

        if intent == "document_specific" and document_id:
            logger.info(f"Document-specific analysis for: {document_id}")
            return analyze_document_failure(document_id, stack_name, max_log_events)
        else:
            logger.info(f"General system analysis for query: {query[:50]}...")
            return analyze_recent_system_errors(
                time_range_hours, stack_name, max_log_events
            )

    except Exception as e:
        logger.error(f"Error in unified analysis: {e}")
        return create_error_response(str(e))
