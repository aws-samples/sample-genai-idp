---
title: "Assessment Feature"
---

# Assessment Feature

Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

## Overview

The Assessment feature provides automated confidence evaluation of document extraction results using Large Language Models (LLMs). This feature analyzes extraction outputs against source documents to provide confidence scores and explanations for each extracted attribute, helping users understand the reliability of automated extractions.

## Key Features

- **Multimodal Analysis**: Combines text analysis with document images for comprehensive confidence assessment
- **Per-Attribute Scoring**: Provides individual confidence scores and explanations for each extracted attribute
- **Automatic Bounding Box Processing**: Spatial localization of extracted fields with UI-compatible geometry output
- **Token-Optimized Processing**: Uses condensed text confidence data for 80-90% token reduction compared to full OCR results
- **UI Integration**: Seamlessly displays assessment results in the web interface with explainability information
- **Confidence Threshold Support**: Configurable global and per-attribute confidence thresholds with color-coded visual indicators
- **Enhanced Visual Feedback**: Real-time confidence assessment with green/red/black color coding in all data viewing interfaces
- **Optional Deployment**: Controlled by `IsAssessmentEnabled` parameter (defaults to false for cost optimization)
- **Flexible Image Usage**: Images only processed when explicitly requested via `{DOCUMENT_IMAGE}` placeholder
- **Granular Assessment**: Advanced scalable approach for complex documents with many attributes or list items
- **Parallel Processing**: Multi-threaded assessment execution for improved performance
- **Prompt Caching**: Leverages LLM caching capabilities to reduce costs for repeated assessments
- **Visual Document Annotation**: Automatic conversion of spatial data for immediate document visualization

## Architecture

### Assessment Workflow

1. **Post-Extraction Processing**: Assessment runs after successful extraction within the same state machine
2. **Document Analysis**: LLM analyzes extraction results against source document text and optionally images
3. **Confidence Scoring**: Generates confidence scores (0.0-1.0) with explanatory reasoning for each attribute
4. **Result Integration**: Appends assessment data to existing extraction results in `explainability_info` format
5. **UI Display**: Assessment results automatically appear in the web interface visual editor

### State Machine Integration

The assessment step is conditionally integrated into Pattern-2's ProcessSections map state:

```json
{
  "AssessSection": {
    "Type": "Task",
    "Resource": "arn:aws:states:::lambda:invoke",
    "Parameters": {
      "FunctionName": "${AssessmentFunction}",
      "Payload": {
        "document.$": "$.document",
        "section_id.$": "$.section_id"
      }
    },
    "End": true
  }
}
```

## Configuration

### Configuration-Based Control

Assessment can now be controlled via the configuration file rather than CloudFormation stack parameters. This provides more flexibility and eliminates the need for stack redeployment when changing assessment behavior.

**Configuration-based Control (Recommended):**
```yaml
assessment:
  enabled: true  # Set to false to disable assessment
  model: us.amazon.nova-lite-v1:0
  temperature: 0.0
  # ... other assessment settings
```

**Key Benefits:**
- **Runtime Control**: Enable/disable without stack redeployment  
- **Cost Optimization**: Zero LLM costs when disabled (`enabled: false`)
- **Simplified Architecture**: No conditional logic in state machines
- **Backward Compatible**: Defaults to `enabled: true` when property is missing

**Behavior When Disabled:**
- Assessment lambda is still called (minimal overhead)
- Service immediately returns with logging: "Assessment is disabled via configuration"
- No LLM API calls or S3 operations are performed
- Document processing continues to completion

**Migration Note**: The previous `IsAssessmentEnabled` CloudFormation parameter has been removed in favor of this configuration-based approach.

### Assessment Configuration Section

Add the assessment section to your configuration YAML:

