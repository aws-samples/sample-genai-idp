# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
DynamoDB tools for error analysis.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict

import boto3
from strands import tool

from ..config import create_error_response, create_success_response, decimal_to_float

logger = logging.getLogger(__name__)


@tool
def get_document_status(object_key: str) -> Dict[str, Any]:
    """
    Retrieve document processing status from DynamoDB tracking table.
    Performs a direct lookup to get the current status and metadata for a specific document.

    Args:
        object_key: The S3 object key for the document

    Returns:
        Dict containing document status information or error details
    """
    try:
        result = get_document_by_key(object_key)

        if result.get("document_found"):
            document = result.get("document", {})
            return create_success_response(
                {
                    "document_found": True,
                    "object_key": object_key,
                    "status": document.get("Status"),
                    "initial_event_time": document.get("InitialEventTime"),
                    "completion_time": document.get("CompletionTime"),
                    "execution_arn": document.get("ExecutionArn"),
                }
            )
        else:
            return result

    except Exception as e:
        logger.error(f"Status lookup failed for '{object_key}': {e}")
        return create_error_response(
            str(e), document_found=False, object_key=object_key
        )


@tool
def get_tracking_table_name() -> Dict[str, Any]:
    """
    Retrieve the DynamoDB tracking table name from environment configuration.
    Checks for the TRACKING_TABLE_NAME environment variable and validates its availability.

    Returns:
        Dict containing table name or error if not configured
    """
    table_name = os.environ.get("TRACKING_TABLE_NAME")
    if table_name:
        return create_success_response(
            {
                "tracking_table_found": True,
                "table_name": table_name,
            }
        )
    return create_error_response(
        "TRACKING_TABLE_NAME environment variable not set", tracking_table_found=False
    )


@tool
def query_tracking_table(
    date: str = "", hours_back: int = 24, limit: int = 100
) -> Dict[str, Any]:
    """
    Query DynamoDB tracking table using efficient time-based partition scanning.
    Searches through time-partitioned data to find documents processed within the specified timeframe.
    Uses optimized querying to minimize DynamoDB read costs.

    Args:
        date: Date in YYYY-MM-DD format (defaults to today)
        hours_back: Number of hours to look back from date (default 24)
        limit: Maximum number of items to return

    Returns:
        Dict containing found items and query metadata
    """
    try:
        table_name = os.environ.get("TRACKING_TABLE_NAME")
        if not table_name:
            return create_error_response(
                "TRACKING_TABLE_NAME environment variable not set",
                items_found=0,
                items=[],
            )

        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(table_name)

        # Use current date if not provided
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        # Generate time-based partition keys to query
        base_date = datetime.strptime(date, "%Y-%m-%d")
        end_time = base_date + timedelta(days=1)
        start_time = end_time - timedelta(hours=hours_back)

        all_items = []
        current_time = start_time

        # Query by hour partitions for efficiency
        while current_time < end_time and len(all_items) < limit:
            hour_str = current_time.strftime("%Y-%m-%dT%H")

            # Query the list partition for this hour
            pk = f"list#{current_time.strftime('%Y-%m-%d')}#s#{current_time.hour // 4:02d}"
            sk_prefix = f"ts#{hour_str}"

            try:
                response = table.query(
                    KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
                    ExpressionAttributeValues={":pk": pk, ":sk_prefix": sk_prefix},
                    Limit=min(limit - len(all_items), 50),
                )

                items = response.get("Items", [])
                all_items.extend(items)

            except Exception as query_error:
                logger.debug(f"Query failed for {pk}: {query_error}")

            current_time += timedelta(hours=1)

        items = [decimal_to_float(item) for item in all_items[:limit]]

        return create_success_response(
            {
                "table_name": table_name,
                "items_found": len(items),
                "items": items,
                "query_date": date,
                "hours_back": hours_back,
            }
        )

    except Exception as e:
        logger.error(f"TrackingTable query failed: {e}")
        return create_error_response(str(e), items_found=0, items=[])


@tool
def get_document_by_key(object_key: str) -> Dict[str, Any]:
    """
    Retrieve a specific document record from DynamoDB tracking table by its object key.
    Performs a direct item lookup using the document's S3 object key as the primary identifier.
    Handles DynamoDB Decimal conversion for JSON compatibility.

    Args:
        object_key: The S3 object key for the document

    Returns:
        Dict containing document data or error information
    """
    try:
        table_name = os.environ.get("TRACKING_TABLE_NAME")
        if not table_name:
            return create_error_response(
                "TRACKING_TABLE_NAME environment variable not set",
                document_found=False,
                object_key=object_key,
            )

        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(table_name)

        # Direct key lookup
        response = table.get_item(Key={"PK": f"doc#{object_key}", "SK": "none"})

        if "Item" in response:
            item = decimal_to_float(response["Item"])
            return create_success_response(
                {
                    "document_found": True,
                    "document": item,
                    "object_key": object_key,
                }
            )
        else:
            return create_error_response(
                f"Document not found for key: {object_key}",
                document_found=False,
                object_key=object_key,
            )

    except Exception as e:
        logger.error(f"Document lookup failed for key '{object_key}': {e}")
        return create_error_response(
            str(e), document_found=False, object_key=object_key
        )
