# Copyright © Amazon.com and Affiliates: This deliverable is considered Developed Content as defined in the AWS Service Terms and the SOW between the parties.

import boto3
import os
import json
from datetime import datetime, timezone, timedelta
import logging
from appsync_helper import AppSyncClient, CREATE_DOCUMENT
from idp_common.models import Document, Status

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize clients
sqs = boto3.client('sqs')
appsync = AppSyncClient()
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
    expiresAfter = int((datetime.now(timezone.utc) + timedelta(days=retentionDays)).timestamp())

    # Create document in DynamoDB via AppSync mutation
    create_input = {
        'input': {
            'ObjectKey': object_key,
            'ObjectStatus': document.status.value,
            'QueuedTime': document.queued_time,
            'InitialEventTime': event['time'],
            'ExpiresAfter': expiresAfter
        }
    }
    
    logger.info(f"Creating document via AppSync: {create_input}")
    result = appsync.execute_mutation(CREATE_DOCUMENT, create_input)
    logger.info(f"AppSync response: {result}")
    
    # Add document ID if returned from AppSync
    if 'id' in result.get('createDocument', {}):
        document.id = result['createDocument']['id']
    
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