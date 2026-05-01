"""
Lambda function to delete test runs and their associated data.
"""

import json
import logging
import os

import boto3
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')
s3 = boto3.client('s3')


def lambda_handler(event, context):
    """
    Delete test runs by removing tracking metadata and calling document delete for all documents.
    """
    try:
        test_run_ids = event['arguments']['testRunIds']
        logger.info(f"Deleting test runs: {test_run_ids}")
        
        tracking_table_name = os.environ.get('TRACKING_TABLE_NAME')
        delete_document_function_name = os.environ.get('DELETE_DOCUMENT_FUNCTION_NAME')
        baseline_bucket = os.environ.get('BASELINE_BUCKET')
        
        tracking_table = dynamodb.Table(tracking_table_name)  # type: ignore[attr-defined]
        all_document_keys = []
        deleted_count = 0
        
        # Collect all document keys from all test runs
        for test_run_id in test_run_ids:
            try:
                response = tracking_table.get_item(
                    Key={'PK': f"testrun#{test_run_id}", 'SK': "metadata"}
                )
                
                if 'Item' not in response:
                    logger.warning(f"Test run {test_run_id} not found")
                    continue
                
                item = response['Item']
                
                # Extract object keys from Files list
                if 'Files' in item and item['Files']:
                    for file_name in item['Files']:
                        object_key = f"{test_run_id}/{file_name}"
                        all_document_keys.append(object_key)
                
                # Delete baseline bucket files for this test run
                if baseline_bucket:
                    _delete_baseline_files(baseline_bucket, test_run_id)
                
                # Delete test run metadata
                tracking_table.delete_item(
                    Key={'PK': f"testrun#{test_run_id}", 'SK': "metadata"}
                )
                
                deleted_count += 1
                logger.info(f"Successfully deleted test run {test_run_id} metadata")
                
            except ClientError as e:
                logger.error(f"Failed to delete test run {test_run_id}: {e}")
                continue
        
        # Delete all documents in one call
        if all_document_keys:
            lambda_client.invoke(
                FunctionName=delete_document_function_name,
                InvocationType='Event',
                Payload=json.dumps({
                    'arguments': {'objectKeys': all_document_keys}
                })
            )
            logger.info(f"Invoked document delete for {len(all_document_keys)} total documents")
        
        return deleted_count > 0
        
    except Exception as e:
        logger.error(f"Error deleting test runs: {e}")
        raise e

def _delete_baseline_files(baseline_bucket, test_run_id):
    """Delete all baseline files for the test run"""
    try:
        # List all objects with the test run prefix
        paginator = s3.get_paginator('list_objects_v2')
        objects_to_delete = []
        
        for page in paginator.paginate(Bucket=baseline_bucket, Prefix=f"{test_run_id}/"):
            if 'Contents' in page:
                for obj in page['Contents']:
                    objects_to_delete.append({'Key': obj['Key']})
        
        # Delete objects in batches (S3 delete_objects supports up to 1000 objects per call)
        if objects_to_delete:
            for i in range(0, len(objects_to_delete), 1000):
                batch = objects_to_delete[i:i+1000]
                s3.delete_objects(
                    Bucket=baseline_bucket,
                    Delete={'Objects': batch}
                )
            logger.info(f"Deleted {len(objects_to_delete)} baseline files for test run {test_run_id}")
        else:
            logger.info(f"No baseline files found for test run {test_run_id}")
            
    except Exception as e:
        logger.error(f"Failed to delete baseline files for test run {test_run_id}: {e}")
        # Don't raise - continue with other cleanup
