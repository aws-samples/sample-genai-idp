# IDP SDK Documentation

The IDP SDK provides programmatic Python access to all IDP Accelerator capabilities with a clean, namespaced API.

## Installation

```bash
# Install from local development
pip install -e ./lib/idp_sdk

# Or with uv
uv pip install -e ./lib/idp_sdk
```

## Quick Start

```python
from idp_sdk import IDPClient

# Create client with stack configuration
client = IDPClient(stack_name="my-idp-stack", region="us-west-2")

# Upload and process a single document
result = client.document.process(file_path="./invoice.pdf")
print(f"Document ID: {result.document_id}, Status: {result.status}")

# Process a batch of documents
batch_result = client.batch.process(source="./documents/")
print(f"Batch: {batch_result.batch_id}, Queued: {batch_result.documents_queued}")

# Check status
status = client.batch.get_status(batch_id=batch_result.batch_id)
print(f"Progress: {status.completed}/{status.total}")
```

## Architecture

The SDK follows a namespaced operation pattern for better organization:

```python
client = IDPClient(stack_name="my-stack")

# Stack operations
client.stack.deploy(...)
client.stack.delete()
client.stack.get_resources()

# Batch operations (multiple documents)
client.batch.process(...)
client.batch.reprocess(...)
client.batch.get_status(...)
client.batch.list()
client.batch.download_results(...)
client.batch.download_sources(...)
client.batch.delete_documents(...)
client.batch.stop_workflows()

# Document operations (single document)
client.document.process(...)
client.document.get_status(...)
client.document.get_metadata(...)
client.document.list(...)
client.document.download_results(...)
client.document.download_source(...)
client.document.reprocess(...)
client.document.delete(...)

# Evaluation operations (baseline comparison)
client.evaluation.create_baseline(...)
client.evaluation.get_report(...)
client.evaluation.get_metrics(...)
client.evaluation.list_baselines(...)
client.evaluation.delete_baseline(...)

# Assessment operations (quality metrics)
client.assessment.get_confidence(...)
client.assessment.get_geometry(...)
client.assessment.get_metrics(...)

# Search operations (knowledge base)
client.search.query(...)

# Configuration operations
client.config.create(...)
client.config.validate(...)
client.config.upload(...)
client.config.download(...)
client.config.list(...)
client.config.activate(...)
client.config.delete(...)

# Manifest operations
client.manifest.generate(...)
client.manifest.validate(...)

# Testing operations
client.testing.load_test(...)
```

## Client Initialization

```python
from idp_sdk import IDPClient

# With stack name (for stack-dependent operations)
client = IDPClient(stack_name="my-stack", region="us-west-2")

# Without stack (for stack-independent operations)
client = IDPClient()

# Stack can be set later
client.stack_name = "new-stack"
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `stack_name` | str | No | CloudFormation stack name |
| `region` | str | No | AWS region (defaults to boto3 default) |

---

## Document Operations

Operations for processing individual documents.

### document.process()

Process a single document (upload and queue for processing).

**Parameters:**
- `file_path` (str, required): Path to local file to upload
- `document_id` (str, optional): Custom document ID (defaults to filename without extension)
- `stack_name` (str, optional): Stack name override

**Returns:** `DocumentUploadResult` with `document_id`, `status`, and `timestamp`

```python
result = client.document.process(
    file_path="/path/to/invoice.pdf",
    document_id="custom-id"  # Optional
)

print(f"Document ID: {result.document_id}")
print(f"Status: {result.status}")  # "queued"
print(f"Timestamp: {result.timestamp}")
```

### document.get_status()

Get processing status for a single document.

**Parameters:**
- `document_id` (str, required): Document identifier (S3 key format: batch-id/filename)
- `stack_name` (str, optional): Stack name override

**Returns:** `DocumentStatus` with processing information including status, duration, pages, sections, and errors

```python
status = client.document.get_status(document_id="batch-123/invoice.pdf")

print(f"Status: {status.status.value}")
print(f"Pages: {status.num_pages}")
print(f"Duration: {status.duration_seconds}s")
```

### document.download_results()

Download processing results (processed outputs) from OutputBucket for a single document.

**Parameters:**
- `document_id` (str, required): Document identifier (S3 key)
- `output_dir` (str, required): Local directory to save results
- `file_types` (list[str], optional): File types to download - "pages", "sections", "summary", "evaluation" (defaults to all)
- `stack_name` (str, optional): Stack name override

**Returns:** `DocumentDownloadResult` with `document_id`, `files_downloaded`, and `output_dir`

```python
result = client.document.download_results(
    document_id="batch-123/invoice.pdf",
    output_dir="./results",
    file_types=["pages", "sections", "summary"]  # Optional
)

