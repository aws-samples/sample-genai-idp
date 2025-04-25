# IDP Common Library

This library provides common utilities and data models for the Intelligent Document Processing (IDP) pipeline.

## Modules

### Models

The core data model for the IDP processing pipeline. The model classes represent documents, pages, and sections as they move through various processing stages.

### Bedrock

Utility functions for working with Amazon Bedrock LLM services, including model invocation, response handling, and prompt preparation.

### Classification

Services for document classification using LLMs.

### Extraction

Services for field extraction from documents using LLMs.

### Evaluation

Tools for evaluating extraction and classification results against baselines.

### OCR

Services for extracting text and structure from documents using AWS Textract.

### Summarization

Services for generating document summaries using LLMs.

### AppSync

Services for storing and retrieving documents through AWS AppSync GraphQL API, with seamless conversion between Document objects and AppSync schema.

## Key Classes

### Document

The `Document` class is the central data structure for the entire IDP pipeline:

```python
@dataclass
class Document:
    """
    Core document type that is passed through the processing pipeline.
    Each processing step enriches this object.
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
    classification: Optional[str] = None
    confidence: float = 0.0
    tables: List[Dict[str, Any]] = field(default_factory=list)
    forms: Dict[str, str] = field(default_factory=dict)
```

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
    STARTED = "STARTED"         # Step function workflow has started
    OCR_COMPLETED = "OCR_COMPLETED"  # OCR processing completed
    CLASSIFIED = "CLASSIFIED"   # Document classification completed
    EXTRACTED = "EXTRACTED"     # Information extraction completed
    SUMMARIZED = "SUMMARIZED"   # Document summarization completed
    PROCESSED = "PROCESSED"     # All processing completed
    FAILED = "FAILED"           # Processing failed
    EVALUATED = "EVALUATED"     # Document has been evaluated against baseline
```

## Common Class Operations

The data model provides common operations for working with documents:

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

## Working with Sections and Pages

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

## Example: Building a Document from Scratch

```python
from idp_common.models import Document, Page, Section, Status

# Create an empty document
document = Document(
    id="invoice-123",
    input_bucket="input-bucket",
    input_key="invoices/invoice-123.pdf",
    output_bucket="output-bucket",
    status=Status.STARTED
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

# Update status
document.status = Status.CLASSIFIED
```

## Example: Loading a Document from Baseline for Evaluation

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

## Working with LLM Prompts

The library provides standardized utilities for working with LLM prompts:

### Format Prompt Templates

The `bedrock.format_prompt` function provides a standard way to replace placeholders in prompt templates:

```python
from idp_common.bedrock import format_prompt

# Template with placeholders
template = """
Classify this document into one of the following types:
{CLASS_NAMES_AND_DESCRIPTIONS}

Document text:
{DOCUMENT_TEXT}
"""

# Substitutions to apply
substitutions = {
    "CLASS_NAMES_AND_DESCRIPTIONS": "Invoice, Receipt, Contract",
    "DOCUMENT_TEXT": "INVOICE #12345\nDate: 2023-05-15\nTotal: $1,250.00"
}

# Required placeholders (will raise ValueError if missing)
required = ["DOCUMENT_TEXT", "CLASS_NAMES_AND_DESCRIPTIONS"]

# Apply substitutions
prompt = format_prompt(template, substitutions, required)
```

This function:
- Validates that required placeholders exist in the template
- Handles replacement in a way that protects against format string vulnerabilities
- Provides consistent behavior across classification, extraction, evaluation, and summarization services

## Service Classes

The library provides several service classes for different document processing tasks:

### OcrService

Processes documents to extract text, tables, and forms using AWS Textract:

```python
from idp_common.ocr.service import OcrService
from idp_common.models import Document

ocr_service = OcrService(
    region="us-east-1",
    enhanced_features=["TABLES", "FORMS"]
)

# Process a document
document = Document(id="doc-123", input_bucket="bucket", input_key="doc.pdf")
processed_document = ocr_service.process_document(document)
```

### ClassificationService

Classifies documents or document pages:

```python
from idp_common.classification.service import ClassificationService

classification_service = ClassificationService(
    region="us-east-1",
    config=config
)

# Classify a document
document = classification_service.classify_document(document)
```

### ExtractionService

Extracts structured information from document sections:

```python
from idp_common.extraction.service import ExtractionService

extraction_service = ExtractionService(
    region="us-east-1",
    config=config
)

# Process a section
document = extraction_service.process_document_section(document, section_id="1")
```

### EvaluationService

Compares extraction results against baseline data:

```python
from idp_common.evaluation.service import EvaluationService

evaluation_service = EvaluationService(
    region="us-east-1",
    config=config
)

# Evaluate a document
evaluated_document = evaluation_service.evaluate_document(
    actual_document=document,
    expected_document=baseline_document
)
```

### SummarizationService

Generates document summaries and creates markdown summary reports:

```python
from idp_common.summarization.service import SummarizationService

summarization_service = SummarizationService(
    region="us-east-1",
    config=config
)

# Get a document summary
document = summarization_service.process_document(document)

# Access the document summary information
print(f"Brief summary: {document.summary}")
print(f"Detailed summary: {document.detailed_summary}")
print(f"Summary report: {document.summary_report_uri}")
```

### DocumentAppSyncService

Manages document storage and retrieval through AWS AppSync:

```python
from idp_common.appsync import DocumentAppSyncService
from idp_common.models import Document, Status

# Create a document
document = Document(
    id="doc-123",
    input_key="documents/sample.pdf",
    status=Status.QUEUED
)

# Initialize the service
appsync_service = DocumentAppSyncService()

# Create document in AppSync with 90-day TTL
ttl = appsync_service.calculate_ttl(days=90)
object_key = appsync_service.create_document(document, expires_after=ttl)

# Later, update the document
document.status = Status.PROCESSED
document.num_pages = 5
updated_document = appsync_service.update_document(document)
```