Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# Assessment Service for IDP Accelerator

This module provides the **standalone confidence assessment step** for the IDP
Accelerator. As of config **v0.6**, confidence is an **output of extraction**:
its settings live under `extraction.confidence.*` (and geometry under
`extraction.geometry.*`), not a top-level `assessment.*` block. This service
implements the standalone step that runs on the Simple (non-agentic) path when
`extraction.confidence.mode: separate` (the default). On the agentic path, and
for `integrated` mode, confidence is produced inside extraction and this
standalone step auto-skips.

> **Granular assessment is retired.** The former `GranularAssessmentService` /
> `granular_service.py` and the `extraction.confidence.granular` config field
> have been **deleted**. Large lists are handled by the standalone large-list
> batching described below (plus a bounded missing-row retry). Any leftover
> `granular.*` keys still validate but are ignored. See
> `docs/migration-granular-retirement.md`.

> **Compact reasons (default prompts).** The shipped confidence prompts ask the
> model to emit `confidence_reason` **only for leaves below 0.9 confidence**;
> confident leaves emit just `{"confidence": <score>}`. Because output tokens
> dominate assessment cost, this materially cuts cost with no effect on the
> scores or threshold/alert logic (`_enhance_dict_assessment` spreads whatever
> leaf keys are present). The many `confidence_reason`-on-every-field examples
> below predate this and are illustrative of the *structure*, not the
> reason-frequency. Widen the 0.9 threshold in the confidence `task_prompt` to
> get a reason on every field.

> **Integrated (simple-path) response shapes.** In `integrated` mode the single
> extraction inference returns values **and** confidence. The service prefers a
> `{"extraction": {...}, "confidence": {...}}` envelope, but also lifts a
> `field_assessment` (or `confidence`) **sibling** key emitted next to the
> extracted fields — stripping it from `inference_result` and promoting it to
> `explainability_info` so the standalone step auto-skips (avoids a redundant
> second Bedrock pass). See `ExtractionService._split_inline_confidence`.

## Overview

The Assessment service is designed to assess the confidence and accuracy of extraction results by analyzing them against source documents using LLMs. It supports both text and image content analysis and provides detailed confidence scores and explanations for each extracted attribute, applying configured confidence thresholds (threshold enrichment) to each field.

## Features

- **LLM-powered confidence assessment** using Amazon Bedrock models
- **Multi-modal analysis** with support for both document text and images
- **Automatic bounding box processing** with spatial localization of extracted fields
- **UI-compatible geometry output** for immediate visualization
- **Optimized token usage** with pre-generated text confidence data (80-90% reduction)
- **Structured confidence output** with scores and explanations per attribute
- **Prompt template support** with placeholder substitution
- **Image placeholder positioning** for precise multimodal prompt construction
- **Fallback mechanisms** for robust error handling
- **Metering integration** for usage tracking
- **Direct Document model integration**
- **Automatic large-list batching** for long tables (see *Large-list batching* below)

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

The assessment service uses configuration-driven prompts and model parameters,
under `extraction.confidence` in v0.6:

```yaml
extraction:
  confidence:
    enabled: true                       # Enable/disable confidence processing
    mode: separate                      # off | separate (default) | integrated
    model: "us.amazon.nova-pro-v1:0"
    temperature: 0
    top_k: 5
    top_p: 0.1
    max_tokens: 4096
    list_batch_size: 25                 # rows per assessment batch for large lists
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

### `enabled` Configuration Property

The assessment service supports runtime enable/disable control via the `enabled` property:

- **`enabled: true`** (default): Assessment processing proceeds normally
- **`enabled: false`**: Assessment is skipped entirely with minimal overhead

**Cost Optimization**: When `enabled: false`, no LLM API calls are made, resulting in zero assessment costs.

**Example - Disabling Assessment:**
```yaml
extraction:
  confidence:
    enabled: false  # Disables all confidence processing (equivalent to mode: off)
    # Other properties can remain but will be ignored
    model: us.amazon.nova-lite-v1:0
    temperature: 0.0
