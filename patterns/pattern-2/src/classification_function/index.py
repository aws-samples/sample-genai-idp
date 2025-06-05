# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Classification function that processes documents and classifies them using LLMs.
Uses the idp_common.classification package for classification functionality.
"""

import json
import logging
import os
import time

from idp_common import classification, metrics, get_config
from idp_common.models import Document, Status
from idp_common.appsync.service import DocumentAppSyncService

# Configuration will be loaded in handler function
region = os.environ['AWS_REGION']
MAX_WORKERS = int(os.environ.get('MAX_WORKERS', 20))

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logging.getLogger('idp_common.bedrock.client').setLevel(os.environ.get("BEDROCK_LOG_LEVEL", "INFO"))

def handler(event, context):
    """
    Lambda handler for document classification.
    """
    logger.info(f"Event: {json.dumps(event)}")
    # Load configuration
    config = get_config()
    logger.info(f"Config: {json.dumps(config)}")
    
    # Extract document from the OCR result
    document = Document.from_dict(event["OCRResult"]["document"])
    
    # Update document status to CLASSIFYING
    document.status = Status.CLASSIFYING
    document.workflow_execution_arn = event.get("execution_arn")
    appsync_service = DocumentAppSyncService()
    logger.info(f"Updating document status to {document.status}")
    appsync_service.update_document(document)
    
    if not document.pages:
        error_message = "Document has no pages to classify"
        logger.error(error_message)
        document.status = Status.FAILED
        document.errors.append(error_message)
    
    t0 = time.time()
    
    # Track pages processed for metrics
    total_pages = len(document.pages)
    metrics.put_metric('BedrockRequestsTotal', total_pages)
    
    # Initialize classification service with DynamoDB caching
    cache_table = os.environ.get('TRACKING_TABLE')
    service = classification.ClassificationService(
        region=region,
        max_workers=MAX_WORKERS,
        config=config,
        cache_table=cache_table
    )
    
    # Classify the document - the service will update the Document directly
    document = service.classify_document(document)
    
    # Check if document processing failed or has pages that failed to classify
    failed_page_exceptions = None
    primary_exception = None
    
    # Check for failed page exceptions in metadata
    if document.metadata and "failed_page_exceptions" in document.metadata:
        failed_page_exceptions = document.metadata["failed_page_exceptions"]
        primary_exception = document.metadata.get("primary_exception")
        
        # Log details about failed pages
        logger.error(f"Document {document.id} has {len(failed_page_exceptions)} pages that failed to classify:")
        for page_id, exc_info in failed_page_exceptions.items():
            logger.error(f"  Page {page_id}: {exc_info['exception_type']} - {exc_info['exception_message']}")
    
    # Check if document processing completely failed or has critical page failures
    if document.status == Status.FAILED or failed_page_exceptions:
        error_message = f"Classification failed for document {document.id}"
        if failed_page_exceptions:
            error_message += f" - {len(failed_page_exceptions)} pages failed to classify"
        
        logger.error(error_message)
        # Update document status in AppSync before raising exception
        appsync_service.update_document(document)
        
        # Raise the original exception type if available, otherwise raise generic exception
        if primary_exception:
            logger.error(f"Re-raising original exception: {type(primary_exception).__name__}")
            raise primary_exception
        else:
            raise Exception(error_message)
    
    t1 = time.time()
    logger.info(f"Time taken for classification: {t1-t0:.2f} seconds")
    
    # Return document in a consistent envelope
    response = {
        "document": document.to_dict()
    }
    
    logger.info(f"Response: {json.dumps(response, default=str)}")
    return response
