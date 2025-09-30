# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Lambda function to summarize document content using the SummarizationService from idp_common.
"""
import json
import os
import logging
import time

# Import the SummarizationService from idp_common
from idp_common import get_config, summarization
from idp_common.models import Document, Status
from idp_common.docs_service import create_document_service

# Configuration will be loaded in handler function

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logging.getLogger('idp_common.bedrock.client').setLevel(os.environ.get("BEDROCK_LOG_LEVEL", "INFO"))

def handler(event, context):
    """
    Lambda handler for document summarization using the SummarizationService.
    
    Args:
        event: Lambda event containing document data and configuration
        context: Lambda context
        
    Returns:
        Dictionary with the summarization result
    """
    logger.info(f"Processing event: {json.dumps(event)}")
    start_time = time.time()
    
    try:
        # Get required parameters - handle both compressed and uncompressed
        document_data = event.get('document', {})
        
        if not document_data:
            raise ValueError("No document data provided")
        
        # Convert data to Document object - handle compression
        working_bucket = os.environ.get('WORKING_BUCKET')
        document = Document.load_document(document_data, working_bucket, logger)
        
        # Update document status to SUMMARIZING
        document.status = Status.SUMMARIZING
        document_service = create_document_service()
        logger.info(f"Updating document status to {document.status}")
        document_service.update_document(document)
        
        # Load configuration and create the summarization service
        config = get_config()
        summarization_service = summarization.SummarizationService(
            config=config
        )        
        # Process the document using the service
        logger.info(f"Processing document with SummarizationService, document ID: {document.id}")
        processed_document = summarization_service.process_document(document)
        
        # Check if document processing failed
        if processed_document.status == Status.FAILED:
            error_message = f"Summarization failed for document {processed_document.id}"
            logger.error(error_message)
            raise Exception(error_message)
        
        # Log the result
        if hasattr(processed_document, 'summary_report_uri') and processed_document.summary_report_uri:
            logger.info(f"Document summarization successful, report URI: {processed_document.summary_report_uri}")
        else:
            logger.warning("Document summarization completed but no summary report URI was set")
        
        # Prepare output with automatic compression if needed
        return {
            'document': processed_document.serialize_document(working_bucket, "summarization", logger),
        }
        
    except Exception as e:
        logger.error(f"Error in summarization function: {str(e)}", exc_info=True)
        
        # Update document status to FAILED if we have a document object
        try:
            if 'document' in locals() and document:
                document.status = Status.FAILED
                document.status_reason = str(e)
                document_service = create_document_service()
                logger.info(f"Updating document status to {document.status} due to error")
                document_service.update_document(document)
        except Exception as status_error:
            logger.error(f"Failed to update document status: {str(status_error)}", exc_info=True)
            
        raise e
