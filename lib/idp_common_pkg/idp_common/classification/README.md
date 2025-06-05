Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

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
- **DynamoDB caching for resilient page-level classification**

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
    "top_k": 5,
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

## DynamoDB Caching for Resilient Classification

The classification service now supports optional DynamoDB caching to improve efficiency and resilience when processing documents with multiple pages. This feature addresses throttling scenarios where some pages succeed while others fail, avoiding the need to reclassify already successful pages on retry.

### How It Works

1. **Cache Check**: Before processing, the service checks for cached classification results for the document
2. **Selective Processing**: Only pages without cached results are classified
3. **Exception-Safe Caching**: Successful page results are cached even when other pages fail
4. **Retry Efficiency**: Subsequent retries only process previously failed pages

### Configuration

#### Via Constructor Parameter
```python
from idp_common import classification, get_config

config = get_config()
service = classification.ClassificationService(
    region="us-east-1",
    config=config,
    backend="bedrock",
    cache_table="classification-cache-table"  # Enable caching
)
```

#### Via Environment Variable
```bash
export CLASSIFICATION_CACHE_TABLE=classification-cache-table
```

```python
# Cache table will be automatically detected from environment
service = classification.ClassificationService(
    region="us-east-1",
    config=config,
    backend="bedrock"
)
```

### DynamoDB Table Schema

The cache uses the following DynamoDB table structure:

- **Primary Key (PK)**: `classcache#{document_id}#{workflow_execution_arn}`
- **Sort Key (SK)**: `none`
- **Attributes**:
  - `page_classifications` (String): JSON-encoded successful page results
  - `cached_at` (String): Unix timestamp of cache creation
  - `document_id` (String): Document identifier
  - `workflow_execution_arn` (String): Workflow execution ARN
  - `ExpiresAfter` (Number): TTL attribute for automatic cleanup (24 hours)

#### Example DynamoDB Item
```json
{
  "PK": "classcache#doc-123#arn:aws:states:us-east-1:123456789012:execution:MyWorkflow:abc-123",
  "SK": "none",
  "page_classifications": "{\"1\":{\"doc_type\":\"invoice\",\"confidence\":1.0,\"metadata\":{\"metering\":{...}},\"image_uri\":\"s3://...\",\"text_uri\":\"s3://...\",\"raw_text_uri\":\"s3://...\"},\"2\":{...}}",
  "cached_at": "1672531200",
  "document_id": "doc-123",
  "workflow_execution_arn": "arn:aws:states:us-east-1:123456789012:execution:MyWorkflow:abc-123",
  "ExpiresAfter": 1672617600
}
```

### Benefits

- **Cost Reduction**: Avoids redundant API calls to Bedrock/SageMaker for already-classified pages
- **Improved Resilience**: Handles partial failures gracefully during concurrent processing
- **Faster Retries**: Subsequent attempts only process failed pages, not the entire document
- **Automatic Cleanup**: TTL ensures cache entries don't accumulate indefinitely
- **Thread Safety**: Safe for concurrent page processing within the same document

### Example: Resilient Processing Flow

```python
from idp_common import classification, get_config
from idp_common.models import Document

config = get_config()
service = classification.ClassificationService(
    region="us-east-1",
    config=config,
    backend="bedrock",
    cache_table="classification-cache-table"
)

# Create document with 5 pages
document = Document(
    id="doc-123",
    workflow_execution_arn="arn:aws:states:us-east-1:123456789012:execution:MyWorkflow:abc-123",
    pages={
        "1": {...},
        "2": {...},
        "3": {...},
        "4": {...},
        "5": {...}
    }
)

try:
    # First attempt: pages 1,2,4 succeed, pages 3,5 fail due to throttling
    document = service.classify_document(document)
except Exception as e:
    # Pages 1,2,4 are cached automatically before exception is raised
    print(f"Classification failed: {e}")

try:
    # Retry: only pages 3,5 are processed (1,2,4 loaded from cache)
    document = service.classify_document(document)
    print("Document classified successfully on retry")
except Exception as e:
    print(f"Retry failed: {e}")
```

