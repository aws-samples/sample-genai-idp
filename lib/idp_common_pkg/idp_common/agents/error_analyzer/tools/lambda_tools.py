# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Lambda tools for document context extraction.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List

import boto3
from strands import tool

from ..config import create_error_response, create_success_response

logger = logging.getLogger(__name__)


def get_lookup_function_name() -> str:
    """
    Retrieve the Lambda lookup function name from environment configuration.
    Checks for LOOKUP_FUNCTION_NAME environment variable with fallback to
    AWS_STACK_NAME-based naming convention.

    Returns:
        Lambda function name string

    Raises:
        ValueError: If neither environment variable is configured
    """
    function_name = os.environ.get("LOOKUP_FUNCTION_NAME")
    if function_name:
        return function_name

    raise ValueError("LOOKUP_FUNCTION_NAME environment variable not set")


def extract_lambda_request_ids(execution_events: List[Dict[str, Any]]) -> List[str]:
    """
    Extract Lambda request IDs from Step Functions execution event history.
    Parses Step Function execution events to find Lambda function invocation request IDs
    for targeted CloudWatch log filtering.

    Args:
        execution_events: List of Step Function execution events

    Returns:
        List of unique Lambda request ID strings
    """
    request_ids = []

    for event in execution_events:
        event_type = event.get("type", "")

        # Look for Lambda task events
        if event_type in [
            "LambdaFunctionSucceeded",
            "LambdaFunctionFailed",
            "LambdaFunctionTimedOut",
        ]:
            # Extract request ID from event details if available
            event_detail = (
                event.get("lambdaFunctionSucceededEventDetails")
                or event.get("lambdaFunctionFailedEventDetails")
                or event.get("lambdaFunctionTimedOutEventDetails")
            )

            if event_detail and isinstance(event_detail, dict):
                # Request ID might be in output or error details
                output = event_detail.get("output", "")
                if output:
                    try:
                        output_data = json.loads(output)
                        if "requestId" in output_data:
                            request_ids.append(output_data["requestId"])
                    except (json.JSONDecodeError, TypeError):
                        pass

    return list(set(request_ids))  # Remove duplicates


@tool
def get_document_context(document_id: str, stack_name: str = "") -> Dict[str, Any]:
    """
    Retrieve comprehensive document processing context via Lambda lookup function.
    Invokes the lookup Lambda function to gather execution context, timing information,
    and Step Function details for a specific document. Provides essential data for
    targeted error analysis and log searching.

    Args:
        document_id: Document ObjectKey to analyze
        stack_name: CloudFormation stack name (optional, for backward compatibility)

    Returns:
        Dict containing document context, execution details, and timing information
    """
    try:
        lambda_client = boto3.client("lambda")
        function_name = get_lookup_function_name()

        logger.info(
            f"Invoking lookup function: {function_name} for document: {document_id}"
        )

        # Invoke lookup function
        response = lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps({"object_key": document_id}),
        )

        # Parse response
        payload = json.loads(response["Payload"].read().decode("utf-8"))

        if payload.get("status") == "NOT_FOUND":
            return create_error_response(
                "Document not found in tracking database",
                document_found=False,
                document_id=document_id,
            )

        if payload.get("status") == "ERROR":
            return create_error_response(
                payload.get("message", "Unknown error from lookup function"),
                document_found=False,
                document_id=document_id,
            )

        # Extract execution context
        processing_detail = payload.get("processingDetail", {})
        execution_arn = processing_detail.get("executionArn")
        execution_events = processing_detail.get("events", [])

        # Extract Lambda request IDs from execution events
        request_ids = extract_lambda_request_ids(execution_events)

        # Get timestamps for precise time windows
        timestamps = payload.get("timing", {}).get("timestamps", {})

        # Calculate processing time window
        start_time = None
        end_time = None

        if timestamps.get("WorkflowStartTime"):
            start_time = datetime.fromisoformat(
                timestamps["WorkflowStartTime"].replace("Z", "+00:00")
            )

        if timestamps.get("CompletionTime"):
            end_time = datetime.fromisoformat(
                timestamps["CompletionTime"].replace("Z", "+00:00")
            )

        return create_success_response(
            {
                "document_found": True,
                "document_id": document_id,
                "document_status": payload.get("status"),
                "execution_arn": execution_arn,
                "lambda_request_ids": request_ids,
                "timestamps": timestamps,
                "processing_start_time": start_time,
                "processing_end_time": end_time,
                "execution_events_count": len(execution_events),
                "lookup_function_response": payload,
            }
        )

    except Exception as e:
        logger.error(f"Error getting document context for {document_id}: {e}")
        return create_error_response(
            str(e), document_found=False, document_id=document_id
        )
