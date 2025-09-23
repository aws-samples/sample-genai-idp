# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0


import os
import json
import time
import logging

from idp_common import metrics, get_config, extraction
from idp_common.models import Document, Section, Status
from idp_common.docs_service import create_document_service

# Configuration will be loaded in handler function

OCR_TEXT_ONLY = os.environ.get('OCR_TEXT_ONLY', 'false').lower() == 'true'

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logging.getLogger('idp_common.bedrock.client').setLevel(os.environ.get("BEDROCK_LOG_LEVEL", "INFO"))


def handler(event, context):
    """
    Process a single section of a document for information extraction
    """
    logger.info(f"Event: {json.dumps(event)}")

    # Load configuration
    config = get_config()
    logger.info(f"Config: {json.dumps(config)}")

    # Check if extraction is enabled
    from idp_common.utils import normalize_boolean_value
    extraction_config = config.get('extraction', {})
    if not normalize_boolean_value(extraction_config.get('enabled', True)):
        logger.info("Extraction is disabled in configuration, skipping.")
        # When skipping, we must still return the expected structure for the Map state output
        section_id = event.get("section_id")
        return {
            "section_id": section_id,
            "document": event.get("document", {})
        }
    
    # For Map state, we get just one section from the document
    # Extract the document and section from the event - handle both compressed and uncompressed
    working_bucket = os.environ.get('WORKING_BUCKET')
    full_document = Document.load_document(event.get("document", {}), working_bucket, logger)
    
    # Get the section ID directly from the Map state input
    # Now using the simplified array of section IDs format
    section_id = event.get("section_id")
    
    if not section_id:
        raise ValueError("No section_id found in event")
    
    # Look up the full section from the decompressed document
    section = None
    for doc_section in full_document.sections:
        if doc_section.section_id == section_id:
            section = doc_section
            break
    
    if not section:
        raise ValueError(f"Section {section_id} not found in document")
    
    logger.info(f"Processing section {section_id} with {len(section.page_ids)} pages")
    
    # Update document status to EXTRACTING
    full_document.status = Status.EXTRACTING
    document_service = create_document_service()
    logger.info(f"Updating document status to {full_document.status}")
    document_service.update_document(full_document)
       
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
    extraction_service = extraction.ExtractionService(config=config)
    
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
        raise Exception(error_message)
    
    # Prepare output with automatic compression if needed
    response = {
        "section_id": section_id,
        "document": section_document.serialize_document(working_bucket, f"extraction_{section_id}", logger)
    }
    
    logger.info(f"Response: {json.dumps(response, default=str)}")
    return response
