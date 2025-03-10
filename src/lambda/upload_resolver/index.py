# src/lambda/upload_resolver/index.py

import json
import os
import boto3
import logging
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Configure S3 client with S3v4 signature
s3_config = Config(
    signature_version='s3v4',
    s3={'addressing_style': 'path'}
)
s3_client = boto3.client('s3', config=s3_config)

def handler(event, context):
    """
    Generates a presigned POST URL for S3 uploads through an AppSync resolver.
    
    Args:
        event (dict): The event data from AppSync
        context (object): Lambda context
    
    Returns:
        dict: A dictionary containing the presigned URL data and object key
    """
    logger.info(f"Received event: {json.dumps(event)}")
    
    try:
        # Extract variables from the event
        arguments = event.get('arguments', {})
        file_name = arguments.get('fileName')
        content_type = arguments.get('contentType', 'application/octet-stream')
        prefix = arguments.get('prefix', '')
        
        if not file_name:
            raise ValueError("fileName is required")
        
        # Get bucket from arguments or fallback to INPUT_BUCKET if needed by patterns
        bucket_name = arguments.get('bucket')
        
        if not bucket_name and os.environ.get('INPUT_BUCKET'):
            # Support legacy pattern usage that relies on INPUT_BUCKET
            bucket_name = os.environ.get('INPUT_BUCKET')
            logger.info(f"Using INPUT_BUCKET fallback: {bucket_name}")
        elif not bucket_name:
            raise ValueError("bucket parameter is required when INPUT_BUCKET is not configured")
        
        # Sanitize file name to avoid URL encoding issues
        sanitized_file_name = file_name.replace(' ', '_')
        
        # Build the object key - only use prefix if provided
        if prefix:
            object_key = f"{prefix}/{sanitized_file_name}"
        else:
            object_key = sanitized_file_name
        
        # Generate a presigned POST URL for uploading
        logger.info(f"Generating presigned POST data for: {object_key} with content type: {content_type}")
        
        presigned_post = s3_client.generate_presigned_post(
            Bucket=bucket_name,
            Key=object_key,
            Fields={
                'Content-Type': content_type
            },
            Conditions=[
                ['content-length-range', 1, 104857600],  # 1 Byte to 100 MB
                {'Content-Type': content_type}
            ],
            ExpiresIn=900  # 15 minutes
        )
        
        logger.info(f"Generated presigned POST data: {json.dumps(presigned_post)}")
        
        # Return the presigned POST data and object key
        return {
            'presignedUrl': json.dumps(presigned_post),
            'objectKey': object_key,
            'usePostMethod': True
        }
    
    except Exception as e:
        logger.error(f"Error generating presigned URL: {str(e)}")
        raise