```

**Behavior When Disabled:**
- Service immediately returns with logging: "Assessment is disabled via configuration"
- No LLM API calls or S3 operations are performed
- Document processing continues to completion
- Minimal performance impact (early return)

## Large-list batching (`assessment/batching.py`)

A single confidence inference over a large list field (e.g. a 120-row transaction
table) is unreliable: the model under-enumerates or omits the list, leaving most
rows unassessed. The standalone Assessment step handles this itself — it does **not**
depend on granular assessment for large lists.

`process_document_section` runs the assessment through the shared
`idp_common.assessment.batching.assess_results_batched`, which:

1. Finds the single largest list field whose length exceeds
   `extraction.confidence.list_batch_size` (default 25).
2. Slices that list into `list_batch_size` chunks and assesses each chunk
   **sequentially**, passing the SAME scalars/context every time so scalar
   assessments and the document context are preserved (scalars come from the first
   batch). Sequential, not a thread pool, is intentional: the historical granular
   path's 20-way fan-out caused a Bedrock prompt-cacheWrite storm — batching
   sequentially avoids it and is why retiring granular is a net cost win.
3. Concatenates the per-row assessments in order and calls
   `reconcile_assessment_to_data` to force the assessment to index-align with the
   extracted data — truncating over-long lists, padding short/omitted ones with
   per-sub-field placeholders (so every un-assessed row is still groundable), and
   fanning any per-row scalar confidence out to per-column leaves.
4. Runs a **bounded missing-row retry**: any rows the model dropped within a
   batch are re-scored in a follow-up pass (missing rows only), so large-list
   coverage reaches 100% without re-scoring rows that already have confidence.

Both `assess_results_batched` and `reconcile_assessment_to_data` are shared with
the agentic in-shard assessment path (`ExtractionService`), so there is exactly one
implementation of large-list assessment. When no list exceeds the batch size the
helper makes a single (still reconciled) call — identical to the previous behavior.

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
      "confidence": 98.7
    },
    {
      "text": "Date: March 15, 2024",
      "confidence": 95.2
    }
  ]
}
```

## Automatic Bounding Box Processing

The assessment service now includes **automatic spatial localization** capabilities that convert LLM-provided bounding box coordinates to UI-compatible geometry format without any configuration.

### How It Works

1. **Enhanced Prompts**: Prompt templates request both confidence scores and spatial coordinates
2. **Automatic Detection**: Service detects when LLM provides `bbox` and `page` data
3. **Coordinate Conversion**: Converts from 0-1000 normalized scale to 0-1 geometry format
4. **UI Integration**: Outputs geometry format compatible with existing visualization

### Example Assessment with Spatial Data

**LLM Response (with bbox data):**
```json
{
  "InvoiceNumber": {
    "confidence": 0.95,
    "confidence_reason": "Clear text with high OCR confidence",
    "bbox": [100, 200, 300, 250],
    "page": 1
  },
  "VendorAddress": {
    "State": {
      "confidence": 0.99,
      "confidence_reason": "State clearly visible",
      "bbox": [230, 116, 259, 126], 
      "page": 1
    }
  }
}
```

**Automatic Conversion Output:**
```json
{
  "InvoiceNumber": {
    "confidence": 0.95,
    "confidence_reason": "Clear text with high OCR confidence",
    "confidence_threshold": 0.9,
    "geometry": [{
      "boundingBox": {
        "top": 0.2,
        "left": 0.1,
        "width": 0.2,
        "height": 0.05
      },
      "page": 1
    }]
  },
  "VendorAddress": {
    "State": {
      "confidence": 0.99,
      "confidence_reason": "State clearly visible",
      "confidence_threshold": 0.9,
      "geometry": [{
        "boundingBox": {
          "top": 0.116,
          "left": 0.23,
          "width": 0.029,
          "height": 0.01
        },
        "page": 1
      }]
    }
  }
}
```

### Supported Attribute Types

**All attribute types support automatic bounding box processing:**

- ✅ **Simple Attributes**: Direct conversion of bbox → geometry
- ✅ **Group Attributes**: Recursive processing of nested bbox data
- ✅ **List Attributes**: Individual bbox conversion for each list item

