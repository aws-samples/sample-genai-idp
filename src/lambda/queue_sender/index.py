# Copyright © Amazon.com and Affiliates: This deliverable is considered Developed Content as defined in the AWS Service Terms and the SOW between the parties.

import boto3
import os
import json
from datetime import datetime, timezone, timedelta
import logging
from appsync_helper import AppSyncClient, CREATE_DOCUMENT

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
    
    # Create document using AppSync mutation
    expiresAfter = int((datetime.now(timezone.utc) + timedelta(days=retentionDays)).timestamp())

    create_input = {
        'input': {
            'ObjectKey': object_key,
            'ObjectStatus': 'QUEUED',
            'QueuedTime': datetime.now(timezone.utc).isoformat(),
            'InitialEventTime': event['time'],
            'ExpiresAfter': expiresAfter
        }
    }
    
    logger.info(f"Creating document via AppSync: {create_input}")
    result = appsync.execute_mutation(CREATE_DOCUMENT, create_input)
    logger.info(f"AppSync response: {result}")
    
    # Send to SQS queue
    message = {
        'QueueUrl': queue_url,
        'MessageBody': json.dumps(event)
    }
    logger.info(f"Sending SQS message: {message}")
    response = sqs.send_message(**message)
    logger.info(f"SQS response: {response}")
    
    return {'statusCode': 200, 'detail': detail}