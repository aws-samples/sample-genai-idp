# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import os
import json
import time
import logging

from idp_common import get_config, assessment
from idp_common.models import Document, Status
from idp_common.appsync.service import DocumentAppSyncService

# Configuration will be loaded in handler function

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logging.getLogger('idp_common.bedrock.client').setLevel(os.environ.get("BEDROCK_LOG_LEVEL", "INFO"))

def handler(event, context):
    """
    Lambda handler for document assessment.
    This function assesses the confidence of extraction results for a document section
    using the Assessment service from the idp_common library.
    """
    logger.info(f"Starting assessment processing for event: {json.dumps(event, default=str)}")

    # Load configuration
    config = get_config()
    logger.info(f"Config: {json.dumps(config)}")
    
    # Extract input from event
    document_dict = event.get('document', {})
    section_id = event.get('section_id')
    
    # Validate inputs
    if not document_dict:
        raise ValueError("No document provided in event")
        
    if not section_id:
        raise ValueError("No section_id provided in event")
        
    # Convert document dictionary to Document object
    document = Document.from_dict(document_dict)
    logger.info(f"Processing assessment for document {document.id}, section {section_id}")

    # Update document status to ASSESSING
    status = Document(
        id=document.id,
        input_key=document.input_key,
        status=Status.ASSESSING,
    )
    appsync_service = DocumentAppSyncService()
    logger.info(f"Updating document status to {status.status}")
    appsync_service.update_document(status)

    # Initialize assessment service
    assessment_service = assessment.AssessmentService(config=config)

    # Process the document section for assessment
    t0 = time.time()
    logger.info(f"Starting assessment for section {section_id}")
    updated_document = assessment_service.process_document_section(document, section_id)
    t1 = time.time()
    logger.info(f"Total extraction time: {t1-t0:.2f} seconds")

    # Check if document processing failed
    if updated_document.status == Status.FAILED:
        error_message = f"Assessment failed for document {updated_document.id}, section {section_id}"
        logger.error(error_message)
        raise Exception(error_message)
    
    # Return the updated document as a dictionary
    result = {
        'document': updated_document.to_dict(),
        'section_id': section_id
    }
    
    logger.info("Assessment processing completed")
    return result

