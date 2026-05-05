# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# src/lambda/upload_resolver/index.py

import json
import logging
import os

import boto3
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logging.getLogger('idp_common.bedrock.client').setLevel(os.environ.get("BEDROCK_LOG_LEVEL", "INFO"))
# Get LOG_LEVEL from environment variable with INFO as default

# Configure S3 client with S3v4 signature
s3_config = Config(
    signature_version='s3v4',
    s3={'addressing_style': 'path'}
)
s3_client = boto3.client('s3', config=s3_config)

# --- inline log sanitizer ---------------------------------------------------
# Minimal inline redactor. Kept here rather than importing from idp_common to
# avoid adding a Lambda Layer dependency to this resolver. If this file grows
# to need idp_common anyway, promote to
# `from idp_common.utils.log_sanitizer import sanitize_event_for_logging`.
_LOG_SENSITIVE_KEYS = (
    "password", "secret", "token", "authorization", "apikey", "api_key",
    "cookie", "credential", "claims", "identity",
)


def _sanitize_for_log(obj):
    """Deep-copy `obj` redacting values whose keys match the denylist."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and any(s in k.lower() for s in _LOG_SENSITIVE_KEYS):
                out[k] = "***REDACTED***" if v is not None else None
            else:
                out[k] = _sanitize_for_log(v)
        return out
    if isinstance(obj, list):
        return [_sanitize_for_log(v) for v in obj]
    return obj

def handler(event, context):
    """
    Generates a presigned POST URL for S3 uploads through an AppSync resolver.
    
    Args:
        event (dict): The event data from AppSync
        context (object): Lambda context
    
    Returns:
        dict: A dictionary containing the presigned URL data and object key
    """
    logger.info(f"Received event: {json.dumps(_sanitize_for_log(event))}")
    
    try:
        # Extract variables from the event
        arguments = event.get('arguments', {})
        file_name = arguments.get('fileName')
        content_type = arguments.get('contentType', 'application/octet-stream')
        prefix = arguments.get('prefix', '')
        version = arguments.get('version')  # Optional version parameter
        
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
        
        # Prepare fields and conditions
        fields = {'Content-Type': content_type}
        conditions = [
            ['content-length-range', 1, 104857600],  # 1 Byte to 100 MB
            {'Content-Type': content_type}
        ]
        
        # Add version as metadata
        if version:
            fields['x-amz-meta-config-version'] = version
            conditions.append({'x-amz-meta-config-version': version})
        
        presigned_post = s3_client.generate_presigned_post(
            Bucket=bucket_name,
            Key=object_key,
            Fields=fields,
            Conditions=conditions,
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
