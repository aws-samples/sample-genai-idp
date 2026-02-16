# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# src/lambda/discovery_upload_resolver/index.py

import json
import os
import boto3
import logging
import uuid
from datetime import datetime, timezone, timedelta
from botocore.config import Config

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Configure S3 client with S3v4 signature
s3_config = Config(
    signature_version='s3v4',
    s3={'addressing_style': 'path'}
)
s3_client = boto3.client('s3', config=s3_config)
sqs_client = boto3.client('sqs')
dynamodb = boto3.resource('dynamodb')

def handler(event, context):
    """
    Generates a presigned POST URL for S3 uploads and manages discovery job tracking.
    
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
        ground_truth_file_name = arguments.get('groundTruthFileName')
        version = arguments.get('version')

        if not file_name:
            raise ValueError("fileName is required")
        
        # Get bucket from arguments
        bucket_name = arguments.get('bucket')

        if not bucket_name:
            raise ValueError("bucket parameter is required")

        object_key, presigned_post = create_s3_signed_post_url(bucket_name, content_type, file_name, 'document', prefix)
        response = {
            'presignedUrl': json.dumps(presigned_post),
            'objectKey': object_key,
            'usePostMethod': True
        }
        gt_object_key = None
        if ground_truth_file_name:
            gt_object_key, gt_presigned_post = create_s3_signed_post_url(bucket_name, content_type, ground_truth_file_name, 'groundtruth', prefix)
            response['groundTruthObjectKey'] = gt_object_key
            response['groundTruthPresignedUrl'] = json.dumps(gt_presigned_post)

        #generate unique job id
        job_id = str(uuid.uuid4())

        create_discovery_job(job_id, object_key, gt_object_key, version)

        # Return the presigned POST data and object key
        return response
    
    except Exception as e:
        logger.error(f"Error generating presigned URL: {str(e)}")
        raise


def create_s3_signed_post_url(bucket_name, content_type, file_name, file_type, prefix):
    # Sanitize file name to avoid URL encoding issues
    sanitized_file_name = file_name.replace(' ', '_')
    # Build the object key with file type prefix
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    if prefix:
        object_key = f"{prefix}/{file_type}/{timestamp}_{sanitized_file_name}"
    else:
        object_key = f"{file_type}/{timestamp}_{sanitized_file_name}"
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
    return object_key, presigned_post


def create_discovery_job(job_id, document_key, ground_truth_key, version):
    """
    Create a new discovery job entry in DynamoDB.
    
    Args:
        job_id (str): Unique job identifier
        document_key (str): S3 key for the document file
        ground_truth_key (str): S3 key for the ground truth file
        version (str): Configuration version to use
    """
    try:
        table_name = os.environ.get('DISCOVERY_TRACKING_TABLE')
        if not table_name:
            logger.warning("DISCOVERY_TRACKING_TABLE not configured, skipping job creation")
            return
        
        table = dynamodb.Table(table_name)

        #retrieve job from table
        item = table.get_item( Key={'jobId': job_id}).get('Item', None)
        if item is None:
            item = {
                'jobId': job_id,
                'status': 'PENDING',
                'createdAt': datetime.now().isoformat(),
                'updatedAt': datetime.now().isoformat(),
                'ExpiresAfter': int((datetime.now(timezone.utc) + timedelta(days=1)).timestamp())
            }
        else:
            item['updatedAt'] = datetime.now().isoformat()
            document_key = item.get('documentKey', document_key)

        if document_key:
            item['documentKey'] = document_key

        if ground_truth_key:
            item['groundTruthKey'] = ground_truth_key
            
        if version:
            item['version'] = version
        
        table.put_item(Item=item)
        logger.info(f"Created discovery job: {job_id}")
        
        send_discovery_message(job_id, document_key, ground_truth_key, version)
        
    except Exception as e:
        logger.error(f"Error creating discovery job: {str(e)}")
        # Don't fail the upload if job tracking fails

def send_discovery_message(job_id, document_key, ground_truth_key, version):
    """
    Send a message to the discovery processing queue.
    
    Args:
        job_id (str): Unique job identifier
        document_key (str): S3 key for the document file
        ground_truth_key (str): S3 key for the ground truth file
        version (str): Configuration version to use
    """
    try:
        queue_url = os.environ.get('DISCOVERY_QUEUE_URL')
        if not queue_url:
            logger.warning("DISCOVERY_QUEUE_URL not configured, skipping message send")
            return
        
        message = {
            'jobId': job_id,
            'documentKey': document_key,
            'groundTruthKey': ground_truth_key,
            'bucket': os.environ.get('DISCOVERY_BUCKET'),
            'version': version,
            'timestamp': datetime.now().isoformat()
        }
        
        sqs_client.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(message)
        )
        
        logger.info(f"Sent discovery message for job: {job_id}")
        
    except Exception as e:
        logger.error(f"Error sending discovery message: {str(e)}")
        # Don't fail the upload if message sending fails