```yaml
assessment:
  model: "anthropic.claude-3-5-sonnet-20241022-v2:0"
  temperature: 0
  top_k: 5
  top_p: 0.1
  max_tokens: 4096
  system_prompt: |
    You are an expert document analyst specializing in assessing the confidence and accuracy of document extraction results.
  task_prompt: |
    <background>
    You are an expert document analysis assessment system. Your task is to evaluate the confidence of extraction results for a document of class {DOCUMENT_CLASS} and provide precise spatial localization for each field.
    </background>

    <task>
    Analyze the extraction results against the source document and provide confidence assessments AND bounding box coordinates for each extracted attribute. Consider factors such as:
    1. Text clarity and OCR quality in the source regions 
    2. Alignment between extracted values and document content 
    3. Presence of clear evidence supporting the extraction 
    4. Potential ambiguity or uncertainty in the source material 
    5. Completeness and accuracy of the extracted information
    6. Precise spatial location of each field in the document
    </task>

    <assessment-guidelines>
    For each attribute, provide: 
    - A confidence score between 0.0 and 1.0 where:
       - 1.0 = Very high confidence, clear and unambiguous evidence
       - 0.8-0.9 = High confidence, strong evidence with minor uncertainty
       - 0.6-0.7 = Medium confidence, reasonable evidence but some ambiguity
       - 0.4-0.5 = Low confidence, weak or unclear evidence
       - 0.0-0.3 = Very low confidence, little to no supporting evidence
    - A clear explanation of the confidence reasoning
    - Precise spatial coordinates where the field appears in the document
    </assessment-guidelines>

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

    <<CACHEPOINT>>

    <document-image>
    {DOCUMENT_IMAGE}
    </document-image>

    <ocr-text-confidence-results>
    {OCR_TEXT_CONFIDENCE}
    </ocr-text-confidence-results>

    <<CACHEPOINT>>

    <attributes-definitions>
    {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}
    </attributes-definitions>

    <extraction-results>
    {EXTRACTION_RESULTS}
    </extraction-results>
    
    Provide confidence assessments with spatial localization in JSON format:
    {
      "attribute_name": {
        "confidence": 0.85,
        "confidence_reason": "Clear text with high OCR confidence, easily identifiable location",
        "bbox": [100, 200, 300, 250],
        "page": 1
      }
    }
```

### Prompt Placeholders

The assessment prompts support the following placeholders:

| Placeholder | Description |
|-------------|-------------|
| `{DOCUMENT_CLASS}` | The classified document type |
| `{EXTRACTION_RESULTS}` | JSON string of extraction results to assess |
| `{ATTRIBUTE_NAMES_AND_DESCRIPTIONS}` | Formatted list of attribute names and descriptions |
| `{DOCUMENT_TEXT}` | Full document text (markdown) from OCR |
| `{OCR_TEXT_CONFIDENCE}` | Condensed OCR confidence data (80-90% token reduction) |
| `{DOCUMENT_IMAGE}` | **Optional** - Inserts document images at specified position |

### Image Processing with DOCUMENT_IMAGE

The `{DOCUMENT_IMAGE}` placeholder enables precise control over image inclusion:

#### Text-Only Assessment (Default)
```yaml
task_prompt: |
  Assess extraction results based on document text and OCR confidence data:
  
  Document Text: {DOCUMENT_TEXT}
  OCR Confidence: {OCR_TEXT_CONFIDENCE}
  Extraction Results: {EXTRACTION_RESULTS}
```

#### Multimodal Assessment
```yaml
task_prompt: |
  Assess extraction results by analyzing both text and visual document content:
  
  Document Text: {DOCUMENT_TEXT}
  
  {DOCUMENT_IMAGE}
  
  Based on the above document image and text, assess these extraction results:
  {EXTRACTION_RESULTS}
```

**Important**: Images are only processed when the `{DOCUMENT_IMAGE}` placeholder is explicitly present in the prompt template.

## Automatic Bounding Box Processing

The assessment feature includes automatic spatial localization capabilities that extract bounding box coordinates from LLM responses and convert them to a UI-compatible geometry format. This provides visual field localization consistent with Pattern-1 (BDA) without requiring additional configuration.

### How It Works

#### 1. Spatial Localization in Task Prompts

Include spatial localization guidelines in your assessment task prompts to request bounding box coordinates from the LLM:

```yaml
assessment:
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
    
    Provide confidence assessments with spatial localization in JSON format:
    {
      "attribute_name": {
        "confidence": 0.85,
        "confidence_reason": "Clear text with high OCR confidence",
        "bbox": [100, 200, 300, 250],
        "page": 1
      }
    }
```

#### 2. Automatic Coordinate Conversion

When the LLM provides bounding box data in the assessment response, the system automatically:

1. **Detects spatial data**: Identifies `bbox` and `page` fields in the LLM response
2. **Converts coordinates**: Transforms from 0-1000 normalized scale to 0-1 decimal format
3. **Calculates dimensions**: Converts [x1, y1, x2, y2] to {top, left, width, height} format
4. **Creates geometry objects**: Formats data for Pattern-1/BDA UI compatibility
5. **Processes recursively**: Handles nested group attributes and list items automatically

#### 3. Coordinate System Transformation

The conversion process transforms coordinates from the LLM's 0-1000 scale to the UI's 0-1 decimal format:

```python
# LLM Response Format
{
  "StatementDate": {
    "confidence": 0.95,
    "bbox": [100, 200, 400, 250],  # [x1, y1, x2, y2] in 0-1000 scale
    "page": 1
  }
}

# Automatically Converted to UI Format
{
  "StatementDate": {
    "confidence": 0.95,
    "confidence_threshold": 0.85,
    "geometry": [{
      "boundingBox": {
        "top": 0.2,     # y1 / 1000
        "left": 0.1,    # x1 / 1000  
        "width": 0.3,   # (x2 - x1) / 1000
        "height": 0.05  # (y2 - y1) / 1000
      },
      "page": 1
    }]
  }
}
```

