# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
OCR function that processes PDFs and extracts text using AWS Textract.
Uses the idp_common.ocr package for OCR functionality.
"""

import json
import logging
import os
import time

from idp_common import get_config, ocr
from idp_common.models import Document, Status
from idp_common.docs_service import create_document_service

# Configuration will be loaded in handler function

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logging.getLogger('idp_common.bedrock.client').setLevel(os.environ.get("BEDROCK_LOG_LEVEL", "INFO"))

# Initialize settings
region = os.environ['AWS_REGION']
METRIC_NAMESPACE = os.environ.get('METRIC_NAMESPACE')
MAX_WORKERS = int(os.environ.get('MAX_WORKERS', 20))

def handler(event, context): 
    """
    Lambda handler for OCR processing.
    """       
    logger.info(f"Event: {json.dumps(event)}")
    
    # Get document from event
    document = Document.from_dict(event["document"])
    
    # Update document status to OCR and update in AppSync
    document.status = Status.OCR
    document.workflow_execution_arn = event.get("execution_arn")
    document_service = create_document_service()
    logger.info(f"Updating document status to {document.status}")
    document_service.update_document(document)
    
    t0 = time.time()
    
    # Load configuration and initialize the OCR service using new simplified pattern
    config = get_config()

    backend = config.get("ocr", {}).get("backend", "textract")
    
    logger.info(f"Initializing OCR with backend: {backend}")
    service = ocr.OcrService(
        region=region,
        config=config,
        backend=backend
    )
    
    # Process the document - the service will read the PDF content directly
    document = service.process_document(document)
    
    # Check if document processing failed
    if document.status == Status.FAILED:
        error_message = f"OCR processing failed for document {document.id}"
        logger.error(error_message)
        # Update status in AppSync before raising exception
        document_service.update_document(document)
        raise Exception(error_message)
    
    t1 = time.time()
    logger.info(f"Total OCR processing time: {t1-t0:.2f} seconds")
    
    # Prepare output with automatic compression if needed
    working_bucket = os.environ.get('WORKING_BUCKET')
    response = {
        "document": document.serialize_document(working_bucket, "ocr", logger)
    }
    
    logger.info(f"Response: {json.dumps(response, default=str)}")
    return response
