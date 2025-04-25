# Pattern 3: UDOP Classification with Claude Extraction

This pattern implements an intelligent document processing workflow that uses UDOP (Unified Document Processing) for page classification and grouping, followed by Claude for information extraction.

<img src="../../images/IDP-Pattern3-UDOP.drawio.png" alt="Architecture" width="800">


## Table of Contents

- [Fine tuning a UDOP model](#fine-tuning-a-udop-model-for-classification)
- [Architecture Overview](#architecture-overview)
  - [State Machine Workflow](#state-machine-workflow)
  - [Lambda Functions](#lambda-functions)
    - [OCR Function](#ocr-function)
    - [Classification Function](#classification-function)
    - [Extraction Function](#extraction-function)
    - [ProcessResults Function](#processresults-function)
  - [UDOP Model on SageMaker](#udop-model-on-sagemaker)
  - [Monitoring and Metrics](#monitoring-and-metrics)
    - [Performance Metrics](#performance-metrics)
    - [Error Tracking](#error-tracking)
    - [Lambda Function Metrics](#lambda-function-metrics)
  - [Template Outputs](#template-outputs)
  - [Configuration](#configuration)
- [Testing](#testing)
- [Best Practices](#best-practices)

## Fine tuning a UDOP model for classification

See [Fine-Tuning Models on SageMaker](./fine-tune-sm-udop-classification/README.md) 

Once you have trained the model, deploy the GenAIIDP stack for Pattern-3 using the path for your new fine tuned model.


## Architecture Overview

The workflow consists of three main processing steps:
1. OCR processing using Amazon Textract
2. Page classification and grouping using a UDOP model deployed on SageMaker
3. Field extraction using Claude via Amazon Bedrock

### State Machine Workflow

The Step Functions state machine (`workflow.asl.json`) orchestrates the following flow:

```
OCRStep → ClassificationStep → ProcessPageGroups (Map State for Extraction)
```

Each step includes comprehensive retry logic for handling transient errors:
- Initial retry after 2 seconds
- Exponential backoff with rate of 2
- Maximum of 10 retry attempts

### Lambda Functions

#### OCR Function
- **Purpose**: Processes input PDFs using Amazon Textract
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
- **Purpose**: Classifies pages using UDOP model on SageMaker, and segments into sections using class boundaries
- **Input**: Output from OCR function plus output bucket
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
- **Purpose**: Extracts fields using Claude via Amazon Bedrock
- **Input**: Individual section from Classification output
- **Output**:
  ```json
  {
    "section": {
      "id": "<ID>",
      "class": "<CLASS>",
      "page_ids": ["<PAGEID>", "..."],
      "outputJSONUri": "<S3_URI>"
    },
    "pages": [
      {
        "Id": "<ID>",
        "Class": "<CLASS>",
        "TextUri": "<S3_URI>",
        "ImageUri": "<S3_URI>"
      }
    ]
  }
  ```

#### ProcessResults Function

- **Purpose**: Aggregates results for all sections
- **Input**: Extraction output from each section extraction
- **Output**: Consumed by the GenAIIDP parent stack workflow tracker to update job status/UI etc
  ```json
  {
    "Sections": [
      {
        "Id": "<ID>",
        "PageIds": ["<PAGEID>", "..."],
        "Class": "<CLASS>",
        "OutputJSONUri": "<S3_URI>"
      }
    ],
    "Pages": [
      {
        "Id": "<ID>",
        "Class": "<CLASS>",
        "TextUri": "<S3_URI>",
        "ImageUri": "<S3_URI>"
      }
    ],
    "PageCount": "<TOTAL_PAGES>"
  }
  ```

### UDOP Model on SageMaker

The pattern includes a complete UDOP model deployment:

- **SageMaker Endpoint**: `sagemaker_classifier_endpoint.yaml` provisions:
  - SageMaker model 
  - Endpoint configuration
  - Endpoint with auto-scaling
  - IAM roles and permissions

To create a new UDOP model fine tuned for your data, see [Fine tuning a UDOP model](#fine-tuning-a-udop-model-for-classification).

### Monitoring and Metrics

The pattern includes a comprehensive CloudWatch dashboard with:

#### Performance Metrics
- Document and page throughput (per minute)
- Token usage (input/output/total)
- Bedrock request statistics and latency
- SageMaker endpoint invocation metrics
- Processing latencies by function

#### Error Tracking
- Lambda function errors with detailed logs
- Long-running invocations with duration metrics
- Classification/extraction failures
- API throttling and retry metrics
- SageMaker endpoint errors

#### Lambda Function Metrics
- Duration (average, p90, maximum)
- Memory usage and utilization
- Error rates and exception counts
- Concurrent execution metrics

### Template Outputs

The pattern exports these outputs to the parent stack:

- `StateMachineName`: Name of Step Functions state machine
- `StateMachineArn`: ARN of Step Functions state machine
- `StateMachineLogGroup`: CloudWatch log group for state machine
- `DashboardName`: Name of pattern-specific dashboard
- `DashboardArn`: ARN of pattern-specific dashboard

### Configuration

Key configurable parameters:

- `UDOPModelArtifactPath`: S3 path to UDOP model artifacts (see [Fine tuning a UDOP model](#fine-tuning-a-udop-model-for-classification))
- `ExtractionModel`: Bedrock model ID for extraction (Claude)
- `MaxConcurrentWorkflows`: Workflow concurrency limit
- `LogRetentionDays`: CloudWatch log retention period
- `ExecutionTimeThresholdMs`: Latency threshold for alerts

## Customizing Extraction

The system uses a combination of prompt engineering and predefined attributes to extract information from documents. You can customize both to match your specific document types and extraction needs.

### Extraction Prompts

The extraction prompts are defined in the template configuration. The structure is similar to the one shown below:

```python
DEFAULT_SYSTEM_PROMPT = "You are a document assistant. Respond only with JSON..."
BASELINE_PROMPT = """
<background>
You are an expert in business document analysis and information extraction. You can understand and extract key information from various types of business documents including letters, memos, financial documents, scientific papers, news articles, advertisements, emails, forms, handwritten notes, invoices, purchase orders, questionnaires, resumes, scientific publications, and specifications...
</background>
...
```
To modify the extraction behavior:

1. Modify the configuration settings in the template.yaml file or through the UI configuration
2. Edit the `system_prompt` to change the AI assistant's basic behavior
3. Customize the `task_prompt` to:
   - Provide domain expertise for your document types
   - Add specific instructions for handling edge cases
   - Modify output formatting requirements


### Extraction Attributes
Attributes to be extracted are defined in the template configuration's `classes` section. The structure is similar to the example below:

Example attribute definition:
```yaml
classes:
  - name: letter
    description: A formal written message that is typically sent from one person to another
    attributes:
      - name: sender_name
        description: The name of the person or entity who wrote or sent the letter. Look for text following or near terms like 'from', 'sender', 'authored by', 'written by', or at the end of the letter before a signature.
      - name: sender_address
        description: The physical address of the sender, typically appearing at the top of the letter. May be labeled as 'address', 'location', or 'from address'.
      - name: recipient_name
        description: The name of the person or entity receiving the letter. Look for this after 'to', 'recipient', 'addressee', or at the beginning of the letter.
      - name: recipient_address
        description: The physical address where the letter is to be delivered. Often labeled as 'to address' or 'delivery address', typically appearing below the recipient name.
  - name: form
    description: A document with blank spaces for filling in information
    attributes:
      - name: form_type
        description: The category or purpose of the form, such as 'application', 'registration', 'request', etc. May be identified by 'form name', 'document type', or 'form category'.
      - name: form_id
        description: The unique identifier for the form, typically a number or alphanumeric code. Often labeled as 'form number', 'id', or 'reference number'.
```

To customize attributes:
1. Modify the `classes` section in the template configuration
2. For each attribute, provide a clear name and detailed description
3. The configuration can be updated through the UI after deployment

Note: Changes to the configuration are applied immediately without requiring function redeployment.


## Testing

Use the provided test events in the `testing/` directory:

```bash
# Test OCR function
sam local invoke OCRFunction --env-vars testing/env.json -e testing/OCRFunction-event.json

# Test classification
sam local invoke ClassificationFunction --env-vars testing/env.json -e testing/ClassificationFunctionEvent.json

# Test extraction
sam local invoke ExtractionFunction --env-vars testing/env.json -e testing/ExtractionFunction-event.json
```

Note that for proper testing of the classification function, you'll need access to a running SageMaker endpoint with the UDOP model deployed.

## Best Practices

1. **SageMaker Endpoint Management**:
   - Configure appropriate instance type based on model size and throughput requirements
   - Enable auto-scaling for cost optimization during varying loads
   - Monitor endpoint performance metrics for potential bottlenecks

2. **Retry Handling**:
   - All functions implement exponential backoff with jitter
   - Configure appropriate retry limits for different types of failures
   - Handle SageMaker endpoint throttling differently from transient failures

3. **Performance Optimization**:
   - Pre-warm the SageMaker endpoint with sample requests during initialization
   - Configure appropriate memory for Lambda functions based on document size
   - Use efficient image preprocessing and data handling techniques

4. **Monitoring**:
   - Set up CloudWatch alarms for critical metrics
   - Use detailed logging with correlation IDs for request tracking
   - Monitor token usage and cost metrics for GenAI components

5. **Security**:
   - Use KMS encryption for data at rest and in transit
   - Implement least privilege IAM roles for all components
   - Protect SageMaker endpoints with appropriate security groups

6. **Error Handling**:
   - Implement graceful degradation strategies
   - Provide clear error messages with actionable information
   - Track error rates by category for targeted improvements