### Enhanced Prompt Requirements

To enable spatial localization, include these instructions in your `task_prompt`:

```yaml
extraction:
  geometry:
    mode: llm_grounded
  confidence:
    task_prompt: |
      <spatial-localization-guidelines>
      For each field, provide bounding box coordinates:
      - bbox: [x1, y1, x2, y2] coordinates in normalized 0-1000 scale
      - page: Page number where the field appears (starting from 1)

      Coordinate system:
      - Use normalized scale 0-1000 for both x and y axes
      - x1, y1 = top-left corner of bounding box
      - x2, y2 = bottom-right corner of bounding box
      - Ensure x2 > x1 and y2 > y1
      - Make bounding boxes tight around the actual text content
      </spatial-localization-guidelines>

      For each attribute, provide:
      {
        "attribute_name": {
          "confidence": 0.95,
          "confidence_reason": "Clear explanation",
          "bbox": [100, 200, 300, 250],
          "page": 1
        }
      }
```

### Benefits

- **No Configuration Required**: Works automatically when LLM provides bbox data
- **Backward Compatible**: Existing assessments without bbox continue working
- **UI Ready**: Geometry format works immediately with existing visualizations
- **Consistent**: applies uniformly across the standalone step and the agentic in-shard path

## Grounding Geometry in Real OCR Data

The bounding boxes produced above are **LLM-estimated**. When the OCR backend supplies real
geometry (Textract or the Mistral OCR LambdaHook), a post-LLM enrichment pass grounds each
field's box in the actual OCR coordinates from the consolidated per-page `pageData.json`
artifact (see `idp_common/ocr/README.md`). Implemented in `idp_common.assessment.ocr_grounding`
and used by the standalone assessment step (`service.py`) and the agentic in-shard path alike.

```python
from idp_common.assessment.ocr_grounding import (
    load_page_ocr_data,
    ground_assessment_geometry,
)

# Read pageData.json for the section's pages (keyed by 1-indexed page number).
page_data = load_page_ocr_data(document.pages, sorted_page_ids)

# Replace LLM-estimated boxes with real OCR boxes where the extracted value matches a line.
enhanced_assessment = ground_assessment_geometry(
    enhanced_assessment, extraction_results, page_data
)
```

Key behaviors:

- **Tiered matching** of each extracted value to OCR `lines[]`: exact → value-in-line →
  multi-line span (boxes unioned) → line fragment → token-overlap fuzzy (≥ 0.6).
