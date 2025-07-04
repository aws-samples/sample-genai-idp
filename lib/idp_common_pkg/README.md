Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# IDP Common Package

This package contains common utilities and services for the GenAI IDP Accelerator patterns.

## Components

### Core Data Model

- **Document Model**: Central data structure for the entire IDP pipeline with automatic compression support for large documents ([models.py](idp_common/models.py), [README](idp_common/README.md))

### Core Services

- **OCR**: Document OCR processing with AWS Textract ([README](idp_common/ocr/README.md))
- **Classification**: Document classification using LLMs and SageMaker/UDOP ([README](idp_common/classification/README.md))
- **Extraction**: Field extraction from documents using LLMs ([README](idp_common/extraction/README.md))
- **Evaluation**: Compare extraction results against ground truth for accuracy measurement ([README](idp_common/evaluation/README.md))
- **Summarization**: Generate summaries for each section in a document ([README](idp_common/summarization/README.md))
- **AppSync**: Integration with AWS AppSync for document storage ([README](idp_common/appsync/README.md))
- **Reporting**: Save document data to reporting storage for analytics ([README](idp_common/reporting/README.md))

### AWS Service Clients

- Bedrock client with retry logic
- S3 client operations
- CloudWatch metrics
- AppSync client for GraphQL operations

### Configuration

- DynamoDB-based configuration management
- Support for default and custom configuration merging

### Image Processing

- Image resizing and preparation
- Support for multimodal inference with Bedrock

### Utils

- Retry/backoff algorithm
- S3 URI parsing
- Metering data aggregation

## Document Compression for Large Documents

The Document model includes automatic compression support to handle large documents that exceed Step Functions payload limits (256KB). This feature is essential for processing multi-page documents with extensive content.

### Key Features

- **Automatic Compression**: Documents exceeding configurable size thresholds are automatically compressed to S3
- **Transparent Handling**: Lambda functions seamlessly handle both compressed and uncompressed documents
- **Section Preservation**: Section IDs are preserved in compressed payloads for Step Functions Map operations
- **Utility Methods**: Simplified input/output handling with `load_document()` and `serialize_document()`

### Usage in Lambda Functions

```python
from idp_common.models import Document
import os

def lambda_handler(event, context):
    working_bucket = os.environ.get('WORKING_BUCKET')
    
    # Handle input - automatically detects and decompresses if needed
    document = Document.load_document(
        event_data=event["document"], 
        working_bucket=working_bucket, 
        logger=logger
    )
    
    # Process document...
    # (your processing logic here)
    
    # Prepare output - automatically compresses if document is large
    response = {
        "document": document.serialize_document(
            working_bucket=working_bucket, 
            step_name="classification", 
            logger=logger
        )
    }
    
    return response
```

### Manual Compression/Decompression

```python
# Manual compression
compressed_data = document.compress(working_bucket, "processing_step")
# Returns: {"document_id": "...", "s3_uri": "...", "section_ids": [...], "compressed": True}

# Manual decompression
restored_document = Document.decompress(working_bucket, compressed_data)

# Handle either compressed or regular document data
document = Document.from_compressed_or_dict(data, working_bucket)
```

### Configuration

- **Default threshold**: 0KB - always compress (configurable)
- **Storage location**: `s3://working-bucket/compressed_documents/{document_id}/{timestamp}_{step_name}_state.json`
- **Automatic cleanup**: Temporary compressed files can be cleaned up via S3 lifecycle policies

## Unified Document-based Architecture

All core services (OCR, Classification, Extraction, and AppSync) use a unified Document model approach with automatic compression support:

```python
from idp_common import get_config
from idp_common.models import Document
from idp_common import ocr, classification, extraction, appsync

# Initialize document
document = Document(
    id="doc-123",
    input_bucket="my-input-bucket",
    input_key="documents/sample.pdf",
    output_bucket="my-output-bucket"
)

# Get configuration
config = get_config()

# Process with OCR
ocr_service = ocr.OcrService(config=config)
document = ocr_service.process_document(document)

# Perform classification (supports both Bedrock and SageMaker/UDOP backends)
classification_service = classification.ClassificationService(
    config=config,
    backend="bedrock"  # or "sagemaker" for SageMaker UDOP model
)
document = classification_service.classify_document(document)

# Extract information from a section
extraction_service = extraction.ExtractionService(config=config)
document = extraction_service.process_document_section(
    document=document, 
    section_id=document.sections[0].section_id
)

# Store document in AppSync
appsync_service = appsync.DocumentAppSyncService()
updated_document = appsync_service.update_document(document)

# Access the extraction results URI
result_uri = document.sections[0].extraction_result_uri
```

