Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# Assessment Service for IDP Accelerator

This module provides assessment capabilities for evaluating document extraction confidence using LLMs within the IDP Accelerator project.

## Overview

The Assessment service is designed to assess the confidence and accuracy of extraction results by analyzing them against source documents using LLMs. It supports both text and image content analysis and provides detailed confidence scores and explanations for each extracted attribute.

## Features

- **LLM-powered confidence assessment** using Amazon Bedrock models
- **Multi-modal analysis** with support for both document text and images
- **Optimized token usage** with pre-generated text confidence data (80-90% reduction)
- **Structured confidence output** with scores and explanations per attribute
- **Prompt template support** with placeholder substitution
- **Image placeholder positioning** for precise multimodal prompt construction
- **Fallback mechanisms** for robust error handling
- **Metering integration** for usage tracking
- **Direct Document model integration**

## Usage Example

```python
from idp_common.assessment.service import AssessmentService
from idp_common.models import Document

# Initialize assessment service with configuration
assessment_service = AssessmentService(
    region="us-east-1",
    config=config_dict
)

# Process a single section
document = assessment_service.process_document_section(document, section_id="1")

# Or assess entire document
document = assessment_service.assess_document(document)

# Access assessment results in the extraction results
section = document.sections[0]
extraction_data = s3.get_json_content(section.extraction_result_uri)
assessment_info = extraction_data.get("explainability_info", {})

# Example assessment output:
# {
#   "vendor_name": {
#     "confidence": 0.95,
#     "confidence_reason": "Vendor name clearly visible in header with high OCR confidence"
#   },
#   "total_amount": {
#     "confidence": 0.87,
#     "confidence_reason": "Amount visible but OCR confidence slightly lower due to formatting"
#   }
# }
```

## Configuration

The assessment service uses configuration-driven prompts and model parameters:

```yaml
assessment:
  model: "anthropic.claude-3-5-sonnet-20241022-v2:0"
  temperature: 0
  top_k: 5
  top_p: 0.1
  max_tokens: 4096
  system_prompt: "You are an expert document analyst..."
  task_prompt: |
    Assess the confidence of extraction results for this {DOCUMENT_CLASS} document.
    
    Text Confidence Data:
    {OCR_TEXT_CONFIDENCE}
    
    Extraction Results:
    {EXTRACTION_RESULTS}
    
    Attributes Definition:
    {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}
    
    Document Images:
    {DOCUMENT_IMAGE}
    
    Respond with confidence assessments in JSON format.
```

## Prompt Template Placeholders

The assessment service supports the following placeholders in prompt templates:

### Standard Placeholders
- `{DOCUMENT_TEXT}` - Parsed document text (markdown format)
- `{DOCUMENT_CLASS}` - Document classification (e.g., "invoice", "contract")
- `{ATTRIBUTE_NAMES_AND_DESCRIPTIONS}` - Formatted list of attributes to extract
- `{EXTRACTION_RESULTS}` - JSON of extraction results to assess

### OCR Confidence Data
- `{OCR_TEXT_CONFIDENCE}` - **NEW** - Optimized text confidence data with 80-90% token reduction

### Image Positioning
- `{DOCUMENT_IMAGE}` - Placeholder for precise image positioning in multimodal prompts

## Text Confidence Data Integration

The assessment service automatically uses pre-generated text confidence data when available, providing significant performance and cost benefits:

### Automatic Data Source Selection
1. **Primary**: Uses pre-generated `textConfidence.json` files from OCR processing
2. **Fallback**: Generates text confidence data on-demand from raw OCR for backward compatibility

### Token Usage Optimization
```python
# Traditional approach (high token usage)
prompt = f"OCR Data: {raw_textract_response}"  # ~50,000 tokens

# Optimized approach (low token usage)  
prompt = f"Text Confidence Data: {text_confidence_data}"  # ~5,000 tokens
```

### Data Format
The text confidence data provides essential information in a minimal format:

```json
{
  "page_count": 2,
  "text_blocks": [
    {
      "text": "INVOICE #12345",
      "confidence": 98.7,
      "type": "PRINTED"
    },
    {
      "text": "Date: March 15, 2024",
      "confidence": 95.2,
      "type": "PRINTED"
    }
  ]
}
```

