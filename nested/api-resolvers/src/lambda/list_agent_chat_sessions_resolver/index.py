# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Lambda function to list chat sessions for the current user.
This function queries the ChatSessionsTable to get session metadata efficiently.
"""

import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Initialize AWS clients
dynamodb = boto3.resource("dynamodb")

# Get environment variables
CHAT_SESSIONS_TABLE = os.environ.get("CHAT_SESSIONS_TABLE")


# --- inline log sanitizer ---------------------------------------------------
# Minimal inline redactor. Kept here rather than importing from idp_common to
# avoid adding a Lambda Layer dependency to this resolver. If this file grows
# to need idp_common anyway, promote to
# `from idp_common.utils.log_sanitizer import sanitize_event_for_logging`.
_LOG_SENSITIVE_KEYS = (
    "password", "secret", "token", "authorization", "apikey", "api_key",
    "cookie", "credential", "claims", "identity",
)


def _sanitize_for_log(obj):
    """Deep-copy `obj` redacting values whose keys match the denylist."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and any(s in k.lower() for s in _LOG_SENSITIVE_KEYS):
                out[k] = "***REDACTED***" if v is not None else None
            else:
                out[k] = _sanitize_for_log(v)
        return out
    if isinstance(obj, list):
        return [_sanitize_for_log(v) for v in obj]
    return obj

def handler(event, context):
    """
    List chat sessions for the current user from the ChatSessionsTable.
    
    Args:
        event: The event dict from AppSync containing:
            - limit: Optional limit for pagination
            - nextToken: Optional pagination token
        context: The Lambda context
        
    Returns:
        ChatSessionConnection with items and nextToken
    """
    logger.info(f"Received list chat sessions event: {json.dumps(_sanitize_for_log(event))}")
    logger.info(f"DEBUG - CHAT_SESSIONS_TABLE env var: {CHAT_SESSIONS_TABLE}")
    
    try:
        # Extract arguments from the event
        arguments = event.get("arguments", {})
        limit = arguments.get("limit", 20)  # Default limit
        next_token = arguments.get("nextToken")
        
        # Get user identity from context
        identity = event.get("identity", {})
        logger.info(f"DEBUG - Full identity context: {json.dumps(identity)}")
        user_id = identity.get("username") or identity.get("sub") or "anonymous"
        
        logger.info(f"Listing chat sessions for user: {user_id}")
        
        # Check if table name is configured
        if not CHAT_SESSIONS_TABLE:
            logger.error("CHAT_SESSIONS_TABLE environment variable not set")
            return {
                "items": [],
                "nextToken": None
            }
        
        # Query the ChatSessionsTable for this user's sessions
        table = dynamodb.Table(CHAT_SESSIONS_TABLE)
        
        # Build query parameters
        query_params = {
            "KeyConditionExpression": "userId = :user_id",
            "ExpressionAttributeValues": {
                ":user_id": user_id
            },
            "ScanIndexForward": False,  # Sort by sessionId descending (most recent first)
            "Limit": limit
        }
        
        if next_token:
            try:
                query_params["ExclusiveStartKey"] = json.loads(next_token)
            except (json.JSONDecodeError, ValueError):
                logger.warn(f"Invalid next_token format: {next_token}")
                # Continue without pagination
        
        # Query the sessions table
        response = table.query(**query_params)
        items = response.get("Items", [])
        
        # Convert DynamoDB items to ChatSession format
        sessions = []
        for item in items:
            session = {
                "sessionId": item.get("sessionId", ""),
                "title": item.get("title", "Untitled Chat"),
                "createdAt": item.get("createdAt", ""),
                "updatedAt": item.get("updatedAt", ""),
                "messageCount": item.get("messageCount", 0),
                "lastMessage": item.get("lastMessage", "")
            }
            sessions.append(session)
        
        # Prepare next token for pagination
        response_next_token = None
        if response.get("LastEvaluatedKey"):
            response_next_token = json.dumps(response["LastEvaluatedKey"])
        
        result = {
            "items": sessions,
            "nextToken": response_next_token
        }
        
        logger.info(f"Returning {len(sessions)} sessions for user {user_id}")
        return result
        
    except ClientError as e:
        error_msg = f"DynamoDB error: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)
    except Exception as e:
        error_msg = f"Error listing chat sessions: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)