print(f"Downloaded {result.files_downloaded} files")
```

### document.download_source()

Download original document source file from InputBucket.

**Parameters:**
- `document_id` (str, required): Document identifier (S3 key)
- `output_path` (str, required): Local file path to save document
- `stack_name` (str, optional): Stack name override

**Returns:** `str` - Local file path where document was saved

```python
file_path = client.document.download_source(
    document_id="batch-123/invoice.pdf",
    output_path="./downloads/invoice.pdf"
)

print(f"Downloaded to: {file_path}")
```

### document.reprocess()

Reprocess a single document from a specific pipeline step.

**Parameters:**
- `document_id` (str, required): Document identifier (S3 key)
- `step` (str or RerunStep, required): Pipeline step to reprocess from (e.g., "classification", "extraction", RerunStep.EXTRACTION)
- `stack_name` (str, optional): Stack name override

**Returns:** `DocumentReprocessResult` with `document_id`, `step`, and `queued` status

```python
from idp_sdk import RerunStep

result = client.document.reprocess(
    document_id="batch-123/invoice.pdf",
    step=RerunStep.EXTRACTION
)

print(f"Queued: {result.queued}")
```

### document.delete()

Permanently delete a single document and all associated data from InputBucket, OutputBucket, and DynamoDB.

**Parameters:**
- `document_id` (str, required): Document identifier (S3 key)
- `stack_name` (str, optional): Stack name override
- `dry_run` (bool, optional): If True, simulate deletion without actually deleting (default: False)

**Returns:** `DocumentDeletionResult` with `success`, `object_key`, `deleted` (dict of deleted items), and `errors`

```python
result = client.document.delete(
    document_id="batch-123/invoice.pdf",
    dry_run=False
)

print(f"Success: {result.success}")
print(f"Deleted: {result.deleted}")
```

### document.list()

List processed documents with pagination support.

**Parameters:**
- `limit` (int, optional): Maximum number of documents to return (default: 100)
- `next_token` (str, optional): Pagination token from previous request
- `stack_name` (str, optional): Stack name override

**Returns:** `DocumentListResult` with `documents` (list of DocumentInfo), `count`, and optional `next_token`

```python
# List documents
result = client.document.list(limit=50)

for doc in result.documents:
    print(f"{doc.document_id}: {doc.status}")

# Pagination
if result.next_token:
    next_page = client.document.list(limit=50, next_token=result.next_token)
```

### document.get_metadata()

Get extracted metadata and fields for a processed document.

**Parameters:**
- `document_id` (str, required): Document identifier (S3 key)
- `section_id` (int, optional): Section number (default: 1)
- `stack_name` (str, optional): Stack name override

**Returns:** `DocumentMetadata` with `document_id`, `section_id`, `document_class`, `fields`, `confidence`, `page_count`, and `metadata`

```python
metadata = client.document.get_metadata(document_id="batch-123/invoice.pdf")

print(f"Document Type: {metadata.document_class}")
print(f"Confidence: {metadata.confidence:.2%}")
print(f"Fields:")
for field_name, field_value in metadata.fields.items():
    print(f"  {field_name}: {field_value}")

# Access specific fields
invoice_number = metadata.fields.get("invoice_number")
total_amount = metadata.fields.get("total_amount")
```

---

## Batch Operations

Operations for processing multiple documents.

### batch.process()

Process multiple documents through the IDP pipeline.

**Parameters:**
- `source` (str, optional): Auto-detected source - directory path, manifest file, or S3 URI
- `manifest` (str, optional): Path to manifest CSV file
- `directory` (str, optional): Local directory path
- `s3_uri` (str, optional): S3 URI (s3://bucket/prefix/)
- `test_set` (str, optional): Test set identifier
- `batch_prefix` (str, optional): Batch ID prefix (default: "sdk-batch")
- `file_pattern` (str, optional): File pattern for filtering (default: "*.pdf")
- `recursive` (bool, optional): Recursively process subdirectories (default: True)
- `number_of_files` (int, optional): Limit number of files to process
- `config_path` (str, optional): Path to custom configuration file
- `stack_name` (str, optional): Stack name override

**Returns:** `BatchResult` with `batch_id`, `document_ids`, `queued`, `uploaded`, `failed`, and `timestamp`

```python
# From directory
result = client.batch.process(source="./documents/")

