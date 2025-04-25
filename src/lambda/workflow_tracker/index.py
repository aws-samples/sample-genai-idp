import boto3
import json
import os
from datetime import datetime, timezone
import logging
from idp_common.models import Document, Status, Page, Section
from idp_common.appsync import DocumentAppSyncService
from botocore.exceptions import ClientError
from typing import Dict, Any, Optional

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
# Get LOG_LEVEL from environment variable with INFO as default

METRIC_NAMESPACE = os.environ['METRIC_NAMESPACE']

dynamodb = boto3.resource('dynamodb')
cloudwatch = boto3.client('cloudwatch')
s3 = boto3.client('s3')
appsync_service = DocumentAppSyncService()
concurrency_table = dynamodb.Table(os.environ['CONCURRENCY_TABLE'])
COUNTER_ID = 'workflow_counter'


def update_document_completion(object_key: str, workflow_status: str, output_data: Dict[str, Any]) -> Document:
    """
    Update document completion status via AppSync
    
    Args:
        object_key: The document object key (ID)
        workflow_status: The final workflow status (SUCCEEDED or FAILED)
        output_data: The output data from the workflow execution
        
    Returns:
        The updated Document object
    """
    # Create a document with basic properties
    document = Document(
        id=object_key,
        input_key=object_key,
        status=Status.PROCESSED if workflow_status == 'SUCCEEDED' else Status.FAILED,
        completion_time=datetime.now(timezone.utc).isoformat()
    )
    
    # Get sections, pages, and metering data if workflow succeeded
    if workflow_status == 'SUCCEEDED' and output_data:
        try:
            # Get the processed document from the output data 
            workflow_result = output_data.get("Result", {})
            
            if "document" in workflow_result:
                # Get document from the final processing step - this contains all data
                processed_doc = Document.from_dict(workflow_result.get("document", {}))
                
                # Copy data from processed document to our update document
                document.num_pages = processed_doc.num_pages
                document.pages = processed_doc.pages
                document.sections = processed_doc.sections
                document.metering = processed_doc.metering
                document.summary_report_uri = processed_doc.summary_report_uri
            else:
                logger.warning("No document found in Result")
                
        except Exception as e:
            logger.warning(f"Could not extract document data: {e}")
    
    # Update document in AppSync
    logger.info(f"Updating document via AppSync: {document.to_json()}")
    updated_doc = appsync_service.update_document(document)
    
    return updated_doc


def put_latency_metrics(document: Document) -> None:
    """
    Publish latency metrics to CloudWatch
    
    Args:
        document: Document object containing timestamps
        
    Raises:
        ValueError: If required timestamps are missing
        ClientError: If CloudWatch operation fails
    """
    try:
        # Check required timestamps
        if not document.queued_time or not document.start_time:
            missing = []
            if not document.queued_time:
                missing.append("queued_time")
            if not document.start_time:
                missing.append("start_time")
            raise ValueError(f"Missing required timestamps: {', '.join(missing)}")

        now = datetime.now(timezone.utc)
        initial_time = datetime.fromisoformat(document.start_time)
        queued_time = datetime.fromisoformat(document.queued_time)
        workflow_start_time = datetime.fromisoformat(document.start_time)
        
        queue_latency = (workflow_start_time - queued_time).total_seconds() * 1000
        workflow_latency = (now - workflow_start_time).total_seconds() * 1000
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
        
        # Get object key from document
        try:
            if "document" in input_data:
                object_key = input_data["document"]["input_key"]
            else:
                raise ValueError("Unable to find object key in input")
        except (KeyError, TypeError) as e:
            logger.error(f"Error extracting object_key from input: {e}")
            logger.error(f"Input data structure: {input_data}")
            raise
            
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
                'completion_time': updated_doc.completion_time,
                'counter_value': counter_value
            }
        }
        
    except Exception as e:
        logger.error(f"Unexpected error in handler: {str(e)}", exc_info=True)
        # Always try to decrement counter in case of any error
        if counter_value is None: # semgrep-ignore: identical-is-comparison - Correctly checking for None.
            decrement_counter()
        raise