## Service Modules

### Document Model (`models.py`)

The central data model for the IDP processing pipeline ([README](idp_common/README.md)):
- Represents the state of a document as it moves through processing
- Tracks pages, sections, processing status, and results
- Common data structure shared between all services
- Support for loading baseline documents from S3 for evaluation

### OCR Service (`ocr`)

Provides OCR processing of documents using AWS Textract:
- Document-based OCR processing with the `process_document()` method
- Multi-page document processing with thread concurrency
- Image extraction and optimization
- Support for enhanced Textract features (TABLES, FORMS, SIGNATURES, LAYOUT) with granular control
- Rich markdown output for tables and forms preservation
- Well-structured results for downstream processing

### Classification Service (`classification`)

Document classification using multimodal LLMs:
- Document-based classification with the `classify_document()` method
- Support for both Bedrock and SageMaker backends
- Page-level and document-level classification
- Section detection for multi-class documents
- Configurable document types and descriptions
- Multimodal classification with both text and images

### Extraction Service (`extraction`)

Field extraction from documents using multimodal LLMs:
- Document-based extraction with the `process_document_section()` method
- Extraction of structured data from document sections
- Support for document class-specific attribute definitions
- Multimodal extraction using both text and images
- Flexible prompt templates configurable via the configuration system
- Results stored in S3 with URIs tracked in the Document model

### Evaluation Service (`evaluation`)

Evaluate extraction results against ground truth:
- Document-based evaluation with the `evaluate_document()` method
- Multiple configurable evaluation methods (EXACT, FUZZY, NUMERIC_EXACT, etc.)
- Rich metrics calculation (precision, recall, F1, accuracy)
- Visual markdown reports with color-coded indicators
- Per-attribute, section, and document-level metrics
- Integration with the Document model for seamless evaluation
- Results and reports stored in S3 with URIs tracked in the Document

### AppSync Service (`appsync`)

Manages document storage and retrieval through AWS AppSync GraphQL API:
- Document-based storage with `create_document()` and `update_document()` methods
- Seamless conversion between Document objects and GraphQL schema
- Handles SigV4 authentication for AppSync requests
- Provides error handling for GraphQL operations
- Manages document TTL (time-to-live) for automatic expiration

### Reporting Service (`reporting`)

Saves document data to reporting storage for analytics:
- Document-based reporting with the `save()` method
- Saves evaluation results as Parquet files in S3
- Hierarchical storage structure by year/month/day/document
- Support for document-level, section-level, and attribute-level metrics
- Extensible design for adding new data types
- Compatible with AWS Glue and Amazon Athena for analytics

## Basic Usage

```python
from idp_common import (
    bedrock,       # Bedrock client and operations
    s3,            # S3 operations
    metrics,       # CloudWatch metrics
    image,         # Image processing
    utils,         # General utilities
    config,        # Configuration module
    get_config,    # Direct access to the configuration function
    ocr,           # OCR service and models
    classification, # Classification service and models
    extraction,    # Extraction service and models
    evaluation,    # Evaluation service and models
    appsync,       # AppSync integration
    reporting      # Reporting services
)
from idp_common.models import Document, Status

# Get configuration (merged from Default and Custom records in the DynamoDb Configuration Table)
cfg = get_config()

# Create a document object
document = Document(
    input_bucket="my-bucket",
    input_key="my-document.pdf",
    output_bucket="output-bucket"
)

# OCR Processing
ocr_service = ocr.OcrService()  # Basic text detection
# ocr_service = ocr.OcrService(enhanced_features=["TABLES", "FORMS"])  # Enhanced features
document = ocr_service.process_document(document)

# Document Classification (choose your backend)
classification_service = classification.ClassificationService(
    config=cfg, 
    backend="bedrock"  # or "sagemaker" for UDOP model
)
document = classification_service.classify_document(document)

# Field Extraction for a section
extraction_service = extraction.ExtractionService(config=cfg)
document = extraction_service.process_document_section(document, section_id="section-1")

# Evaluate extraction results
# Load expected document from baseline files in S3
expected_document = Document.from_s3(bucket="baseline-bucket", input_key=document.input_key)
evaluation_service = evaluation.EvaluationService(config=cfg)
document = evaluation_service.evaluate_document(document, expected_document)
# Access evaluation report URI
report_uri = document.evaluation_report_uri
# The evaluation result is also available directly
evaluation_result = document.evaluation_result

# Save evaluation results to reporting storage
reporter = reporting.SaveReportingData("reporting-bucket")
reporter.save(document, data_to_save=["evaluation_results"])

# Store document in AppSync
appsync_service = appsync.DocumentAppSyncService()
updated_document = appsync_service.update_document(document)

# Publish a metric
metrics.put_metric("MetricName", 1)

# Invoke Bedrock
response = bedrock.invoke_model(...)

# Read from S3
content = s3.get_text_content("s3://bucket/key.json")

# Process an image for model input
image_bytes = image.prepare_image("s3://bucket/image.jpg")

# Parse S3 URI
bucket, key = utils.parse_s3_uri("s3://bucket/key")
```

