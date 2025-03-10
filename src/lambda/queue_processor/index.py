import boto3
import json
import os
from datetime import datetime, timezone
from botocore.exceptions import ClientError
import logging
from appsync_helper import AppSyncClient, UPDATE_DOCUMENT, AppSyncError
import requests
from typing import Dict, Any, List, Tuple

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sfn = boto3.client('stepfunctions')
dynamodb = boto3.resource('dynamodb')
appsync = AppSyncClient()
concurrency_table = dynamodb.Table(os.environ['CONCURRENCY_TABLE'])
state_machine_arn = os.environ['STATE_MACHINE_ARN']
MAX_CONCURRENT = int(os.environ.get('MAX_CONCURRENT', '5'))
COUNTER_ID = 'workflow_counter'

def update_counter(increment: bool = True) -> bool:
    """
    Update the concurrency counter
    
    Args:
        increment: Whether to increment (True) or decrement (False) the counter
        
    Returns:
        bool: True if update successful, False if at limit
        
    Raises:
        ClientError: If DynamoDB operation fails
    """
    logger.info(f"Updating counter: increment={increment}, max={MAX_CONCURRENT}")
    try:
        update_args = {
            'Key': {'counter_id': COUNTER_ID},
            'UpdateExpression': 'ADD active_count :inc',
            'ExpressionAttributeValues': {
                ':inc': 1 if increment else -1,
                ':max': MAX_CONCURRENT
            },
            'ReturnValues': 'UPDATED_NEW'
        }
        
        if increment:
            update_args['ConditionExpression'] = 'active_count < :max'
        
        logger.info(f"Counter update args: {update_args}")
        response = concurrency_table.update_item(**update_args)
        logger.info(f"Counter update response: {response}")
        return True
        
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            logger.warning("Concurrency limit reached")
            return False
        logger.error(f"Error updating counter: {e}")
        raise

def start_workflow(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Start Step Functions workflow
    
    Args:
        body: The workflow input
        
    Returns:
        Dict containing execution details
        
    Raises:
        ClientError: If Step Functions operation fails
    """
    execution = sfn.start_execution(
        stateMachineArn=state_machine_arn,
        input=json.dumps(body)
    )
    logger.info(f"Workflow started: {execution['executionArn']}")
    return execution

def update_document_status(object_key: str, execution_arn: str) -> Dict[str, Any]:
    """
    Update document status via AppSync
    
    Args:
        object_key: The document key
        execution_arn: The Step Functions execution ARN
        
    Returns:
        The updated document data
        
    Raises:
        AppSyncError: If the GraphQL operation fails
    """
    update_input = {
        'input': {
            'ObjectKey': object_key,
            'ObjectStatus': 'STARTED',
            'WorkflowExecutionArn': execution_arn,
            'WorkflowStartTime': datetime.now(timezone.utc).isoformat()
        }
    }
    
    logger.info(f"Updating document via AppSync: {update_input}")
    result = appsync.execute_mutation(UPDATE_DOCUMENT, update_input)
    return result['updateDocument']

def process_message(record: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Process a single SQS message
    
    Args:
        record: The SQS message record
        
    Returns:
        Tuple of (success, message_id)
        
    Note: This function handles its own errors and returns success/failure
    """
    message = record['body']
    message_id = record['messageId']
    
    try:
        body = json.loads(message)
        object_key = body['detail']['object']['key']
        logger.info(f"Processing message {message_id} for object {object_key}")
        
        # Try to increment counter
        if not update_counter(increment=True):
            logger.warning(f"Concurrency limit reached for {object_key}")
            return False, message_id
        
        try:
            # Start workflow
            execution = start_workflow(body)
            
            # Update document
            document = update_document_status(object_key, execution['executionArn'])
            logger.info(f"Document updated: {document}")
            
            return True, message_id
            
        except Exception as e:
            logger.error(f"Error processing {object_key}: {str(e)}", exc_info=True)
            # Decrement counter on failure
            try:
                update_counter(increment=False)
            except Exception as counter_error:
                logger.error(f"Failed to decrement counter: {counter_error}", exc_info=True)
            return False, message_id
            
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in message {message_id}: {str(e)}")
        return False, message_id
        
    except KeyError as e:
        logger.error(f"Missing required field in message {message_id}: {str(e)}")
        return False, message_id
        
    except Exception as e:
        logger.error(f"Unexpected error processing message {message_id}: {str(e)}", exc_info=True)
        return False, message_id

def handler(event, context):
    logger.info(f"Processing event: {json.dumps(event)}")
    logger.info(f"Processing batch of {len(event['Records'])} messages")
    
    failed_message_ids = []
    
    for record in event['Records']:
        success, message_id = process_message(record)
        if not success:
            failed_message_ids.append(message_id)
    
    return {
        "batchItemFailures": [
            {"itemIdentifier": message_id} for message_id in failed_message_ids
        ]
    }