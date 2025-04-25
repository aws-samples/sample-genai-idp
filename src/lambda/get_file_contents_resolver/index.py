import json
import boto3
import logging
import html
import mimetypes
import os
from urllib.parse import urlparse
from botocore.exceptions import ClientError

# Set up logging
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
# Get LOG_LEVEL from environment variable with INFO as default

s3_client = boto3.client('s3')

def handler(event, context):
    """
    Lambda function to fetch contents of a file from S3
    
    Parameters:
        event (dict): Lambda event data containing GraphQL arguments
        context (object): Lambda context
        
    Returns:
        dict: Dictionary containing file contents and metadata
        
    Raises:
        Exception: Various exceptions related to S3 operations or invalid input
    """
    try:
        logger.info(f"Received event: {json.dumps(event)}")
        
        # Extract S3 URI from arguments
        s3_uri = event['arguments']['s3Uri']
        logger.info(f"Processing S3 URI: {s3_uri}")
        
        # Parse S3 URI to get bucket and key
        parsed_uri = urlparse(s3_uri)
        bucket = parsed_uri.netloc.split('.')[0]  # Extract bucket name from hostname
        key = parsed_uri.path.lstrip('/')  # Remove leading slash from path
        
        logger.info(f"Fetching from bucket: {bucket}, key: {key}")
        
        # Get object from S3
        response = s3_client.get_object(
            Bucket=bucket,
            Key=key
        )
        
        # Get content type from S3 response or infer from file extension
        content_type = response.get('ContentType', '')
        if not content_type or content_type == 'binary/octet-stream' or content_type == 'application/octet-stream':
            content_type = mimetypes.guess_type(key)[0] or 'text/plain'
        
        logger.info(f"File content type: {content_type}")
        logger.info(f"File size: {response['ContentLength']}")
        
        # Read file content with error handling for different encodings
        try:
            # First try UTF-8
            file_content = response['Body'].read().decode('utf-8')
        except UnicodeDecodeError:
            # If UTF-8 fails, try with error handling
            try:
                response['Body'].seek(0)  # Reset the file pointer
                file_content = response['Body'].read().decode('utf-8', errors='replace')
                logger.warning("File content contained invalid UTF-8 characters that were replaced")
            except Exception as decode_error:
                # Last resort - if it's a binary file format with text extension
                logger.error(f"Failed to decode content with error handling: {str(decode_error)}")
                return {
                    'content': "This file contains binary content that cannot be displayed as text.",
                    'contentType': content_type,
                    'size': response['ContentLength'],
                    'isBinary': True
                }
        
        # For HTML content, escape the HTML to prevent XSS
        if content_type.startswith('text/html') or content_type.startswith('application/xhtml+xml'):
            file_content = html.escape(file_content)
            
        # Return both content and metadata
        return {
            'content': file_content,
            'contentType': content_type,
            'size': response['ContentLength'],
            'isBinary': False
        }
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        logger.error(f"S3 ClientError: {error_code} - {error_message}")
        
        if error_code == 'NoSuchKey':
            raise Exception(f"File not found: {key}")
        elif error_code == 'NoSuchBucket':
            raise Exception(f"Bucket not found: {bucket}")
        else:
            raise Exception(f"Error accessing S3: {error_message}")
            
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise Exception(f"Error fetching file: {str(e)}")