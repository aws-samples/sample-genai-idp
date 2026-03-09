Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# IDP Common Core Data Models

This document describes the core data models for the IDP processing pipeline. For a high-level overview of the entire package, see the [main README](../README.md).

## 📑 Module Structure

The IDP Common library provides these main modules:

- **Models**: Core document representation (this document)
- **[Bedrock](bedrock/README.md)**: Utilities for working with Amazon Bedrock LLMs
- **[Classification](classification/README.md)**: Document classification services
- **[Extraction](extraction/README.md)**: Field extraction services
- **[Evaluation](evaluation/README.md)**: Result evaluation tools
- **[Rule Validation](rule_validation/README.md)**: Business rule validation and compliance checking
- **[OCR](ocr/README.md)**: Text extraction using AWS Textract
- **[Summarization](summarization/README.md)**: Document summarization services
- **[BDA](bda/README.md)**: Bedrock Data Automation integration
- **[AppSync](appsync/README.md)**: Document storage through GraphQL API
- **[Reporting](reporting/README.md)**: Analytics data storage

## 🗃️ Key Classes

### Document

The `Document` class is the central data structure for the entire IDP pipeline with automatic compression support for large documents:

```python
@dataclass
class Document:
    """
    Core document type that is passed through the processing pipeline.
    Each processing step enriches this object.
    
    The Document class provides comprehensive support for handling large documents
    in Step Functions workflows through automatic compression and decompression.
    """
    # Core identifiers
    id: Optional[str] = None            # Generated document ID
    input_bucket: Optional[str] = None  # S3 bucket containing the input document
    input_key: Optional[str] = None     # S3 key of the input document
    output_bucket: Optional[str] = None # S3 bucket for processing outputs
    
    # Processing state and timing
    status: Status = Status.QUEUED
    queued_time: Optional[str] = None
    start_time: Optional[str] = None
    completion_time: Optional[str] = None
    workflow_execution_arn: Optional[str] = None
    
    # Document content details
    num_pages: int = 0
    pages: Dict[str, Page] = field(default_factory=dict)
    sections: List[Section] = field(default_factory=list)
    summary: Optional[str] = None
    detailed_summary: Optional[str] = None
    
    # Processing metadata
    metering: Dict[str, Any] = field(default_factory=dict)
    evaluation_report_uri: Optional[str] = None
    evaluation_result: Any = None  # Holds the DocumentEvaluationResult object
    rule_validation_result: Optional[RuleValidationResult] = None  # Holds rule validation results
    errors: List[str] = field(default_factory=list)
```

### Page

The `Page` class represents individual pages within a document:

```python
@dataclass
class Page:
    """Represents a single page in a document."""
    page_id: str
    image_uri: Optional[str] = None
    raw_text_uri: Optional[str] = None
    parsed_text_uri: Optional[str] = None
    text_confidence_uri: Optional[str] = None
    classification: Optional[str] = None
    confidence: float = 0.0
    tables: List[Dict[str, Any]] = field(default_factory=list)
    forms: Dict[str, str] = field(default_factory=dict)
```

**Key URIs:**
- `image_uri`: S3 URI to the page image (JPG format)
- `raw_text_uri`: S3 URI to the raw Textract response (full JSON with all metadata)
- `parsed_text_uri`: S3 URI to the parsed text content (markdown format)
- `text_confidence_uri`: S3 URI to condensed text confidence data (optimized for assessment prompts)

### Section

The `Section` class represents a logical section of the document (typically with a consistent document class):

```python
@dataclass
class Section:
    """Represents a section of pages with the same classification."""
    section_id: str
    classification: str
    confidence: float = 1.0
    page_ids: List[str] = field(default_factory=list)
    extraction_result_uri: Optional[str] = None
    attributes: Optional[Dict[str, Any]] = None
```

### Status

The document processing status is represented by the `Status` enum:

```python
class Status(Enum):
    """Document processing status."""
    QUEUED = "QUEUED"           # Initial state when document is added to queue
    RUNNING = "RUNNING"         # Step function workflow has started
    OCR = "OCR"                 # OCR processing
    CLASSIFYING = "CLASSIFYING" # Document classification
    EXTRACTING = "EXTRACTING"   # Information extraction 
    POSTPROCESSING = "POSTPROCESSING" # Document summarization
    SUMMARIZING = "SUMMARIZING" # Document summarization
    COMPLETED = "COMPLETED"     # All processing completed
    FAILED = "FAILED"           # Processing failed
```

## 📦 Document Compression for Large Documents

The Document class includes automatic compression support to handle large documents that exceed Step Functions payload limits (256KB). This is essential for processing multi-page documents with extensive content.

### Compression Methods

```python
# Automatic compression when document exceeds threshold
compressed_data = document.compress(working_bucket, "processing_step")
# Returns: {"document_id": "...", "s3_uri": "...", "section_ids": [...], "compressed": True}

# Restore full document from compressed data
restored_document = Document.decompress(working_bucket, compressed_data)

# Handle either compressed or regular document data
document = Document.from_compressed_or_dict(data, working_bucket)
```

### Lambda Function Integration Utilities

```python
# Handle input - automatically detects and decompresses if needed
document = Document.load_document(
    event_data=event["document"], 
    working_bucket=working_bucket, 
    logger=logger
)

# Prepare output - automatically compresses if document is large
response_data = document.serialize_document(
    working_bucket=working_bucket, 
    step_name="classification", 
    logger=logger,
    size_threshold_kb=200  # Optional: custom threshold
)
```

### Key Compression Features