#### 4. Pattern-1 Compatibility

The geometry format exactly matches Pattern-1 (BDA) specifications:
- **boundingBox object**: Contains top, left, width, height as decimal values (0-1)
- **page field**: 1-based page numbering
- **Array structure**: geometry as array to support multiple regions per field
- **Recursive processing**: Handles nested attributes like `CompanyAddress.State`

### Configuration-Free Operation

The bounding box feature requires no additional configuration:
- **Automatic detection**: System detects when LLM provides spatial data
- **Fallback handling**: Works normally when no bounding boxes are provided
- **Backward compatibility**: Existing configurations continue to work unchanged
- **Optional enhancement**: Bounding boxes enhance existing assessment without breaking changes

## Output Format

Assessment results are appended to extraction results in the `explainability_info` format expected by the UI. The format varies based on the attribute type defined in your document class configuration.

### Attribute Types and Assessment Formats

The assessment service supports three types of attributes, each with a specific assessment response format:

#### 1. Simple Attributes

For basic single-value extractions like dates, amounts, or names:

**Configuration:**
```yaml
properties:
  StatementDate:
    type: string
    description: "The date of the bank statement"
```

**Assessment Response (without spatial data):**
```json
{
  "StatementDate": {
    "confidence": 0.85,
    "confidence_reason": "Date clearly visible in statement header"
  }
}
```

**Assessment Response (with automatic spatial data):**
```json
{
  "StatementDate": {
    "confidence": 0.85,
    "confidence_reason": "Date clearly visible in statement header",
    "confidence_threshold": 0.85,
    "geometry": [{
      "boundingBox": {
        "top": 0.2,
        "left": 0.1,
        "width": 0.15,
        "height": 0.03
      },
      "page": 1
    }]
  }
}
```

#### 2. Group Attributes

For nested object structures with multiple related fields:

**Configuration:**
```yaml
properties:
  AccountDetails:
    type: object
    description: "Bank account information"
    properties:
      AccountNumber:
        type: string
        description: "The account number"
      RoutingNumber:
        type: string
        description: "The bank routing number"
```

**Assessment Response (with automatic spatial data):**
```json
{
  "AccountDetails": {
    "AccountNumber": {
      "confidence": 0.90,
      "confidence_reason": "Account number clearly printed in standard location",
      "confidence_threshold": 0.90,
      "geometry": [{
        "boundingBox": {
          "top": 0.15,
          "left": 0.2,
          "width": 0.25,
          "height": 0.04
        },
        "page": 1
      }]
    },
    "RoutingNumber": {
      "confidence": 0.75,
      "confidence_reason": "Routing number visible but slightly blurred",
      "confidence_threshold": 0.90,
      "geometry": [{
        "boundingBox": {
          "top": 0.2,
          "left": 0.2,
          "width": 0.2,
          "height": 0.03
        },
        "page": 1
      }]
    }
  }
}
```

#### 3. List Attributes

For arrays of items, such as transactions in a bank statement:

**Configuration:**
```yaml
properties:
  Transactions:
    type: array
    description: "List of all transactions on the statement"
    x-aws-idp-list-item-description: "Individual transaction entry"
    items:
      type: object
      properties:
        Date:
          type: string
          description: "Transaction date"
        Description:
          type: string
          description: "Transaction description"
        Amount:
          type: string
          description: "Transaction amount"
```

**Assessment Response (with automatic spatial data):**
```json
{
  "Transactions": [
    {
      "Date": {
        "confidence": 0.95,
        "confidence_reason": "Date clearly printed in standard format",
        "confidence_threshold": 0.80,
        "geometry": [{
          "boundingBox": {
            "top": 0.3,
            "left": 0.1,
            "width": 0.12,
            "height": 0.025
          },
          "page": 1
        }]
      },
      "Description": {
        "confidence": 0.88,
        "confidence_reason": "Description text is clear and readable",
        "confidence_threshold": 0.75,
        "geometry": [{
          "boundingBox": {
            "top": 0.3,
            "left": 0.25,
            "width": 0.35,
            "height": 0.025
          },
          "page": 1
        }]
      },
      "Amount": {
        "confidence": 0.92,
        "confidence_reason": "Amount aligned in currency column with clear digits",
        "confidence_threshold": 0.85,
        "geometry": [{
          "boundingBox": {
            "top": 0.3,
            "left": 0.65,
            "width": 0.15,
            "height": 0.025
          },
          "page": 1
        }]
      }
    },
    {
      "Date": {
        "confidence": 0.90,
        "confidence_reason": "Date visible but slightly smudged",
        "confidence_threshold": 0.80,
        "geometry": [{
          "boundingBox": {
            "top": 0.33,
            "left": 0.1,
            "width": 0.12,
            "height": 0.025
          },
          "page": 1
        }]
      },
      "Description": {
        "confidence": 0.85,
        "confidence_reason": "Description partially cut off but main text readable",
        "confidence_threshold": 0.75,
        "geometry": [{
          "boundingBox": {
            "top": 0.33,
            "left": 0.25,
            "width": 0.3,
            "height": 0.025
          },
          "page": 1
        }]
      },
      "Amount": {
        "confidence": 0.94,
        "confidence_reason": "Amount clearly printed with proper decimal alignment",
        "confidence_threshold": 0.85,
        "geometry": [{
          "boundingBox": {
            "top": 0.33,
            "left": 0.65,
            "width": 0.15,
            "height": 0.025
          },
          "page": 1
        }]
      }
    }
  ]
}
```