# From manifest
result = client.batch.process(source="./manifest.csv")

# From S3
result = client.batch.process(source="s3://bucket/path/")

# With options
result = client.batch.process(
    source="./documents/",
    batch_prefix="my-batch",
    file_pattern="*.pdf",
    recursive=True,
    number_of_files=10,
    config_path="./config.yaml"
)

print(f"Batch ID: {result.batch_id}")
print(f"Documents queued: {result.queued}")
```

### batch.get_status()

Get processing status for all documents in a batch.

**Parameters:**
- `batch_id` (str, required): Batch identifier
- `stack_name` (str, optional): Stack name override

**Returns:** `BatchStatus` with `batch_id`, `documents` (list of DocumentStatus), `total`, `completed`, `failed`, `in_progress`, `queued`, `success_rate`, and `all_complete`

```python
status = client.batch.get_status(batch_id="batch-20250123-123456")

print(f"Total: {status.total}")
print(f"Completed: {status.completed}")
print(f"Failed: {status.failed}")
print(f"Success Rate: {status.success_rate:.1%}")

for doc in status.documents:
    print(f"  {doc.document_id}: {doc.status.value}")
```

### batch.list()

List recent batch processing jobs with pagination support.

**Parameters:**
- `limit` (int, optional): Maximum number of batches to return (default: 10)
- `next_token` (str, optional): Pagination token from previous request
- `stack_name` (str, optional): Stack name override

**Returns:** `BatchListResult` with `batches` (list of BatchInfo), `count`, and optional `next_token`

```python
# List recent batches
result = client.batch.list(limit=20)

for batch in result.batches:
    print(f"{batch.batch_id}: {batch.queued} docs, {batch.timestamp}")

# Pagination
if result.next_token:
    next_page = client.batch.list(limit=20, next_token=result.next_token)

# Iterate directly (backward compatible)
for batch in result:
    print(f"{batch.batch_id}")
```

### batch.download_results()

Download processing results (processed outputs) from OutputBucket for all documents in a batch.

**Parameters:**
- `batch_id` (str, required): Batch identifier
- `output_dir` (str, required): Local directory to save results
- `file_types` (list[str], optional): File types to download - "pages", "sections", "summary", "evaluation", or "all" (default: ["all"])
- `stack_name` (str, optional): Stack name override

**Returns:** `BatchDownloadResult` with `files_downloaded`, `documents_downloaded`, and `output_dir`

```python
result = client.batch.download_results(
    batch_id="batch-20250123-123456",
    output_dir="./results",
    file_types=["summary", "sections"]
)

print(f"Downloaded {result.files_downloaded} files")
```

### batch.download_sources()

Download original source files from InputBucket for all documents in a batch.

**Parameters:**
- `batch_id` (str, required): Batch identifier
- `output_dir` (str, required): Local directory to save source files
- `stack_name` (str, optional): Stack name override

**Returns:** `BatchDownloadResult` with `files_downloaded`, `documents_downloaded`, and `output_dir`

```python
result = client.batch.download_sources(
    batch_id="batch-20250123-123456",
    output_dir="./source_files"
)

print(f"Downloaded {result.files_downloaded} source files")
```

### batch.delete_documents()

Permanently delete all documents in a batch and their associated data from InputBucket, OutputBucket, and DynamoDB.

**Parameters:**
- `batch_id` (str, required): Batch identifier
- `status_filter` (str, optional): Filter by document status (e.g., "FAILED", "COMPLETED")
- `stack_name` (str, optional): Stack name override
- `dry_run` (bool, optional): If True, simulate deletion without actually deleting (default: False)
- `continue_on_error` (bool, optional): Continue deleting if one document fails (default: True)

**Returns:** `BatchDeletionResult` with `success`, `deleted_count`, `failed_count`, `total_count`, `dry_run`, and `results` (list of DocumentDeletionResult)

```python
# Delete entire batch
result = client.batch.delete_documents(batch_id="batch-123")

