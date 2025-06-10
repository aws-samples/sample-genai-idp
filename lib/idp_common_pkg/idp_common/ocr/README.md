Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

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
- **Text confidence data generation** for efficient assessment prompts
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
    print(f"Page {page_id}: Text confidence data at {page.text_confidence_uri}")
```

## Text Confidence Data

The OCR service automatically generates optimized text confidence data for each page, which is specifically designed for LLM assessment prompts. This feature dramatically reduces token usage while preserving all information needed for confidence evaluation.

### Generated Files per Page

For each page, the OCR service creates:

- **`image.jpg`** - Page image in JPEG format
- **`rawText.json`** - Complete Textract response (full metadata, geometric data, relationships)
- **`result.json`** - Parsed markdown text content for human readability
- **`textConfidence.json`** - **NEW** - Condensed text confidence data for assessment prompts

### Text Confidence Data Format

The condensed format includes only essential information:

```json
{
  "page_count": 1,
  "text_blocks": [
    {
      "text": "WESTERN DARK FIRED TOBACCO GROWERS' ASSOCIATION",
      "confidence": 99.35,
      "type": "PRINTED"
    },
    {
      "text": "206 Maple Street",
      "confidence": 91.41,
      "type": "PRINTED"
    }
  ]
}
```

### Benefits

- **80-90% token reduction** compared to raw Textract output
- **Preserved assessment data**: Text content, OCR confidence scores, text type (PRINTED/HANDWRITING)
- **Removed overhead**: Geometric data, relationships, block IDs, and verbose metadata
- **Cost efficiency**: Significantly reduced LLM inference costs for assessment workflows
- **Automated generation**: Created during initial OCR processing, not repeatedly during assessment

### Usage in Assessment Prompts

Assessment services can reference this data using the `{OCR_TEXT_CONFIDENCE}` placeholder in prompt templates:

```python
task_prompt = """
Assess the extraction confidence for this document.

Text Confidence Data:
{OCR_TEXT_CONFIDENCE}

Extraction Results:
{EXTRACTION_RESULTS}
"""
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