### Complete Example

Here's a complete example showing all three attribute types in a single assessment response:

```json
{
  "inference_result": {
    "StatementDate": "2024-01-31",
    "AccountDetails": {
      "AccountNumber": "1234567890",
      "RoutingNumber": "021000021"
    },
    "Transactions": [
      {
        "Date": "2024-01-15",
        "Description": "Direct Deposit - Salary",
        "Amount": "3500.00"
      },
      {
        "Date": "2024-01-20", 
        "Description": "ATM Withdrawal",
        "Amount": "-200.00"
      }
    ]
  },
  "explainability_info": [
    {
      "StatementDate": {
        "confidence": 0.95,
        "confidence_reason": "Statement date clearly printed in header",
        "confidence_threshold": 0.85,
        "geometry": [{
          "boundingBox": {"top": 0.1, "left": 0.1, "width": 0.15, "height": 0.03},
          "page": 1
        }]
      },
      "AccountDetails": {
        "AccountNumber": {
          "confidence": 0.90,
          "confidence_reason": "Account number clearly visible in account section",
          "confidence_threshold": 0.90,
          "geometry": [{
            "boundingBox": {"top": 0.15, "left": 0.2, "width": 0.25, "height": 0.04},
            "page": 1
          }]
        },
        "RoutingNumber": {
          "confidence": 0.85,
          "confidence_reason": "Routing number printed clearly below account number", 
          "confidence_threshold": 0.90,
          "geometry": [{
            "boundingBox": {"top": 0.2, "left": 0.2, "width": 0.2, "height": 0.03},
            "page": 1
          }]
        }
      },
      "Transactions": [
        {
          "Date": {
            "confidence": 0.95,
            "confidence_reason": "Transaction date clearly printed",
            "confidence_threshold": 0.80,
            "geometry": [{
              "boundingBox": {"top": 0.3, "left": 0.1, "width": 0.12, "height": 0.025},
              "page": 1
            }]
          },
          "Description": {
            "confidence": 0.88,
            "confidence_reason": "Description text is clear and complete",
            "confidence_threshold": 0.75,
            "geometry": [{
              "boundingBox": {"top": 0.3, "left": 0.25, "width": 0.35, "height": 0.025},
              "page": 1
            }]
          },
          "Amount": {
            "confidence": 0.92,
            "confidence_reason": "Amount properly aligned in currency format",
            "confidence_threshold": 0.85,
            "geometry": [{
              "boundingBox": {"top": 0.3, "left": 0.65, "width": 0.15, "height": 0.025},
              "page": 1
            }]
          }
        },
        {
          "Date": {
            "confidence": 0.90,
            "confidence_reason": "Date readable with minor print quality issues",
            "confidence_threshold": 0.80,
            "geometry": [{
              "boundingBox": {"top": 0.33, "left": 0.1, "width": 0.12, "height": 0.025},
              "page": 1
            }]
          },
          "Description": {
            "confidence": 0.85,
            "confidence_reason": "Description clear, standard ATM format",
            "confidence_threshold": 0.75,
            "geometry": [{
              "boundingBox": {"top": 0.33, "left": 0.25, "width": 0.3, "height": 0.025},
              "page": 1
            }]
          },
          "Amount": {
            "confidence": 0.94,
            "confidence_reason": "Negative amount clearly indicated with proper formatting",
            "confidence_threshold": 0.85,
            "geometry": [{
              "boundingBox": {"top": 0.33, "left": 0.65, "width": 0.15, "height": 0.025},
              "page": 1
            }]
          }
        }
      ]
    }
  ],
  "metadata": {
    "assessment_time_seconds": 4.12,
    "assessment_parsing_succeeded": true
  }
}
```

### Assessment Response Requirements

**Important Guidelines:**

1. **Match Extraction Structure**: The assessment response must exactly match the structure of the `inference_result`
2. **List Item Assessment**: For list attributes, assess **each individual item** separately, not as an aggregate
3. **Nested Confidence**: Group attributes should have confidence assessments for each sub-attribute
4. **Consistent Format**: Each confidence assessment should include `confidence` (0.0-1.0) and optionally `confidence_reason`
5. **Threshold Integration**: The system automatically adds `confidence_threshold` values based on configuration

