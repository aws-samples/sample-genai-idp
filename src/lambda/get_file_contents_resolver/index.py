import json
import boto3
import logging
from urllib.parse import urlparse
from botocore.exceptions import ClientError

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')

def handler(event, context):
    """
    Lambda function to fetch contents of a file from S3
    
    Parameters:
        event (dict): Lambda event data containing GraphQL arguments
        context (object): Lambda context
        
    Returns:
        str: Contents of the S3 file as string
        
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
        
        # Read file content and decode as UTF-8
        file_content = response['Body'].read().decode('utf-8')
        
        # For additional debugging if needed:
        logger.info(f"File content type: {response['ContentType']}")
        logger.info(f"File size: {response['ContentLength']}")
        
        return file_content
        
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