# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import os
import boto3
import logging
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from idp_common.models import Document, Status

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

sqs = boto3.client('sqs')

# These will be set by environment variables in Lambda, but defaulted for testing
QUEUE_URL = os.environ.get('QUEUE_URL', '')
APPSYNC_API_URL = os.environ.get('APPSYNC_API_URL', '')
DATA_RETENTION_IN_DAYS = int(os.environ.get('DATA_RETENTION_IN_DAYS', '30'))
OUTPUT_BUCKET = os.environ.get('OUTPUT_BUCKET', '')


def extract_user_id_from_path(object_key):
    """
    Extract user ID from S3 object key path.
    Expected format: users/<user_id>/filename.ext
    
    Args:
        object_key: S3 object key
        
    Returns:
        str: User ID extracted from path
        
    Raises:
        ValueError: If path format is invalid
    """
    if not object_key.startswith('users/'):
        raise ValueError(f"Invalid path format. Expected 'users/<user_id>/', got: {object_key}")
    
    # Split path and extract user ID
    parts = object_key.split('/')
    if len(parts) < 3:
        raise ValueError(f"Invalid path structure. Expected at least 3 parts, got: {object_key}")
    
    user_id = parts[1]
    
    if not user_id:
        raise ValueError(f"User ID is empty in path: {object_key}")
    
    logger.info(f"Extracted user_id: {user_id} from path: {object_key}")
    return user_id


def validate_user_id(user_id):
    """
    Validate that user ID looks like a Cognito UUID.
    Logs warning if format doesn't match but allows it through.
    
    Args:
        user_id: User ID to validate
        
    Returns:
        str: The user ID (unchanged)
    """
    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    if not re.match(uuid_pattern, user_id, re.IGNORECASE):
        logger.warning(f"User ID doesn't match UUID pattern: {user_id}")
    return user_id


def handler(event, context):
    """
    Handles S3 Object Created events from EventBridge.
    Extracts user context from S3 path and sends to SQS with UserId.
    
    Args:
        event: EventBridge event for S3 Object Created
        context: Lambda context
        
    Returns:
        dict: Response with status
    """
    logger.info(f"QueueSender invoked with event: {json.dumps(event)}")
    
    try:
        # Extract S3 event details
        detail = event.get('detail', {})
        bucket_name = detail.get('bucket', {}).get('name')
        object_key = detail.get('object', {}).get('key')
        
        if not bucket_name or not object_key:
            raise ValueError("Missing bucket name or object key in event")
        
        logger.info(f"Processing S3 event: bucket={bucket_name}, key={object_key}")
        
        # Extract user ID from path
        try:
            user_id = extract_user_id_from_path(object_key)
            user_id = validate_user_id(user_id)
        except ValueError as e:
            logger.error(f"Path validation error: {str(e)}")
            # This will go to DLQ for investigation
            raise
        
        # Create a Document object (same pattern as reprocess_document_resolver)
        current_time = datetime.now(timezone.utc).isoformat()
        event_time = detail.get('object', {}).get('last-modified') or current_time
        
        document = Document(
            id=object_key,
            input_bucket=bucket_name,
            input_key=object_key,
            output_bucket=OUTPUT_BUCKET,
            status=Status.QUEUED,
            queued_time=event_time,
            initial_event_time=event_time,
            user_id=user_id,
            pages={},
            sections=[],
        )
        
        logger.info(f"Created document object for user {user_id}: {object_key}")
        
        # Calculate expiry timestamp
        expires_after = int((datetime.now(timezone.utc) + timedelta(days=DATA_RETENTION_IN_DAYS)).timestamp())
        
        # Serialize document to JSON
        doc_json = document.to_json()
        
        # Prepare SQS message with document and metadata
        message_body = doc_json
        
        logger.info(f"Sending message to SQS with UserId: {user_id}")
        
        # Send to SQS
        queue_url = os.environ.get('QUEUE_URL', QUEUE_URL)  # Use runtime env var if available
        response = sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=message_body,
            MessageAttributes={
                'UserId': {
                    'StringValue': user_id,
                    'DataType': 'String'
                },
                'ObjectKey': {
                    'StringValue': object_key,
                    'DataType': 'String'
                },
                'ExpiresAfter': {
                    'StringValue': str(expires_after),
                    'DataType': 'Number'
                }
            }
        )
        
        logger.info(f"Successfully sent message to SQS. MessageId: {response['MessageId']}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Successfully queued document',
                'messageId': response['MessageId'],
                'userId': user_id,
                'objectKey': object_key
            })
        }
        
    except Exception as e:
        logger.error(f"Error in QueueSender: {str(e)}", exc_info=True)
        raise