## Confidence Thresholds

### Overview

The assessment feature supports flexible confidence threshold configuration to help users identify extraction results that may require review. Thresholds can be set globally or per-attribute, with the UI providing immediate visual feedback through color-coded displays.

### Configuration Options

#### Global Thresholds
Set system-wide confidence requirements for all attributes:

```json
{
  "inference_result": {
    "YTDNetPay": "75000",
    "PayPeriodStartDate": "2024-01-01"
  },
  "explainability_info": [
    {
      "global_confidence_threshold": 0.85,
      "YTDNetPay": {
        "confidence": 0.92,
        "confidence_reason": "Clear match found in document"
      },
      "PayPeriodStartDate": {
        "confidence": 0.75,
        "confidence_reason": "Moderate OCR confidence"
      }
    }
  ]
}
```

#### Per-Attribute Thresholds
Override global settings for specific fields requiring different confidence levels:

```json
{
  "explainability_info": [
    {
      "YTDNetPay": {
        "confidence": 0.92,
        "confidence_threshold": 0.95,
        "confidence_reason": "Financial data requires high confidence"
      },
      "PayPeriodStartDate": {
        "confidence": 0.75,
        "confidence_threshold": 0.70,
        "confidence_reason": "Date fields can accept moderate confidence"
      }
    }
  ]
}
```

#### Mixed Configuration
Combine global defaults with attribute-specific overrides:

```json
{
  "explainability_info": [
    {
      "global_confidence_threshold": 0.80,
      "CriticalField": {
        "confidence": 0.85,
        "confidence_threshold": 0.95,
        "confidence_reason": "Override: higher threshold for critical data"
      },
      "StandardField": {
        "confidence": 0.82,
        "confidence_reason": "Uses global threshold of 0.80"
      }
    }
  ]
}
```

### Assessment Prompt Integration

Include threshold guidance in your assessment prompts to ensure consistent confidence evaluation:

```yaml
assessment:
  task_prompt: |
    Assess extraction confidence using these thresholds as guidance:
    - Financial data (amounts, taxes): 0.90+ confidence required
    - Personal information (names, addresses): 0.85+ confidence required  
    - Dates and standard fields: 0.75+ confidence acceptable
    
    Provide confidence scores between 0.0 and 1.0 with explanatory reasoning:
    {
      "attribute_name": {
        "confidence": 0.85,
        "confidence_threshold": 0.90,
        "confidence_reason": "Explanation of confidence assessment"
      }
    }
```

## UI Integration

Assessment results automatically appear in the web interface with enhanced visual indicators:

### Visual Feedback System

The UI provides immediate confidence feedback through color-coded displays:

#### Color Coding
- 🟢 **Green**: Confidence meets or exceeds threshold (high confidence)
- 🔴 **Red**: Confidence falls below threshold (requires review)
- ⚫ **Black**: Confidence available but no threshold for comparison

#### Display Modes

**1. With Threshold (Color-Coded)**
```
YTDNetPay: 75000
Confidence: 92.0% / Threshold: 95.0% [RED - Below Threshold]

PayPeriodStartDate: 2024-01-01  
Confidence: 85.0% / Threshold: 70.0% [GREEN - Above Threshold]
```

**2. Confidence Only (Black Text)**
```
EmployeeName: John Smith
Confidence: 88.5% [BLACK - No Threshold Set]
```

**3. No Display**
When neither confidence nor threshold data is available, no confidence indicator is shown.

### Interface Coverage

**1. Visual Editor Tab**
- Split-pane layout with document image (left) and form-based field editing (right)
- Color-coded confidence display (green=meets threshold, red=below threshold, black=no threshold)
- **Bounding Box Visualization**: Assessment geometry data automatically displayed as overlays on document images
- Visual connection between form fields and document bounding boxes with spatial localization
- Interactive overlay showing precise field locations from assessment spatial data
- Supports nested data structures (arrays, objects) with recursive confidence display
- Inline editing with change tracking (✏️ Edited badges, blue/orange left borders)

**2. JSON Editor Tab**
- Raw JSON editing for advanced users with full JSON validation
- Section filtering with multiselect dropdown
- Same confidence data available in JSON structure

**3. Revision History Tab**
- Complete audit trail showing all edits with timestamps
- Reviewer identification and field-level diffs
- Confidence scores preserved in edit history

**4. Smart Filtering**
- **Low Confidence Filter**: Toggle to show only fields with confidence below threshold
- **Evaluation Mismatches Filter**: Show only fields where prediction doesn't match baseline
- **Collapsible Tree Navigation**: Expand/Collapse All controls for nested structures

