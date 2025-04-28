import json
import os
import boto3
import logging
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

s3_client = boto3.client('s3')

def handler(event, context):
    logger.info(f"Event: {json.dumps(event)}")

    try:
        # Get the input bucket name from the environment variable
        input_bucket = os.environ.get('INPUT_BUCKET')
        if not input_bucket:
            raise Exception("INPUT_BUCKET environment variable is not set")

        # Extract object keys from the arguments
        args = event.get('arguments', {})
        object_keys = args.get('objectKeys', [])
        
        if not object_keys:
            return {
                'statusCode': 400,
                'body': 'No document keys provided'
            }

        logger.info(f"Reprocessing documents: {object_keys}")
        
        # Copy each object over itself to trigger the S3 event notification
        for key in object_keys:
            logger.info(f"Reprocessing document: {key}")
            
            # Copy the object to itself using the copy_object API
            s3_client.copy_object(
                Bucket=input_bucket,
                CopySource={'Bucket': input_bucket, 'Key': key},
                Key=key,
                MetadataDirective='REPLACE',
                Metadata={
                    'reprocessed': 'true',
                    'reprocessed_timestamp': datetime.utcnow().isoformat()
                }
            )
            
            logger.info(f"Successfully reprocessed document: {key}")

        return True
    except Exception as e:
        logger.error(f"Error reprocessing documents: {str(e)}")
        raise e