### Cache Lifecycle

1. **Creation**: Cache entries are created when `classify_document()` completes successfully or encounters exceptions
2. **Retrieval**: Cache is checked at the start of each `classify_document()` call
3. **Update**: Cache entries are updated with new successful results from each processing attempt
4. **Expiration**: Entries automatically expire after 24 hours via DynamoDB TTL

### Important Notes

- Caching only applies to the `classify_document()` method, not individual `classify_page()` calls
- Cache entries are scoped to specific document and workflow execution combinations
- Only successful page classifications (without errors in metadata) are cached
- The cache is transparent - existing code continues to work without modifications

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

## Few Shot Example Feature

The classification service supports few shot learning through example-based prompting. This feature allows you to provide concrete examples of documents with their expected classifications and attribute extractions, significantly improving model accuracy and consistency.

### Overview

Few shot examples work by including reference documents with known classifications and expected attribute values in the prompts sent to the AI model. This helps the model understand the expected format and accuracy requirements for your specific use case.

### Configuration

Few shot examples are configured in the document class definitions within your configuration file:

```yaml
classes:
  - name: letter
    description: "A formal written correspondence..."
    attributes:
      - name: sender_name
        description: "The name of the person who wrote the letter..."
      # ... other attributes
    examples:
      - classPrompt: "This is an example of the class 'letter'"
        name: "Letter1"
        attributesPrompt: |
          expected attributes are:
              "sender_name": "Will E. Clark",
              "sender_address": "206 Maple Street P.O. Box 1056 Murray Kentucky 42071-1056",
              "recipient_name": "The Honorable Wendell H. Ford",
              # ... other expected attributes
        imagePath: "config_library/pattern-2/few_shot_example/example-images/letter1.jpg"
      - classPrompt: "This is an example of the class 'letter'" 
        name: "Letter2"
        attributesPrompt: |
          expected attributes are:
              "sender_name": "William H. W. Anderson",
              # ... other expected attributes
        imagePath: "config_library/pattern-2/few_shot_example/example-images/letter2.png"
```

### Configuration Parameters

Each few shot example includes:

- **classPrompt**: A description identifying this as an example of the document class
- **name**: A unique identifier for the example (for reference and debugging)
- **attributesPrompt**: The expected attribute extraction results in a structured format
- **imagePath**: Path to example document image(s) - supports single files, local directories, or S3 prefixes

#### Image Path Options

The `imagePath` field now supports multiple formats for maximum flexibility:

**Single Image File (Original functionality)**:
```yaml
imagePath: "config_library/pattern-2/few_shot_example/example-images/letter1.jpg"
```

**Local Directory with Multiple Images (New)**:
```yaml
imagePath: "config_library/pattern-2/few_shot_example/example-images/"
```

**S3 Prefix with Multiple Images (New)**:
```yaml
imagePath: "s3://my-config-bucket/few-shot-examples/letter/"
```

**Direct S3 Image URI**:
```yaml
imagePath: "s3://my-config-bucket/few-shot-examples/letter/example1.jpg"
```

When pointing to a directory or S3 prefix, the system automatically:
- Discovers all image files with supported extensions (`.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.tiff`, `.tif`, `.webp`)
- Sorts them alphabetically by filename for consistent ordering
- Includes each image as a separate content item in the few-shot examples
- Gracefully handles individual image loading failures without breaking the entire process

#### Environment Variables for Path Resolution

The system uses these environment variables for resolving relative paths:

- **`CONFIGURATION_BUCKET`**: S3 bucket name for configuration files
  - Used when `imagePath` doesn't start with `s3://`
  - The path is treated as a key within this bucket

- **`ROOT_DIR`**: Root directory for local file resolution
  - Used when `CONFIGURATION_BUCKET` is not set
  - The path is treated as relative to this directory

### Benefits

Using few shot examples provides several advantages:

