import boto3
import json
import logging
from typing import Dict, Any, Optional, Union
from ..utils import parse_s3_uri

logger = logging.getLogger(__name__)

# Initialize clients
_s3_client = None

def get_s3_client():
    """
    Get or initialize the S3 client
    
    Returns:
        boto3 S3 client
    """
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client('s3')
    return _s3_client

def get_text_content(s3_uri: str) -> str:
    """
    Read text content from an S3 URI
    
    Args:
        s3_uri: The S3 URI in format s3://bucket/key
        
    Returns:
        Text content from the S3 object
    """
    try:
        bucket, key = parse_s3_uri(s3_uri)
        s3 = get_s3_client()
        response = s3.get_object(Bucket=bucket, Key=key)
        content = json.loads(response['Body'].read().decode('utf-8'))
        return content.get('text', '')
    except Exception as e:
        logger.error(f"Error reading text from {s3_uri}: {e}")
        raise

def get_json_content(s3_uri: str) -> Dict[str, Any]:
    """
    Read JSON content from an S3 URI
    
    Args:
        s3_uri: The S3 URI in format s3://bucket/key
        
    Returns:
        Parsed JSON content
    """
    try:
        bucket, key = parse_s3_uri(s3_uri)
        s3 = get_s3_client()
        response = s3.get_object(Bucket=bucket, Key=key)
        return json.loads(response['Body'].read().decode('utf-8'))
    except Exception as e:
        logger.error(f"Error reading JSON from {s3_uri}: {e}")
        raise

def get_binary_content(s3_uri: str) -> bytes:
    """
    Read binary content from an S3 URI
    
    Args:
        s3_uri: The S3 URI in format s3://bucket/key
        
    Returns:
        Binary content from the S3 object
    """
    try:
        bucket, key = parse_s3_uri(s3_uri)
        s3 = get_s3_client()
        response = s3.get_object(Bucket=bucket, Key=key)
        return response['Body'].read()
    except Exception as e:
        logger.error(f"Error reading binary content from {s3_uri}: {e}")
        raise

def write_content(content: Union[str, bytes, Dict[str, Any]], 
                 bucket: str, key: str, 
                 content_type: Optional[str] = None) -> None:
    """
    Write content to S3
    
    Args:
        content: The content to write (string, bytes, or dict that will be converted to JSON)
        bucket: The S3 bucket
        key: The S3 key
        content_type: Optional content type for the S3 object
    """
    try:
        s3 = get_s3_client()
        
        # Handle different content types
        if isinstance(content, dict):
            body = json.dumps(content)
            if content_type is None:
                content_type = 'application/json'
        elif isinstance(content, str):
            body = content
            if content_type is None:
                content_type = 'text/plain'
        else:
            body = content
            if content_type is None:
                content_type = 'application/octet-stream'
        
        # Upload to S3
        extra_args = {}
        if content_type:
            extra_args['ContentType'] = content_type
            
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            **extra_args
        )
        logger.info(f"Successfully wrote to s3://{bucket}/{key}")
    except Exception as e:
        logger.error(f"Error writing to s3://{bucket}/{key}: {e}")
        raise