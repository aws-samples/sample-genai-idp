# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import os
import json
import time
import logging

from idp_common import get_config, assessment
from idp_common.models import Document, Status
from idp_common.docs_service import create_document_service

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
    
    # Extract input from event - handle both compressed and uncompressed
    document_data = event.get('document', {})
    section_id = event.get('section_id')
    
    # Validate inputs
    if not document_data:
        raise ValueError("No document provided in event")
        
    if not section_id:
        raise ValueError("No section_id provided in event")
        
    # Convert document data to Document object - handle compression
    working_bucket = os.environ.get('WORKING_BUCKET')
    document = Document.load_document(document_data, working_bucket, logger)
    logger.info(f"Processing assessment for document {document.id}, section {section_id}")

    # Find the section we're processing
    section = None
    for s in document.sections:
        if s.section_id == section_id:
            section = s
            break
    
    if not section:
        raise ValueError(f"Section {section_id} not found in document")

    # Intelligent Assessment Skip: Check if extraction results already contain explainability_info
    if section.extraction_result_uri and section.extraction_result_uri.strip():
        try:
            from idp_common import s3
            logger.info(f"Checking extraction results for existing assessment: {section.extraction_result_uri}")
            extraction_data = s3.get_json_content(section.extraction_result_uri)
            
            # If explainability_info exists, assessment was already done
            if extraction_data.get('explainability_info'):
                logger.info(f"Skipping assessment for section {section_id} - extraction results already contain explainability_info")
                
                # Create section-specific document (same as normal processing) to match output format
                section_document = Document(
                    id=document.id,
                    input_bucket=document.input_bucket,
                    input_key=document.input_key,
                    output_bucket=document.output_bucket,
                    status=Status.ASSESSING,  # Keep status consistent with normal flow
                    initial_event_time=document.initial_event_time,
                    queued_time=document.queued_time,
                    start_time=document.start_time,
                    completion_time=document.completion_time,
                    workflow_execution_arn=document.workflow_execution_arn,
                    num_pages=len(section.page_ids),
                    summary_report_uri=document.summary_report_uri,
                    evaluation_status=document.evaluation_status,
                    evaluation_report_uri=document.evaluation_report_uri,
                    evaluation_results_uri=document.evaluation_results_uri,
                    errors=document.errors,
                    metering={}  # Empty metering for skipped processing
                )
                
                # Add only the pages needed for this section
                for page_id in section.page_ids:
                    if page_id in document.pages:
                        section_document.pages[page_id] = document.pages[page_id]
                
                # Add only the section being processed (preserve existing data)
                section_document.sections = [section]
                
                # Return consistent format for Map state collation
                response = {
                    "section_id": section_id, 
                    "document": section_document.serialize_document(working_bucket, f"assessment_skip_{section_id}", logger)
                }
                
                logger.info(f"Assessment skipped - Response: {json.dumps(response, default=str)}")
                return response
            else:
                logger.info(f"Assessment needed for section {section_id} - no explainability_info found in extraction results")
        except Exception as e:
            logger.warning(f"Error checking extraction results for assessment skip: {e}")
            # Continue with normal assessment if check fails

    # Normal assessment processing
    document.status = Status.ASSESSING

    # Update document status to ASSESSING for UI only
    # Create new 'shell' document since our input document has only 1 section. 
    docStatus = Document(
        id=document.id,
        input_key=document.input_key,
        status=Status.ASSESSING,
    )
    document_service = create_document_service()
    logger.info(f"Updating document status to {docStatus.status}")
    document_service.update_document(docStatus)

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
    
    # Prepare output with automatic compression if needed
    result = {
        'document': updated_document.serialize_document(working_bucket, f"assessment_{section_id}", logger),
        'section_id': section_id
    }
    
    logger.info("Assessment processing completed")
    return result
