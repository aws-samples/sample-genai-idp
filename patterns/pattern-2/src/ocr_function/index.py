"""
OCR function that processes PDFs and extracts text using AWS Textract.
Uses the idp_common.ocr package for OCR functionality.
"""

import json
import logging
import os
import time

from idp_common import get_config, ocr
from idp_common.models import Document

# Configuration
CONFIG = get_config()

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize settings
region = os.environ['AWS_REGION']
METRIC_NAMESPACE = os.environ.get('METRIC_NAMESPACE')
MAX_WORKERS = int(os.environ.get('MAX_WORKERS', 20))

def handler(event, context): 
    """
    Lambda handler for OCR processing.
    """       
    logger.info(f"Event: {json.dumps(event)}")
    
    # Get document from event
    document = Document.from_dict(event["document"])
    
    t0 = time.time()
    
    # Initialize the OCR service
    features = [feature['name'] for feature in CONFIG.get("ocr",{}).get("features",[])]
    logger.info(f"Initializing OCR for MAX_WORKERS: {MAX_WORKERS}, enhanced_features: {features}")
    service = ocr.OcrService(
        region=region,
        max_workers=MAX_WORKERS,
        enhanced_features=features
    )
    
    # Process the document - the service will read the PDF content directly
    document = service.process_document(document)
    
    t1 = time.time()
    logger.info(f"Total OCR processing time: {t1-t0:.2f} seconds")
    
    # Return the document as a dict - it will be passed to the next function
    response = {
        "document": document.to_dict()
    }
    
    logger.info(f"Response: {json.dumps(response, default=str)}")
    return response