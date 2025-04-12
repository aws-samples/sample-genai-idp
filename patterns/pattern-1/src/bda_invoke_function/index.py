import json
import boto3
import os
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any
from botocore.exceptions import ClientError
from idp_common import metrics, utils
from idp_common.models import Document


logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Retry configuration
MAX_RETRIES = 8
INITIAL_BACKOFF = 2  # seconds
MAX_BACKOFF = 300   # 5 minutes

# Initialize client
bda_client = boto3.client('bedrock-data-automation-runtime')
dynamodb = boto3.resource('dynamodb')
tracking_table = dynamodb.Table(os.environ['TRACKING_TABLE'])


def build_s3_uri(bucket: str, key: str) -> str:
    return utils.build_s3_uri(bucket, key)

def build_payload(input_s3_uri: str, output_s3_uri: str, data_project_arn: str) -> Dict[str, Any]:
    region = os.environ.get('AWS_REGION', 'us-east-1')
    account_id = boto3.client('sts').get_caller_identity().get('Account')
    
    return {
        "inputConfiguration": {
            "s3Uri": input_s3_uri
        },
        "outputConfiguration": {
            "s3Uri": output_s3_uri
        },
        "dataAutomationConfiguration": {
            "dataAutomationProjectArn": data_project_arn,
            "stage": "LIVE",
        },
        "dataAutomationProfileArn": f"arn:aws:bedrock:{region}:{account_id}:data-automation-profile/us.data-automation-v1",
        "notificationConfiguration": {
            "eventBridgeConfiguration": {
                "eventBridgeEnabled": True
            }
        }
    }

def invoke_data_automation(payload: Dict[str, Any]) -> Dict[str, Any]:
    retry_count = 0
    last_exception = None
    request_start_time = time.time()

    metrics.put_metric('BDARequestsTotal', 1)

    while retry_count < MAX_RETRIES:
        try:
            logger.info(f"BDA API request attempt {retry_count + 1}/{MAX_RETRIES}")
            
            attempt_start_time = time.time()
            response = bda_client.invoke_data_automation_async(**payload)
            duration = time.time() - attempt_start_time
            
            logger.info(f"BDA API request successful after {retry_count + 1} attempts. "
                       f"Duration: {duration:.2f}s")

            metrics.put_metric('BDARequestsSucceeded', 1)
            metrics.put_metric('BDARequestsLatency', duration * 1000, 'Milliseconds')
            
            if retry_count > 0:
                metrics.put_metric('BDARequestsRetrySuccess', 1)

            total_duration = time.time() - request_start_time
            metrics.put_metric('BDARequestsTotalLatency', total_duration * 1000, 'Milliseconds')

            return response

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            retryable_errors = [
                'ThrottlingException',
                'ServiceQuotaExceededException',
                'RequestLimitExceeded',
                'TooManyRequestsException',
                'InternalServerException'
            ]
            
            if error_code in retryable_errors:
                retry_count += 1
                metrics.put_metric('BDARequestsThrottles', 1)
                
                if retry_count == MAX_RETRIES:
                    logger.error(f"Max retries ({MAX_RETRIES}) exceeded. Last error: {error_message}")
                    metrics.put_metric('BDARequestsFailed', 1)
                    metrics.put_metric('BDARequestsMaxRetriesExceeded', 1)
                    raise
                
                backoff = utils.calculate_backoff(retry_count, INITIAL_BACKOFF, MAX_BACKOFF)
                logger.warning(f"BDA API throttling occurred (attempt {retry_count}/{MAX_RETRIES}). "
                             f"Error: {error_message}. "
                             f"Backing off for {backoff:.2f}s")
                
                time.sleep(backoff)  # semgrep-ignore: arbitrary-sleep - Intentional delay backoff/retry. Duration is algorithmic and not user-controlled.
                last_exception = e
            else:
                logger.error(f"Non-retryable BDA API error: {error_code} - {error_message}")
                metrics.put_metric('BDARequestsFailed', 1)
                metrics.put_metric('BDARequestsNonRetryableErrors', 1)
                raise

        except Exception as e:
            logger.error(f"Unexpected error invoking BDA API: {str(e)}", exc_info=True)
            metrics.put_metric('BDARequestsFailed', 1)
            metrics.put_metric('BDARequestsUnexpectedErrors', 1)
            raise
        
    if last_exception:
        raise last_exception
    
def track_task_token(object_key: str, task_token: str) -> None:
    try:
        # Record in DynamoDB
        tracking_item = {
            'PK': f"tasktoken#{object_key}",
            'SK': 'none',
            'TaskToken': task_token,
            'TaskTokenTime': datetime.now(timezone.utc).isoformat(),
            'ExpiresAfter': int((datetime.now(timezone.utc) + timedelta(days=1)).timestamp())
        }
        logger.info(f"Recording tasktoken entry: {tracking_item}")
        tracking_table.put_item(Item=tracking_item)

    except Exception as e:
        logger.error(f"Error recording tasktoken record: {e}")
        raise

def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    try:
        logger.info(f"Received event: {json.dumps(event)}")

        # Get document from event
        document = Document.from_dict(event["document"])
        input_bucket = document.input_bucket
        object_key = document.input_key
        working_bucket = event['working_bucket']
        data_project_arn = event['BDAProjectArn']
        task_token = event['taskToken']
        
        track_task_token(object_key, task_token)

        input_s3_uri = build_s3_uri(input_bucket, object_key)
        output_s3_uri = build_s3_uri(working_bucket, f"{object_key}/bda_responses")
        payload = build_payload(input_s3_uri, output_s3_uri, data_project_arn)
        bda_response = invoke_data_automation(payload)

        response = {
            "metadata": {
                "input_bucket": input_bucket, 
                "object_key": object_key,
                "working_bucket": working_bucket,
                "output_prefix": object_key, 
            },
            "bda_response": bda_response
        }
        logger.info(f"API invocation successful. Response: {json.dumps(bda_response, default=str)}")
        return response

    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        raise