Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# Using Notebooks with IDP Common Library

This guide provides detailed instructions on how to use existing notebooks and create new notebooks for experimentation with the IDP Common Library.

## Table of Contents

- [Introduction](#introduction)
- [Getting Started](#getting-started)
  - [Setting Up Your Environment](#setting-up-your-environment)
  - [Installing the IDP Common Package](#installing-the-idp-common-package)
  - [Configuring Environment Variables](#configuring-environment-variables)
- [Using Existing Notebooks](#using-existing-notebooks)
  - [Available Example Notebooks](#available-example-notebooks)
  - [Running Example Notebooks](#running-example-notebooks)
- [Creating New Notebooks](#creating-new-notebooks)
  - [Basic Structure](#basic-structure)
  - [Common Patterns](#common-patterns)
  - [Best Practices](#best-practices)
- [Common Use Cases](#common-use-cases)
  - [Working with Bedrock Client](#working-with-bedrock-client)
  - [OCR Processing](#ocr-processing)
  - [Document Classification](#document-classification)
  - [Information Extraction](#information-extraction)
  - [Evaluation](#evaluation)
  - [Bedrock Data Automation (BDA)](#business-document-analysis-bda)
- [Tips and Troubleshooting](#tips-and-troubleshooting)
- [Advanced Topics](#advanced-topics)
  - [Working with Custom Models](#working-with-custom-models)
  - [Performance Optimization](#performance-optimization)
  - [Integration with Other AWS Services](#integration-with-other-aws-services)

## Introduction

Jupyter Notebooks provide an interactive environment for experimenting with and testing the IDP Common Library. They allow you to:

- Test individual components of the IDP pipeline
- Experiment with different configurations and parameters
- Process documents end-to-end in a controlled environment
- Evaluate extraction results and calculate accuracy metrics
- Visualize outputs and debug issues

The IDP Common Library provides a unified Document model and modular services for OCR, classification, extraction, and evaluation, making it ideal for notebook-based experimentation.

## Getting Started

### Setting Up Your Environment

1. Ensure you have Jupyter installed in your environment:
   ```bash
   pip install jupyter
   ```

2. Navigate to the notebooks directory:
   ```bash
   cd notebooks
   ```

3. Launch Jupyter:
   ```bash
   jupyter notebook
   ```

### Installing the IDP Common Package

The IDP Common package should be installed in development mode to make changes immediately available without reinstallation:

```python
# First uninstall any existing version
%pip uninstall -y idp_common

# Install in development mode with all components
%pip install -q -e "../lib/idp_common_pkg[dev, all]"
```

For specific components only:

```python
# Install only specific components
%pip install -q -e "../lib/idp_common_pkg[ocr,classification,extraction]"
```

### Configuring Environment Variables

Create a `.env` file in the notebooks directory to store your AWS configuration:

```bash
# Sample .env file
AWS_REGION=us-east-1
METRIC_NAMESPACE=IDP-Notebook-Example
IDP_INPUT_BUCKET_NAME=my-input-bucket
IDP_OUTPUT_BUCKET_NAME=my-output-bucket
```

Load these variables in your notebook:

```python
try:
    from dotenv import load_dotenv
    load_dotenv()  
except ImportError:
    pass  
```

## Using Existing Notebooks

### Available Example Notebooks

The IDP Accelerator provides several example notebooks:

| Notebook | Description |
|----------|-------------|
| `evaluation_methods_demo.ipynb` | Demonstrates various evaluation methods for comparing extraction results |
| `e2e-example-with-multimodal-page-classification.ipynb` | End-to-end document processing example using multimodal page classification |
| `e2e-example-with-multimodal-page-classification-few-shot-prompting.ipynb` | Example using few-shot prompting with multimodal page classification |
| `e2e-holistic-packet-classification.ipynb` | End-to-end processing using holistic document classification |
| `e2e-holistic-packet-classification-summarization.ipynb` | Document classification and summarization example |
| `test_few_shot_classification.ipynb` | Demonstrates few-shot learning for document classification |
| `test_few_shot_extraction.ipynb` | Demonstrates few-shot learning for information extraction |
| `bedrock_client_test.ipynb` | Test notebook for the Bedrock client |
| `bedrock_client_cachepoint_test.ipynb` | Test notebook for the Bedrock client with caching functionality |
| `bda/kie-bda-happy-path.ipynb` | Example using Bedrock Data Automation (BDA) for key information extraction |

### Running Example Notebooks

1. Open the desired notebook in Jupyter.
2. Review the notebook documentation and structure.
3. Execute the cells sequentially to understand the workflow.
4. Modify parameters as needed for your use case.

## Creating New Notebooks

### Basic Structure

A typical IDP notebook follows this structure:

1. **Setup and Imports**
   ```python
   %load_ext autoreload
   %autoreload 2
   
   # Install the IDP common package
   %pip install -q -e "../lib/idp_common_pkg[dev, all]"
   
   # Import core libraries
   import os
   import json
   import boto3
   import logging
   from idp_common.models import Document, Status, Section
   from idp_common import ocr, classification, extraction, evaluation
   
   # Configure logging
   logging.basicConfig(level=logging.INFO)
   ```

2. **Environment Configuration**
   ```python
   # Load environment variables
   from dotenv import load_dotenv
   load_dotenv()
   
   # Set up AWS environment
   region = os.environ.get('AWS_REGION', 'us-east-1')
   input_bucket = os.environ.get('IDP_INPUT_BUCKET_NAME')
   output_bucket = os.environ.get('IDP_OUTPUT_BUCKET_NAME')
   ```

3. **IDP Configuration**
   ```python
   # Define configuration similar to what would be in DynamoDB
   CONFIG = {
       "classes": [...],
       "classification": {...},
       "extraction": {...},
       "evaluation": {...}
   }
   ```

4. **Document Processing**
   ```python
   # Initialize document
   document = Document(
       id="my-document",
       input_bucket=input_bucket,
       input_key="document.pdf",
       output_bucket=output_bucket
   )
   
   # Process with OCR
   ocr_service = ocr.OcrService()
   document = ocr_service.process_document(document)
   
   # Classify document
   classification_service = classification.ClassificationService(config=CONFIG)
   document = classification_service.classify_document(document)
   
   # Extract information
   extraction_service = extraction.ExtractionService(config=CONFIG)
   for section in document.sections:
       document = extraction_service.process_document_section(document, section.section_id)
   ```

5. **Results Analysis**
   ```python
   # Display results
   for section in document.sections:
       print(f"Section: {section.section_id}, Class: {section.classification}")
       if section.attributes:
           print(json.dumps(section.attributes, indent=2))
   ```

### Common Patterns

1. **Document Creation Pattern**
   ```python
   document = Document(
       id="doc-id",
       input_bucket="my-bucket",
       input_key="document.pdf",
       output_bucket="output-bucket"
   )
   ```

2. **Service Initialization Pattern**
   ```python
   # OCR with enhanced features
   ocr_service = ocr.OcrService(
       enhanced_features=["TABLES", "FORMS", "LAYOUT"]
   )
   
   # Classification with Bedrock backend
   classification_service = classification.ClassificationService(
       config=CONFIG,
       backend="bedrock"  # or "sagemaker"
   )
   
   # Extraction service
   extraction_service = extraction.ExtractionService(config=CONFIG)
   
   # Evaluation service
   evaluation_service = evaluation.EvaluationService(config=CONFIG)
   ```

3. **Processing Pattern**
   ```python
   # Each service operation takes a document and returns an updated document
   document = ocr_service.process_document(document)
   document = classification_service.classify_document(document)
   document = extraction_service.process_document_section(document, "section-1")
   ```

4. **Evaluation Pattern**
   ```python
   # Create expected document
   expected_document = Document.from_s3(bucket="baseline", input_key=document.input_key)
   
   # Evaluate results
   document = evaluation_service.evaluate_document(document, expected_document)
   
   # Access evaluation report
   report_uri = document.evaluation_report_uri
   ```

### Best Practices

1. **Use Autoreload**
   ```python
   %load_ext autoreload
   %autoreload 2
   ```
   This ensures that code changes in the library are automatically reloaded.

2. **Modular Configuration**
   Keep configuration sections separate for easy modification:
   ```python
   OCR_CONFIG = {...}
   CLASSIFICATION_CONFIG = {...}
   EXTRACTION_CONFIG = {...}
   ```

3. **Error Handling**
   ```python
   try:
       document = ocr_service.process_document(document)
   except Exception as e:
       print(f"OCR processing failed: {str(e)}")
       # Handle failure
   ```

4. **Performance Metrics**
   ```python
   import time
   
   start_time = time.time()
   document = ocr_service.process_document(document)
   ocr_time = time.time() - start_time
   
   print(f"OCR processing completed in {ocr_time:.2f} seconds")
   ```

5. **Resource Cleanup**
   ```python
   def cleanup_s3_objects(bucket, prefix):
       s3_client = boto3.client('s3')
       response = s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix)
       if 'Contents' in response:
           for obj in response['Contents']:
               s3_client.delete_object(Bucket=bucket, Key=obj['Key'])
   
   # Clean up at the end of the notebook
   cleanup_s3_objects(output_bucket, document.id)
   ```

## Common Use Cases

### Working with Bedrock Client

The IDP Common Library provides a robust Bedrock client implementation with built-in retry logic and caching capabilities. Two example notebooks demonstrate these features:

```python
# Import the Bedrock client functionality
from idp_common.bedrock import get_bedrock_client, invoke_model, get_model_id

# Get a configured Bedrock client
bedrock_client = get_bedrock_client()

# Basic model invocation
response = invoke_model(
    model_id="us.amazon.nova-lite-v1:0",
    prompt="Summarize the following document: {text}",
    temperature=0.0,
    top_k=5,
    max_tokens=1000
)

# With caching for improved performance
# The cachepoint tag in the prompt marks where the prompt should be split for caching
prompt = """System: You are a document classifier.
User: Classify this document as either invoice, letter, or form.

<<CACHEPOINT>>

Document content: {document_text}
"""

# The invoke_model function automatically handles caching when it detects the CACHEPOINT tag
response = invoke_model(
    model_id="us.amazon.nova-lite-v1:0",
    prompt=prompt.format(document_text="Sample document content..."),
    temperature=0.0,
    top_k=5,
    max_tokens=100
)
```

The `bedrock_client_test.ipynb` notebook demonstrates basic Bedrock client usage, while `bedrock_client_cachepoint_test.ipynb` shows how to leverage the caching functionality using the CACHEPOINT marker in prompts.

Benefits of the idp_common Bedrock client:
- Automatic retries with exponential backoff for transient errors
- Response caching for improved performance and cost reduction
- Support for streaming responses
- Standardized error handling
- Track token usage for cost monitoring

### OCR Processing

Example for extracting text from documents:

```python
# For basic text extraction
ocr_service = ocr.OcrService()
document = ocr_service.process_document(document)

# For enhanced features
ocr_service = ocr.OcrService(
    enhanced_features=["TABLES", "FORMS", "SIGNATURES", "LAYOUT"]
)
document = ocr_service.process_document(document)

# Access extracted text
for page_id, page in document.pages.items():
    print(f"Page {page_id}:")
    
    # Load text from S3
    raw_text = s3.get_json_content(page.raw_text_uri)
    print(raw_text)
    
    # Access tables if extracted
    for table in page.tables:
        print(f"Table: {json.dumps(table, indent=2)}")
```

### Document Classification

Example for classifying documents:

```python
# Text-based classification
classification_service = classification.ClassificationService(
    config=CONFIG,
    backend="bedrock"
)
document = classification_service.classify_document(document)

# Multimodal classification (text + images)
config = {
    "classification": {
        "classificationMethod": "multimodalPageLevelClassification",
        "model": "us.amazon.nova-pro-v1:0"
        # other configuration...
    }
}
classification_service = classification.ClassificationService(
    config=config,
    backend="bedrock"
)
document = classification_service.classify_document(document)

# Access classification results
for section in document.sections:
    print(f"Section {section.section_id}: {section.classification} (confidence: {section.confidence})")
    print(f"  Pages: {section.page_ids}")
```

### Information Extraction

Example for extracting structured data:

```python
# Configure extraction
extraction_service = extraction.ExtractionService(config=CONFIG)

# Process each section
for section in document.sections:
    document = extraction_service.process_document_section(
        document=document,
        section_id=section.section_id
    )

# Access extracted attributes
for section in document.sections:
    if section.extraction_result_uri:
        # Load extraction results from S3
        extraction_results = s3.get_json_content(section.extraction_result_uri)
        print(f"Section {section.section_id} ({section.classification}):")
        print(json.dumps(extraction_results, indent=2))
```

### Evaluation

Example for evaluating extraction results:

```python
# Define expected results
expected_results = {
    "section-1": {
        "customer_name": "John Smith",
        "invoice_number": "INV-12345",
        "total_amount": 1250.00
    }
}

# Create expected document
expected_document = create_ground_truth_document(document, expected_results)

# Evaluate results
evaluation_service = evaluation.EvaluationService(config=CONFIG)
document = evaluation_service.evaluate_document(document, expected_document)

# Display results
print(f"Evaluation report: {document.evaluation_report_uri}")
print(f"Overall metrics: {document.evaluation_result.overall_metrics}")
```

### Bedrock Data Automation (BDA)

The IDP Common Library provides integration with Amazon Bedrock Data Automation (BDA) capabilities, which offers built-in extraction for common business document types like invoices, receipts, and more.

Example for using BDA for key information extraction:

```python
# Import BDA modules
from idp_common.bda import BDAService
from idp_common.models import Document

# Create a document
document = Document(
    id="invoice-doc-001",
    input_bucket="my-input-bucket",
    input_key="invoices/sample.pdf",
    output_bucket="my-output-bucket"
)

# Initialize BDA service
bda_service = BDAService(
    region="us-east-1",
    analyze_expense=True,  # For receipts/expense documents
    analyze_lending=True   # For lending documents (W2, paystubs, etc.)
)

# Process document with BDA
document = bda_service.process_document(document)

# Access extracted BDA data
for page_id, page in document.pages.items():
    # Access expense fields
    if hasattr(page, 'expense_fields'):
        print(f"Expense fields for page {page_id}:")
        for field in page.expense_fields:
            print(f"{field['Type']['Text']}: {field['ValueDetection']['Text']}")
    
    # Access lending fields
    if hasattr(page, 'lending_fields'):
        print(f"Lending fields for page {page_id}:")
        for field in page.lending_fields:
            print(f"{field['Type']['Text']}: {field['ValueDetection']['Text']}")
```

The `bda/kie-bda-happy-path.ipynb` notebook demonstrates a complete workflow using BDA for key information extraction:

1. Setting up the necessary AWS resources and permissions
2. Processing documents with BDA
3. Parsing and normalizing BDA results
4. Storing and visualizing the structured data

Key benefits of using BDA:

- Built-in extractors for common business documents
- No need for training custom models
- High accuracy for supported document types
- Integration with the Document model for consistent workflows
- Support for a wide range of document types:
  - Invoices and receipts
  - Tax documents (W-2, 1099)
  - Bank statements
  - Paystubs
  - ID documents

## Tips and Troubleshooting

### Common Issues

1. **Missing Dependencies**
   
   If you encounter import errors, ensure you have installed the correct components:
   ```python
   %pip install -q -e "../lib/idp_common_pkg[dev, all]"
   ```

2. **S3 Access Issues**
   
   Ensure your AWS credentials have permission to access the specified buckets:
   ```python
   # Check bucket access
   s3_client = boto3.client('s3')
   try:
       s3_client.head_bucket(Bucket=bucket_name)
       print("Bucket access confirmed")
   except Exception as e:
       print(f"Bucket access error: {str(e)}")
   ```

3. **Bedrock Model Access**
   
   Verify you have access to the Bedrock models:
   ```python
   # List available models
   from idp_common.bedrock import get_bedrock_client
   
   bedrock_client = get_bedrock_client()
   response = bedrock_client.list_foundation_models()
   for model in response['modelSummaries']:
       print(f"{model['modelId']}: {model['modelName']}")
   ```

4. **Debug Logging**
   
   Enable detailed logging:
   ```python
   import logging
   
   # Configure logging
   logging.basicConfig(level=logging.DEBUG)
   logging.getLogger('idp_common').setLevel(logging.DEBUG)
   ```

### Debugging Techniques

1. **Inspect Document State**
   
   Print the document's state at different stages:
   ```python
   print(f"Status: {document.status.value}")
   print(f"Pages: {len(document.pages)}")
   print(f"Sections: {len(document.sections)}")
   
   # Convert to dictionary for easier inspection
   document_dict = document.to_dict()
   print(json.dumps(document_dict, indent=2))
   ```

2. **Examine S3 Content**
   
   Inspect files stored in S3:
   ```python
   def view_s3_content(uri):
       bucket, key = parse_s3_uri(uri)
       response = s3_client.get_object(Bucket=bucket, Key=key)
       content = response['Body'].read().decode('utf-8')
       try:
           return json.loads(content)
       except:
           return content
   
   # View extraction results
   for section in document.sections:
       if section.extraction_result_uri:
           print(view_s3_content(section.extraction_result_uri))
   ```

3. **Test Individual Components**
   
   Isolate components for testing:
   ```python
   # Test OCR only
   ocr_document = Document(input_bucket=bucket, input_key=key, output_bucket=output_bucket)
   ocr_document = ocr_service.process_document(ocr_document)
   
   # Test classification only with pre-processed text
   classification_document = Document(input_bucket=bucket, input_key=key, output_bucket=output_bucket)
   classification_document.pages = ocr_document.pages  # Copy pages with OCR results
   classification_document = classification_service.classify_document(classification_document)
   ```

## Advanced Topics

### Working with Custom Models

Example for using your own models:

```python
# SageMaker classification
classification_service = classification.ClassificationService(
    config=CONFIG,
    backend="sagemaker",
    endpoint_name="my-custom-classifier"
)

# Custom model configuration
custom_config = {
    "classification": {
        "classificationMethod": "textbasedHolisticClassification",
        "endpoint_name": "my-custom-endpoint",
        "region": "us-east-1"
    }
}
```

### Performance Optimization

Tips for optimizing performance:

```python
# Parallel processing for multiple documents
from concurrent.futures import ThreadPoolExecutor

def process_document(doc_key):
    doc = Document(input_bucket=bucket, input_key=doc_key, output_bucket=output_bucket)
    doc = ocr_service.process_document(doc)
    doc = classification_service.classify_document(doc)
    return doc

document_keys = ["doc1.pdf", "doc2.pdf", "doc3.pdf"]
with ThreadPoolExecutor(max_workers=3) as executor:
    results = list(executor.map(process_document, document_keys))
```

### Integration with Other AWS Services

Example for integrating with other AWS services:

```python
# Amazon Comprehend for entity extraction
def extract_entities(text):
    comprehend = boto3.client('comprehend')
    response = comprehend.detect_entities(
        Text=text,
        LanguageCode='en'
    )
    return response['Entities']

# Process each page
for page_id, page in document.pages.items():
    text = s3.get_text_content(page.raw_text_uri)
    entities = extract_entities(text)
    print(f"Entities in page {page_id}:")
    print(entities)
```

## Conclusion

Notebooks provide an excellent environment for experimenting with the IDP Common Library. By following the patterns and best practices outlined in this guide, you can:

- Test various components of the IDP pipeline
- Develop custom processing workflows
- Evaluate accuracy and performance
- Iterate quickly on improvements

The modular architecture of the IDP Common Library makes it easy to experiment with different configurations and approaches, while the unified Document model ensures consistent data flow throughout the processing pipeline.
