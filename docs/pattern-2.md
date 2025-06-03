Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# Pattern 2: Bedrock Classification and Extraction

This pattern implements an intelligent document processing workflow that uses Amazon Bedrock with Nova or Claude models for both page classification/grouping and information extraction.

<img src="../../images/IDP-Pattern2-Bedrock.drawio.png" alt="Architecture" width="800">

## Table of Contents

- [Architecture Overview](#architecture-overview)
  - [State Machine Workflow](#state-machine-workflow)
  - [Lambda Functions](#lambda-functions)
    - [OCR Function](#ocr-function)
    - [Classification Function](#classification-function)
    - [Extraction Function](#extraction-function)
    - [ProcessResults Function](#processresults-function)
  - [Monitoring and Metrics](#monitoring-and-metrics)
    - [Performance Metrics](#performance-metrics)
    - [Error Tracking](#error-tracking)
    - [Lambda Function Metrics](#lambda-function-metrics)
  - [Template Outputs](#template-outputs)
  - [Configuration](#configuration)
- [Customizing Classification](#customizing-classification)
- [Few Shot Example Feature](#few-shot-example-feature)
- [Customizing Extraction](#customizing-extraction)
- [Testing](#testing)
- [Best Practices](#best-practices)

## Architecture Overview

The workflow consists of three main processing steps:
1. OCR processing using Amazon Textract
2. Document classification using Claude via Amazon Bedrock (with two available methods):
   - Page-level classification: Classifies individual pages and groups them
   - Holistic packet classification: Analyzes multi-document packets to identify document boundaries
3. Field extraction using Claude via Amazon Bedrock

### State Machine Workflow

The Step Functions state machine (`workflow.asl.json`) orchestrates the following flow:

```
OCRStep → ClassificationStep → ProcessPageGroups (Map State for Extraction) → ProcessResultsStep
```

Each step includes comprehensive retry logic for handling transient errors:
- Initial retry after 2 seconds
- Exponential backoff with rate of 2
- Maximum of 8-10 retry attempts depending on the step

### Lambda Functions

#### OCR Function
- **Purpose**: Processes input PDFs using Amazon Textract
- **Key Features**:
  - Concurrent page processing with ThreadPoolExecutor
  - Image preprocessing and optimization
  - Comprehensive error handling and retries
  - Detailed metrics tracking
- **Input**:
  ```json
  {
    "execution_arn": "<ARN>",
    "output_bucket": "<BUCKET>",
    "input": {
      "detail": {
        "bucket": { "name": "<BUCKET>" },
        "object": { "key": "<KEY>" }
      }
    }
  }
  ```
- **Output**:
  ```json
  {
    "metadata": {
      "input_bucket": "<BUCKET>",
      "object_key": "<KEY>",
      "output_bucket": "<BUCKET>",
      "output_prefix": "<PREFIX>",
      "num_pages": "<NUMBER OF PAGES>"
    },
    "pages": {
      "<PAGE_NUMBER>": {
        "rawTextUri": "<S3_URI>",
        "parsedTextUri": "<S3_URI>",
        "imageUri": "<S3_URI>"
      }
    }
  }
  ```

#### Classification Function
- **Purpose**: Classifies pages or document packets using Claude via Bedrock and segments into sections
- **Key Features**:
  - Two classification methods:
    - Page-level classification (multimodalPageLevelClassification)
    - Holistic packet classification (textbasedHolisticClassification)
  - RVL-CDIP dataset categories for classification
  - Concurrent page processing
  - Automatic image resizing and optimization
  - Robust error handling with exponential backoff
  - **Few shot example support for improved accuracy**
- **Input**: Output from OCR function
- **Output**:
  ```json
  {
    "metadata": "<FROM_OCR>",
    "sections": [
      {
        "id": "<GROUP_ID>",
        "class": "<CLASS>",
        "pages": [...]
      }
    ]
  }
  ```

#### Extraction Function
- **Purpose**: Extracts fields using Claude via Bedrock
- **Key Features**:
  - Document class-specific attribute extraction
  - Configurable extraction attributes
  - Comprehensive error handling
  - Token usage tracking
  - **Few shot example support for improved accuracy**
- **Input**: Individual section from Classification output
- **Output**:
  ```json
  {
    "section": {
      "id": "<ID>",
      "class": "<CLASS>",
      "page_ids": ["<PAGEID>", ...],
      "outputJSONUri": "<S3_URI>"
    },
    "pages": [...]
  }
  ```

#### ProcessResults Function
- **Purpose**: Consolidates results from all sections
- **Output**: Standardized format for GenAIIDP parent stack:
  ```json
  {
    "Sections": [{
      "Id": "<ID>",
      "PageIds": ["<PAGEID>", ...],
      "Class": "<CLASS>",
      "OutputJSONUri": "<S3_URI>"
    }],
    "Pages": [{
      "Id": "<ID>",
      "Class": "<CLASS>",
      "TextUri": "<S3_URI>",
      "ImageUri": "<S3_URI>"
    }],
    "PageCount": "<TOTAL_PAGES>"
  }
  ```

### Monitoring and Metrics

The pattern includes a comprehensive CloudWatch dashboard with:

#### Performance Metrics
- Document and page throughput
- Token usage (input/output/total)
- Bedrock request statistics
- Processing latencies
- Throttling and retry metrics

#### Error Tracking
- Lambda function errors
- Long-running invocations
- Classification/extraction failures
- Throttling events

#### Lambda Function Metrics
- Duration
- Memory usage
- Error rates
- Concurrent executions

### Template Outputs

The pattern exports these outputs to the parent stack:

- `StateMachineName`: Name of Step Functions state machine
- `StateMachineArn`: ARN of Step Functions state machine
- `StateMachineLogGroup`: CloudWatch log group for state machine
- `DashboardName`: Name of pattern-specific dashboard
- `DashboardArn`: ARN of pattern-specific dashboard

### Configuration

**Stack Deployment Parameters:**
- `ClassificationMethod`: Classification methodology to use (options: 'multimodalPageLevelClassification' or 'textbasedHolisticClassification')
- `IsSummarizationEnabled`: Boolean to enable/disable summarization functionality (true|false)
- `ConfigurationDefaultS3Uri`: Optional S3 URI to custom configuration (uses default configuration if not specified)
- `MaxConcurrentWorkflows`: Workflow concurrency limit
- `LogRetentionDays`: CloudWatch log retention period
- `ExecutionTimeThresholdMs`: Latency threshold for alerts

**Configuration Management:**
- Model selection is now handled through configuration files rather than CloudFormation parameters
- Configuration supports multiple presets per pattern (e.g., default, checkboxed_attributes_extraction, medical_records_summarization, few_shot_example)
- Configuration can be updated through the Web UI without stack redeployment
- Model choices are constrained through enum constraints in the configuration schema

## Customizing Classification

The pattern supports two different classification methods:

1. **Page-Level Classification (multimodalPageLevelClassification)**: This is the default method that classifies each page independently based on its visual layout and textual content. It outputs a simple JSON format with a single class label per page.

2. **Holistic Packet Classification (textbasedHolisticClassification)**: This method examines the document as a whole to identify boundaries between different document types within a multi-document packet. It can detect logical document boundaries and identifies document types in the context of the whole document. This is especially useful for packets where individual pages may not be clearly classifiable on their own. It outputs a JSON format that identifies document segments with start and end page numbers.

You can select which method to use by setting the `ClassificationMethod` parameter when deploying the stack.

The classification system uses RVL-CDIP dataset categories and can be customized through the configuration files. Classification models and prompts are now managed through the configuration library rather than CloudFormation parameters.

Available categories:
- letter
- form
- email
- handwritten
- advertisement
- scientific_report
- scientific_publication
- specification
- file_folder
- news_article
- budget
- invoice
- presentation
- questionnaire
- resume
- memo

## Few Shot Example Feature

Pattern 2 supports few shot learning through example-based prompting to significantly improve classification and extraction accuracy. This feature allows you to provide concrete examples of documents with their expected classifications and attribute extractions.

### Overview

Few shot examples work by including reference documents with known classifications and expected attribute values in the prompts sent to the AI model. This helps the model understand the expected format and accuracy requirements for your specific use case.

### Configuration

Few shot examples are configured using the configuration files in the `config_library/pattern-2/` directory. The `few_shot_example` configuration demonstrates how to set up examples:

```yaml
classes:
  - name: letter
    description: "A formal written correspondence..."
    attributes:
      - name: sender_name
        description: "The name of the person who wrote the letter..."
    examples:
      - classPrompt: "This is an example of the class 'letter'"
        name: "Letter1"
        attributesPrompt: |
          expected attributes are:
              "sender_name": "Will E. Clark",
              "sender_address": "206 Maple Street P.O. Box 1056 Murray Kentucky 42071-1056",
              "recipient_name": "The Honorable Wendell H. Ford"
        imagePath: "config_library/pattern-2/few_shot_example/example-images/letter1.jpg"
  - name: email
    description: "A digital message with email headers..."
    examples:
      - classPrompt: "This is an example of the class 'email'"
        name: "Email1"
        attributesPrompt: |
          expected attributes are: 
             "from_address": "Kelahan, Ben",
             "to_address": "TI New York: 'TI Minnesota",
             "subject": "FW: Morning Team Notes 4/20"
        imagePath: "config_library/pattern-2/few_shot_example/example-images/email1.jpg"
```

### Benefits

Using few shot examples provides several advantages:

1. **Improved Accuracy**: Models perform better when given concrete examples
2. **Consistent Formatting**: Examples help ensure consistent output structure  
3. **Domain Adaptation**: Examples help models understand domain-specific terminology
4. **Reduced Hallucination**: Examples reduce the likelihood of made-up data
5. **Better Edge Case Handling**: Examples can demonstrate how to handle unusual cases

### Integration with Template Prompts

The few shot examples are automatically integrated into the classification and extraction prompts using the `{FEW_SHOT_EXAMPLES}` placeholder. You can also use the `{DOCUMENT_IMAGE}` placeholder for precise image positioning:

**Standard Template with Text Only:**
```python
# In classification task_prompt
task_prompt: |
  Classify this document into exactly one of these categories:
  {CLASS_NAMES_AND_DESCRIPTIONS}
  
  <few_shot_examples>
  {FEW_SHOT_EXAMPLES}
  </few_shot_examples>
  
  <document_ocr_data>
  {DOCUMENT_TEXT}
  </document_ocr_data>

# In extraction task_prompt  
task_prompt: |
  Extract attributes from this document.
  
  <few_shot_examples>
  {FEW_SHOT_EXAMPLES}
  </few_shot_examples>
  
  
  <document_ocr_data>
  {DOCUMENT_TEXT}
  </document_ocr_data>
```

**Enhanced Template with Image Placement:**
```python
# In classification task_prompt with image positioning
task_prompt: |
  Classify this document into exactly one of these categories:
  {CLASS_NAMES_AND_DESCRIPTIONS}
  
  <few_shot_examples>
  {FEW_SHOT_EXAMPLES}
  </few_shot_examples>
  
  Now examine this new document:
  {DOCUMENT_IMAGE}
  
  <document_ocr_data>
  {DOCUMENT_TEXT}
  </document_ocr_data>
  
  Classification:

# In extraction task_prompt with image positioning
task_prompt: |
  Extract attributes from this {DOCUMENT_CLASS} document:
  {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}
  
  <few_shot_examples>
  {FEW_SHOT_EXAMPLES}
  </few_shot_examples>
  
  Analyze this document image:
  {DOCUMENT_IMAGE}
  
  <document_ocr_data>
  {DOCUMENT_TEXT}
  </document_ocr_data>
  
  Extract as JSON:
```

### Available Template Placeholders

Pattern 2 supports several placeholders for building dynamic prompts:

- **`{CLASS_NAMES_AND_DESCRIPTIONS}`**: List of document classes and their descriptions
- **`{FEW_SHOT_EXAMPLES}`**: Examples from the configuration (class-specific for extraction, all classes for classification)
- **`{DOCUMENT_TEXT}`**: OCR-extracted text content from the document
- **`{DOCUMENT_IMAGE}`**: Document image(s) positioned at specific locations in the prompt
- **`{DOCUMENT_CLASS}`**: The classified document type (used in extraction prompts)
- **`{ATTRIBUTE_NAMES_AND_DESCRIPTIONS}`**: List of attributes to extract with their descriptions

**Image Placement Benefits:**
- **Visual Context**: Position images where they provide maximum context for the task
- **Multimodal Understanding**: Help models correlate visual and textual information effectively
- **Flexible Design**: Create prompts that flow naturally between different content types
- **Enhanced Accuracy**: Strategic image placement can improve both classification and extraction performance

### Using Few Shot Examples

To use few shot examples in your deployment:

1. **Use the example configuration**: Deploy with `ConfigurationDefaultS3Uri` pointing to `config_library/pattern-2/few_shot_example/config.yaml`
2. **Create custom examples**: Copy the example configuration and modify it with your own document examples
3. **Provide example images**: Place example document images in the appropriate directory and reference them in the `imagePath` field

### Best Practices

1. **Quality over Quantity**: Use 1-3 high-quality examples per document class
2. **Representative Examples**: Choose examples that represent typical documents in your use case
3. **Clear Attribution**: Ensure examples clearly show expected attribute extractions
4. **Diverse Coverage**: Include examples that cover different variations and edge cases

## Customizing Extraction

The extraction system can be customized through the configuration files rather than CloudFormation parameters:

1. **Attribute Definitions**: 
   - Define attributes per document class in the `classes` section of the configuration
   - Specify descriptions for each attribute
   - Configure the format and structure

2. **Extraction Prompts**:
   - Customize system behavior through the `system_prompt` in configuration
   - Add domain expertise and guidance in the `task_prompt`
   - Modify output formatting requirements

3. **Model Selection**:
   - Model selection is handled through enum constraints in the configuration
   - Available models are defined in the configuration schema
   - Changes can be made through the Web UI without redeployment

Example attribute definition from the configuration:
```yaml
classes:
  - name: invoice
    description: A commercial document issued by a seller to a buyer relating to a sale
    attributes:
      - name: invoice_number
        description: The unique identifier for the invoice. Look for 'invoice no', 'invoice #', or 'bill number', typically near the top of the document.
      - name: invoice_date
        description: The date when the invoice was issued. May be labeled as 'date', 'invoice date', or 'billing date'.
      - name: total_amount
        description: The final amount to be paid including all charges. Look for 'total', 'grand total', or 'amount due', typically the last figure on the invoice.
```

## Testing

Modify and use the provided test events and env files:

```bash
# Test OCR function
sam local invoke OCRFunction --env-vars testing/env.json -e testing/OCRFunction-event.json

# Test classification
sam local invoke ClassificationFunction --env-vars testing/env.json -e testing/ClassificationFunctionEvent.json

# Test extraction
sam local invoke ExtractionFunction --env-vars testing/env.json -e testing/ExtractionFunction-event.json
```

## Best Practices

1. **Configuration Management**:
   - Use the configuration library for different use cases (default, medical_records, few_shot_example)
   - Test configuration changes thoroughly before production deployment
   - Leverage the Web UI for configuration updates without redeployment

2. **Throttling Management**:
   - Implement exponential backoff with jitter
   - Configure appropriate retry limits
   - Monitor throttling metrics

3. **Error Handling**:
   - Comprehensive error logging
   - Graceful degradation
   - Clear error messages

4. **Performance Optimization**:
   - Concurrent processing where appropriate
   - Image optimization
   - Resource pooling

5. **Monitoring**:
   - Detailed CloudWatch metrics
   - Performance dashboards
   - Error tracking

6. **Security**:
   - KMS encryption
   - Least privilege IAM roles
   - Secure configuration management

7. **Few Shot Examples**:
   - Use high-quality, representative examples
   - Include examples for all document classes you expect to process
   - Regularly review and update examples based on real-world performance
   - Test configurations with examples before production deployment
