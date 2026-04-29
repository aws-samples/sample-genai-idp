# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

# src/lambda/discovery_upload_resolver/index.py

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import boto3
from botocore.config import Config
from idp_common.utils.log_sanitizer import sanitize_event_for_logging

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

sfn_client = boto3.client('stepfunctions')


def handler(event, context):
    """
    Handles discovery-related GraphQL mutations:
    - uploadDiscoveryDocument: presigned URL + job creation
    - autoDetectSections: LLM-based section boundary detection
    - startMultiDocDiscovery: Start multi-document discovery pipeline
    - uploadMultiDocDiscoveryZip: Upload zip file for multi-doc discovery
    """
    logger.info(f"Received event: {json.dumps(sanitize_event_for_logging(event))}")

    # Route based on which GraphQL field is being resolved
    field_name = event.get('info', {}).get('fieldName', 'uploadDiscoveryDocument')
    if field_name == 'autoDetectSections':
        return handle_auto_detect_sections(event, context)
    elif field_name == 'startMultiDocDiscovery':
        return handle_start_multi_doc_discovery(event, context)
    elif field_name == 'uploadMultiDocDiscoveryZip':
        return handle_upload_multi_doc_discovery_zip(event, context)

    return handle_upload_discovery_document(event, context)


def handle_auto_detect_sections(event, context):
    """
    Use ClassesDiscovery to auto-detect document section boundaries.
    Reads config from the selected version, sends PDF to Bedrock via idp_common.
    """
    from idp_common.discovery.classes_discovery import ClassesDiscovery

    arguments = event.get('arguments', {})
    document_key = arguments.get('documentKey')
    bucket = arguments.get('bucket')
    version = arguments.get('version')

    if not document_key or not bucket:
        raise ValueError("documentKey and bucket are required")

    logger.info(f"Auto-detecting sections for s3://{bucket}/{document_key}, version={version}")

    try:
        # Use ClassesDiscovery which reads config from DynamoDB (selected version)
        discovery = ClassesDiscovery(
            input_bucket=bucket,
            input_prefix=document_key,
            region=os.environ.get('AWS_REGION'),
            version=version,
        )

        sections = discovery.auto_detect_sections(
            input_bucket=bucket,
            input_prefix=document_key,
        )

        logger.info(f"Auto-detected {len(sections)} sections")
        return json.dumps(sections)

    except Exception as e:
        logger.error(f"Error auto-detecting sections: {str(e)}")
        raise


def handle_upload_discovery_document(event, context):
    """
    Generates a presigned POST URL for S3 uploads and manages discovery job tracking.
    """
    try:
        # Extract variables from the event
        arguments = event.get('arguments', {})
        file_name = arguments.get('fileName')
        content_type = arguments.get('contentType', 'application/octet-stream')
        prefix = arguments.get('prefix', '')
        ground_truth_file_name = arguments.get('groundTruthFileName')
        version = arguments.get('version')
        page_ranges = arguments.get('pageRanges') or []
        page_labels = arguments.get('pageLabels') or []
        skip_job_creation = arguments.get('skipJobCreation', False)

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

        # Create discovery jobs — one per page range, or one for the whole document
        # skipJobCreation=True is used by the auto-detect sections flow which only needs
        # a presigned URL to upload the document, without creating any discovery jobs.
        if not skip_job_creation:
            if page_ranges and len(page_ranges) > 0:
                logger.info(f"Creating {len(page_ranges)} discovery jobs for page ranges: {page_ranges}")
                for i, page_range in enumerate(page_ranges):
                    job_id = str(uuid.uuid4())
                    page_label = page_labels[i] if i < len(page_labels) else None
                    create_discovery_job(job_id, object_key, gt_object_key, version, page_range=page_range, class_name_hint=page_label)
            else:
                job_id = str(uuid.uuid4())
                create_discovery_job(job_id, object_key, gt_object_key, version)
        else:
            logger.info("skipJobCreation=True — returning presigned URL only, no jobs created")

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


def create_discovery_job(job_id, document_key, ground_truth_key, version, page_range=None, class_name_hint=None):
    """
    Create a new discovery job entry in DynamoDB.
    
    Args:
        job_id (str): Unique job identifier
        document_key (str): S3 key for the document file
        ground_truth_key (str): S3 key for the ground truth file
        version (str): Configuration version to use
        page_range (str, optional): Page range string (e.g., "1-3") for multi-section discovery
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

        if page_range:
            item['pageRange'] = page_range
        
        table.put_item(Item=item)
        logger.info(f"Created discovery job: {job_id}" + (f" (pages {page_range})" if page_range else ""))
        
        send_discovery_message(job_id, document_key, ground_truth_key, version, page_range=page_range, class_name_hint=class_name_hint)
        
    except Exception as e:
        logger.error(f"Error creating discovery job: {str(e)}")
        # Don't fail the upload if job tracking fails

def send_discovery_message(job_id, document_key, ground_truth_key, version, page_range=None, class_name_hint=None):
    """
    Send a message to the discovery processing queue.
    
    Args:
        job_id (str): Unique job identifier
        document_key (str): S3 key for the document file
        ground_truth_key (str): S3 key for the ground truth file
        version (str): Configuration version to use
        page_range (str, optional): Page range string (e.g., "1-3") for multi-section discovery
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

        if page_range:
            message['pageRange'] = page_range

        if class_name_hint:
            message['classNameHint'] = class_name_hint
        
        sqs_client.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(message)
        )
        
        logger.info(f"Sent discovery message for job: {job_id}")
        
    except Exception as e:
        logger.error(f"Error sending discovery message: {str(e)}")
        # Don't fail the upload if message sending fails


