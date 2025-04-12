"""
Classification function for Pattern 3 that classifies documents using a SageMaker UDOP model.
Uses the common classification service with the SageMaker backend.
"""

import json
import logging
import os
import time

from idp_common import classification, metrics, get_config
from idp_common.models import Document, Status

# Configuration
CONFIG = get_config()
region = os.environ['AWS_REGION']
MAX_WORKERS = int(os.environ.get('MAX_WORKERS', 20))

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    """
    Lambda handler for document classification using SageMaker UDOP model.
    """
    logger.info(f"Event: {json.dumps(event)}")
    
    # Extract document from the OCR result
    document = Document.from_dict(event["OCRResult"]["document"])
    
    if document.status != Status.OCR_COMPLETED:
        raise ValueError(f"Document is not in OCR_COMPLETED stage, current status: {document.status}")
    
    if not document.pages:
        raise ValueError("Document has no pages to classify")
    
    t0 = time.time()
    
    # Track pages processed for metrics
    total_pages = len(document.pages)
    metrics.put_metric('ClassificationRequestsTotal', total_pages)
    
    # Update config with SageMaker endpoint name
    config_with_endpoint = CONFIG.copy() if CONFIG else {}
    config_with_endpoint["sagemaker_endpoint_name"] = os.environ['SAGEMAKER_ENDPOINT_NAME']
    
    # Initialize classification service with SageMaker backend
    service = classification.ClassificationService(
        region=region,
        max_workers=MAX_WORKERS,
        config=config_with_endpoint,
        backend="sagemaker"
    )
    
    # Classify the document - the service will update the Document directly
    document = service.classify_document(document)
    
    t1 = time.time()
    logger.info(f"Time taken for classification: {t1-t0:.2f} seconds")
    
    # Return document in a consistent envelope
    response = {
        "document": document.to_dict()
    }
    
    logger.info(f"Response: {json.dumps(response, default=str)}")
    return response