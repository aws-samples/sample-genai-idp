# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Lambda function to get agent chat messages for a specific session.
This function queries the ChatMessagesTable by sessionId and returns messages in chronological order.
"""

import copy
import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


# Minimal inline log-sanitizer. Kept here rather than importing from
# idp_common to avoid adding a Lambda Layer dependency to this small
# resolver. If this file grows further, promote it to use
# idp_common.utils.log_sanitizer.sanitize_event_for_logging instead.
_LOG_SENSITIVE_KEYS = (
    "password",
    "secret",
    "token",
    "authorization",
    "apikey",
    "api_key",
    "cookie",
    "credential",
    "claims",
    "identity",
)


def _sanitize_for_log(obj):
    """Return a deep-copied version of obj with sensitive keys redacted.

    Matches AppSync event shapes: event.identity.claims is the primary
    leak vector (Cognito sub, email, groups, cognito:groups).
    """
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
    return copy.copy(obj)


# Initialize AWS clients
dynamodb = boto3.resource("dynamodb")

# Get environment variables
CHAT_MESSAGES_TABLE = os.environ.get("CHAT_MESSAGES_TABLE")
CHAT_SESSIONS_TABLE = os.environ.get("CHAT_SESSIONS_TABLE")

# Feature flag: enforce that the calling Cognito user owns the session before
# returning messages. Defaults to "true". An operator can set this to "false"
# via the ENFORCE_CHAT_SESSION_OWNERSHIP environment variable to restore the
# pre-fix behavior during migration (e.g., if legacy sessions predate the
# ChatSessionsTable and need to be accessible to administrators). We log a
# warning when the enforcement is disabled.
ENFORCE_CHAT_SESSION_OWNERSHIP = (
    os.environ.get("ENFORCE_CHAT_SESSION_OWNERSHIP", "true").lower() != "false"
)


def _verify_session_ownership(session_id: str, user_id: str) -> bool:
    """Return True if the given user owns the given chat session.

    Looks up the session metadata in ChatSessionsTable (PK=userId, SK=sessionId).
    If the session record does not exist for this user, ownership cannot be
    established and access MUST be denied. If the sessions table is not
    configured (early-deployment state), we log a warning and return True
    to preserve functionality — operators are expected to set CHAT_SESSIONS_TABLE.
    """
    if not CHAT_SESSIONS_TABLE:
        logger.warning(
            "CHAT_SESSIONS_TABLE is not configured; cannot verify chat session "
            "ownership. Allowing access; set CHAT_SESSIONS_TABLE in the Lambda "
            "environment to enable ownership enforcement."
        )
        return True

    try:
        sessions_table = dynamodb.Table(CHAT_SESSIONS_TABLE)
        response = sessions_table.get_item(
            Key={"userId": user_id, "sessionId": session_id}
        )
        return "Item" in response
    except ClientError as e:
        # Fail-closed: on any DynamoDB error during ownership check, deny access.
        logger.error(
            f"Error verifying session ownership for user={user_id} "
            f"session={session_id}: {e}"
        )
        return False


def handler(event, context):
    """
    Get agent chat messages for a specific session.

    Args:
        event: The event dict from AppSync containing:
            - sessionId: The session ID to retrieve messages for
        context: The Lambda context

    Returns:
        List of AgentChatMessage objects
    """
    # Log a redacted copy — event.identity.claims contains Cognito user info.
    logger.info(
        f"Received get agent chat messages event: "
        f"{json.dumps(_sanitize_for_log(event))}"
    )

    try:
        # Extract arguments from the event
        arguments = event.get("arguments", {})
        session_id = arguments.get("sessionId")

        if not session_id:
            raise ValueError("sessionId parameter is required")

        # Get user identity from context for security
        identity = event.get("identity", {})
        user_id = identity.get("username") or identity.get("sub") or "anonymous"

        logger.info(
            f"Getting agent chat messages for session {session_id} (user: {user_id})"
        )

        # Authorization: enforce that the calling user owns the requested
        # session. Chat sessions can contain sensitive PII (user queries,
        # document content quoted by the LLM), so same-account Cognito
        # authentication alone is not sufficient. We verify ownership via
        # the ChatSessionsTable which is keyed (userId, sessionId).
        if ENFORCE_CHAT_SESSION_OWNERSHIP:
            if user_id == "anonymous":
                logger.warning(
                    "Rejecting getChatMessages request with no resolvable user "
                    "identity in event.identity (username/sub both absent)."
                )
                raise Exception("Unauthorized: caller identity not available.")
            if not _verify_session_ownership(session_id, user_id):
                logger.warning(
                    f"Rejecting getChatMessages: user={user_id} does not own "
                    f"session={session_id}"
                )
                raise Exception("Unauthorized: session not found for this user.")
        else:
            logger.warning(
                "ENFORCE_CHAT_SESSION_OWNERSHIP is disabled. Skipping "
                "session-ownership check for user=%s session=%s.",
                user_id,
                session_id,
            )

        # Query the ChatMessagesTable for this specific session
        table = dynamodb.Table(CHAT_MESSAGES_TABLE)

        # Query by PK (sessionId) to get all messages for this session
        response = table.query(
            KeyConditionExpression="PK = :session_id",
            ExpressionAttributeValues={":session_id": session_id},
            ScanIndexForward=True,  # Sort by SK (timestamp) in ascending order
        )

        items = response.get("Items", [])

        # Convert DynamoDB items to AgentChatMessage format
        messages = []
        for item in items:
            message = {
                "role": item.get("role", ""),
                "content": item.get("content", ""),
                "timestamp": item.get("timestamp", ""),
                "isProcessing": item.get("isProcessing", False),
                "sessionId": item.get("PK", ""),  # PK is the sessionId
            }
            messages.append(message)

        logger.info(f"Returning {len(messages)} messages for session {session_id}")
        return messages

    except ClientError as e:
        error_msg = f"DynamoDB error: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)
    except ValueError as e:
        # Re-raise validation errors so they become GraphQL errors
        logger.error(f"Validation error: {str(e)}")
        raise e
    except Exception as e:
        error_msg = f"Error getting agent chat messages: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)
