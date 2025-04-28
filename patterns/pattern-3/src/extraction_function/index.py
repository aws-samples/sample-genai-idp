# Copyright © Amazon.com and Affiliates: This deliverable is considered Developed Content as defined in the AWS Service Terms and the SOW between the parties.

import os
import json
import time
import logging

from idp_common import metrics, get_config, extraction
from idp_common.models import Document, Section, Status
from idp_common.appsync.service import DocumentAppSyncService

CONFIG = get_config()

OCR_TEXT_ONLY = os.environ.get('OCR_TEXT_ONLY', 'false').lower() == 'true'

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
# Get LOG_LEVEL from environment variable with INFO as default


def handler(event, context):
    """
    Process a single section of a document for information extraction
    """
    logger.info(f"Event: {json.dumps(event)}")
    logger.info(f"Config: {json.dumps(CONFIG)}")
    
    # For Map state, we get just one section from the document
    # Extract the document and section from the event
    full_document = Document.from_dict(event.get("document", {}))
    section = Section.from_dict(event.get("section", {}))
    
    # Get the section ID for later use
    section_id = section.section_id
    
    # Update document status to EXTRACTING
    full_document.status = Status.EXTRACTING
    appsync_service = DocumentAppSyncService()
    logger.info(f"Updating document status to {full_document.status}")
    appsync_service.update_document(full_document)
       
    # Create a section-specific document by modifying the original document
    section_document = full_document
    section_document.sections = [section]
    section_document.metering = {}
    
    # Filter to keep only the pages needed for this section
    needed_pages = {}
    for page_id in section.page_ids:
        if page_id in full_document.pages:
            needed_pages[page_id] = full_document.pages[page_id]
    section_document.pages = needed_pages
    
    # Initialize the extraction service
    extraction_service = extraction.ExtractionService(config=CONFIG)
    
    # Track metrics
    metrics.put_metric('InputDocuments', 1)
    metrics.put_metric('InputDocumentPages', len(section.page_ids))
    
    # Process the section in our focused document
    t0 = time.time()
    section_document = extraction_service.process_document_section(
        document=section_document,
        section_id=section_id
    )
    t1 = time.time()
    logger.info(f"Total extraction time: {t1-t0:.2f} seconds")
    
    # Check if document processing failed
    if section_document.status == Status.FAILED:
        error_message = f"Extraction failed for document {section_document.id}, section {section_id}"
        logger.error(error_message)
        # Update status in AppSync before raising exception
        full_document.status = Status.FAILED
        full_document.errors.append(error_message)
        appsync_service.update_document(full_document)
        raise Exception(error_message)
    
    # Return section extraction result with the document
    # The state machine will later combine all section results
    response = {
        "section_id": section_id,
        "document": section_document.to_dict()
    }
    
    logger.info(f"Response: {json.dumps(response, default=str)}")
    return response