# Delete with status filter
result = client.batch.delete_documents(
    batch_id="batch-123",
    status_filter="FAILED"
)

# Dry run
result = client.batch.delete_documents(
    batch_id="batch-123",
    dry_run=True
)

print(f"Deleted: {result.deleted_count}/{result.total_count}")
```

### batch.reprocess()

Reprocess existing documents from a specific pipeline step.

**Parameters:**
- `step` (str or RerunStep, required): Pipeline step to reprocess from (e.g., "classification", "extraction", RerunStep.EXTRACTION)
- `document_ids` (list[str], optional): Specific document IDs to reprocess
- `batch_id` (str, optional): Batch ID to reprocess all documents in batch
- `stack_name` (str, optional): Stack name override

**Note:** Must specify either `document_ids` or `batch_id`

**Returns:** `BatchReprocessResult` with `documents_queued`, `documents_failed`, `failed_documents`, and `step`

```python
from idp_sdk import RerunStep

# Reprocess batch
result = client.batch.reprocess(
    step=RerunStep.EXTRACTION,
    batch_id="batch-20250123-123456"
)

# Reprocess specific documents
result = client.batch.reprocess(
    step="classification",
    document_ids=["batch/doc1.pdf", "batch/doc2.pdf"]
)

print(f"Queued: {result.documents_queued}")
```

### batch.stop_workflows()

Stop all running Step Functions workflows and purge the SQS queue.

**Parameters:**
- `stack_name` (str, optional): Stack name override
- `skip_purge` (bool, optional): Skip purging the SQS queue (default: False)
- `skip_stop` (bool, optional): Skip stopping executions (default: False)

**Returns:** `StopWorkflowsResult` with `executions_stopped`, `documents_aborted`, and `queue_purged`

```python
result = client.batch.stop_workflows()

print(f"Queue purged: {result.queue_purged}")
print(f"Executions stopped: {result.executions_stopped}")
```

---

## Evaluation Operations

Operations for baseline comparison and accuracy measurement.

### evaluation.create_baseline()

Create evaluation baseline for a document to enable automated accuracy testing.

**Parameters:**
- `document_id` (str, required): Document identifier (S3 key)
- `baseline_data` (dict, required): Expected extraction results with sections and fields
- `metadata` (dict, optional): Optional metadata (created_by, purpose, etc.)
- `stack_name` (str, optional): Stack name override

**Returns:** `dict` with baseline creation result

```python
baseline = {
    "sections": [
        {
            "section_id": 1,
            "document_class": "invoice",
            "fields": {
                "invoice_number": "INV-12345",
                "total_amount": "1250.00",
                "invoice_date": "2024-01-15"
            }
        }
    ]
}

result = client.evaluation.create_baseline(
    document_id="test-invoice-001.pdf",
    baseline_data=baseline,
    metadata={"created_by": "qa_team"}
)
```

### evaluation.get_report()

Get evaluation report comparing extraction results to baseline.

**Parameters:**
- `document_id` (str, required): Document identifier (S3 key)
- `section_id` (int, optional): Section number (default: 1)
- `stack_name` (str, optional): Stack name override

**Returns:** `EvaluationReport` with `document_id`, `section_id`, `accuracy`, `field_results`, and `summary`

```python
report = client.evaluation.get_report(document_id="test-invoice-001.pdf")

print(f"Accuracy: {report.accuracy:.1%}")

for field, result in report.field_results.items():
    if result['match']:
        print(f"✓ {field}: {result['extracted']}")
    else:
        print(f"✗ {field}: expected '{result['expected']}', got '{result['extracted']}'")
```

### evaluation.get_metrics()

Get aggregated evaluation metrics across multiple documents.

**Parameters:**
- `start_date` (str, optional): Filter by start date (ISO format: "2024-01-15")
- `end_date` (str, optional): Filter by end date (ISO format: "2024-01-31")
- `document_class` (str, optional): Filter by document type (e.g., "invoice")
- `batch_id` (str, optional): Filter by batch identifier
- `stack_name` (str, optional): Stack name override

**Returns:** `EvaluationMetrics` with `total_evaluations`, `average_accuracy`, and `by_document_class`

```python
metrics = client.evaluation.get_metrics(
    start_date="2024-01-01",
    end_date="2024-01-31"
)