**5. Nested Data Support**
Confidence indicators work with complex document structures:
```
FederalTaxes[0]:
  ├── YTD: 2111.2 [Confidence: 67.6% / Threshold: 85.0% - RED]
  └── Period: 40.6 [Confidence: 75.8% - BLACK]

StateTaxes[0]:
  ├── YTD: 438.36 [Confidence: 84.4% / Threshold: 80.0% - GREEN]
  └── Period: 8.43 [Confidence: 83.2% / Threshold: 80.0% - GREEN]
```

## Image Processing Configuration

The assessment service supports configurable image dimensions for optimal confidence evaluation:

### New Default Behavior (Preserves Original Resolution)

**Important Change**: Empty strings or unspecified image dimensions now preserve the original document resolution for maximum assessment accuracy:

```yaml
assessment:
  model: "us.amazon.nova-lite-v1:0"
  # Image processing settings - preserves original resolution
  image:
    target_width: ""     # Empty string = no resizing (recommended)
    target_height: ""    # Empty string = no resizing (recommended)
```

### Custom Image Dimensions

Configure specific dimensions when performance optimization is needed:

```yaml
# For detailed visual assessment with controlled dimensions
assessment:
  image:
    target_width: "1200"   # Resize to 1200 pixels wide
    target_height: "1600"  # Resize to 1600 pixels tall

# For standard confidence evaluation
assessment:
  image:
    target_width: "800"    # Smaller for faster processing
    target_height: "1000"  # Maintains good quality
```

### Image Resizing Features for Assessment

- **Original Resolution Preservation**: Empty strings preserve full document resolution for maximum assessment accuracy
- **Aspect Ratio Preservation**: Images maintain proportions for accurate visual analysis when dimensions are specified
- **Smart Scaling**: Only downsizes when necessary to preserve visual detail
- **High-Quality Resampling**: Better image quality for confidence assessment
- **Performance Optimization**: Configurable dimensions allow balancing accuracy vs. speed

### Configuration Benefits for Assessment

- **Maximum Assessment Accuracy**: Empty strings preserve full document resolution for best confidence evaluation
- **Enhanced Visual Analysis**: Original resolution improves confidence evaluation accuracy
- **Better OCR Verification**: Higher quality images help verify extraction results against visual content
- **Improved Confidence Scoring**: Better image quality leads to more accurate confidence assessments
- **Service-Specific Tuning**: Optimize image dimensions for different assessment complexity levels
- **Resource Optimization**: Choose between accuracy (original resolution) and performance (smaller dimensions)

### Migration from Previous Versions

**Previous Behavior**: Empty strings defaulted to 951x1268 pixel resizing
**New Behavior**: Empty strings preserve original image resolution

If you were relying on the previous default resizing behavior, explicitly set dimensions:

```yaml
# To maintain previous default behavior
assessment:
  image:
    target_width: "951"
    target_height: "1268"
```

### Best Practices for Assessment

1. **Use Empty Strings for High Accuracy**: For critical confidence assessment, use empty strings to preserve original resolution
2. **Consider Assessment Complexity**: Complex documents with fine details benefit from higher resolution
3. **Test Assessment Quality**: Evaluate confidence assessment accuracy with your specific document types
4. **Monitor Resource Usage**: Higher resolution images consume more memory and processing time
5. **Balance Accuracy vs Performance**: Choose appropriate settings based on your assessment requirements and processing volume

## Granular Assessment

### Overview

For complex documents with many attributes or large lists (such as bank statements with hundreds of transactions), the standard assessment approach can become inefficient and less accurate. The **Granular Assessment** feature addresses these challenges by breaking down the assessment process into smaller, focused tasks that can be processed in parallel.

### When to Use Granular Assessment

Consider granular assessment for:
- **Documents with many attributes** (10+ simple attributes)
- **Large list structures** (bank transactions, line items, etc.)
- **Complex nested data** (multiple group attributes)
- **Performance-critical scenarios** where parallel processing provides benefits
- **Cost optimization** when prompt caching is available

### Key Benefits

1. **Improved Accuracy**: Smaller, focused prompts lead to better LLM performance
2. **Cost Optimization**: Leverages prompt caching to reduce token usage significantly
3. **Reduced Latency**: Parallel processing of independent assessment tasks
4. **Better Scalability**: Handles documents with hundreds of attributes or list items

### Configuration

Enable granular assessment by adding the `granular` section to your assessment configuration:

