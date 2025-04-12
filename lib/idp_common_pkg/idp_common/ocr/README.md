# OCR Service for IDP Accelerator

This module provides OCR (Optical Character Recognition) capabilities for processing documents within the IDP Accelerator project.

## Overview

The OCR service is designed to process PDF documents and extract text using AWS Textract. It supports both basic text detection and enhanced document analysis with tables and forms recognition. The service works directly with the Document model from the common data model.

## Features

- PDF processing with page-by-page OCR
- Concurrent processing of pages for improved performance
- Support for basic text detection (faster) or enhanced document analysis with granular Textract feature selection
- Direct integration with the Document data model
- Automatic S3 retrieval of input documents
- S3 storage of intermediate and final results
- Metering data collection for usage tracking
- Comprehensive error handling
- Rich markdown output for tables and forms when using enhanced features

## Usage Example

```python
from idp_common import ocr
from idp_common.models import Document

# Create or retrieve a Document object with input/output details
document = Document(
    id="doc-123",
    input_bucket="input-bucket",
    input_key="document.pdf",
    output_bucket="output-bucket"
)

# Initialize OCR service
ocr_service = ocr.OcrService(
    region='us-east-1',
    max_workers=20,
    enhanced_features=False  # Default: basic text detection (faster)
    # enhanced_features=["TABLES", "FORMS"]  # For table and form recognition
    # enhanced_features=["LAYOUT"]  # For layout analysis
    # enhanced_features=["TABLES", "FORMS", "SIGNATURES"]  # Multiple features
)

# Process document - this will automatically get the PDF from S3
processed_document = ocr_service.process_document(document)

# Use the results
print(f"Processed {processed_document.num_pages} pages")
for page_id, page in processed_document.pages.items():
    print(f"Page {page_id}: Image at {page.image_uri}")
    print(f"Page {page_id}: Text and Markdown at {page.parsed_text_uri}")
```

## Lambda Integration Example

```python
import json
import logging
import os
from idp_common import ocr
from idp_common.models import Document

# Initialize settings
region = os.environ['AWS_REGION']
MAX_WORKERS = int(os.environ.get('MAX_WORKERS', 20))

def handler(event, context): 
    # Get document from event
    document = Document.from_dict(event["document"])
    
    # Initialize the OCR service
    service = ocr.OcrService(
        region=region,
        max_workers=MAX_WORKERS,
        enhanced_features=False  # Use basic OCR (or specify features as a list)
    )
    
    # Process the document - the service will read the PDF content directly
    document = service.process_document(document)
    
    # Return the document as a dict - it will be passed to the next function
    return {
        "document": document.to_dict()
    }
```

## Roadmap

### Phase 1: Current Implementation (Basic Integration)
- ✅ Basic OCR service with PyMuPDF for PDF processing
- ✅ Support for Textract's text detection
- ✅ Compatible with existing Pattern workflow
- ✅ Full integration with Document data model
- ✅ Automatic document retrieval from S3
- ✅ Comprehensive error handling

### Phase 2: Enhanced Features
- ✅ Support for table extraction and form recognition
- ✅ Granular control of Textract feature types (TABLES, FORMS, SIGNATURES, LAYOUT)
- ✅ Improved parsing for extracted tables and forms
- ✅ Markdown output format for richer text representation
- 🔲 PDF processing options (resolution, format)