print(f"Total evaluations: {metrics.total_evaluations}")
print(f"Average accuracy: {metrics.average_accuracy:.1%}")

for doc_class, accuracy in metrics.by_document_class.items():
    print(f"{doc_class}: {accuracy:.1%}")
```

### evaluation.list_baselines()

List evaluation baselines with pagination support.

**Parameters:**
- `limit` (int, optional): Maximum number of baselines to return (default: 100)
- `next_token` (str, optional): Pagination token from previous request
- `stack_name` (str, optional): Stack name override

**Returns:** `EvaluationBaselineListResult` with `baselines`, `count`, and optional `next_token`

```python
result = client.evaluation.list_baselines(limit=50)

for baseline in result.baselines:
    print(f"{baseline['document_id']}: {baseline['created_at']}")

if result.next_token:
    next_page = client.evaluation.list_baselines(limit=50, next_token=result.next_token)
```

### evaluation.delete_baseline()

Delete evaluation baseline for a document.

**Parameters:**
- `document_id` (str, required): Document identifier (S3 key)
- `stack_name` (str, optional): Stack name override

**Returns:** `dict` with deletion result

```python
result = client.evaluation.delete_baseline(document_id="test-invoice-001.pdf")
print(f"Deleted: {result['success']}")
```

---

## Assessment Operations

Operations for quality metrics and confidence scoring.

### assessment.get_confidence()

Get confidence scores for all extracted fields in a document section.

**Parameters:**
- `document_id` (str, required): Document identifier (S3 key)
- `section_id` (int, optional): Section number (default: 1)
- `stack_name` (str, optional): Stack name override

**Returns:** `AssessmentConfidenceResult` with `document_id`, `section_id`, and `attributes` (dict of AssessmentFieldConfidence)

**AssessmentFieldConfidence fields:**
- `confidence`: Float 0.0-1.0 (e.g., 0.95 = 95% confident)
- `confidence_threshold`: Minimum acceptable confidence from config
- `meets_threshold`: Boolean indicating if confidence is acceptable
- `reason`: Explanation for the confidence level

```python
confidence = client.assessment.get_confidence(document_id="batch-001/invoice.pdf")

# Check if any fields need review
low_conf_fields = [
    field for field, attr in confidence.attributes.items()
    if not attr.meets_threshold
]

if low_conf_fields:
    print(f"Review needed for: {', '.join(low_conf_fields)}")

# Get confidence for specific field
total_amount = confidence.attributes.get("total_amount")
if total_amount:
    print(f"Total amount confidence: {total_amount.confidence:.2%}")
    print(f"Meets threshold: {total_amount.meets_threshold}")
```

### assessment.get_geometry()

Get bounding box coordinates for all extracted fields in a document section.

**Parameters:**
- `document_id` (str, required): Document identifier (S3 key)
- `section_id` (int, optional): Section number (default: 1)
- `stack_name` (str, optional): Stack name override

**Returns:** `AssessmentGeometryResult` with `document_id`, `section_id`, and `attributes` (dict of AssessmentFieldGeometry)

**AssessmentFieldGeometry fields:**
- `page`: Page number where field was found (1-indexed)
- `bbox`: Normalized bounding box [left, top, width, height] (0.0-1.0)
- `bounding_box`: Absolute pixel coordinates {Left, Top, Width, Height}

```python
geometry = client.assessment.get_geometry(document_id="batch-001/invoice.pdf")

# Highlight fields in document viewer
for field_name, geo in geometry.attributes.items():
    print(f"{field_name} found on page {geo.page}")
    # Draw rectangle at normalized coordinates
    draw_highlight(
        page=geo.page,
        left=geo.bbox[0],
        top=geo.bbox[1],
        width=geo.bbox[2],
        height=geo.bbox[3]
    )
```

### assessment.get_metrics()

Get aggregated quality metrics across multiple documents.

**Parameters:**
- `start_date` (str, optional): Filter by start date (ISO format: "2024-01-15")
- `end_date` (str, optional): Filter by end date (ISO format: "2024-01-31")
- `document_class` (str, optional): Filter by document type (e.g., "invoice")
- `batch_id` (str, optional): Filter by batch identifier
- `stack_name` (str, optional): Stack name override

**Returns:** `dict` with aggregated metrics

```python
metrics = client.assessment.get_metrics(
    start_date="2024-01-15",
    end_date="2024-01-15"
)