```yaml
assessment:
  # Standard assessment configuration
  model: "us.anthropic.claude-3-7-sonnet-20250219-v1:0"
  temperature: 0
  system_prompt: "You are an expert document analyst..."
  task_prompt: |
    Assess the confidence of extraction results for this {DOCUMENT_CLASS} document.
    
    Attributes to assess:
    {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}
    
    Extraction results:
    {EXTRACTION_RESULTS}
    
    Document context:
    {DOCUMENT_TEXT}
    {OCR_TEXT_CONFIDENCE}
    {DOCUMENT_IMAGE}
    
    Provide confidence assessments in JSON format.
  
  # Granular assessment configuration
  granular:
    max_workers: 6              # Number of parallel threads
    simple_batch_size: 3        # Attributes per simple batch
    list_batch_size: 1          # List items per batch (usually 1)
```

### How It Works

The granular assessment service automatically:

1. **Analyzes attribute structure** to determine optimal task breakdown
2. **Creates focused tasks**:
   - **Simple batches**: Groups of 3-5 simple attributes
   - **Group tasks**: Individual group attributes with their sub-attributes
   - **List item tasks**: Individual items from list attributes
3. **Builds cached base content** with document context and images
4. **Processes tasks in parallel** using configurable thread pool
5. **Aggregates results** into the same format as standard assessment

### Task Types

#### Simple Batch Tasks
Groups simple attributes together for efficient processing:
```yaml
# Configuration with 10 simple attributes
attributes:
  - name: "StatementDate"
  - name: "AccountNumber"
  - name: "RoutingNumber"
  # ... 7 more attributes

# Results in 4 tasks: [3, 3, 3, 1] attributes each
```

#### Group Tasks
Processes complex nested structures as single units:
```yaml
# Each group becomes one focused task
properties:
  AccountDetails:
    type: object
    properties:
      AccountNumber:
        type: string
      RoutingNumber:
        type: string
      AccountType:
        type: string
```

#### List Item Tasks
Assesses each list item individually for maximum accuracy:
```yaml
# 100 transactions = 100 individual assessment tasks
properties:
  Transactions:
    type: array
    items:
      type: object
      properties:
        Date:
          type: string
        Description:
          type: string
        Amount:
          type: string
```

### Performance Tuning

#### Batch Size Configuration
```yaml
granular:
  simple_batch_size: 3    # Smaller = more accurate, larger = faster
  list_batch_size: 1      # Usually keep at 1 for best accuracy
  max_workers: 6          # Balance between speed and resource usage
```

#### Model Selection
Granular assessment works best with models supporting prompt caching:
- `us.anthropic.claude-3-7-sonnet-20250219-v1:0` (recommended)
- `us.anthropic.claude-3-5-haiku-20241022-v1:0` (cost-effective)
- `us.amazon.nova-lite-v1:0` or `us.amazon.nova-pro-v1:0`

### Cost Optimization with Caching

The granular approach leverages prompt caching for significant cost savings:

```
First Task:  [Full document context] + [3 attributes] = Full cost
Second Task: [Cached context] + [3 different attributes] = Cache read + new content only
Third Task:  [Cached context] + [3 different attributes] = Cache read + new content only
...
```

**Typical savings**: 60-80% reduction in token costs for documents with many attributes.

### Usage Example

```python
from idp_common.assessment import create_assessment_service

# Load configuration with granular settings
config = {
    "assessment": {
        "model": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
        "granular": {
            "max_workers": 6,
            "simple_batch_size": 3,
            "list_batch_size": 1
        }
        # ... other assessment config
    }
}

# Factory function automatically selects granular service
assessment_service = create_assessment_service(
    region="us-west-2",
    config=config
)

# Same interface as standard assessment
document = assessment_service.assess_document(document)
```

### Monitoring Granular Assessment

Granular assessment provides additional metadata:

```json
{
  "metadata": {
    "granular_assessment_used": true,
    "assessment_tasks_total": 25,
    "assessment_tasks_successful": 24,
    "assessment_tasks_failed": 1,
    "assessment_time_seconds": 8.5
  }
}
```

### Migration from Standard Assessment

1. **Add granular configuration** to existing assessment config
2. **Test with small documents** first to validate behavior
3. **Tune batch sizes** based on your document complexity
4. **Monitor performance** and cost metrics
5. **Gradually roll out** to production workloads

The granular service maintains full backward compatibility - existing configurations continue to work without changes.

## Cost Optimization

### Token Reduction Strategy

The assessment feature implements several cost optimization techniques:

1. **Text Confidence Data**: Uses condensed OCR confidence information instead of full raw OCR results (80-90% token reduction)
2. **Conditional Image Processing**: Images only processed when `{DOCUMENT_IMAGE}` placeholder is present
3. **Configuration-Based Control**: Assessment can be enabled/disabled via configuration `enabled` property for flexible deployment
4. **Efficient Prompting**: Optimized prompt templates minimize token usage while maintaining accuracy
5. **Configurable Image Dimensions**: Adjust image resolution to balance assessment quality and processing costs
6. **Granular Assessment with Caching**: For complex documents, use granular assessment with prompt caching for 60-80% cost reduction


## Testing and Validation

### End-to-End Testing