- **Spatial disambiguation** of repeated values: when a value matches multiple lines, the
  candidate nearest the LLM-estimated box wins; with no usable reference box the field keeps
  its LLM box (so identical amounts across table rows don't collapse onto one line).
- **Coordinates stay 0–1**: `pageData` geometry is already normalized, so grounded boxes skip
  the 0–1000 → 0–1 rescale that LLM boxes go through. No mixed scales in `explainability_info`.
- **Additive output**: a matched field gets `geometry_source` (`"ocr"`/`"ocr-paragraph"`/
  `"llm"`) and, when available, `ocr_confidence` (0–1). The LLM `confidence`/`confidence_reason`
  are never modified, so HITL and confidence alerts are unaffected.
- **Config gate**: `extraction.geometry.mode` (`ocr_only` default | `llm_grounded` | `llm` | `off`). The legacy `assessment.ground_geometry_in_ocr: false` maps to `llm`; old configs are migrated on read.
- **Safe fallback**: absent `pageData.json`, `geometryAvailable: false`, or no value match →
  keep the LLM-estimated box (identical to prior behavior). `pageData.json` is read from S3, so
  the `{OCR_TEXT_CONFIDENCE}` prompt and token budget are unchanged.

See the *Geometry / Bounding Boxes* section of `docs/extraction-and-confidence.md`
for the user-facing description.

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
- Processes all document pages without image count restrictions
- Graceful fallback when images are unavailable
- Info logging for image count monitoring

## Attribute Types and Assessment Formats

The assessment service supports three distinct attribute types, each requiring a specific assessment response format. The service automatically detects the attribute type from your document class configuration and handles the assessment processing accordingly.

### 1. Simple Attributes

For basic single-value extractions like dates, amounts, or names.

**Configuration Example:**
```yaml
attributes:
  - name: "InvoiceNumber"
    attributeType: "simple"  # or omit for default
    description: "The invoice number from the document"
  - name: "TotalAmount"
    attributeType: "simple"
    description: "The total amount due"
```

**Expected Assessment Response:**
```json
{
  "InvoiceNumber": {
    "confidence": 0.92,
    "confidence_reason": "Invoice number clearly visible in standard location"
  },
  "TotalAmount": {
    "confidence": 0.87,
    "confidence_reason": "Amount visible but OCR confidence slightly lower due to formatting"
  }
}
```

### 2. Group Attributes

For nested object structures with multiple related fields that are logically grouped together.

**Configuration Example:**
```yaml
attributes:
  - name: "VendorDetails"
    attributeType: "group"
    description: "Vendor contact information"
    groupAttributes:
      - name: "VendorName"
        description: "Name of the vendor company"
      - name: "VendorAddress"
        description: "Vendor's business address"
      - name: "VendorPhone"
        description: "Vendor's contact phone number"
```

**Expected Assessment Response:**
```json
{
  "VendorDetails": {
    "VendorName": {
      "confidence": 0.95,
      "confidence_reason": "Company name clearly printed in header"
    },
    "VendorAddress": {
      "confidence": 0.88,
      "confidence_reason": "Address visible with good OCR quality"
    },
    "VendorPhone": {
      "confidence": 0.82,
      "confidence_reason": "Phone number partially blurred but readable"
    }
  }
}
```

### 3. List Attributes

For arrays of items where each item has the same structure, such as line items, transactions, or entries.

**Configuration Example:**
```yaml
attributes:
  - name: "LineItems"
    attributeType: "list"
    description: "Individual line items on the invoice"
    listItemTemplate:
      itemDescription: "A single invoice line item"
      itemAttributes:
        - name: "Description"
          description: "Item description or service name"
        - name: "Quantity"
          description: "Number of items or hours"
        - name: "UnitPrice"
          description: "Price per unit"
        - name: "Total"
          description: "Line item total (quantity × unit price)"
```

**Expected Assessment Response:**
```json
{
  "LineItems": [
    {
      "Description": {
        "confidence": 0.94,
        "confidence_reason": "Service description clearly printed"
      },
      "Quantity": {
        "confidence": 0.91,
        "confidence_reason": "Quantity number easily readable"
      },
      "UnitPrice": {
        "confidence": 0.89,
        "confidence_reason": "Unit price in standard currency format"
      },
      "Total": {
        "confidence": 0.93,
        "confidence_reason": "Total amount calculation clearly visible"
      }
    },
    {
      "Description": {
        "confidence": 0.87,
        "confidence_reason": "Description text slightly compressed but readable"
      },
      "Quantity": {
        "confidence": 0.95,
        "confidence_reason": "Quantity clearly printed in quantity column"
      },
      "UnitPrice": {
        "confidence": 0.88,
        "confidence_reason": "Unit price readable with minor OCR uncertainty"
      },
      "Total": {
        "confidence": 0.92,
        "confidence_reason": "Line total properly formatted and clear"
      }
    }
  ]
}
```

### Service Processing Behavior

The assessment service automatically handles each attribute type differently:

**Simple Attributes:**
- Expects a single confidence assessment object
- Adds confidence threshold to the assessment data
- Creates alerts for low confidence scores

**Group Attributes:**
- Processes each sub-attribute within the group independently
- Applies confidence thresholds to each sub-attribute
- Creates individual alerts for each sub-attribute that falls below threshold

**List Attributes:**
- Processes each array item separately (individual assessment per list item)
- Applies the same confidence thresholds to all items in the list
- Creates alerts using array notation (e.g., "LineItems[0].Description", "LineItems[1].Total")
- **Important**: Does NOT create aggregate assessments - each item must be assessed individually

### Assessment Response Requirements

**Critical Guidelines:**

1. **Structure Matching**: Assessment response must exactly mirror the extraction result structure
2. **List Processing**: For list attributes, assess each array item individually, never as an aggregate
3. **Nested Consistency**: Group attributes require confidence assessments for all sub-attributes
4. **Individual Focus**: Each confidence assessment should evaluate a specific field, not summarize multiple fields

**Common Mistakes to Avoid:**

```json
// ❌ WRONG: Aggregate assessment for list
{
  "LineItems": {
    "confidence": 0.85,
    "confidence_reason": "Overall line items look good"
  }
}

// ✅ CORRECT: Individual item assessments
{
  "LineItems": [
    {
      "Description": {"confidence": 0.94, "confidence_reason": "..."},
      "Quantity": {"confidence": 0.91, "confidence_reason": "..."}
    },
    {
      "Description": {"confidence": 0.87, "confidence_reason": "..."},
      "Quantity": {"confidence": 0.95, "confidence_reason": "..."}
    }
  ]
}
```

## Complete Assessment Output Example

Here's a comprehensive example showing all three attribute types in a single assessment:

```json
{
  "inference_result": {
    "InvoiceNumber": "INV-12345",
    "VendorDetails": {
      "VendorName": "ACME Corporation",
      "VendorAddress": "123 Business St, City, ST 12345",
      "VendorPhone": "(555) 123-4567"
    },
    "LineItems": [
      {
        "Description": "Professional Services",
        "Quantity": "40",
        "UnitPrice": "$125.00",
        "Total": "$5,000.00"
      },
      {
        "Description": "Materials",
        "Quantity": "10",
        "UnitPrice": "$25.00", 
        "Total": "$250.00"
      }
    ]
  },
  "explainability_info": [
    {
      "InvoiceNumber": {
        "confidence": 0.92,
        "confidence_reason": "Invoice number clearly visible in standard header location",
        "confidence_threshold": 0.85
      },
      "VendorDetails": {
        "VendorName": {
          "confidence": 0.95,
          "confidence_reason": "Company name clearly printed in document header with high OCR confidence",
          "confidence_threshold": 0.90
        },
        "VendorAddress": {
          "confidence": 0.88,
          "confidence_reason": "Address visible with good OCR quality, standard formatting",
          "confidence_threshold": 0.80
        },
        "VendorPhone": {
          "confidence": 0.82,
          "confidence_reason": "Phone number readable but slightly compressed in layout",
          "confidence_threshold": 0.75
        }
      },
      "LineItems": [
        {
          "Description": {
            "confidence": 0.94,
            "confidence_reason": "Service description clearly printed in line item table",
            "confidence_threshold": 0.80
          },
          "Quantity": {
            "confidence": 0.91,
            "confidence_reason": "Quantity number clearly visible in quantity column",
            "confidence_threshold": 0.85
          },
          "UnitPrice": {
            "confidence": 0.89,
            "confidence_reason": "Unit price in standard currency format, well aligned",
            "confidence_threshold": 0.85
          },
          "Total": {
            "confidence": 0.93,
            "confidence_reason": "Total amount clearly calculated and displayed",
            "confidence_threshold": 0.85
          }
        },
        {
          "Description": {
            "confidence": 0.87,
            "confidence_reason": "Description text slightly compressed but fully readable",
            "confidence_threshold": 0.80
          },
          "Quantity": {
            "confidence": 0.95,
            "confidence_reason": "Quantity clearly printed with excellent OCR confidence",
            "confidence_threshold": 0.85
          },
          "UnitPrice": {
            "confidence": 0.88,
            "confidence_reason": "Unit price readable with standard formatting",
            "confidence_threshold": 0.85
          },
          "Total": {
            "confidence": 0.92,
            "confidence_reason": "Line total properly formatted and clearly visible",
            "confidence_threshold": 0.85
          }
        }
      ]
    }
  ],
  "metadata": {
    "assessment_time_seconds": 4.23,
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
