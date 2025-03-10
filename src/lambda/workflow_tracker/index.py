import boto3
import json
import os
from datetime import datetime, timezone
import logging
from appsync_helper import AppSyncClient, UPDATE_DOCUMENT, AppSyncError
import requests
from botocore.exceptions import ClientError
from typing import Dict, Any, Optional, List

logger = logging.getLogger()
logger.setLevel(logging.INFO)

METRIC_NAMESPACE = os.environ['METRIC_NAMESPACE']
OUTPUT_BUCKET = os.environ['OUTPUT_BUCKET']

dynamodb = boto3.resource('dynamodb')
cloudwatch = boto3.client('cloudwatch')
s3 = boto3.client('s3')
appsync = AppSyncClient()
concurrency_table = dynamodb.Table(os.environ['CONCURRENCY_TABLE'])
COUNTER_ID = 'workflow_counter'


def update_document_completion(object_key: str, workflow_status: str, output_data: str) -> Dict[str, Any]:
    """
    Update document completion status via AppSync
    """
    completionTime = datetime.now(timezone.utc).isoformat()
    pageCount = 0
    sections = []
    pages = []
    # Get sections and pages data if workflow succeeded
    if workflow_status == 'SUCCEEDED':
        sections = output_data.get("Sections",[])
        pages = output_data.get("Pages",[])
        pageCount = output_data.get("PageCount",0)

    
    update_input = {
        'input': {
            'ObjectKey': object_key,
            'ObjectStatus': 'COMPLETED' if workflow_status == 'SUCCEEDED' else 'FAILED',
            'CompletionTime': completionTime,
            'WorkflowStatus': workflow_status,
            'PageCount': pageCount,
            'Sections': sections,
            'Pages': pages
        }
    }
    
    logger.info(f"Updating document via AppSync: {update_input}")
    result = appsync.execute_mutation(UPDATE_DOCUMENT, update_input)
    return result['updateDocument']


def put_latency_metrics(item: Dict[str, Any]) -> None:
    """
    Publish latency metrics to CloudWatch
    
    Args:
        item: Document data containing timestamps
        
    Raises:
        ValueError: If required timestamps are missing
        ClientError: If CloudWatch operation fails
    """
    try:
        # Validate required timestamps
        required_timestamps = ['InitialEventTime', 'QueuedTime', 'WorkflowStartTime']
        missing = [ts for ts in required_timestamps if not item.get(ts)]
        if missing:
            raise ValueError(f"Missing required timestamps: {', '.join(missing)}")

        now = datetime.now(timezone.utc)
        initial_time = datetime.fromisoformat(item['InitialEventTime'])
        QueuedTime = datetime.fromisoformat(item['QueuedTime'])
        WorkflowStartTime = datetime.fromisoformat(item['WorkflowStartTime'])
        
        queue_latency = (WorkflowStartTime - QueuedTime).total_seconds() * 1000
        workflow_latency = (now - WorkflowStartTime).total_seconds() * 1000
        total_latency = (now - initial_time).total_seconds() * 1000
        
        logger.info(
            f"Publishing latency metrics - queue: {queue_latency}ms, "
            f"workflow: {workflow_latency}ms, total: {total_latency}ms"
        )
        
        cloudwatch.put_metric_data(
            Namespace=f'{METRIC_NAMESPACE}',
            MetricData=[
                {
                    'MetricName': 'QueueLatencyMilliseconds',
                    'Value': queue_latency,
                    'Unit': 'Milliseconds'
                },
                {
                    'MetricName': 'WorkflowLatencyMilliseconds',
                    'Value': workflow_latency,
                    'Unit': 'Milliseconds'
                },
                {
                    'MetricName': 'TotalLatencyMilliseconds',
                    'Value': total_latency,
                    'Unit': 'Milliseconds'
                }
            ]
        )
    except ValueError as e:
        logger.error(f"Invalid timestamps in metrics data: {e}")
        raise
    except ClientError as e:
        logger.error(f"Failed to publish CloudWatch metrics: {e}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Unexpected error publishing metrics: {e}", exc_info=True)
        raise

def decrement_counter() -> Optional[int]:
    """
    Decrement the concurrency counter
    
    Returns:
        The new counter value or None if operation failed
        
    Note: This function handles its own errors
    """
    try:
        logger.info("Decrementing concurrency counter")
        response = concurrency_table.update_item(
            Key={'counter_id': COUNTER_ID},
            UpdateExpression='ADD active_count :dec',
            ExpressionAttributeValues={':dec': -1},
            ReturnValues='UPDATED_NEW'
        )
        new_count = response.get('Attributes', {}).get('active_count')
        logger.info(f"Counter decremented. New value: {new_count}")
        return new_count
    except ClientError as e:
        logger.error(f"Failed to decrement counter: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Unexpected error decrementing counter: {e}", exc_info=True)
        return None

def handler(event, context):
    logger.info(f"Processing event: {json.dumps(event)}")
    counter_value = None

    try:
        # Extract data from event
        input_data = json.loads(event['detail']['input'])
        output_data = None
        if event['detail'].get('output'):
            output_data = json.loads(event['detail']['output'])
        object_key = input_data['detail']['object']['key']
        workflow_status = event['detail']['status']
        
        # Update document completion status
        updated_doc = update_document_completion(object_key, workflow_status, output_data)
        
        # Publish metrics for successful executions
        if workflow_status == 'SUCCEEDED':
            try:
                logger.info("Workflow succeeded, publishing latency metrics")
                put_latency_metrics(updated_doc)
            except Exception as metrics_error:
                logger.error(f"Failed to publish metrics: {metrics_error}", exc_info=True)
                # Continue processing even if metrics fail
        else:
            logger.info(
                f"Workflow did not succeed (status: {workflow_status}), "
                "skipping latency metrics"
            )
        
        # Always decrement counter
        counter_value = decrement_counter()
        
        return {
            'statusCode': 200,
            'body': {
                'object_key': object_key,
                'workflow_status': workflow_status,
                'completionTime': updated_doc['CompletionTime'],
                'counter_value': counter_value
            }
        }
        
    except Exception as e:
        logger.error(f"Unexpected error in handler: {str(e)}", exc_info=True)
        # Always try to decrement counter in case of any error
        if counter_value is None: # semgrep-ignore: identical-is-comparison - Correctly checking for None.
            decrement_counter()
        raise