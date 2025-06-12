# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Lambda function for evaluating document extraction results.

This module provides a lambda handler that evaluates document extraction results by comparing
them against baseline results using the EvaluationService from idp_common.
"""

import json
import os
import logging
import time
from typing import Dict, Any, Optional, List
from enum import Enum

# Import IDP common packages
from idp_common.models import Document, Status
from idp_common import get_config, evaluation
from idp_common.appsync import DocumentAppSyncService

# Import local modules
from save_to_reporting import save_evaluation_to_reporting_bucket

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logging.getLogger('idp_common.bedrock.client').setLevel(os.environ.get("BEDROCK_LOG_LEVEL", "INFO"))
# Get LOG_LEVEL from environment variable with INFO as default

# Get bucket names from environment variables
METRIC_NAMESPACE = os.environ.get('METRIC_NAMESPACE', 'GENAIDP')
BASELINE_BUCKET = os.environ['BASELINE_BUCKET']
REPORTING_BUCKET = os.environ['REPORTING_BUCKET']

# Configuration will be loaded in handler function

# Create AppSync service
appsync_service = DocumentAppSyncService()

# Define evaluation status constants
class EvaluationStatus(Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    NO_BASELINE = "NO_BASELINE"

def update_document_evaluation_status(document: Document, status: EvaluationStatus) -> Document:
    """
    Update document evaluation status via AppSync
    
    Args:
        document: The Document object to update
        status: The evaluation status
        
    Returns:
        The updated Document object
        
    Raises:
        AppSyncError: If the GraphQL operation fails
    """
    document.status = Status.COMPLETED
    document.evaluation_status = status.value
    logger.info(f"Updating document via AppSync: {document.input_key} with status: {status.value}")
    return appsync_service.update_document(document)

def extract_document_from_event(event: Dict[str, Any]) -> Optional[Document]:
    """
    Extract document from Lambda event
    
    Args:
        event: Lambda event
        
    Returns:
        Document object or None if not found
        
    Raises:
        ValueError: If document cannot be extracted from event
    """
    try:
        input_data = json.loads(event['detail']['input'])
        output_data = json.loads(event['detail']['output'])
        
        if not output_data:
            raise ValueError("No output data found in event")
            
        # Get the processed document from the output data
        processed_result = output_data.get("Result", {})
        if "document" not in processed_result:
            raise ValueError("No document found in Result")
            
        # Get document from the final processing step
        document = Document.from_dict(processed_result.get("document", {}))
        logger.info(f"Successfully loaded actual document with {len(document.pages)} pages and {len(document.sections)} sections")
        return document
    except Exception as e:
        logger.error(f"Error extracting document from event: {str(e)}")
        raise ValueError(f"Failed to extract document from event: {str(e)}")

def load_baseline_document(document_key: str) -> Optional[Document]:
    """
    Load baseline document from S3
    
    Args:
        document_key: The document key to load
        
    Returns:
        Document object or None if no baseline is found
        
    Raises:
        ValueError: If baseline document cannot be loaded
    """
    try:
        logger.info(f"Loading baseline document for {document_key} from {BASELINE_BUCKET}")
        
        expected_document = Document.from_s3(
            bucket=BASELINE_BUCKET, 
            input_key=document_key
        )
        
        # Check if the expected document has meaningful data
        if not expected_document.sections:
            logger.warning(f"No baseline data found for {document_key} in {BASELINE_BUCKET} (empty document)")
            return None
            
        # Baseline data exists and is valid
        logger.info(f"Successfully loaded expected (baseline) document with {len(expected_document.pages)} pages and {len(expected_document.sections)} sections")
        return expected_document
        
    except Exception as e:
        logger.error(f"Error loading baseline document: {str(e)}")
        raise ValueError(f"Failed to load baseline document: {str(e)}")



def create_response(status_code: int, message: str, additional_data: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Create a standardized response
    
    Args:
        status_code: HTTP status code
        message: Response message
        additional_data: Optional additional data to include in response
        
    Returns:
        Formatted response dictionary
    """
    response = {
        'statusCode': status_code,
        'body': json.dumps({
            'message': message,
            **(additional_data or {})
        })
    }
    return response

def handler(event, context):
    """
    Lambda function handler
    
    Args:
        event: Lambda event
        context: Lambda context
        
    Returns:
        Response with evaluation results
    """
    actual_document = None
    start_time = time.time()
    
    try:
        logger.info(f"Starting evaluation process with event: {json.dumps(event, indent=2)}")
        
        # Extract document from event
        actual_document = extract_document_from_event(event)
        
        # Update document status to RUNNING
        update_document_evaluation_status(actual_document, EvaluationStatus.RUNNING)
        
        # Load baseline document
        expected_document = load_baseline_document(actual_document.input_key)
        
        # If no baseline document is found, update status and exit
        if not expected_document:
            update_document_evaluation_status(actual_document, EvaluationStatus.NO_BASELINE)
            return create_response(
                200,
                'Evaluation skipped - no baseline data available',
                {'document_key': actual_document.input_key}
            )
        
        # Load configuration and create evaluation service
        config = get_config()
        evaluation_service = evaluation.EvaluationService(config=config)
        
        # Run evaluation
        logger.info(f"Starting evaluation for document {actual_document.id}")
        evaluated_document = evaluation_service.evaluate_document(
            actual_document=actual_document,
            expected_document=expected_document,
            store_results=True
        )
        
        # Check for evaluation errors
        if evaluated_document.errors:
            error_msg = f"Evaluation encountered errors: {evaluated_document.errors}"
            logger.error(error_msg)
            update_document_evaluation_status(evaluated_document, EvaluationStatus.FAILED)
            return create_response(500, 'Evaluation failed', {'error': error_msg})
       
        # Save evaluation results to reporting bucket for analytics
        save_evaluation_to_reporting_bucket(evaluated_document, REPORTING_BUCKET)
        
        # Update document evaluation status to COMPLETED
        update_document_evaluation_status(evaluated_document, EvaluationStatus.COMPLETED)
        logger.info("Evaluation process completed successfully")
        
        # Return success response
        return create_response(
            200,
            'Evaluation completed successfully',
            {
                'report_location': evaluated_document.evaluation_report_uri,
                'execution_time': time.time() - start_time
            }
        )
    
    except Exception as e:
        error_msg = f"Error in lambda_handler: {str(e)}"
        logger.error(error_msg)
        
        # Update document status to FAILED if we have the document
        if actual_document:
            try:
                update_document_evaluation_status(actual_document, EvaluationStatus.FAILED)
            except Exception as update_error:
                logger.error(f"Failed to update evaluation status: {str(update_error)}")
        
        return create_response(500, 'Evaluation failed', {'error': error_msg})