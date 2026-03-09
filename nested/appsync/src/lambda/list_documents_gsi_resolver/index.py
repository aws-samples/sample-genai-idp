# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Lambda resolver for listDocuments and getDocumentCount GraphQL queries.

Uses the TypeDateIndex GSI on TrackingTable for efficient queries:
- listDocuments: Paginated query with date range filtering
- getDocumentCount: COUNT query for header display

This replaces:
1. The old VTL scan-based listDocuments resolver
2. The shard-based N+1 pattern (listDocumentsDateShard → getDocument per item)
3. The listDocumentsByDateRange Lambda (shard iteration + BatchGetItem)

Performance: O(matched items) instead of O(total table items)
"""

import json
import logging
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

dynamodb = boto3.resource("dynamodb")

# Limits
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

# GSI name
TYPE_DATE_INDEX = "TypeDateIndex"


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal objects from DynamoDB."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            if obj % 1 == 0:
                return int(obj)
            return float(obj)
        return super().default(obj)


def handler(event, context):
    """
    AppSync Lambda resolver handler.
    
    Routes to listDocuments or getDocumentCount based on the field name.
    """
    field_name = event.get("info", {}).get("fieldName", "")
    logger.info(f"Resolver invoked for field: {field_name}")
    
    if field_name == "listDocuments":
        return list_documents(event)
    elif field_name == "getDocumentCount":
        return get_document_count(event)
    else:
        raise ValueError(f"Unknown field: {field_name}")


def list_documents(event):
    """
    List documents using TypeDateIndex GSI with server-side pagination.
    
    Args (from GraphQL):
        startDateTime: ISO 8601 start time
        endDateTime: ISO 8601 end time  
        limit: Page size (default 50, max 200)
        nextToken: Pagination token from previous response
    
    Returns:
        {
            Documents: [Document],
            nextToken: String | null,
            totalCount: Int | null
        }
    """
    args = event.get("arguments", {})
    start_dt = args.get("startDateTime")
    end_dt = args.get("endDateTime")
    limit = min(int(args.get("limit") or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE)
    next_token = args.get("nextToken")
    
    table_name = os.environ["TRACKING_TABLE_NAME"]
    table = dynamodb.Table(table_name)
    
    # Build GSI query
    query_kwargs = {
        "IndexName": TYPE_DATE_INDEX,
        "Limit": limit,
        "ScanIndexForward": False,  # Newest first
    }
    
    # Key condition: always filter by ItemType = "document"
    if start_dt and end_dt:
        query_kwargs["KeyConditionExpression"] = (
            Key("ItemType").eq("document") & 
            Key("InitialEventTime").between(start_dt, end_dt)
        )
    elif start_dt:
        query_kwargs["KeyConditionExpression"] = (
            Key("ItemType").eq("document") & 
            Key("InitialEventTime").gte(start_dt)
        )
    elif end_dt:
        query_kwargs["KeyConditionExpression"] = (
            Key("ItemType").eq("document") & 
            Key("InitialEventTime").lte(end_dt)
        )
    else:
        query_kwargs["KeyConditionExpression"] = Key("ItemType").eq("document")
    
    # Handle pagination token
    if next_token:
        try:
            query_kwargs["ExclusiveStartKey"] = json.loads(next_token)
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Invalid nextToken: {next_token}")
    
    logger.info(f"Querying TypeDateIndex: limit={limit}, start={start_dt}, end={end_dt}")
    
    try:
        response = table.query(**query_kwargs)
    except Exception as e:
        logger.error(f"GSI query failed: {e}")
        raise
    
    items = response.get("Items", [])
    last_key = response.get("LastEvaluatedKey")
    
    logger.info(f"Query returned {len(items)} items, has more: {last_key is not None}")
    
    # Transform GSI projection items to match the Document GraphQL type
    documents = []
    for item in items:
        doc = _gsi_item_to_document(item)
        documents.append(doc)
    
    result = {
        "Documents": documents,
        "nextToken": json.dumps(last_key, cls=DecimalEncoder) if last_key else None,
    }
    
    return result


def get_document_count(event):
    """
    Get document count using TypeDateIndex GSI with SELECT COUNT.
    
    This is an efficient O(matched items) count that doesn't read item data.
    
    Args (from GraphQL):
        startDateTime: ISO 8601 start time
        endDateTime: ISO 8601 end time
    
    Returns:
        { count: Int }
    """
    args = event.get("arguments", {})
    start_dt = args.get("startDateTime")
    end_dt = args.get("endDateTime")
    
    table_name = os.environ["TRACKING_TABLE_NAME"]
    table = dynamodb.Table(table_name)
    
    # Build GSI count query
    query_kwargs = {
        "IndexName": TYPE_DATE_INDEX,
        "Select": "COUNT",
    }
    
    if start_dt and end_dt:
        query_kwargs["KeyConditionExpression"] = (
            Key("ItemType").eq("document") & 
            Key("InitialEventTime").between(start_dt, end_dt)
        )
    elif start_dt:
        query_kwargs["KeyConditionExpression"] = (
            Key("ItemType").eq("document") & 
            Key("InitialEventTime").gte(start_dt)
        )
    elif end_dt:
        query_kwargs["KeyConditionExpression"] = (
            Key("ItemType").eq("document") & 
            Key("InitialEventTime").lte(end_dt)
        )
    else:
        query_kwargs["KeyConditionExpression"] = Key("ItemType").eq("document")
    
    logger.info(f"Counting documents: start={start_dt}, end={end_dt}")
    
    # Paginate through all count pages (DynamoDB may split count across pages)
    total_count = 0
    while True:
        response = table.query(**query_kwargs)
        total_count += response.get("Count", 0)
        
        last_key = response.get("LastEvaluatedKey")
        if last_key:
            query_kwargs["ExclusiveStartKey"] = last_key
        else:
            break
    
    logger.info(f"Total document count: {total_count}")
    return {"count": total_count}


def _gsi_item_to_document(item):
    """
    Transform a GSI projection item to match the Document GraphQL type.
    
    The GSI INCLUDE projection has a subset of Document fields.
    We map them to the expected GraphQL field names.
    """
    # Extract PK to get ObjectKey if not directly available
    pk = item.get("PK", "")
    object_key = item.get("ObjectKey") or (pk.replace("doc#", "", 1) if pk.startswith("doc#") else pk)
    
    # Build confidence alert count from ConfidenceAlertCount attribute
    confidence_alert_count = item.get("ConfidenceAlertCount")
    
    doc = {
        "PK": item.get("PK"),
        "SK": item.get("SK", "none"),
        "ObjectKey": object_key,
        "ObjectStatus": item.get("ObjectStatus"),
        "InitialEventTime": item.get("InitialEventTime"),
        "CompletionTime": item.get("CompletionTime"),
        "ConfigVersion": item.get("ConfigVersion") or item.get("ConfigurationVersion"),
        "EvaluationStatus": item.get("EvaluationStatus"),
        "HITLStatus": item.get("HITLStatus"),
        "HITLTriggered": item.get("HITLTriggered"),
        "HITLCompleted": item.get("HITLCompleted"),
        "HITLReviewOwner": item.get("HITLReviewOwner"),
        "HITLReviewedBy": item.get("HITLReviewedBy"),
        "PageCount": item.get("NumPages"),
        "ConfidenceAlertCount": confidence_alert_count,
    }
    
    # Remove None values to keep response clean
    return {k: v for k, v in doc.items() if v is not None}