1. **Improved Accuracy**: Models perform better when given concrete examples
2. **Consistent Formatting**: Examples help ensure consistent output structure
3. **Domain Adaptation**: Examples help models understand domain-specific terminology
4. **Reduced Hallucination**: Examples reduce the likelihood of made-up data
5. **Better Edge Case Handling**: Examples can demonstrate how to handle unusual cases

### Best Practices

When creating few shot examples:

#### 1. Quality over Quantity
- Use 1-3 high-quality examples per document class
- Ensure examples are representative of real-world documents
- Include diverse examples that cover different variations

#### 2. Clear and Complete Examples
```yaml
# Good example - specific and complete
attributesPrompt: |
  expected attributes are:
      "invoice_number": "INV-2024-001",
      "invoice_date": "01/15/2024",
      "vendor_name": "ACME Corp",
      "total_amount": "$1,250.00"

# Avoid incomplete examples
attributesPrompt: |
  expected attributes are:
      "invoice_number": "INV-2024-001"
      # Missing other important attributes
```

#### 3. Handle Null Values Appropriately
```yaml
attributesPrompt: |
  expected attributes are:
      "sender_name": "John Smith",
      "cc": null,  # Explicitly show when fields are not present
      "reference_number": null
```

#### 4. Use Realistic Examples
- Choose examples that represent typical documents in your use case
- Include examples with both common and edge case scenarios
- Ensure image quality is good and text is clearly readable

### Usage with Classification Service

The few shot examples are automatically integrated when using the classification service:

```python
from idp_common import classification, get_config
from idp_common.models import Document

# Load configuration with few shot examples
config = get_config()

# Initialize service - few shot examples are automatically used
service = classification.ClassificationService(
    region="us-east-1", 
    config=config
)

# Examples are automatically included in prompts during classification
document = service.classify_document(document)
```

The service automatically:
1. Loads few shot examples from the configuration
2. Includes them in classification prompts using the `{FEW_SHOT_EXAMPLES}` placeholder
3. Formats examples appropriately for both classification and extraction tasks

### Example Configuration Structure

Here's a complete example showing how few shot examples integrate with document class definitions:

```yaml
classes:
  - name: email
    description: "A digital message with email headers..."
    attributes:
      - name: from_address
        description: "The email address of the sender..."
      - name: to_address  
        description: "The email address of the primary recipient..."
      - name: subject
        description: "The topic of the email..."
      - name: date_sent
        description: "The date and time when the email was sent..."
    examples:
      - classPrompt: "This is an example of the class 'email'"
        name: "Email1"
        attributesPrompt: |
          expected attributes are: 
             "from_address": "john.doe@company.com",
             "to_address": "jane.smith@client.com", 
             "subject": "FW: Meeting Notes 4/20",
             "date_sent": "04/18/2024"
        imagePath: "config_library/pattern-2/few_shot_example/example-images/email1.jpg"

classification:
  task_prompt: |
    Classify this document into exactly one of these categories:
    
    {CLASS_NAMES_AND_DESCRIPTIONS}
    
    <few_shot_examples>
    {FEW_SHOT_EXAMPLES}
    </few_shot_examples>
    
    <document_ocr_data>
    {DOCUMENT_TEXT}
    </document_ocr_data>
```

### Troubleshooting

Common issues and solutions:

1. **Images Not Found**: Ensure image paths are correct and files exist
2. **Inconsistent Results**: Review example quality and ensure they're representative
3. **Poor Performance**: Consider adding more diverse examples or improving example quality
4. **Format Errors**: Ensure attributesPrompt follows exact JSON-like format expected by your prompts

## Future Enhancements

- ✅ Support for SageMaker UDOP models
- ✅ Direct integration with Document data model
- ✅ Improved error handling and retry mechanisms
- ✅ Few shot example support for improved accuracy
- 🔲 Better confidence score estimation
- 🔲 More advanced document structure analysis
- 🔲 Support for additional classification backends (custom models)
- 🔲 Multi-model classification for improved accuracy
- 🔲 Dynamic few shot example selection based on document similarity
