# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import os
import boto3
import logging
from datetime import datetime, timezone, timedelta

# Import IDP Common modules
from idp_common.models import Document, Status
from idp_common.docs_service import create_document_service

logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

# Initialize AWS clients
sqs_client = boto3.client('sqs')
s3_client = boto3.client('s3')

# Initialize document service (same as queue_sender - defaults to AppSync)
document_service = create_document_service()

# Environment variables
queue_url = os.environ.get('QUEUE_URL')
input_bucket = os.environ.get('INPUT_BUCKET')
output_bucket = os.environ.get('OUTPUT_BUCKET')
retentionDays = int(os.environ.get('DATA_RETENTION_IN_DAYS', '365'))

def handler(event, context):
    logger.info(f"Reprocess resolver invoked with event: {json.dumps(event)}")
    
    try:
        # Validate environment variables
        if not input_bucket:
            raise Exception("INPUT_BUCKET environment variable is not set")
        if not output_bucket:
            raise Exception("OUTPUT_BUCKET environment variable is not set")
        if not queue_url:
            raise Exception("QUEUE_URL environment variable is not set")
        
        # Extract arguments from GraphQL event
        args = event.get('arguments', {})
        object_keys = args.get('objectKeys', [])
        version = args.get('version')  # Optional version parameter
        
        if not object_keys:
            logger.error("objectKeys is required but not provided")
            return False
        
        logger.info(f"Reprocessing {len(object_keys)} documents" + (f" with version: {version}" if version else ""))
        
        # Process each document
        success_count = 0
        for object_key in object_keys:
            try:
                reprocess_document(object_key, version)
                success_count += 1
            except Exception as e:
                logger.error(f"Error reprocessing document {object_key}: {str(e)}", exc_info=True)
                # Continue with other documents even if one fails
        
        logger.info(f"Successfully queued {success_count}/{len(object_keys)} documents for reprocessing")
        return True
        
    except Exception as e:
        logger.error(f"Error in reprocess handler: {str(e)}", exc_info=True)
        raise e

def reprocess_document(object_key, version=None):
    """
    Reprocess a document by creating a fresh Document object and queueing it.
    This exactly mirrors the queue_sender pattern for consistency and avoids
    S3 copy operations that can trigger duplicate events for large files.
    
    Args:
        object_key: S3 object key of the document to reprocess
        version: Optional configuration version to use for reprocessing
    """
    logger.info(f"Reprocessing document: {object_key}" + (f" with version: {version}" if version else ""))
    
    # Verify file exists in S3
    try:
        s3_client.head_object(Bucket=input_bucket, Key=object_key)
    except Exception as e:
        raise ValueError(f"Document {object_key} not found in S3 bucket {input_bucket}: {str(e)}")
    
    # Create a fresh Document object (same as queue_sender does)
    current_time = datetime.now(timezone.utc).isoformat()
    
    document = Document(
        id=object_key,  # Document ID is the object key
        input_bucket=input_bucket,
        input_key=object_key,
        output_bucket=output_bucket,
        status=Status.QUEUED,
        queued_time=current_time,
        initial_event_time=current_time,
        pages={},
        sections=[],
        config_version=version,  # Set the configuration version if provided
    )
    
    logger.info(f"Created fresh document object for reprocessing: {object_key}")
    
    # Calculate expiry date (same as queue_sender)
    expires_after = int((datetime.now(timezone.utc) + timedelta(days=retentionDays)).timestamp())
    
    # Create document in DynamoDB via document service (same as queue_sender - uses AppSync by default)
    logger.info(f"Creating document via document service: {document.input_key}")
    created_key = document_service.create_document(document, expires_after=expires_after)
    logger.info(f"Document created with key: {created_key}")
    
    # Send serialized document to SQS queue (same as queue_sender)
    doc_json = document.to_json()
    message = {
        'QueueUrl': queue_url,
        'MessageBody': doc_json,
        'MessageAttributes': {
            'EventType': {
                'StringValue': 'DocumentReprocessed',
                'DataType': 'String'
            },
            'ObjectKey': {
                'StringValue': object_key,
                'DataType': 'String'
            }
        }
    }
    logger.info(f"Sending document to SQS queue: {object_key}")
    response = sqs_client.send_message(**message)
    logger.info(f"SQS response: {response}")
    
    logger.info(f"Successfully reprocessed document: {object_key}")
    return response.get('MessageId')
