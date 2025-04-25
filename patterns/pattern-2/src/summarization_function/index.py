"""
Lambda function to summarize document content using the SummarizationService from idp_common.
"""
import json
import os
import logging
import time

# Import the SummarizationService from idp_common
from idp_common import get_config, summarization
from idp_common.models import Document

# Configuration
CONFIG = get_config()

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
# Get LOG_LEVEL from environment variable with INFO as default

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
        # Get required parameters
        document_dict = event.get('document', {})
        
        if not document_dict:
            raise ValueError("No document data provided")
        
        # Convert dict to Document object
        document = Document.from_dict(document_dict)
        
        # Create the summarization service with provided config
        summarization_service = summarization.SummarizationService(
            config=CONFIG
        )        
        # Process the document using the service
        logger.info(f"Processing document with SummarizationService, document ID: {document.id}")
        processed_document = summarization_service.process_document(document)
        
        # Log the result
        if hasattr(processed_document, 'summary_report_uri') and processed_document.summary_report_uri:
            logger.info(f"Document summarization successful, report URI: {processed_document.summary_report_uri}")
        else:
            logger.warning("Document summarization completed but no summary report URI was set")
        
        # Return the processed document
        return {
            'document': processed_document.to_dict(),
        }
        
    except Exception as e:
        logger.error(f"Error in summarization function: {str(e)}", exc_info=True)
        raise e