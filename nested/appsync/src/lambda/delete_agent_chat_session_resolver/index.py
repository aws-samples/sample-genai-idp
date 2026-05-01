# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Lambda function to delete an agent chat session and all its messages.
This function deletes the session metadata from ChatSessionsTable and all messages from ChatMessagesTable.
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
CHAT_MESSAGES_TABLE = os.environ.get("CHAT_MESSAGES_TABLE")
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
    Delete an agent chat session and all its messages.
    
    Args:
        event: The event dict from AppSync containing:
            - sessionId: The session ID to delete
        context: The Lambda context
        
    Returns:
        Boolean indicating success
    """
    logger.info(f"Received delete agent chat session event: {json.dumps(_sanitize_for_log(event))}")
    
    try:
        # Extract arguments from the event
        arguments = event.get("arguments", {})
        session_id = arguments.get("sessionId")
        
        if not session_id:
            raise ValueError("sessionId parameter is required")
        
        # Get user identity from context for security
        identity = event.get("identity", {})
        user_id = identity.get("username") or identity.get("sub") or "anonymous"
        
        logger.info(f"Deleting agent chat session {session_id} (user: {user_id})")
        
        # Initialize both tables
        messages_table = dynamodb.Table(CHAT_MESSAGES_TABLE)
        sessions_table = dynamodb.Table(CHAT_SESSIONS_TABLE)
        
        # Step 1: Delete session metadata from ChatSessionsTable
        try:
            sessions_table.delete_item(
                Key={
                    "userId": user_id,
                    "sessionId": session_id
                }
            )
            logger.info(f"Deleted session metadata for {session_id}")
        except ClientError as e:
            # Log but don't fail if session metadata doesn't exist
            logger.warn(f"Could not delete session metadata: {str(e)}")
        
        # Step 2: Delete all messages from ChatMessagesTable
        response = messages_table.query(
            KeyConditionExpression="PK = :session_id",
            ExpressionAttributeValues={
                ":session_id": session_id
            },
            ProjectionExpression="PK, SK"  # Only need keys for deletion
        )
        
        items = response.get("Items", [])
        
        if not items:
            logger.info(f"No messages found for session {session_id}")
            return True  # Session doesn't exist, consider it successfully deleted
        
        # Delete all messages in batches
        deleted_count = 0
        
        # DynamoDB batch_writer handles batching automatically
        with messages_table.batch_writer() as batch:
            for item in items:
                batch.delete_item(
                    Key={
                        "PK": item["PK"],
                        "SK": item["SK"]
                    }
                )
                deleted_count += 1
        
        logger.info(f"Successfully deleted session metadata and {deleted_count} messages for session {session_id}")
        return True
        
    except ClientError as e:
        error_msg = f"DynamoDB error: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)
    except ValueError as e:
        # Re-raise validation errors so they become GraphQL errors
        logger.error(f"Validation error: {str(e)}")
        raise e
    except Exception as e:
        error_msg = f"Error deleting agent chat session: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)
