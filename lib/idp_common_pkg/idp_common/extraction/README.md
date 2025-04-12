# IDP Extraction Module

This module provides functionality for extracting structured information from document sections using LLMs.

## Overview

The extraction module is designed to process document sections, extract key information based on configured attributes, and return structured results. It supports multimodal extraction using both text and images.

## Components

- **ExtractionService**: Main service class for performing extractions
- **Models**: Data classes for extraction results

## Usage

The ExtractionService uses a Document-based approach which simplifies integration with the entire IDP pipeline:

```python
from idp_common import get_config
from idp_common.extraction.service import ExtractionService
from idp_common.models import Document

# Initialize the service with configuration
config = get_config()
extraction_service = ExtractionService(config=config)

# Load your document
document = Document(...)  # Document with sections already classified

# Process a specific section in the document
updated_document = extraction_service.process_document_section(
    document=document,
    section_id="section-123"
)

# Access the extraction results URI from the section
section = next(s for s in updated_document.sections if s.section_id == "section-123")
result_uri = section.extraction_result_uri
print(f"Extraction results stored at: {result_uri}")

# To get the attributes, you would load them from the result URI
# For example:
# extracted_fields = s3.get_json_content(result_uri)
```

### Lambda Function Pattern

For AWS Lambda functions, we recommend using a focused document with only the relevant section:

```python
# Get document and section from event
full_document = Document.from_dict(event.get("document", {}))
section_id = event.get("section", {}).get("section_id", "")

# Find the section - should be present
section = next((s for s in full_document.sections if s.section_id == section_id), None)
if not section:
    raise ValueError(f"Section {section_id} not found in document")

# Filter document to only include this section and its pages
section_document = full_document
section_document.sections = [section]

# Keep only pages needed for this section
needed_pages = {}
for page_id in section.page_ids:
    if page_id in full_document.pages:
        needed_pages[page_id] = full_document.pages[page_id]
section_document.pages = needed_pages

# Process the focused document
extraction_service = ExtractionService(config=CONFIG)
processed_document = extraction_service.process_document_section(
    document=section_document,
    section_id=section_id
)
```

## Configuration

The extraction service uses the following configuration structure:

```json
{
    "extraction": {
        "model": "anthropic.claude-3-sonnet-20240229-v1:0",
        "temperature": 0.0,
        "top_k": 0.5,
        "system_prompt": "You are an expert at extracting information from documents...",
        "task_prompt": "Extract the following fields from this {DOCUMENT_CLASS} document: {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}\n\nDocument text:\n{DOCUMENT_TEXT}"
    },
    "classes": [
        {
            "name": "invoice",
            "description": "An invoice document",
            "attributes": [
                {
                    "name": "invoice_number",
                    "description": "The invoice number or ID"
                },
                {
                    "name": "date",
                    "description": "The invoice date"
                }
            ]
        }
    ]
}
```

## Error Handling

The ExtractionService has built-in error handling:

1. If a section ID is not found in the document, an exception is raised
2. If extraction fails for any reason, the error is captured in `document.errors`
3. All errors are logged for debugging

## Performance Optimization

For optimal performance, especially in serverless environments:

1. Only include the section being processed and its required pages
2. Set clear expectations about document structure and fail fast on violations
3. Use the Document model to track metering data

### Extraction Results Storage

The extraction service stores extraction results in S3 and only includes the S3 URI in the document:

1. Extracted attributes are written to S3 as JSON files
2. Only the S3 URI (`extraction_result_uri`) is included in the document
3. This approach prevents the document from growing too large when extraction results contain many attributes
4. To access the actual attributes, load them from the S3 URI when needed

## Multimodal Extraction

The service supports both text and image inputs:

1. Text content is read from each page's `parsed_text_uri`
2. Images are retrieved from each page's `image_uri`
3. Both are combined in a multimodal prompt to the LLM

## Thread Safety

The extraction service is designed to be thread-safe, supporting concurrent processing of multiple sections in parallel workloads.