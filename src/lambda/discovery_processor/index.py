# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# src/lambda/discovery_processor/index.py
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
import json
import os
import logging
from datetime import datetime
import time
import boto3
import requests
from aws_requests_auth.aws_auth import AWSRequestsAuth
from botocore.exceptions import ClientError
from idp_common.discovery.classes_discovery import ClassesDiscovery

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logging.getLogger('idp_common.bedrock.client').setLevel(os.environ.get("BEDROCK_LOG_LEVEL", "INFO"))
# Get LOG_LEVEL from environment variable with INFO as default

dynamodb = boto3.resource('dynamodb')

# Initialize AWS session for AppSync authentication
session = boto3.Session()
credentials = session.get_credentials()

# Get environment variables
APPSYNC_API_URL = os.environ.get("APPSYNC_API_URL")



def handler(event, context):
    """
    Processes discovery jobs from SQS queue.

    Args:
        event (dict): SQS event containing discovery job messages
        context (object): Lambda context

    Returns:
        dict: Processing results
    """
    logger.info(f"Received event: {json.dumps(event)}")

    results = []
    status = 'SUCCESS'

    #sleep for 30 secs
    time.sleep(30)
    batch_item_failures = []
    sqs_batch_response = {}
    for record in event.get('Records', []):
        try:
            # Parse the SQS message
            message_body = json.loads(record['body'])
            job_id = message_body.get('jobId')
            document_key = message_body.get('documentKey')
            ground_truth_key = message_body.get('groundTruthKey')
            bucket = message_body.get('bucket')
            version = message_body.get('version')

            logger.info(f"Processing discovery job: {job_id} with version: {version}")

            # Update job status to IN_PROGRESS
            update_job_status(job_id, 'IN_PROGRESS')

            # Process the discovery job
            result = process_discovery_job(job_id, document_key, ground_truth_key, bucket, version)
            results.append(result)

        except Exception as e:
            status = 'Failed'
            logger.error(f"Error processing record: {str(e)}")
            batch_item_failures.append({"itemIdentifier": record['messageId']})
            # Update job status to FAILED if we have a job_id
            if 'job_id' in locals():
                update_job_status(job_id, 'FAILED', str(e))
            results.append({'status': 'error', 'error': str(e)})

    
    sqs_batch_response["batchItemFailures"] = batch_item_failures
    return sqs_batch_response


def process_discovery_job(job_id, document_key, ground_truth_key, bucket, version):
    """
    Process a single discovery job using ClassesDiscovery.

    Args:
        job_id (str): Unique job identifier
        document_key (str): S3 key for the document file
        ground_truth_key (str): S3 key for the ground truth file
        bucket (str): S3 bucket name
        version (str): Configuration version to save to

    Returns:
        dict: Processing result
    """
    try:
        logger.info(f"Processing discovery job {job_id}: document={document_key}, ground_truth={ground_truth_key}")

        # Get required environment variables
        region = os.environ.get("AWS_REGION")
        
        # Initialize ClassesDiscovery
        classes_discovery = ClassesDiscovery(
            input_bucket=bucket,
            input_prefix=document_key,
            region=region,
            version=version
        )

        # Process the discovery job based on whether ground truth is provided
        if ground_truth_key:
            logger.info(f"Processing with ground truth: {ground_truth_key}")
            result = classes_discovery.discovery_classes_with_document_and_ground_truth(
                input_bucket=bucket,
                input_prefix=document_key,
                ground_truth_key=ground_truth_key
            )
        else:
            logger.info("Processing without ground truth")
            result = classes_discovery.discovery_classes_with_document(
                input_bucket=bucket,
                input_prefix=document_key
            )

        # Update job status to COMPLETED
        update_job_status(job_id, 'COMPLETED')

        logger.info(f"Successfully processed discovery job: {job_id}")

        return {
            "status": result["status"],
            "jobId": job_id,
            "message": "Discovery job processed successfully - document classes discovered and configuration updated"
        }

    except Exception as e:
        logger.error(f"Error processing discovery job {job_id}: {str(e)}")
        update_job_status(job_id, 'FAILED', str(e))
        raise


