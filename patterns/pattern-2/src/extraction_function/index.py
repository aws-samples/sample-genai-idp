# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0


import os
import json
import time
import logging

from idp_common import metrics, get_config, extraction
from idp_common.models import Document, Section, Status
from idp_common.docs_service import create_document_service
from idp_common.utils import normalize_boolean_value

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

    # For Map state, we get just one section from the document
    # Extract the document and section from the event - handle both compressed and uncompressed
    working_bucket = os.environ.get('WORKING_BUCKET')
    full_document = Document.load_document(event.get("document", {}), working_bucket, logger)
    
    # Log loaded document for troubleshooting
    logger.info(f"Loaded document - ID: {full_document.id}, input_key: {full_document.input_key}")
    logger.info(f"Document buckets - input_bucket: {full_document.input_bucket}, output_bucket: {full_document.output_bucket}")
    logger.info(f"Document status: {full_document.status}, num_pages: {full_document.num_pages}")
    logger.info(f"Document pages count: {len(full_document.pages)}, sections count: {len(full_document.sections)}")
    logger.info(f"Full document content: {json.dumps(full_document.to_dict(), default=str)}")
    
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
      
    extraction_config = config.get('extraction', {})
    # Intelligent Extraction detection: Skip if section already has extraction data
    if section.extraction_result_uri and section.extraction_result_uri.strip():
        if not normalize_boolean_value(extraction_config.get('tuning', False)):
            logger.info(f"Skipping extraction for section {section_id} - already has extraction data: {section.extraction_result_uri}")
            
            # Return the section without processing
            response = {
                "section_id": section_id,
                "document": full_document.serialize_document(working_bucket, f"extraction_skip_{section_id}", logger)
            }
            
            logger.info(f"Extraction skipped - Response: {json.dumps(response, default=str)}")
            return response
        else:
            logger.info(f"Processing section {section_id} - no extraction data found, proceeding with extraction")
        
    # Normal extraction processing or selective processing for modified sections
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
        error_details = ''
        if hasattr(section_document, 'errors') and section_document.errors:
            error_details = '; '.join(str(e) for e in section_document.errors)
        error_message = f"Extraction failed for document {section_document.id}, section {section_id}"
        if error_details:
            error_message += f" Details: {error_details}"
        logger.error(error_message)
        raise Exception(error_message)
    
    # Prepare output with automatic compression if needed
    response = {
        "section_id": section_id,
        "document": section_document.serialize_document(working_bucket, f"extraction_{section_id}", logger)
    }
    
    logger.info(f"Response: {json.dumps(response, default=str)}")
    return response