## Configuration

The configuration module provides a way to retrieve and merge configuration from DynamoDB. It expects:

1. A DynamoDB table with a primary key named 'Configuration'
2. Two configuration items with keys 'Default' and 'Custom'

The `get_config()` function retrieves both configurations and merges them, with custom values taking precedence over default ones.

```python
# Get configuration with default table name from CONFIGURATION_TABLE_NAME environment variable
config = get_config()

# Or specify a table name explicitly
config = get_config(table_name="my-config-table")
```

## Installation with Granular Dependencies

To minimize Lambda package size, you can install only the specific components you need:

```bash
# Install core functionality only (minimal dependencies)
pip install "idp_common[core]"

# Install with OCR support
pip install "idp_common[ocr]"

# Install with classification support
pip install "idp_common[classification]"

# Install with extraction support
pip install "idp_common[extraction]"

# Install with evaluation support
pip install "idp_common[evaluation]"

# Install with reporting support
pip install "idp_common[reporting]"

# Install with AppSync support
pip install "idp_common[appsync]"

# Install with image processing support
pip install "idp_common[image]"

# Install everything
pip install "idp_common[all]"

# Install multiple components
pip install "idp_common[ocr,classification]"
```

For Lambda functions, specify only the required components in requirements.txt:

```
../../lib/idp_common_pkg[extraction]
```

This ensures that only the necessary dependencies are included in your Lambda deployment package.

## Development Notes

This package has been refactored to use a unified Document-based approach across all services:

1. All services now accept and return Document objects
2. Each service updates the Document with its results
3. Results are properly encapsulated in the Document model
4. Large results (like extraction attributes) are stored in S3 with only URIs in the Document

Key benefits:
- Consistency across all services
- Simplified data flow in serverless functions
- Better resource usage with the focused document pattern
- Improved maintainability with standardized interfaces

## Testing

This package includes a comprehensive test suite using pytest. To run the tests:

```bash
# Install the package with test dependencies
pip install -e ".[test]"

# Run all tests
pytest

# Run tests for a specific module
pytest tests/unit/test_models.py
```

### Test Structure

- **Unit Tests**: Located in `tests/unit/`, these test individual components in isolation
- **Integration Tests**: Located in `tests/integration/`, these test how components work together
- **Fixtures**: Common test fixtures are defined in `tests/conftest.py`

### Test Configuration

The test configuration is defined in `pytest.ini`:

- Coverage reporting is enabled by default
- Tests are organized by markers (`unit`, `integration`, `slow`)
- HTML and XML coverage reports are generated

### Adding New Tests

When adding new functionality to the package, please also add corresponding tests:

1. For new modules, create a new test file in `tests/unit/`
2. Use the appropriate fixtures from `conftest.py`
3. Use mocking for external dependencies
4. Add integration tests for interactions between components
## Testing

This package includes a simple test suite using pytest. To run the tests:

```bash
# Install the package with test dependencies
pip install -e ".[test]"

# Run all tests
pytest

# Run with coverage report in terminal only
pytest --cov=idp_common --cov-report=term-missing

# Run tests and generate JUnit XML report and coverage XML report
pytest

# Specify custom output locations
pytest --junitxml=custom-test-results.xml --cov=idp_common --cov-report=xml:custom-coverage.xml

# Run tests in parallel (faster for large test suites)
pytest -xvs
```

By default, running pytest will:
- Run all tests in the `tests` directory
- Generate a test results report in JUnit XML format at `test-results.xml`
- Generate a coverage report in XML format at `coverage.xml`
- Display a coverage summary in the terminal

These reports can be used for CI/CD integration and code quality monitoring.

### Adding More Tests

When adding new functionality to the package, please add corresponding tests in the `tests/unit/` directory.