print(f"Processed: {metrics['total_documents']} documents")
print(f"Avg confidence: {metrics['average_confidence']:.2%}")
print(f"SLA compliance: {metrics['threshold_compliance']:.2%}")
```

---

## Search Operations

Operations for knowledge base queries and semantic search.

### search.query()

Query knowledge base with natural language questions.

**Parameters:**
- `question` (str, required): Natural language question
- `document_ids` (list[str], optional): Limit search to specific documents
- `limit` (int, optional): Maximum number of results to return (default: 10)
- `next_token` (str, optional): Pagination token from previous request
- `stack_name` (str, optional): Stack name override

**Returns:** `SearchResult` with `answer`, `confidence`, `citations`, and optional `next_token`

```python
# Ask a question
result = client.search.query(
    question="What is the total amount on invoice INV-12345?"
)

print(f"Answer: {result.answer}")
print(f"Confidence: {result.confidence:.1%}")

for citation in result.citations:
    print(f"Source: {citation.document.document_id}")
    print(f"Page: {citation.document.page}")
    print(f"Text: {citation.text}")

# Search within specific documents
result = client.search.query(
    question="What is the vendor name?",
    document_ids=["batch-001/invoice1.pdf", "batch-001/invoice2.pdf"]
)
```

---

## Stack Operations

Operations for deploying and managing IDP stacks.

### stack.deploy()

Deploy or update an IDP stack.

```python
from idp_sdk import Pattern

result = client.stack.deploy(
    stack_name="my-new-stack",
    pattern=Pattern.PATTERN_2,
    admin_email="admin@example.com",
    max_concurrent=100,
    wait=True
)

if result.success:
    print(f"Stack deployed: {result.stack_name}")
    print(f"Outputs: {result.outputs}")
```

### stack.delete()

Delete an IDP stack.

```python
result = client.stack.delete(
    empty_buckets=True,
    force_delete_all=False,
    wait=True
)

print(f"Status: {result.status}")
```

### stack.get_resources()

Get stack resource information.

```python
resources = client.stack.get_resources()

print(f"Input Bucket: {resources.input_bucket}")
print(f"Output Bucket: {resources.output_bucket}")
print(f"Queue URL: {resources.document_queue_url}")
```

---

## Configuration Operations

Operations for managing IDP configurations.

### config.create()

Generate an IDP configuration template.

```python
result = client.config.create(
    features="min",           # min, core, all, or comma-separated
    pattern="pattern-2",
    output="config.yaml",
    include_prompts=False,
    include_comments=True
)

print(result.yaml_content)
```

### config.validate()

Validate a configuration file.

```python
result = client.config.validate(
    config_file="./config.yaml",
    pattern="pattern-2"
)

if result.valid:
    print("Configuration is valid")
else:
    for error in result.errors:
        print(f"Error: {error}")
```

### config.upload()

Upload configuration to a deployed stack.

```python
result = client.config.upload(
    config_file="./my-config.yaml",
    validate=True
)

if result.success:
    print("Configuration uploaded")
```

### config.download()

Download configuration from a deployed stack.

```python
result = client.config.download(
    output="downloaded-config.yaml",
    format="minimal"  # "full" or "minimal"
)

print(result.yaml_content)
```

### config.list()

List all configuration versions in a deployed stack.

```python
result = client.config.list()

print(f"Found {result['count']} versions:")
for version in result['versions']:
    status = " (ACTIVE)" if version.get('isActive') else ""
    print(f"  - {version['versionName']}{status}")
```

### config.activate()

Activate a configuration version.

```python
result = client.config.activate("v2")

if result["success"]:
    print(f"Activated version: {result['activated_version']}")
else:
    print(f"Failed to activate: {result['error']}")
```

### config.delete()

Delete a configuration version.

```python
result = client.config.delete("old-version")

if result["success"]:
    print(f"Deleted version: {result['deleted_version']}")
else:
    print(f"Failed to delete: {result['error']}")
```

**Note:** Cannot delete 'default' or currently active versions.

---

## Manifest Operations

Operations for manifest generation and validation.

### manifest.generate()

Generate a manifest file from a directory or S3 URI.

```python
result = client.manifest.generate(
    directory="./documents/",
    baseline_dir="./baselines/",
    output="manifest.csv",
    file_pattern="*.pdf",
    recursive=True
)

