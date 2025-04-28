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

# Configuration
CONFIG = get_config()
region = os.environ['AWS_REGION']
MAX_WORKERS = int(os.environ.get('MAX_WORKERS', 20))

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
# Get LOG_LEVEL from environment variable with INFO as default


def handler(event, context):
    """
    Lambda handler for document classification.
    """
    logger.info(f"Event: {json.dumps(event)}")
    logger.info(f"Config: {json.dumps(CONFIG)}")
    
    # Extract document from the OCR result
    document = Document.from_dict(event["OCRResult"]["document"])
    
    # Update document status to CLASSIFYING
    document.status = Status.CLASSIFYING
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
    
    # Initialize classification service
    service = classification.ClassificationService(
        region=region,
        max_workers=MAX_WORKERS,
        config=CONFIG
    )
    
    # Classify the document - the service will update the Document directly
    document = service.classify_document(document)
    
    # Check if document processing failed
    if document.status == Status.FAILED:
        error_message = f"Classification failed for document {document.id}"
        logger.error(error_message)
        # Update document status in AppSync before raising exception
        appsync_service.update_document(document)
        raise Exception(error_message)
    
    t1 = time.time()
    logger.info(f"Time taken for classification: {t1-t0:.2f} seconds")
    
    # Return document in a consistent envelope
    response = {
        "document": document.to_dict()
    }
    
    logger.info(f"Response: {json.dumps(response, default=str)}")
    return response