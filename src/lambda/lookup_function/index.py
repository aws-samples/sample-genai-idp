# Copyright © Amazon.com and Affiliates: This deliverable is considered Developed Content as defined in the AWS Service Terms and the SOW between the parties.

import boto3
import json
import os
from datetime import datetime, timezone
import logging

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
# Get LOG_LEVEL from environment variable with INFO as default

def calculate_durations(timestamps):
    try:
        durations = {}
        if 'QueuedTime' in timestamps and 'WorkflowStartTime' in timestamps:
            queue_time = (datetime.fromisoformat(timestamps['WorkflowStartTime']) - 
                         datetime.fromisoformat(timestamps['QueuedTime'])).total_seconds() * 1000
            durations['queue'] = int(queue_time)
            
        if 'WorkflowStartTime' in timestamps and 'CompletionTime' in timestamps:
            processing_time = (datetime.fromisoformat(timestamps['CompletionTime']) - 
                             datetime.fromisoformat(timestamps['WorkflowStartTime'])).total_seconds() * 1000
            durations['processing'] = int(processing_time)
            
        if 'InitialEventTime' in timestamps and 'CompletionTime' in timestamps:
            total_time = (datetime.fromisoformat(timestamps['CompletionTime']) - 
                         datetime.fromisoformat(timestamps['InitialEventTime'])).total_seconds() * 1000
            durations['total'] = int(total_time)
            
        return durations
    except Exception as e:
        logger.error(f"Error calculating durations: {e}", exc_info=True)
        return {}

def handler(event, context):

    logger.info(f"Event: {json.dumps(event)}")

    object_key = event.get('object_key')
    if not object_key:
        return {'status': 'ERROR', 'message': 'object_key is required'}
    
    dynamodb = boto3.resource('dynamodb')
    tracking_table = dynamodb.Table(os.environ['TRACKING_TABLE'])
    sfn = boto3.client('stepfunctions')
    
    try:
        PK = f"doc#{object_key}"
        response = tracking_table.get_item(
            Key={'PK': PK, 'SK': "none"},
            ConsistentRead=True
        )
        
        if 'Item' not in response:
            return {'status': 'NOT_FOUND'}
            
        item = response['Item']
        timestamps = {
            'InitialEventTime': item.get('InitialEventTime'),
            'QueuedTime': item.get('QueuedTime'),
            'WorkflowStartTime': item.get('WorkflowStartTime'),
            'CompletionTime': item.get('CompletionTime')
        }
        
        result = {
            'status': item.get('ObjectStatus'),
            'timing': {
                'timestamps': timestamps,
                'elapsed': calculate_durations(timestamps)
            }
        }
        
        execution_arn = item.get('WorkflowExecutionArn')
        if execution_arn:
            try:
                execution = sfn.describe_execution(executionArn=execution_arn)
                history = sfn.get_execution_history(
                    executionArn=execution_arn,
                    maxResults=100
                )
                
                result['processingDetail'] = {
                    'executionArn': execution_arn,
                    'execution': {k: str(v) if isinstance(v, datetime) else v 
                                for k, v in execution.items() 
                                if k != 'ResponseMetadata'},
                    'events': [{k: str(v) if isinstance(v, datetime) else v 
                              for k, v in event.items()}
                              for event in history['events']]
                }
            except Exception as e:
                logger.error(f"Error getting Step Functions details: {e}", exc_info=True)
                result['processingDetail'] = {
                    'executionArn': execution_arn,
                    'error': str(e)
                }
        
        return result
        
    except Exception as e:
        logger.error(f"Error looking up document: {e}", exc_info=True)
        return {
            'status': 'ERROR',
            'message': str(e)
        }