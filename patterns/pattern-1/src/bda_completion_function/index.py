# Copyright © Amazon.com and Affiliates: This deliverable is considered Developed Content as defined in the AWS Service Terms and the SOW between the parties.
import json
import logging
import boto3
import os
from idp_common import metrics

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
stepfunctions = boto3.client('stepfunctions')
tracking_table = dynamodb.Table(os.environ['TRACKING_TABLE'])

METRIC_NAMESPACE = os.environ['METRIC_NAMESPACE']

def get_task_token(object_key: str) -> str:
    try:
        # Get current tracking record using consistent read
        key = f"tasktoken#{object_key}"
        logger.info(f"Performing consistent read for tracking record: {key}")
        response = tracking_table.get_item(
            Key={'PK': key, 'SK': 'none'},
            ConsistentRead=True
        )
        
        if 'Item' not in response:
            error_msg = f"No tracking record found for {key} (with consistent read)"
            logger.error(error_msg)
            raise Exception(error_msg)
        
        item = response['Item']
        return item['TaskToken']

    except Exception as e:
        logger.error(f"Error retrieving tracking record: {e}")
        raise

# Using metrics.put_metric directly

def send_task_response(task_token, job_status, job_detail):
    metrics.put_metric('BDAJobsTotal', 1)
    try:
        if job_status == 'SUCCESS':
            logger.info(f"Sending task success for token: {task_token}")
            stepfunctions.send_task_success(
                taskToken=task_token,
                output=json.dumps({
                    'status': "SUCCESS",
                    'job_detail': job_detail
                })
            )
            metrics.put_metric('BDAJobsSucceeded', 1)
        else:
            logger.info(f"Sending task failure for token: {task_token}")
            stepfunctions.send_task_failure(
                taskToken=task_token,
                error='JobExecutionError',
                cause=job_detail.get('error_message') or 'Job execution failed'
            )
            metrics.put_metric('BDAJobsFailed', 1)
    except Exception as e:
        logger.error(f"Error sending task response: {e}")
        raise

def handler(event, context):
    logger.info(f"Event: {json.dumps(event)}")
    
    try:
        # Extract required information from event
        detail = event['detail']
        object_key = detail['input_s3_object']['name']
        job_status = detail['job_status']
        
        logger.info(f"Processing job completion for object: {object_key}, status: {job_status}")
        
        # Get the task token from DynamoDB
        task_token = get_task_token(object_key)
        logger.info(f"Retrieved task_token: {task_token}")
        
        # Send appropriate response to Step Functions
        send_task_response(task_token, job_status, detail)
        
        response = {
            'statusCode': 200,
            'body': 'Task response sent successfully'
        }
        logger.info(f"Response: {json.dumps(response, default=str)}")
        return response
        
    except Exception as e:
        logger.error(f"Error processing event: {e}")
        raise