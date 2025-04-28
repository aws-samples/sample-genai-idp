# Document Classification for IDP Accelerator

This module provides document classification capabilities for the IDP Accelerator project, allowing classification of documents based on their text and image content. It supports multiple classification backends including Bedrock LLMs and SageMaker UDOP models.

## Features

- Classification of documents using multiple backend options:
  - Amazon Bedrock LLMs
  - SageMaker UDOP models
- Direct integration with the Document data model
- Support for both text and image content
- Concurrent processing of multiple pages
- Structured data models for results
- Grouping of pages into sections by classification
- Comprehensive error handling and retry mechanisms

## Usage Example

### Using with Bedrock LLMs (Default)

```python
from idp_common import classification, get_config
from idp_common.models import Document

# Load configuration
config = get_config()

# Initialize classification service with Bedrock backend
service = classification.ClassificationService(
    region="us-east-1",
    config=config,
    backend="bedrock"  # This is the default
)

# Create or get a Document object
document = Document(
    id="doc-123",
    input_bucket="input-bucket",
    input_key="document.pdf",
    output_bucket="output-bucket",
    pages={
        "1": {
            "page_id": "1",
            "parsed_text_uri": "s3://bucket/document/pages/1/result.json",
            "image_uri": "s3://bucket/document/pages/1/image.jpg",
            "raw_text_uri": "s3://bucket/document/pages/1/rawText.json"
        }
    }
)

# Classify the document - updates the Document object directly
document = service.classify_document(document)

# Document now contains classification results
print(f"Document has {len(document.sections)} sections")
for section in document.sections:
    print(f"Section {section.section_id}: {section.classification}")
    print(f"Pages: {section.page_ids}")
```

### Using with SageMaker UDOP Models

```python
from idp_common import classification, get_config
from idp_common.models import Document

# Load configuration and add SageMaker endpoint
config = get_config()
config["sagemaker_endpoint_name"] = "udop-classification-endpoint"

# Initialize classification service with SageMaker backend
service = classification.ClassificationService(
    region="us-east-1",
    config=config,
    backend="sagemaker"
)

# Create or get a Document object
document = Document(
    id="doc-123",
    input_bucket="input-bucket",
    input_key="document.pdf",
    output_bucket="output-bucket",
    pages={
        "1": {
            "page_id": "1",
            "parsed_text_uri": "s3://bucket/document/pages/1/result.json",
            "image_uri": "s3://bucket/document/pages/1/image.jpg",
            "raw_text_uri": "s3://bucket/document/pages/1/rawText.json"
        }
    }
)

# Classify the document using SageMaker
document = service.classify_document(document)

# Access classification results from the Document
print(f"Document status: {document.status}")
for page_id, page in document.pages.items():
    print(f"Page {page_id} classified as: {page.classification}")
```

### Legacy Method (Still Supported)

```python
# Classify a single page
page_result = service.classify_page(
    page_id="1",
    text_uri="s3://bucket/document/pages/1/result.json",
    image_uri="s3://bucket/document/pages/1/image.jpg"
)

# Print the classification result
print(f"Page classified as: {page_result.classification.doc_type}")

# Classify multiple pages concurrently
pages = {
    "1": {"parsedTextUri": "s3://bucket/document/pages/1/result.json", "imageUri": "s3://bucket/document/pages/1/image.jpg"},
    "2": {"parsedTextUri": "s3://bucket/document/pages/2/result.json", "imageUri": "s3://bucket/document/pages/2/image.jpg"}
}

result = service.classify_pages(pages)

# Print the sections
for section in result.sections:
    print(f"Section {section.section_id}: {section.classification.doc_type}")
    for page in section.pages:
        print(f"  - Page {page.page_id}")

# Convert to dictionary for API response
api_response = result.to_dict()
```

## Configuration

The classification service uses the following configuration structure:

```json
{
  "model_id": "anthropic.claude-3-sonnet-20240229-v1:0", // Top-level model_id for Bedrock (optional)
  "sagemaker_endpoint_name": "udop-classification-endpoint", // SageMaker endpoint name (optional)
  "classes": [
    {
      "name": "invoice",
      "description": "An invoice that specifies an amount of money to be paid."
    },
    {
      "name": "financial_statement",
      "description": "Documents that summarize financial performance, such as income statements, balance sheets, or cash flow statements."
    }
  ],
  "classification": {
    "model": "anthropic.claude-3-sonnet-20240229-v1:0", // Specific model for classification (used if top-level model_id not specified)
    "temperature": 0,
    "top_k": 0.5,
    "system_prompt": "You are a document classification expert...",
    "task_prompt": "Classify the following document into one of these types: {CLASS_NAMES_AND_DESCRIPTIONS}...\n\nDocument text:\n{DOCUMENT_TEXT}"
  }
}
```

## Integration with Lambda Functions

### Using with Bedrock Backend

```python
from idp_common import classification, get_config
from idp_common.models import Document, Status

def handler(event, context):
    # Extract document from event
    document = Document.from_dict(event["OCRResult"]["document"])
       
    # Initialize classification service
    config = get_config()
    service = classification.ClassificationService(config=config) 
    
    # Classify document
    document = service.classify_document(document)
    
    # Return response
    return {
        "document": document.to_dict()
    }
```

### Using with SageMaker Backend

```python
from idp_common import classification, get_config
from idp_common.models import Document, Status
import os

def handler(event, context):
    # Extract document from event
    document = Document.from_dict(event["OCRResult"]["document"])
    
    # Configure SageMaker endpoint
    config = get_config() or {}
    config["sagemaker_endpoint_name"] = os.environ["SAGEMAKER_ENDPOINT_NAME"]
    
    # Initialize classification service with SageMaker backend
    service = classification.ClassificationService(
        config=config,
        backend="sagemaker"
    )
    
    # Classify document using SageMaker
    document = service.classify_document(document)
    
    # Return response
    return {
        "document": document.to_dict()
    }
```

## Data Models

- `DocumentType`: Definition of a document type with name and description
- `DocumentClassification`: Classification result with document type and confidence
- `PageClassification`: Classification result for a single page
- `DocumentSection`: A section of consecutive pages with the same classification
- `ClassificationResult`: Overall result of a classification operation
- `Document`: Core document data model used throughout the IDP pipeline

## Backend Options

### Bedrock Backend

The Bedrock backend uses Amazon Bedrock LLMs to classify documents:

- Supports multiple model options (Claude, Titan, etc.)
- Works with both text and image content 
- Uses natural language understanding for classification
- Configurable system prompts and parameters

### SageMaker Backend

The SageMaker backend uses custom UDOP (Unified Document Processing) models:

- Uses vision-language models specifically trained for document understanding
- Requires both image and raw text URIs to be available
- Better performance for document-specific classification tasks
- Requires a deployed SageMaker endpoint

## Future Enhancements

- ✅ Support for SageMaker UDOP models
- ✅ Direct integration with Document data model
- ✅ Improved error handling and retry mechanisms
- 🔲 Better confidence score estimation
- 🔲 More advanced document structure analysis
- 🔲 Support for additional classification backends (custom models)
- 🔲 Multi-model classification for improved accuracy