print(f"Documents: {result.document_count}")
print(f"Baselines matched: {result.baselines_matched}")
```

### manifest.validate()

Validate a manifest file.

```python
result = client.manifest.validate(manifest_path="./manifest.csv")

if result.valid:
    print(f"Valid manifest with {result.document_count} documents")
else:
    print(f"Invalid: {result.error}")
```

---

## Testing Operations

Operations for load testing and performance validation.

### testing.load_test()

Run load testing.

```python
result = client.testing.load_test(
    source_file="./sample.pdf",
    rate=100,              # Files per minute
    duration=5,            # Duration in minutes
    dest_prefix="load-test"
)

print(f"Total files: {result.total_files}")
```

---

## Response Models

All operations return typed Pydantic models:

```python
from idp_sdk import (
    # Document models
    DocumentUploadResult,
    DocumentStatus,
    DocumentDownloadResult,
    DocumentReprocessResult,
    DocumentDeletionResult,
    DocumentMetadata,
    DocumentInfo,
    DocumentListResult,
    
    # Batch models
    BatchResult,
    BatchProcessResult,
    BatchStatus,
    BatchInfo,
    BatchListResult,
    BatchReprocessResult,
    BatchDownloadResult,
    BatchDeletionResult,
    
    # Evaluation models
    EvaluationReport,
    EvaluationMetrics,
    EvaluationBaselineListResult,
    
    # Assessment models
    AssessmentConfidenceResult,
    AssessmentFieldConfidence,
    AssessmentGeometryResult,
    AssessmentFieldGeometry,
    
    # Search models
    SearchResult,
    SearchCitation,
    SearchDocumentReference,
    
    # Stack models
    StackDeploymentResult,
    StackDeletionResult,
    StackResources,
    
    # Config models
    ConfigCreateResult,
    ConfigValidationResult,
    ConfigUploadResult,
    ConfigDownloadResult,
    
    # Manifest models
    ManifestResult,
    ManifestValidationResult,
    
    # Testing models
    LoadTestResult,
    StopWorkflowsResult,
    
    # Enums
    DocumentState,
    Pattern,
    RerunStep,
    StackState,
    
    # Exceptions
    IDPError,
    IDPConfigurationError,
    IDPStackError,
    IDPProcessingError,
    IDPResourceNotFoundError,
    IDPValidationError,
    IDPTimeoutError,
)
```

---

## Error Handling

```python
from idp_sdk import IDPClient, IDPProcessingError, IDPResourceNotFoundError

client = IDPClient(stack_name="my-stack")

try:
    result = client.document.process(file_path="./invoice.pdf")
except IDPProcessingError as e:
    print(f"Processing error: {e}")
except IDPResourceNotFoundError as e:
    print(f"Resource not found: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
```

---

## Complete Example

```python
from idp_sdk import IDPClient, RerunStep
import time

# Initialize client
client = IDPClient(stack_name="my-idp-stack", region="us-west-2")

# Upload single document
doc_result = client.document.process(file_path="./invoice.pdf")
doc_id = doc_result.document_id

# Monitor document processing
while True:
    status = client.document.get_status(document_id=doc_id)
    print(f"Status: {status.status.value}")
    
    if status.status.value in ["COMPLETED", "FAILED"]:
        break
    
    time.sleep(5)

# Download results if successful
if status.status.value == "COMPLETED":
    client.document.download_results(
        document_id=doc_id,
        output_dir="./results"
    )
    print("Results downloaded successfully")

# Process a batch
batch_result = client.batch.process(source="./documents/")
batch_id = batch_result.batch_id

# Monitor batch progress
while True:
    batch_status = client.batch.get_status(batch_id=batch_id)
    print(f"Progress: {batch_status.completed}/{batch_status.total}")
    
    if batch_status.all_complete:
        break
    
    time.sleep(10)

# Download batch results
client.batch.download_results(
    batch_id=batch_id,
    output_dir="./batch_results"
)

print(f"Batch complete! Success rate: {batch_status.success_rate:.1%}")
```

---

## See Also

- [IDP CLI Documentation](./idp-cli.md) - Command-line interface
- [SDK Examples](../lib/idp_sdk/examples/) - Code examples
- [API Reference](../lib/idp_sdk/README.md) - Detailed API documentation