Use the provided notebooks for comprehensive testing:

```bash
# Standard assessment testing
jupyter notebook notebooks/e2e-example-with-assessment.ipynb

# Granular assessment testing
jupyter notebook notebooks/examples/step4_assessment_granular.ipynb
```

The notebooks demonstrate:
- Document processing with assessment enabled
- Confidence score interpretation
- Integration with existing extraction workflows
- Performance and cost analysis
- Granular assessment configuration and usage

### Configuration Validation

Assessment enforces strict configuration requirements:

```python
# Missing prompt template
ValueError: "Assessment task_prompt is required in configuration but not found"

# Invalid DOCUMENT_IMAGE usage
ValueError: "Invalid DOCUMENT_IMAGE placeholder usage: found 2 occurrences, but exactly 1 is required"

# Template formatting error
ValueError: "Assessment prompt template formatting failed: missing required placeholder"
```

## Best Practices

### 1. Prompt Design

- **Be Specific**: Clearly define what constitutes high vs. low confidence
- **Include Examples**: Provide examples of confidence reasoning in system prompts
- **Use Structured Output**: Request consistent JSON format for programmatic processing

### 2. Cost Management

- **Enable Selectively**: Only enable assessment for critical document types
- **Text-First**: Start with text-only assessment before adding images
- **Monitor Usage**: Track token consumption and adjust prompts accordingly

### 3. Model Selection

- **Claude 3.5 Sonnet**: Recommended for balanced performance and cost
- **Claude 3 Haiku**: Consider for high-volume, cost-sensitive scenarios
- **Temperature 0**: Use deterministic output for consistent confidence scoring

### 4. Confidence Threshold Configuration

- **Risk-Based Thresholds**: Set higher thresholds (0.90+) for critical financial or personal data
- **Field-Specific Requirements**: Use per-attribute thresholds for different data types
- **Global Defaults**: Establish reasonable global thresholds (0.75-0.85) as baselines
- **Incremental Tuning**: Start with conservative thresholds and adjust based on accuracy analysis

### 5. Integration Patterns

- **Conditional Logic**: Implement business rules based on confidence scores and thresholds
- **Human Review**: Route low-confidence extractions (below threshold) for manual review
- **Quality Metrics**: Track confidence distributions to identify improvement opportunities
- **Visual Feedback**: Leverage color-coded UI indicators for immediate quality assessment

## Troubleshooting

### Common Issues

1. **Assessment Not Running**
   - Verify `assessment.enabled: true` in configuration file
   - Check state machine definition includes assessment step
   - Confirm assessment Lambda function deployed successfully

2. **Template Errors**
   - Ensure `task_prompt` is defined in assessment configuration
   - Validate placeholder syntax and formatting
   - Check for exactly one `{DOCUMENT_IMAGE}` placeholder if using images

3. **Poor Confidence Scores**
   - Review prompt templates for clarity and specificity
   - Consider adding domain-specific guidance in system prompts
   - Validate OCR quality and text confidence data

4. **High Costs**
   - Monitor token usage in CloudWatch logs
   - Consider text-only assessment without images
   - Optimize prompt templates to reduce unnecessary context

5. **Confidence Threshold Issues**
   - Verify `confidence_threshold` values are between 0.0 and 1.0
   - Check explainability_info structure includes threshold data
   - Ensure UI displays match expected color coding (green/red/black)
   - Validate nested data confidence display for complex structures

### Monitoring

Key metrics to monitor:

- `InputDocumentsForAssessment`: Number of documents assessed
- `assessment_time_seconds`: Processing time per assessment
- `assessment_parsing_succeeded`: Success rate of JSON parsing
- Token consumption logs in CloudWatch

## Skipping Assessment for Excluded Classes

If a document class is marked with
`x-aws-idp-exclude-from-processing: true` (see
[Excluding Static Pages in the Classification docs](classification.md#excluding-static-pages-eg-instructions-legal-boilerplate)),
both `AssessmentService.process_document_section` and
`GranularAssessmentService.process_document_section` short-circuit for
sections classified as that class:

- **No LLM call is made** — no confidence scores are produced because no
  extraction was performed for that section.
- **No stub file is written** — the extraction stub (`result.json`
  written by `ExtractionService`) is already authoritative; anything
  inspecting "what happened to this section?" reads the extraction
  stub. This avoids duplicating metadata and keeps the output surface
  minimal for skipped sections.
- The document is returned unchanged to the caller.

The skip check uses the shared
`idp_common.section_exclusion.is_section_excluded(section)` helper.

## Related Documentation

- [Pattern 2 Documentation](./pattern-2.md) - Assessment integration details
- [Configuration Guide](./configuration.md) - Configuration schema details
- [Extraction Documentation](./extraction.md) - Base extraction functionality
- [Web UI Documentation](./web-ui.md) - UI integration and display