def update_job_status_via_appsync(job_id, status, error_message=None):
    """
    Update discovery job status via AppSync GraphQL mutation to trigger subscriptions.
    
    Args:
        job_id (str): Unique job identifier
        status (str): New status
        error_message (str, optional): Error message if status is FAILED
    """
    try:
        if not APPSYNC_API_URL:
            logger.warning("APPSYNC_API_URL not configured, falling back to direct DynamoDB update")
            update_job_status_direct(job_id, status, error_message)
            return

        # Prepare the GraphQL mutation
        if error_message:
            mutation = """
            mutation UpdateDiscoveryJobStatus($jobId: ID!, $status: String!, $errorMessage: String) {
                updateDiscoveryJobStatus(jobId: $jobId, status: $status, errorMessage: $errorMessage) {
                    jobId
                    status
                    errorMessage
                }
            }
            """
        else:
            mutation = """
            mutation UpdateDiscoveryJobStatus($jobId: ID!, $status: String!) {
                updateDiscoveryJobStatus(jobId: $jobId, status: $status) {
                    jobId
                    status
                    errorMessage
                }
            }
            """
        
        logger.info(f"Updating AppSync for discovery job {job_id}, status {status}")
        
        # Prepare the variables
        variables = {
            "jobId": job_id,
            "status": status
        }
        
        if error_message:
            variables["errorMessage"] = error_message
        
        # Set up AWS authentication
        region = session.region_name or os.environ.get('AWS_REGION', 'us-east-1')
        auth = AWSRequestsAuth(
            aws_access_key=credentials.access_key,
            aws_secret_access_key=credentials.secret_key,
            aws_token=credentials.token,
            aws_host=APPSYNC_API_URL.replace('https://', '').replace('/graphql', ''),
            aws_region=region,
            aws_service='appsync'
        )
        
        # Prepare the request
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        payload = {
            'query': mutation,
            'variables': variables
        }
        
        logger.info(f"Publishing discovery job update to AppSync for job: {job_id}")
        logger.debug(f"Mutation payload: {json.dumps(payload)}")
        
        # Make the request
        response = requests.post(
            APPSYNC_API_URL,
            json=payload,
            headers=headers,
            auth=auth,
            timeout=30
        )
        
        # Check for successful response
        if response.status_code == 200:
            response_json = response.json()
            if "errors" not in response_json:
                logger.info(f"Successfully published discovery job update for: {job_id}")
                logger.debug(f"Response: {response.text}")
                return True
            else:
                logger.error(f"GraphQL errors in response: {json.dumps(response_json.get('errors'))}")
                logger.error(f"Full mutation payload: {json.dumps(payload)}")
                return False
        else:
            logger.error(f"Failed to publish discovery job update. Status: {response.status_code}, Response: {response.text}")
            return False
        
    except Exception as e:
        logger.error(f"Error updating job status via AppSync: {str(e)}")
        import traceback
        logger.error(f"Error traceback: {traceback.format_exc()}")
        # Fall back to direct DynamoDB update
        update_job_status_direct(job_id, status, error_message)
        return False


def update_job_status_direct(job_id, status, error_message=None):
    """
    Fallback method to update discovery job status directly in DynamoDB.
    Used when AppSync is not available or fails.

    Args:
        job_id (str): Unique job identifier
        status (str): New status
        error_message (str, optional): Error message if status is FAILED
    """
    try:
        table_name = os.environ.get('DISCOVERY_TRACKING_TABLE')
        if not table_name:
            logger.warning("DISCOVERY_TRACKING_TABLE not configured, skipping status update")
            return

        table = dynamodb.Table(table_name)

        update_expression = "SET #status = :status, updatedAt = :updated_at"
        expression_attribute_names = {'#status': 'status'}
        expression_attribute_values = {
            ':status': status,
            ':updated_at': datetime.now().isoformat()
        }

        if error_message:
            update_expression += ", errorMessage = :error_message"
            expression_attribute_values[':error_message'] = error_message

        table.update_item(
            Key={'jobId': job_id},
            UpdateExpression=update_expression,
            ExpressionAttributeNames=expression_attribute_names,
            ExpressionAttributeValues=expression_attribute_values
        )

        logger.info(f"Updated job {job_id} status to {status} (direct DynamoDB)")

    except Exception as e:
        logger.error(f"Error updating job status directly: {str(e)}")
        # Don't fail the processing if status update fails


# Keep the old function name for backward compatibility
def update_job_status(job_id, status, error_message=None):
    """
    Update discovery job status. This now uses AppSync by default.
    """
    update_job_status_via_appsync(job_id, status, error_message)


