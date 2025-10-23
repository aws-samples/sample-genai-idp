# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# src/lambda/upload_resolver/index.py

import json
import os
import boto3
import logging
import re
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logging.getLogger('idp_common.bedrock.client').setLevel(os.environ.get("BEDROCK_LOG_LEVEL", "INFO"))

# Configure S3 client with S3v4 signature
s3_config = Config(
    signature_version='s3v4',
    s3={'addressing_style': 'path'}
)
s3_client = boto3.client('s3', config=s3_config)


def extract_user_id(event):
    """
    Extract Cognito user ID (UUID) from AppSync event context.
    Prioritizes 'sub' field which contains the actual Cognito UUID.
    Falls back to 'username' only if 'sub' is not available.
    
    Args:
        event: AppSync event with identity context
        
    Returns:
        str: Cognito user ID (UUID format)
        
    Raises:
        ValueError: If no user ID found in identity context
    """
    identity = event.get('identity', {})
    
    # PRIORITY 1: Extract from 'sub' field (this is the actual Cognito UUID)
    user_id = identity.get('sub')
    if user_id:
        logger.info(f"Extracted user_id from sub: {user_id}")
        return user_id
    
    # PRIORITY 2: Fallback to 'username' if 'sub' is not available
    user_id = identity.get('username')
    if user_id:
        logger.info(f"Extracted user_id from username: {user_id}")
        return user_id
    
    logger.error("No user ID found in identity context")
    logger.error(f"Identity context: {json.dumps(identity)}")
    raise ValueError("User not authenticated - missing user ID")


def validate_user_id(user_id):
    """
    Validate user ID format (should be UUID-like from Cognito).
    Logs warning if format doesn't match but allows it through.
    
    Args:
        user_id: User ID to validate
        
    Returns:
        str: The user ID (unchanged)
    """
    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    if not re.match(uuid_pattern, user_id, re.IGNORECASE):
        logger.warning(f"User ID doesn't match UUID pattern: {user_id}")
    return user_id

def handler(event, context):
    """
    Generates a presigned POST URL for S3 uploads through an AppSync resolver.
    Automatically scopes uploads to the authenticated user's directory.
    
    Args:
        event (dict): The event data from AppSync
        context (object): Lambda context
    
    Returns:
        dict: A dictionary containing the presigned URL data and object key
    """
    logger.info(f"Received event: {json.dumps(event)}")
    
    try:
        # Extract and validate user ID from AppSync context
        user_id = extract_user_id(event)
        user_id = validate_user_id(user_id)
        logger.info(f"Processing upload request for user: {user_id}")
        
        # Extract variables from the event
        arguments = event.get('arguments', {})
        file_name = arguments.get('fileName')
        content_type = arguments.get('contentType', 'application/octet-stream')
        user_prefix = arguments.get('prefix', '')  # User-provided subdirectory (optional)
        
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
        
        # Build USER-SCOPED object key: users/<user_id>/[optional-subdir/]filename
        # This enforces user isolation at the S3 level
        if user_prefix:
            # User provided a subdirectory - append it after user ID
            object_key = f"users/{user_id}/{user_prefix}/{sanitized_file_name}"
        else:
            # No subdirectory - just user ID
            object_key = f"users/{user_id}/{sanitized_file_name}"
        
        logger.info(f"User-scoped upload path: {object_key}")
        
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
        
        logger.info(f"Generated presigned POST data for user {user_id}")
        
        # Return the presigned POST data and object key
        return {
            'presignedUrl': json.dumps(presigned_post),
            'objectKey': object_key,
            'usePostMethod': True,
            'userId': user_id  # Include user ID in response for front-end logging
        }
    
    except Exception as e:
        logger.error(f"Error generating presigned URL: {str(e)}", exc_info=True)
        raise
