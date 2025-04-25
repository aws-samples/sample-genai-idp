# Copyright © Amazon.com and Affiliates: This deliverable is considered Developed Content as defined in the AWS Service Terms and the SOW between the parties.

import boto3
import os
import json
from datetime import datetime, timezone, timedelta
import logging
from idp_common.models import Document, Status
from idp_common.appsync import DocumentAppSyncService

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
# Get LOG_LEVEL from environment variable with INFO as default

# Initialize clients
sqs = boto3.client('sqs')
appsync_service = DocumentAppSyncService()
queue_url = os.environ['QUEUE_URL']
retentionDays = int(os.environ['DATA_RETENTION_IN_DAYS'])

def handler(event, context):
    logger.info(f"Processing event: {json.dumps(event)}")
    
    detail = event['detail']
    object_key = detail['object']['key']
    logger.info(f"Processing file: {object_key}")
    
    # Get output bucket from environment for the document
    output_bucket = os.environ.get('OUTPUT_BUCKET', '')
    if output_bucket == '':
        raise Exception("OUTPUT_BUCKET environment variable not set")
    
    # Create document object
    current_time = datetime.now(timezone.utc).isoformat()
    document = Document.from_s3_event(event, output_bucket)
    document.status = Status.QUEUED
    document.queued_time = current_time
    
    # Calculate expiry date
    expires_after = int((datetime.now(timezone.utc) + timedelta(days=retentionDays)).timestamp())

    # Create document in DynamoDB via AppSync
    logger.info(f"Creating document via AppSync: {document.input_key}")
    
    # Create document in AppSync with TTL
    created_key = appsync_service.create_document(document, expires_after=expires_after)
    logger.info(f"Document created with key: {created_key}")
    
    # Send serialized document to SQS queue
    doc_json = document.to_json()
    message = {
        'QueueUrl': queue_url,
        'MessageBody': doc_json,
        'MessageAttributes': {
            'EventType': {
                'StringValue': 'DocumentQueued',
                'DataType': 'String'
            },
            'ObjectKey': {
                'StringValue': object_key,
                'DataType': 'String'
            }
        }
    }
    logger.info(f"Sending document to SQS queue: {object_key}")
    response = sqs.send_message(**message)
    logger.info(f"SQS response: {response}")
    
    return {'statusCode': 200, 'detail': detail, 'document_id': document.id}