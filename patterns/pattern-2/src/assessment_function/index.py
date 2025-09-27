# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import os
import json
import time
import logging

from idp_common import get_config, assessment
from idp_common.models import Document, Status
from idp_common.docs_service import create_document_service
from idp_common import s3
from idp_common.utils import normalize_boolean_value
from assessment_validator import AssessmentValidator

# Custom exception for throttling scenarios
class ThrottlingException(Exception):
    """Exception raised when throttling is detected in document processing results"""
    pass

# Throttling detection constants
THROTTLING_KEYWORDS = [
    "throttlingexception",
    "provisionedthroughputexceededexception", 
    "servicequotaexceededexception",
    "toomanyrequestsexception",
    "requestlimitexceeded",
    "too many tokens",
    "please wait before trying again",
    "reached max retries"
]

THROTTLING_EXCEPTIONS = [
    "ThrottlingException",
    "ProvisionedThroughputExceededException",
    "ServiceQuotaExceededException", 
    "TooManyRequestsException",
    "RequestLimitExceeded"
]

# Configuration will be loaded in handler function

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logging.getLogger('idp_common.bedrock.client').setLevel(os.environ.get("BEDROCK_LOG_LEVEL", "INFO"))

def is_throttling_exception(exception):
    """
    Check if an exception is related to throttling.
    
    Args:
        exception: The exception to check
        
    Returns:
        bool: True if the exception is throttling-related, False otherwise
    """
    from botocore.exceptions import ClientError
    
    if isinstance(exception, ClientError):
        error_code = exception.response.get('Error', {}).get('Code', '')
        return error_code in THROTTLING_EXCEPTIONS
    
    exception_name = type(exception).__name__
    exception_message = str(exception).lower()
    
    return (
        exception_name in THROTTLING_EXCEPTIONS or
        any(keyword in exception_message for keyword in THROTTLING_KEYWORDS)
    )

def check_document_for_throttling_errors(document):
    """
    Check if a document has throttling errors in its errors field.
    
    Args:
        document: The document object to check
        
    Returns:
        tuple: (has_throttling_errors: bool, first_throttling_error: str or None)
    """
    if document.status != Status.FAILED or not document.errors:
        return False, None
    
    for error_msg in document.errors:
        error_lower = str(error_msg).lower()
        if any(keyword in error_lower for keyword in THROTTLING_KEYWORDS):
            return True, error_msg
    
    return False, None

def handler(event, context):
    """
    Lambda handler for document assessment.
    This function assesses the confidence of extraction results for a document section
    using the Assessment service from the idp_common library.
    """
    logger.info(f"Starting assessment processing for event: {json.dumps(event, default=str)}")

    # Load configuration
    config = get_config()
    # Use default=str to handle Decimal and other non-serializable types
    logger.info(f"Config: {json.dumps(config, default=str)}")
    
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

    # Initialize assessment service with cache table for enhanced retry handling
    cache_table = os.environ.get('TRACKING_TABLE')
    
    # Check if granular assessment is enabled
    granular_config = config.get('assessment', {}).get('granular', {})
    granular_enabled = granular_config.get('enabled', False)
    
    if granular_enabled:
        # Use enhanced granular assessment service with caching and retry support
        from idp_common.assessment.granular_service import GranularAssessmentService
        assessment_service = GranularAssessmentService(config=config, cache_table=cache_table)
        logger.info("Using granular assessment service with enhanced error handling and caching")
    else:
        # Use regular assessment service
        assessment_service = assessment.AssessmentService(config=config)
        logger.info("Using regular assessment service")

    # Process the document section for assessment
    t0 = time.time()
    logger.info(f"Starting assessment for section {section_id}")
    
    try:
        updated_document = assessment_service.process_document_section(document, section_id)
        if updated_document.status == Status.FAILED:
            error_message = f"Assesment failed for document {updated_document.id}, section {section_id} Details: {updated_document.errors[-1]}"
            logger.error(error_message)
            raise Exception(error_message)
        
        t1 = time.time()
        logger.info(f"Total assessment time: {t1-t0:.2f} seconds")
        
        # Check for failed assessment tasks that might require retry (granular assessment)
        if hasattr(updated_document, 'metadata') and updated_document.metadata:
            failed_tasks = updated_document.metadata.get('failed_assessment_tasks', {})
            if failed_tasks:
                throttling_tasks = {
                    task_id: task_info for task_id, task_info in failed_tasks.items()
                    if task_info.get('is_throttling', False)
                }
                
                logger.warning(
                    f"Assessment completed with {len(failed_tasks)} failed tasks, "
                    f"{len(throttling_tasks)} due to throttling"
                )
                
                if throttling_tasks:
                    logger.info(
                        f"Throttling detected in {len(throttling_tasks)} tasks. "
                        f"Successful tasks have been cached for retry."
                    )
        
        # Check for throttling errors in document status and errors field
        has_throttling, throttling_error = check_document_for_throttling_errors(updated_document)
        if has_throttling:
            logger.error(f"Throttling error detected in document errors: {throttling_error}")
            logger.error("Raising ThrottlingException to trigger Step Functions retry")
            raise ThrottlingException(f"Throttling detected in document processing: {throttling_error}")
        
    except Exception as e:
        t1 = time.time()
        logger.error(f"Assessment failed after {t1-t0:.2f} seconds: {str(e)}")
        
        # Check if this is a throttling exception that should trigger retry
        if is_throttling_exception(e):
            logger.error(f"Throttling exception detected: {type(e).__name__}. This will trigger state machine retry.")
            # Update document status before re-raising
            document_service.update_document(docStatus)
            # Re-raise to trigger state machine retry
            raise
        else:
            logger.error(f"Non-throttling exception: {type(e).__name__}. Marking document as failed.")
            # Set document status to failed for non-throttling exceptions
            updated_document = document
            updated_document.status = Status.FAILED
            updated_document.errors.append(str(e))

    # Assessment validation
    assessment_config = config.get('assessment', {})
    assessment_enabled = normalize_boolean_value(assessment_config.get('enabled', False))
    validation_enabled = assessment_enabled and normalize_boolean_value(assessment_config.get('validation_enabled', True))
    logger.info(f"Assessment Enabled:{assessment_enabled}")
    logger.info(f"Validation Enabled:{validation_enabled}")
    if not assessment_enabled:
        logger.info("Assessment is disabled.")
    elif not validation_enabled:
        logger.info("Assessment validation is disabled.")
    else:
        for section in updated_document.sections:
            if section.section_id == section_id and section.extraction_result_uri:
                logger.info(f"Loading assessment results from: {section.extraction_result_uri}")
                # Load extraction data with assessment results
                extraction_data = s3.get_json_content(section.extraction_result_uri)
                validator = AssessmentValidator(extraction_data,
                                                assessment_config=assessment_config,
                                                enable_missing_check=True,
                                                enable_count_check=True)
                validation_results = validator.validate_all()
                if not validation_results['is_valid']:
                    # Handle validation failure
                    updated_document.status = Status.FAILED
                    validation_errors = validation_results['validation_errors']
                    updated_document.errors.extend(validation_errors)
                    logger.error(f"Validation Error: {validation_errors}")

    # Prepare output with automatic compression if needed
    result = {
        'document': updated_document.serialize_document(working_bucket, f"assessment_{section_id}", logger),
        'section_id': section_id
    }
    
    logger.info("Assessment processing completed")
    return result