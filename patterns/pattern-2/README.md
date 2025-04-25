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

Key configurable parameters:

- `ClassificationModel`: Bedrock model ID for classification
- `ClassificationMethod`: Classification methodology to use (options: 'multimodalPageLevelClassification' or 'textbasedHolisticClassification')
- `ExtractionModel`: Bedrock model ID for extraction
- `MaxConcurrentWorkflows`: Workflow concurrency limit
- `LogRetentionDays`: CloudWatch log retention period
- `ExecutionTimeThresholdMs`: Latency threshold for alerts

## Customizing Classification

The pattern supports two different classification methods:

1. **Page-Level Classification (multimodalPageLevelClassification)**: This is the default method that classifies each page independently based on its visual layout and textual content. It outputs a simple JSON format with a single class label per page.

2. **Holistic Packet Classification (textbasedHolisticClassification)**: This method examines the document as a whole to identify boundaries between different document types within a multi-document packet. It can detect logical document boundaries and identifies document types in the context of the whole document. This is especially useful for packets where individual pages may not be clearly classifiable on their own. It outputs a JSON format that identifies document segments with start and end page numbers.

You can select which method to use by setting the `ClassificationMethod` parameter when deploying the stack.

The classification system uses RVL-CDIP dataset categories and can be customized through the configuration settings in the template.yaml file. The default prompts are defined in the template:

```python
# For multimodalPageLevelClassification
SYSTEM_PROMPT = """You are a document classification system..."""
CLASSIFICATION_PROMPT = """Classify this document into exactly one of these categories..."""

# For textbasedHolisticClassification
SYSTEM_PROMPT = """You are a document classification expert who can analyze and classify multiple documents..."""
CLASSIFICATION_PROMPT = """The <document-text> XML tags contains the text separated into pages from the document package..."""
```

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

## Customizing Extraction

The extraction system can be customized through the configuration settings in the template.yaml file:

1. **Attribute Definitions**: 
   - Define attributes per document class in the `classes` section
   - Specify descriptions for each attribute
   - Configure the format and structure

2. **Extraction Prompts**:
   - Customize system behavior through the `system_prompt`
   - Add domain expertise and guidance in the `task_prompt`
   - Modify output formatting requirements

Example attribute definition from the template:
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

1. **Throttling Management**:
   - Implement exponential backoff with jitter
   - Configure appropriate retry limits
   - Monitor throttling metrics

2. **Error Handling**:
   - Comprehensive error logging
   - Graceful degradation
   - Clear error messages

3. **Performance Optimization**:
   - Concurrent processing where appropriate
   - Image optimization
   - Resource pooling

4. **Monitoring**:
   - Detailed CloudWatch metrics
   - Performance dashboards
   - Error tracking

5. **Security**:
   - KMS encryption
   - Least privilege IAM roles
   - Secure configuration management