def handle_start_multi_doc_discovery(event, context):
    """
    Start a multi-document discovery pipeline via Step Functions.

    Creates a tracking entry in DynamoDB and starts the state machine execution.
    Supports two modes:
    - S3 path: directly analyze documents at an S3 location
    - Zip upload: documents were previously uploaded as a zip file
    """
    arguments = event.get('arguments', {})
    s3_bucket = arguments.get('s3Bucket')
    s3_prefix = arguments.get('s3Prefix', '')
    config_version = arguments.get('configVersion')
    zip_file_name = arguments.get('zipFileName')
    zip_file_size = arguments.get('zipFileSize')

    if not config_version:
        raise ValueError("configVersion is required")

    if not s3_bucket and not zip_file_name:
        raise ValueError("Either s3Bucket/s3Prefix or zipFileName is required")

    job_id = str(uuid.uuid4())
    bucket = s3_bucket or os.environ.get('DISCOVERY_BUCKET', '')
    is_zip_upload = bool(zip_file_name)
    prefix = s3_prefix

    # For zip uploads, the prefix is the zip file key in the discovery bucket
    if is_zip_upload:
        prefix = f"multi-doc-discovery/{job_id}/upload/{zip_file_name}"
        bucket = os.environ.get('DISCOVERY_BUCKET', '')

    logger.info(
        f"Starting multi-doc discovery job {job_id}: "
        f"bucket={bucket}, prefix={prefix}, "
        f"configVersion={config_version}, isZip={is_zip_upload}"
    )

    # Create tracking entry in DynamoDB
    table_name = os.environ.get('DISCOVERY_TRACKING_TABLE')
    if table_name:
        table = dynamodb.Table(table_name)
        now = datetime.now(timezone.utc)
        item = {
            'jobId': job_id,
            'status': 'QUEUED',
            'jobType': 'multi-document',
            'currentStep': 'Queued',
            'version': config_version,
            'createdAt': now.isoformat(),
            'updatedAt': now.isoformat(),
            'ExpiresAfter': int((now + timedelta(days=7)).timestamp()),
        }
        if s3_bucket:
            item['documentKey'] = f"s3://{bucket}/{prefix}"
        if zip_file_name:
            item['documentKey'] = zip_file_name
        table.put_item(Item=item)

    # Start Step Functions execution
    state_machine_arn = os.environ.get('MULTI_DOC_DISCOVERY_STATE_MACHINE_ARN')
    if not state_machine_arn:
        raise ValueError("MULTI_DOC_DISCOVERY_STATE_MACHINE_ARN not configured")

    sfn_input = {
        'jobId': job_id,
        'bucket': bucket,
        'prefix': prefix,
        'configVersion': config_version,
        'isZipUpload': is_zip_upload,
    }

    execution = sfn_client.start_execution(
        stateMachineArn=state_machine_arn,
        name=f"multi-doc-{job_id[:8]}",
        input=json.dumps(sfn_input),
    )

    logger.info(f"Started Step Functions execution: {execution['executionArn']}")

    return {
        'jobId': job_id,
        'status': 'QUEUED',
        'configVersion': config_version,
        'currentStep': 'Queued',
        'createdAt': datetime.now(timezone.utc).isoformat(),
        'updatedAt': datetime.now(timezone.utc).isoformat(),
    }


def handle_upload_multi_doc_discovery_zip(event, context):
    """
    Generate a presigned POST URL for uploading a zip file for multi-doc discovery.

    Returns presigned URL and object key. The caller should:
    1. Upload the zip to the presigned URL
    2. Call startMultiDocDiscovery with the zipFileName
    """
    arguments = event.get('arguments', {})
    file_name = arguments.get('fileName')
    file_size = arguments.get('fileSize', 0)
    config_version = arguments.get('configVersion')

    if not file_name:
        raise ValueError("fileName is required")
    if not file_name.lower().endswith('.zip'):
        raise ValueError("File must be a .zip file")
    if not config_version:
        raise ValueError("configVersion is required")

    # Generate a job ID for the upload prefix
    job_id = str(uuid.uuid4())
    bucket = os.environ.get('DISCOVERY_BUCKET', '')
    object_key = f"multi-doc-discovery/{job_id}/upload/{file_name}"

    logger.info(
        f"Generating presigned POST for multi-doc zip: "
        f"bucket={bucket}, key={object_key}, size={file_size}"
    )

    # Generate presigned POST URL
    presigned_post = s3_client.generate_presigned_post(
        Bucket=bucket,
        Key=object_key,
        Fields={
            'Content-Type': 'application/zip',
        },
        Conditions=[
            ['content-length-range', 1, 1073741824],  # 1 Byte to 1 GB
            {'Content-Type': 'application/zip'},
        ],
        ExpiresIn=900,  # 15 minutes
    )

    return {
        'testSetId': job_id,  # Reuses TestSetUploadResponse type
        'presignedUrl': json.dumps(presigned_post),
        'objectKey': object_key,
    }


