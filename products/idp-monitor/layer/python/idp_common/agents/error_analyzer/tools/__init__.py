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

from .cloudwatch_tool import search_cloudwatch_logs, search_performance_issues
from .dynamodb_tool import (
    fetch_document_record,
    fetch_recent_records,
)
from .lambda_tool import retrieve_document_context
from .stepfunction_tool import analyze_workflow_execution
from .xray_tool import (
    analyze_document_trace,
    analyze_system_performance,
)

__all__ = [
    "search_cloudwatch_logs",
    "search_performance_issues",
    "retrieve_document_context",
    "fetch_document_record",
    "fetch_recent_records",
    "analyze_workflow_execution",
    "analyze_document_trace",
    "analyze_system_performance",
]
