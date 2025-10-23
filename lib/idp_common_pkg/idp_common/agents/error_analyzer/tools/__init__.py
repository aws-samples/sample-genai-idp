# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Error Analyzer tools for Strands agents.

Provides comprehensive error analysis capabilities including:
- Document-specific failure analysis
- System-wide error pattern detection
- CloudWatch log searching and filtering
- DynamoDB tracking table queries
- Step Function execution analysis
- Lambda function context extraction
"""

from .cloudwatch_tools import search_document_logs, search_stack_logs
from .document_analysis_tool import analyze_document_failure
from .dynamodb_tools import (
    get_document_by_key,
    get_document_status,
    get_tracking_table_name,
    query_tracking_table,
)
from .error_analysis_tool import analyze_errors
from .general_analysis_tool import analyze_recent_system_errors
from .lambda_tools import get_document_context
from .stepfunction_tools import analyze_stepfunction_execution

__all__ = [
    "analyze_errors",
    "analyze_document_failure",
    "analyze_recent_system_errors",
    "search_document_logs",
    "search_stack_logs",
    "get_document_context",
    "get_document_by_key",
    "get_document_status",
    "get_tracking_table_name",
    "query_tracking_table",
    "analyze_stepfunction_execution",
]
