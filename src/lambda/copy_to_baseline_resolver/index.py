import boto3
import os
import logging
import json
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def handler(event, context):
    logger.info(f"Received event: {json.dumps(event)}")

    try:
        object_key = event['arguments']['objectKey']
        
        # Get bucket names from environment variables
        source_bucket = os.environ['OUTPUT_BUCKET']
        destination_bucket = os.environ['EVALUATION_BASELINE_BUCKET']
        
        # Create S3 client
        s3_client = boto3.client('s3')
        
        # List all objects under the prefix
        paginator = s3_client.get_paginator('list_objects_v2')
        operation_parameters = {
            'Bucket': source_bucket,
            'Prefix': object_key
        }

        copied_count = 0
        for page in paginator.paginate(**operation_parameters):
            if 'Contents' not in page:
                continue
                
            for obj in page['Contents']:
                # Copy each object
                copy_source = {
                    'Bucket': source_bucket,
                    'Key': obj['Key']
                }
                
                s3_client.copy_object(
                    CopySource=copy_source,
                    Bucket=destination_bucket,
                    Key=obj['Key']
                )
                copied_count += 1

        logger.info(f'Successfully copied {copied_count} files under prefix {object_key} to baseline bucket')
        return {
            'success': True,
            'message': f'Successfully copied {copied_count} files under prefix {object_key} to baseline bucket'
        }
        
    except ClientError as e:
        error_message = str(e)
        logger.error(f'Failed to copy files: {error_message}')
        return {
            'success': False,
            'message': f'Failed to copy files: {error_message}'
        }
    except Exception as e:
        logger.error(f'Unexpected error: {str(e)}')
        return {
            'success': False,
            'message': f'Unexpected error: {str(e)}'
        }
