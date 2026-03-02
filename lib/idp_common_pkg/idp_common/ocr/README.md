Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# OCR Service for IDP Accelerator

This module provides OCR (Optical Character Recognition) capabilities for processing documents within the IDP Accelerator project.

## Overview

The OCR service is designed to process PDF documents and extract text using multiple backend options. It supports AWS Textract for traditional OCR with confidence scores, Amazon Bedrock for LLM-based text extraction, and image-only processing. The service works directly with the Document model from the common data model.

## OCR Backend Options

The service supports three OCR backends, each with different capabilities and use cases:

### 1. Textract Backend (Default - Recommended for Assessment)
- **Technology**: AWS Textract OCR service
- **Confidence Data**: ✅ Full granular confidence scores per text line (displayed as markdown table)
- **Features**: Basic text detection + enhanced document analysis (tables, forms, signatures, layout)
- **Assessment Quality**: ⭐⭐⭐ Optimal - Real OCR confidence enables accurate assessment
- **Use Cases**: Standard document processing, when assessment is enabled, production workflows

### 2. Bedrock Backend (LLM-based OCR)
- **Technology**: Amazon Bedrock LLMs (Claude, Nova) for text extraction
- **Confidence Data**: ❌ No confidence data (displays "No confidence data available from LLM OCR")
- **Features**: Advanced text understanding, better handling of challenging/degraded documents
- **Assessment Quality**: ❌ No confidence data for assessment
- **Use Cases**: Challenging documents where traditional OCR fails, specialized text extraction needs

### 3. None Backend (Image-only)
- **Technology**: No OCR processing
- **Confidence Data**: ❌ No confidence data (displays "No OCR performed")
- **Features**: Image extraction and storage only
- **Assessment Quality**: ❌ No text confidence for assessment
- **Use Cases**: Image-only workflows, custom OCR integration

> ⚠️ **CRITICAL for Assessment**: When assessment functionality is enabled, use `backend="textract"` (default) to preserve granular confidence data. Using `backend="bedrock"` results in empty confidence data that eliminates assessment capability.

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

### New Simplified Pattern (Recommended)

```python
from idp_common import ocr, get_config
from idp_common.models import Document

# Load configuration (typically from DynamoDB)
config = get_config()

# Create or retrieve a Document object with input/output details
document = Document(
    id="doc-123",
    input_bucket="input-bucket",
    input_key="document.pdf",
    output_bucket="output-bucket"
)

# Initialize OCR service with config dictionary
ocr_service = ocr.OcrService(
    region='us-east-1',
    config=config,  # Pass entire config dictionary
    backend='textract'  # Optional: override backend from config
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

### Legacy Pattern (Deprecated)

```python
# The old pattern with individual parameters is still supported but deprecated
ocr_service = ocr.OcrService(
    region='us-east-1',
    max_workers=20,
    enhanced_features=False,  # or ["TABLES", "FORMS"]
    dpi=150,
    resize_config={"target_width": 1024, "target_height": 1024},
    backend='textract'
)
```

## Configuration Structure

When using the new pattern, the OCR service expects configuration in the following structure:

```yaml
ocr:
  backend: "textract"  # Options: "textract", "bedrock", "none"
  max_workers: 20
  features:
    - name: "TABLES"
    - name: "FORMS"
  image:
    dpi: 150  # DPI for PDF page extraction (default: 150)
    target_width: 1024
    target_height: 1024
    preprocessing: false  # Enable adaptive binarization
  # For Bedrock backend only:
  model_id: "anthropic.claude-3-sonnet-20240229-v1:0"
  system_prompt: "You are an OCR system..."
  task_prompt: "Extract all text from this image..."