## Multimodal Assessment

The service supports sophisticated multimodal prompts with precise image positioning:

### Image Placeholder Usage
```python
task_prompt = """
Analyze the extraction results for accuracy.

Extraction Results:
{EXTRACTION_RESULTS}

{DOCUMENT_IMAGE}

Based on the document image above and the OCR confidence data below, 
assess each extracted field:

{OCR_TEXT_CONFIDENCE}
"""
```

### Automatic Image Handling
- Supports both single and multiple document images
- Automatically limits to 20 images per Bedrock constraints
- Graceful fallback when images are unavailable

## Assessment Output Structure

The service appends assessment results to existing extraction results:

```json
{
  "inference_result": {
    "vendor_name": "ACME Corporation",
    "invoice_number": "INV-12345",
    "total_amount": "$1,250.00"
  },
  "explainability_info": {
    "vendor_name": {
      "confidence": 0.95,
      "confidence_reason": "Vendor name clearly visible in document header with high OCR confidence (98.7%). Text format and positioning consistent with standard invoice layout."
    },
    "invoice_number": {
      "confidence": 0.92,
      "confidence_reason": "Invoice number clearly extracted with good OCR confidence (96.1%). Standard format and location confirmed."
    },
    "total_amount": {
      "confidence": 0.87,
      "confidence_reason": "Amount visible and extracted correctly, though OCR confidence slightly lower (89.3%) due to formatting complexity in table structure."
    }
  },
  "metadata": {
    "assessment_time_seconds": 3.47,
    "assessment_parsing_succeeded": true
  }
}
```

## Error Handling and Fallbacks

The assessment service includes comprehensive error handling:

### Parsing Failures
- Automatic fallback to default confidence scores (0.5) when LLM response parsing fails
- Detailed error logging for troubleshooting
- Continued processing of other sections

### Data Source Fallbacks
- Primary: Pre-generated text confidence files
- Secondary: On-demand text confidence generation from raw OCR
- Tertiary: Graceful degradation without OCR confidence data

### Template Validation
- Validates required placeholders in prompt templates
- Fallback to default prompts when template validation fails
- Flexible placeholder enforcement for partial templates

## Integration Example

```python
import json
from idp_common.assessment.service import AssessmentService
from idp_common.models import Document
from idp_common import s3

def lambda_handler(event, context):
    # Initialize service
    assessment_service = AssessmentService(
        region=os.environ['AWS_REGION'],
        config=event.get('config', {})
    )
    
    # Get document from event
    document = Document.from_dict(event['document'])
    
    # Assess all sections in the document
    assessed_document = assessment_service.assess_document(document)
    
    # Return updated document
    return {
        'document': assessed_document.to_dict()
    }
```

## Best Practices

### Prompt Design
- Use `{OCR_TEXT_CONFIDENCE}` instead of raw OCR data for optimal token usage
- Position `{DOCUMENT_IMAGE}` strategically in multimodal prompts
- Include clear instructions for confidence scoring (0.0 to 1.0 scale)

### Configuration
- Set appropriate temperature (0 for deterministic assessment)
- Configure max_tokens based on expected response length
- Use system prompts to establish assessment criteria

### Performance
- Leverage pre-generated text confidence data for best performance
- Monitor assessment timing and token usage through metering data
- Consider image limits for large multi-page documents

## Service Classes

### AssessmentService

Main service class for document assessment:

```python
class AssessmentService:
    def __init__(self, region: str = None, config: Dict[str, Any] = None)
    
    def process_document_section(self, document: Document, section_id: str) -> Document
    def assess_document(self, document: Document) -> Document
    
    # Internal methods for text confidence data and prompt building
    def _get_text_confidence_data(self, page) -> str
    def _build_content_with_or_without_image_placeholder(...) -> List[Dict[str, Any]]
```

### Assessment Models

Data models for structured assessment results:

```python
@dataclass
class AttributeAssessment:
    confidence: float
    confidence_reason: str

@dataclass 
class AssessmentResult:
    attributes: Dict[str, AttributeAssessment]
    metadata: Dict[str, Any]