- **Automatic Detection**: Utility methods automatically detect compressed vs uncompressed documents
- **Size Threshold**: Configurable compression threshold (default 0KB - always compress)
- **Section Preservation**: Section IDs are preserved in compressed payloads for Step Functions Map operations
- **Transparent Handling**: Lambda functions work seamlessly with both compressed and uncompressed documents
- **S3 Storage**: Compressed documents are stored in `s3://working-bucket/compressed_documents/{document_id}/`

## 🔄 Common Operations

### Document Creation

```python
# Create an empty document
document = Document(
    id="doc-123",
    input_bucket="my-input-bucket",
    input_key="documents/sample.pdf",
    output_bucket="my-output-bucket"
)

# Create from an S3 event
document = Document.from_s3_event(s3_event, output_bucket="my-output-bucket")

# Create from a dictionary
document = Document.from_dict(document_dict)

# Create from a JSON string
document = Document.from_json(document_json_string)

# Create from baseline files in S3
document = Document.from_s3(bucket="baseline-bucket", input_key="documents/sample.pdf")
```

### Document Serialization

```python
# Convert to dictionary
document_dict = document.to_dict()

# Convert to JSON
document_json = document.to_json()
```

## 📄 Working with Sections and Pages

The document model makes it easy to work with sections and pages:

```python
# Get a specific page
page = document.pages["1"]

# Get all pages in a section
section = document.sections[0]
pages = [document.pages[page_id] for page_id in section.page_ids]

# Add a new section
document.sections.append(Section(
    section_id="new-section",
    classification="invoice",
    page_ids=["1", "2", "3"]
))

# Add a new page
document.pages["new-page"] = Page(
    page_id="new-page",
    image_uri="s3://bucket/image.jpg",
    classification="form"
)
```

## 🛠️ Building a Document from Scratch Example

```python
from idp_common.models import Document, Page, Section, Status

# Create an empty document
document = Document(
    id="invoice-123",
    input_bucket="input-bucket",
    input_key="invoices/invoice-123.pdf",
    output_bucket="output-bucket",
    status=Status.RUNNING
)

# Add pages
document.pages["1"] = Page(
    page_id="1",
    image_uri="s3://output-bucket/invoices/invoice-123.pdf/pages/1/image.jpg",
    raw_text_uri="s3://output-bucket/invoices/invoice-123.pdf/pages/1/rawText.json",
    parsed_text_uri="s3://output-bucket/invoices/invoice-123.pdf/pages/1/result.json",
    classification="invoice",
    confidence=0.98
)

document.pages["2"] = Page(
    page_id="2",
    image_uri="s3://output-bucket/invoices/invoice-123.pdf/pages/2/image.jpg",
    raw_text_uri="s3://output-bucket/invoices/invoice-123.pdf/pages/2/rawText.json",
    parsed_text_uri="s3://output-bucket/invoices/invoice-123.pdf/pages/2/result.json",
    classification="invoice",
    confidence=0.97
)

# Update number of pages
document.num_pages = len(document.pages)

# Add a section
document.sections.append(Section(
    section_id="1",
    classification="invoice",
    confidence=0.98,
    page_ids=["1", "2"],
    extraction_result_uri="s3://output-bucket/invoices/invoice-123.pdf/sections/1/result.json"
))
```

## 📊 Loading a Document for Evaluation Example

```python
from idp_common.models import Document

# Load actual document from processing results
actual_document = Document.from_dict(processed_result["document"])

# Load expected document from baseline files
expected_document = Document.from_s3(
    bucket="baseline-bucket",
    input_key=actual_document.input_key
)

# Now both documents can be compared for evaluation
```

## 🔗 Integration with Services

The document model integrates with all IDP services:

```python
from idp_common import ocr, classification, extraction, evaluation, rule_validation, appsync

# OCR Processing
ocr_service = ocr.OcrService()
document = ocr_service.process_document(document)

# Document Classification
classification_service = classification.ClassificationService(config=config)
document = classification_service.classify_document(document)

# Field Extraction
extraction_service = extraction.ExtractionService(config=config)
document = extraction_service.process_document_section(document, section_id="1")

# Rule Validation
rule_validation_service = rule_validation.RuleValidationService(config=config)
document = rule_validation_service.validate_document(document)

# Rule Validation Orchestration
orchestrator = rule_validation.RuleValidationOrchestratorService(config=config)
document = orchestrator.consolidate_and_save(document, config=config, multiple_sections=True)

# Document Evaluation
evaluation_service = evaluation.EvaluationService(config=config)
document = evaluation_service.evaluate_document(document, expected_document)

# Document Class Discovery (generates JSON Schema for new document types)
from idp_common.discovery.classes_discovery import ClassesDiscovery
discovery = ClassesDiscovery(input_bucket="bucket", input_prefix="doc.pdf", region="us-west-2")
# With local file bytes (no S3 read):
result = discovery.discovery_classes_with_document(
    input_bucket="local", input_prefix="doc.pdf",
    file_bytes=open("doc.pdf", "rb").read(), save_to_config=False
)
schema = result["schema"]  # JSON Schema dict

# Store in AppSync
appsync_service = appsync.DocumentAppSyncService()
document = appsync_service.update_document(document)
```

## 📝 Best Practices

1. **Always use the Document.load_document() method** to handle input data in Lambda functions
2. **Always use document.serialize_document()** to prepare output data
3. **Keep the Document model as the central data structure** across all processing steps
4. **Store large data in S3** and reference by URI in the Document model
5. **Use Section objects** to group related pages by document type