```

### Memory-Optimized Image Extraction

The OCR service uses advanced memory optimization to prevent OutOfMemory errors when processing large high-resolution documents:

**Direct Size Extraction**: When resize configuration is provided (`target_width` and `target_height`), images are extracted directly at the target dimensions using pypdfium2 matrix transformations. This completely eliminates memory spikes from creating oversized images.

**Example for Large Document:**
- **Original approach**: Extract 7469×9623 (101MB) → Resize to 951×1268 (5MB) → Memory spike
- **Optimized approach**: Extract directly at 951×1268 (5MB) → No memory spike

**Preserved Logic**: The optimization maintains all existing resize behavior:
- ✅ Never upscales images (only applies scaling when scale_factor < 1.0)
- ✅ Preserves aspect ratio using `min(width_ratio, height_ratio)`
- ✅ Handles edge cases (no config, images already smaller than targets)
- ✅ Full backward compatibility

### DPI Configuration

The DPI (dots per inch) setting controls the base resolution when extracting images from PDF pages:
- **Default**: 150 DPI (good balance of quality and file size)
- **Range**: 72-300 DPI  
- **Location**: `ocr.image.dpi` in the configuration
- **Behavior**: 
  - Only applies to PDF files (image files maintain their original resolution)
  - Combined with resize configuration for optimal memory usage
  - Higher DPI = better quality but larger file sizes (use with resize config for large documents)
  - 150 DPI is recommended for most OCR use cases
  - 300 DPI for documents with small text or fine details (ensure resize config is set)
  - 100 DPI for simple documents to reduce processing time

**Memory Considerations**: For large documents with high DPI settings, always configure `target_width` and `target_height` to prevent memory issues. The service will intelligently extract at the optimal size.


## Migration Guide

To migrate from the old pattern to the new pattern:

1. **In Lambda functions:**
   ```python
   # Old pattern
   features = [feature['name'] for feature in ocr_config.get("features", [])]
   service = ocr.OcrService(
       region=region,
       max_workers=MAX_WORKERS,
       enhanced_features=features,
       resize_config=resize_config,
       backend=backend
   )
   
   # New pattern
   config = get_config()
   service = ocr.OcrService(
       region=region,
       config=config,
       backend=config.get("ocr", {}).get("backend", "textract")
   )
   ```

2. **In notebooks:**
   ```python
   # Old pattern
   ocr_service = ocr.OcrService(
       region=region,
       enhanced_features=features
   )
   
   # New pattern
   ocr_service = ocr.OcrService(
       region=region,
       config=CONFIG  # Where CONFIG is your loaded configuration
   )
   ```

The new pattern provides:
- Cleaner, more consistent API across all IDP services
- Easier configuration management
- No need to extract individual parameters
- Future-proof design for adding new features

## Text Confidence Data

The OCR service automatically generates optimized text confidence data for each page, which is specifically designed for LLM assessment prompts. This feature dramatically reduces token usage while preserving all information needed for confidence evaluation.

### Generated Files per Page

For each page, the OCR service creates:

- **`image.jpg`** - Page image in JPEG format
- **`rawText.json`** - Complete Textract response (full metadata, geometric data, relationships)
- **`result.json`** - Parsed markdown text content for human readability
- **`textConfidence.json`** - **NEW** - Condensed text confidence data for assessment prompts

### Text Confidence Data Format

The format varies by OCR backend:

**Textract Backend (with confidence data):**
```json
{
  "text": "| Text | Confidence |\n|------|------------|\n| WESTERN DARK FIRED TOBACCO GROWERS' ASSOCIATION | 99.4 |\n| 206 Maple Street | 91.4 |\n| Murray, KY 42071 | 98.7 |"
}
```

The `text` field contains a markdown table with two columns:
- **Text**: The extracted text content (with pipe characters escaped as `\|`)
- **Confidence**: OCR confidence score rounded to 1 decimal point
- Handwriting is indicated with "(HANDWRITING)" suffix in the text column

**Bedrock Backend (no confidence data):**
```json
{
  "text": "| Text | Confidence |\n|------|------------|\n| *No confidence data available from LLM OCR* | N/A |"
}
```

**None Backend (no OCR):**
```json
{
  "text": "| Text | Confidence |\n|------|------------|\n| *No OCR performed* | N/A |"
}
```

### Benefits

- **85-95% token reduction** compared to raw Textract output (markdown table format is more compact than JSON)
- **Preserved assessment data**: Text content, OCR confidence scores (rounded to 1 decimal), text type (PRINTED/HANDWRITING)
- **Removed overhead**: Geometric data, relationships, block IDs, verbose metadata, and unnecessary JSON syntax
- **Improved readability**: Markdown table format is human-readable in both UI and assessment prompts
- **Cost efficiency**: Significantly reduced LLM inference costs for assessment workflows
- **UI compatibility**: Displays beautifully in the Text Confidence View using existing markdown rendering
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
- ✅ Basic OCR service with pypdfium2 for PDF processing
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
