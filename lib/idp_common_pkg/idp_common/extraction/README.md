Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# IDP Extraction Module

This module provides functionality for extracting structured information from document sections using LLMs with support for few-shot example prompting to improve accuracy.

## Overview

The extraction module is designed to process document sections, extract key information based on configured attributes, and return structured results. It supports multimodal extraction using both text and images, and can leverage concrete examples to improve extraction accuracy and consistency.

## Components

- **ExtractionService**: Main service class for performing extractions with few-shot example support
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
    "top_k": 5,
    "system_prompt": "You are an expert at extracting information from documents...",
    "task_prompt": "Extract the following fields from this {DOCUMENT_CLASS} document: {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}\n\n{FEW_SHOT_EXAMPLES}\n\nDocument text:\n{DOCUMENT_TEXT}"
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

## Few Shot Example Feature

The extraction service supports few-shot learning through example-based prompting. This feature allows you to provide concrete examples of documents with their expected attribute extractions, significantly improving model accuracy, consistency, and reducing hallucination.

### Overview

Few-shot examples work by including reference documents with known expected attribute values in the prompts sent to the AI model. Unlike classification which uses examples from all document classes, extraction uses examples only from the specific class being processed to provide targeted guidance for attribute extraction.

### Key Differences from Classification

- **Example Scope**: Extraction uses examples ONLY from the specific document class being processed (e.g., only "letter" examples when extracting from a "letter" document)
- **Prompt Field**: Uses `attributesPrompt` instead of `classPrompt` from examples
- **Purpose**: Shows expected attribute extraction format and values rather than distinguishing between document types

### Configuration

Few-shot examples are configured in the document class definitions within your configuration file:

```yaml
classes:
  - name: letter
    description: "A formal written correspondence..."
    attributes:
      - name: sender_name
        description: "The name of the person who wrote the letter..."
      - name: sender_address
        description: "The physical address of the sender..."
      - name: recipient_name
        description: "The name of the person receiving the letter..."
      # ... other attributes
    examples:
      - classPrompt: "This is an example of the class 'letter'"
        name: "Letter1"
        attributesPrompt: |
          expected attributes are:
              "sender_name": "Will E. Clark",
              "sender_address": "206 Maple Street P.O. Box 1056 Murray Kentucky 42071-1056",
              "recipient_name": "The Honorable Wendell H. Ford",
              "recipient_address": "United States Senate Washington, D. C. 20510",
              "date": "10/31/1995",
              "subject": null,
              "letter_type": "opposition letter",
              "signature": "Will E. Clark",
              "cc": null,
              "reference_number": "TNJB 0008497"
        imagePath: "config_library/unified/few_shot_example/example-images/letter1.jpg"
      - classPrompt: "This is an example of the class 'letter'"
        name: "Letter2"
        attributesPrompt: |
          expected attributes are:
              "sender_name": "William H. W. Anderson",
              "sender_address": "P O. BOX 12046 CAMERON VILLAGE STATION RALEIGH N. c 27605",
              "recipient_name": "Mr. Addison Y. Yeaman",
              "recipient_address": "1600 West Hill Street Louisville, Kentucky 40201",
              "date": "10/14/1970",
              "subject": "Invitation to the Twelfth Annual Meeting of the TGIC",
              "letter_type": "Invitation",
              "signature": "Bill",
              "cc": null,
              "reference_number": null
        imagePath: "config_library/unified/few_shot_example/example-images/letter2.png"
```

### Configuration Parameters

Each few-shot example includes:

- **classPrompt**: A description identifying this as an example of the document class (used for classification)
- **attributesPrompt**: The expected attribute extraction results showing the exact JSON format and values expected
- **name**: A unique identifier for the example (for reference and debugging)
- **imagePath**: Path to example document image(s) - supports single files, local directories, or S3 prefixes

#### Image Path Options

The `imagePath` field now supports multiple formats for maximum flexibility:

**Single Image File (Original functionality)**:

```yaml
imagePath: "config_library/unified/few_shot_example/example-images/letter1.jpg"
```

**Local Directory with Multiple Images (New)**:

```yaml
imagePath: "config_library/unified/few_shot_example/example-images/"
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

### Task Prompt Integration

To use few-shot examples, your task prompt must include the `{FEW_SHOT_EXAMPLES}` placeholder:

```yaml
extraction:
  task_prompt: |
    <background>
    You are an expert in business document analysis and information extraction.

    <task>
    Your task is to take the unstructured text provided and convert it into a
    well-organized table format using JSON. Identify the main entities,
    attributes, or categories mentioned in the attributes list below and use
    them as keys in the JSON object.

    Here are the attributes you should extract:
    <attributes>
    {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}
    </attributes>

    <few_shot_examples>
    {FEW_SHOT_EXAMPLES}
    </few_shot_examples>

    </task>
    </background>

    The document type is {DOCUMENT_CLASS}. Here is the document content:
    <document_ocr_data>
    {DOCUMENT_TEXT}
    </document_ocr_data>
```

### Benefits

Using few-shot examples provides several advantages for extraction:

1. **Improved Accuracy**: Models understand the expected extraction format and attribute relationships better
2. **Consistent Formatting**: Examples establish exact JSON structure and value formats expected
3. **Reduced Hallucination**: Examples reduce the likelihood of made-up attribute values
4. **Better Null Handling**: Examples show when attributes should be null vs. empty strings
5. **Domain-Specific Understanding**: Examples help models understand domain-specific terminology and formats

### Best Practices

When creating few-shot examples for extraction:

#### 1. Show Complete Attribute Sets

```yaml
# Good example - shows all attributes with realistic values
attributesPrompt: |
  expected attributes are:
      "invoice_number": "INV-2024-001",
      "invoice_date": "01/15/2024",
      "vendor_name": "ACME Corp",
      "customer_name": "Tech Solutions Inc",
      "total_amount": "$1,250.00",
      "due_date": "02/15/2024",
      "po_number": "PO-789456"

# Avoid incomplete examples
attributesPrompt: |
  expected attributes are:
      "invoice_number": "INV-2024-001"
      # Missing other important attributes
```

#### 2. Handle Null Values Explicitly

```yaml
attributesPrompt: |
  expected attributes are:
      "sender_name": "John Smith",
      "cc": null,  # Explicitly show when fields are not present
      "reference_number": null,
      "subject": "Meeting Request",
      "attachments": null
```

#### 3. Use Realistic and Diverse Examples

- Include examples with different formatting styles
- Show both common cases and edge cases
- Use realistic data that represents your actual documents
- Include examples with varying levels of completeness

#### 4. Maintain Consistent Format

```yaml
# Consistent JSON format across all examples
attributesPrompt: |
  expected attributes are:
      "field1": "value1",
      "field2": "value2",
      "field3": null

# Avoid inconsistent formatting
attributesPrompt: |
  field1: value1
  field2 = "value2"
  field3: (empty)
```

#### 5. Organize Multiple Images

When using directories or S3 prefixes with multiple images:

```yaml
# Good: Use descriptive, ordered filenames
imagePath: "examples/letters/"
# Contents: 001_formal_letter.jpg, 002_informal_letter.png, 003_business_letter.jpg

# Good: Group related examples together
imagePath: "s3://config-bucket/examples/invoices/"
# Contents: invoice_simple.jpg, invoice_complex.png, invoice_international.jpg
```

### Class-Specific Example Filtering

The extraction service automatically filters examples by document class:

```python
# When processing a "letter" document, only letter examples are used
# When processing an "invoice" document, only invoice examples are used

# This ensures extraction examples are relevant and targeted
document = extraction_service.process_document_section(
    document=letter_document,  # Classified as "letter"
    section_id="section-1"
)
# Only letter examples will be included in the prompt
```

### Usage with Extraction Service

The few-shot examples are automatically integrated when using the extraction service:

```python
from idp_common import get_config
from idp_common.extraction.service import ExtractionService
from idp_common.models import Document

# Load configuration with few-shot examples
config = get_config()

# Initialize service - few-shot examples are automatically used
service = ExtractionService(
    region="us-east-1",
    config=config
)

# Examples are automatically included in prompts during extraction
# Only examples matching the document's classification are used
document = service.process_document_section(document, section_id)
```

The service automatically:

1. Loads few-shot examples from the configuration
2. Filters examples to only include those from the document's classified type
3. Includes them in extraction prompts using the `{FEW_SHOT_EXAMPLES}` placeholder
4. Formats examples with both text and images for multimodal understanding

### Example Configuration Structure

Here's a complete example showing how few-shot examples integrate with document class definitions:

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
             "from_address": "Kelahan, Ben",
             "to_address": "TI New York: 'TI Minnesota",
             "cc_address": "Ashley Bratich (MSMAIL)",
             "bcc_address": null,
             "subject": "FW: Morning Team Notes 4/20",
             "date_sent": "04/18/1998",
             "attachments": null,
             "priority": null,
             "thread_id": null,
             "message_id": null
        imagePath: "config_library/unified/few_shot_example/example-images/email1.jpg"

extraction:
  task_prompt: |
    <background>
    You are an expert in business document analysis and information extraction.

    <task>
    Your task is to take the unstructured text provided and convert it into a
    well-organized table format using JSON.

    Here are the attributes you should extract:
    <attributes>
    {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}
    </attributes>

    <few_shot_examples>
    {FEW_SHOT_EXAMPLES}
    </few_shot_examples>

    </task>
    </background>

    The document type is {DOCUMENT_CLASS}. Here is the document content:
    <document_ocr_data>
    {DOCUMENT_TEXT}
    </document_ocr_data>
```

### Testing Few-Shot Examples

Use the provided test notebook to validate the few-shot functionality:

```python
# Test few-shot extraction examples
import sys
sys.path.append('../lib/idp_common_pkg')

from idp_common.extraction.service import ExtractionService
import yaml

# Load configuration with examples
with open('config_library/unified/few_shot_example/config.yaml', 'r') as f:
    config = yaml.safe_load(f)

# Initialize service
service = ExtractionService(config=config)

# Test building examples for specific class
examples = service._build_few_shot_examples_content('letter')
print(f"Found {len(examples)} example items for 'letter' class")

# Test complete content building
content = service._build_content_with_few_shot_examples(
    task_prompt_template=config['extraction']['task_prompt'],
    document_text="Sample letter text...",
    class_label="letter",
    attribute_descriptions="sender_name\t[The person who wrote the letter]"
)
print(f"Built content with {len(content)} items")
```

### Troubleshooting

Common issues and solutions:

1. **No Examples Loaded**:
   - Verify `{FEW_SHOT_EXAMPLES}` placeholder exists in task_prompt
   - Check that examples are defined for the document class being processed
   - Ensure example image paths are correct

2. **Images Not Found**:
   - Set `ROOT_DIR` environment variable for local development
   - Set `CONFIGURATION_BUCKET` for S3 deployment
   - Verify image files exist at specified paths

3. **Inconsistent Extraction Results**:
   - Review example quality and ensure they're representative
   - Check that `attributesPrompt` format matches expected output
   - Ensure examples cover the range of variations in your documents

4. **Poor Performance**:
   - Add more diverse examples for the document class
   - Improve example quality and accuracy
   - Ensure examples demonstrate proper null handling

## Error Handling

The ExtractionService has built-in error handling:

1. If a section ID is not found in the document, an exception is raised
2. If extraction fails for any reason, the error is captured in `document.errors`
3. All errors are logged for debugging
4. Few-shot example loading errors are handled gracefully with fallback to standard prompts

## Performance Optimization

For optimal performance, especially in serverless environments:

1. Only include the section being processed and its required pages
2. Set clear expectations about document structure and fail fast on violations
3. Use the Document model to track metering data
4. Consider the trade-off between few-shot example accuracy improvements and increased token costs

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
4. Few-shot examples include both text prompts and document images for better understanding

## Thread Safety

The extraction service is designed to be thread-safe, supporting concurrent processing of multiple sections in parallel workloads.

## Agentic Extraction with Table Parsing Tool

The extraction service supports an optional **agentic extraction mode** powered by the Strands agent framework with tool-based structured output. When enabled, the extraction agent gains intelligent tools including a deterministic table parser for robust tabular data extraction.

### Enabling Agentic Extraction

Configure agentic extraction in your configuration file:

```yaml
extraction:
  model: "us.anthropic.claude-sonnet-4-20250514-v1:0"  # or Nova models
  agentic:
    enabled: true
    review_agent: false  # Optional second-pass review
    review_agent_model: null  # or specify a model for review
    max_concurrent_batches: 1  # Parallel processing (2-10 for very large docs)
    table_parsing:
      enabled: true  # Enable deterministic table parser tool
      min_confidence_threshold: 95.0  # OCR confidence target (Textract only)
      min_parse_success_rate: 0.90  # Parse quality threshold
      use_confidence_data: true  # Cross-reference with OCR confidence
      max_empty_line_gap: 3  # Tolerate up to N empty lines in tables
      auto_merge_adjacent_tables: true  # Merge table fragments
```

### Table Parsing Tool

When `table_parsing.enabled: true`, the extraction agent gains a `parse_table` tool that:

1. **Deterministically parses Markdown tables** from OCR text without LLM inference
2. **Handles OCR artifacts robustly**:
   - Tolerates empty lines (page breaks) within tables via configurable lookahead
   - Recovers from missing pipe characters in corrupted rows
   - Automatically merges table fragments with identical columns
3. **Provides quality metrics and warnings**:
   - `parse_success_rate`: Ratio of cleanly parsed rows
   - `avg_confidence`: OCR confidence scores (when available from Textract)
   - `low_confidence_cells`: Specific cells needing LLM verification
   - **⚠️ Warnings**: Alert agent to table fragmentation or quality issues
   - **ℹ️ Info**: Confirm successful gap recovery
4. **Enables hybrid extraction workflow**:
   - Agent uses `parse_table` for well-structured tabular data
   - Falls back to LLM extraction for complex layouts or poor quality
   - Cross-validates low-confidence cells using multimodal reasoning

### How It Works

```
1. Agent analyzes document and identifies Markdown tables
2. Agent calls parse_table(table_text, expected_columns)
3. Tool returns:
   - Structured rows as list of dicts
   - Quality metrics (parse_success_rate, avg_confidence)
   - Warnings about potential incompleteness
4. Agent reviews quality:
   - If good (parse_rate >= 0.90, confidence >= 95):
     * Calls map_table_to_schema with column mapping and transforms
     * Calls finalize_table_extraction with scalar fields
   - If poor or warnings present:
     * Falls back to LLM extraction for affected sections
     * Verifies low-confidence cells using document images
5. Agent validates completeness:
   - Cross-checks row counts against document visuals
   - Extracts from ALL table fragments if multiple found
   - Verifies schema constraints (e.g., min_length) are met
```

### Three-Tool Table Extraction Workflow

The table extraction uses a three-tool pipeline that keeps large data out of the LLM context, minimizing token usage:

```
parse_table ──► map_table_to_schema ──► finalize_table_extraction
   │                    │                        │
   ▼                    ▼                        ▼
 Agent State:       Agent State:             Agent State:
 last_parse_        mapped_table_            current_extraction
 table_result       rows                     (validated Pydantic)
```

**Step 1: `parse_table`** — Deterministic Markdown parser. Finds all tables, recovers from OCR artifacts, returns structured rows with quality metrics. Result stored in agent state as `last_parse_table_result`.

**Step 2: `map_table_to_schema`** — Bulk transformation of parsed rows using a column mapping. The agent provides a small mapping dict; the tool transforms all rows instantly. Supports:
- **`column_mapping`**: Maps table columns to schema fields (case-insensitive, fuzzy substring matching)
- **`static_fields`**: Constant values added to every row (e.g., `{"account_number": "1234"}`)
- **`value_transforms`**: Per-field transforms applied during mapping:
  - `strip_currency`: Removes `$` and `,` (e.g., `"$1,234.56"` → `"1234.56"`)
  - `strip_whitespace`: Removes all internal whitespace
  - `lowercase` / `uppercase`: Case conversion
- **Merged-row auto-splitting**: Detects OCR page-boundary artifacts where two rows are concatenated on one line (e.g., `"$57.90 $55.11"` in multiple columns) and splits them back into separate rows

Mapped rows accumulate in agent state as `mapped_table_rows` (supports multiple calls for chunked processing).

**Step 3: `finalize_table_extraction`** — Combines mapped table rows (from state) with scalar fields the agent provides. Validates the complete extraction against the Pydantic schema model. The agent never generates large JSON — only a small `scalar_fields` dict.
- **`table_array_field`**: Schema field name for the table array (e.g., `"transactions"`)
- **`scalar_fields`**: Non-table fields (e.g., `{"statement_period": "Jan 2025"}`)

### Page Markers and Batch Extraction

When processing multi-page documents, the service inserts page boundary markers between page texts:

```
--- PAGE 1 ---
Account Number: 12345
Statement Period: January 2025

| Date | Description | Amount |
|---|---|---|
| 01/15 | Deposit | 3500.00 |
--- PAGE 2 ---
| 01/16 | ATM | -200.00 |
| 01/20 | Transfer | -1500.00 |
```

**Page marker format**: `--- PAGE {N} ---` (1-indexed)

The table parser transparently skips page markers inside tables — they do not break table continuity or appear in parsed rows.

**Batch extraction** (`max_concurrent_batches > 1`): The document is split into N page ranges, and N agents run in parallel. Each batch agent receives the full document text but extracts only its assigned page range, using page markers to identify boundaries. Results are merged: list fields are concatenated, scalar fields take the last non-None value.

```yaml
# Enable batch extraction with 4 concurrent agents
extraction:
  agentic:
    enabled: true
    max_concurrent_batches: 4
    table_parsing:
      enabled: true
```

### Configuration Options

#### `max_empty_line_gap` (integer, 0-10, default: 3)
Maximum consecutive empty lines to tolerate within a table before treating as table boundary. Higher values increase tolerance for OCR page breaks but may merge unrelated tables.

**Tuning guidance**:
- **High-quality OCR** (Textract LAYOUT): Use 2
- **Standard quality**: Use 3 (default)
- **Low-quality or complex documents**: Use 5-7
- **Multiple similar tables close together**: Use 1-2

#### `auto_merge_adjacent_tables` (boolean, default: true)
Automatically merge consecutive tables with identical column structure. Recovers from table splits caused by OCR artifacts like page breaks.

**When to disable**:
- Documents contain multiple distinct tables with same columns
- Need to preserve table boundaries for semantic reasons

#### `min_confidence_threshold` (float, 0-100, default: 95.0)
Minimum average OCR confidence (Textract scale) for agent to prefer table parsing over LLM extraction. Only applies when using Textract OCR backend.

#### `min_parse_success_rate` (float, 0-1, default: 0.90)
Minimum parse success rate for agent to trust parsed results. Below this threshold, agent should fall back to LLM extraction.

### Schema-Constraint Validation and Model Escalation

Agentic extraction always validates the agent's output against the **Pydantic
model** generated from the class JSON Schema (`field_constraints=True`), so
`enum`, `pattern`, numeric bounds and `minItems`/`maxItems` violations are fed
back to the agent for self-correction during extraction.

The optional `extraction.agentic.validation` block adds **full JSON-Schema
validation** of the final result — most importantly the `format` keyword
(`date`, `date-time`, `email`, `uri`, `uuid`, ...), which the generated Pydantic
model does **not** enforce — and an optional **bounded model escalation** when
validation still fails.

```yaml
extraction:
  agentic:
    enabled: true
    validation:
      enabled: false          # Off by default (no behavior change on upgrade)
      check_formats: true     # Enforce JSON-Schema 'format' keywords
      fail_action: escalate   # warn | escalate | reject
      escalation_model: "us.anthropic.claude-opus-4-8"  # stronger tier; "" = retry same model
```

How it works:

1. After extraction, the merged result is validated against the full class
   schema. All violations are collected at once (not one-at-a-time) with
   human-readable field paths.
2. `fail_action` controls the response when validation fails:
   - **`warn`** — record a `validation` block in the result metadata and proceed.
   - **`escalate`** — re-extract **only the failing top-level fields** with a
     stronger model (`escalation_model`), then merge the corrected fields back
     into the result. Scoping to the failing fields keeps the schema, prompt and
     output small — far cheaper and faster than re-running the whole section —
     and the fields that already validated are preserved untouched. The merged
     result is kept only if it is valid or has strictly fewer violations; then
     warn if it still fails. (When the failures can't be expressed as a field
     subset — e.g. they're root-level only — it falls back to a whole-section
     re-extraction.)
   - **`reject`** — mark `parsing_succeeded=false` so downstream/HITL can act.
3. The outcome is recorded under `metadata.validation` (see *Audit metadata*
   below).

**Audit metadata.** Each section's extraction result records, under `metadata`:
- `extraction_model` and `extraction_model_overridden` — the model that actually
  ran the section and whether it came from a per-class override.
- `metadata.validation` — `valid`, `error_count`, `failed_fields`, `errors`
  (path + validator + message), `check_formats`, `fail_action`,
  `initial_error_count` / `initial_failed_fields` (before any escalation), and —
  when escalation ran — `escalated`, `escalation_model`, `escalation_scope`
  (`field-subset` | `full-section`), `escalation_fields`, and
  `resolved_by_escalation`.

**Escalation model precedence:** per-class `x-aws-idp-extraction-escalation-model`
schema extension → global `validation.escalation_model` → the extraction model
itself (escalation becomes a plain second attempt).

**Configuration UI.** The global `validation` block (enabled / check_formats /
fail_action / escalation_model) is editable under **Extraction → Agentic
Extraction → Schema Validation & Escalation** in the Configuration editor. The
per-class `x-aws-idp-extraction-escalation-model` override is editable as
"Escalation Model Override" in the **Document Schema** editor, next to the
per-class extraction-model override.

**Null = absent.** Extraction follows the convention "return `null` if a field is
not found", and the generated Pydantic model makes every non-required property
`Optional[...] = None`. Validation therefore treats a `null` property as
**absent**: an optional field left null passes, while a *required* field left
null surfaces as a `required` violation (not a confusing type error). Enum /
pattern / format / numeric / `minItems` checks on present values are unaffected.

> **`format: date` caveat.** JSON-Schema `format: date` means ISO-8601
> (`YYYY-MM-DD`). The default extraction prompt asks the model for `MM/DD/YYYY`,
> which is **not** a valid `date` format and will fail format validation. If
> your schema uses `format: date` for non-ISO dates, either set
> `check_formats: false` or use a `pattern` instead of `format`.

### Benefits

- **Faster extraction**: Deterministic parsing is faster than LLM inference for well-structured tables
- **Higher accuracy**: Eliminates LLM hallucination for tabular data
- **Better completeness**: Intelligent recovery from OCR artifacts prevents data loss
- **Cost reduction**: Reduces token usage for large tables
- **Hybrid flexibility**: Agent intelligently chooses between parsing and LLM based on quality

### OCR Backend Compatibility

The table parsing tool works with any OCR backend producing Markdown tables:

| OCR Backend | Markdown Support | Confidence Data | Notes |
|-------------|-----------------|-----------------|-------|
| **Textract** (TABLES) | ✅ Yes | ✅ Yes | Best for structured tables |
| **Textract** (LAYOUT) | ✅ Yes | ✅ Yes | Handles complex layouts |
| **Bedrock OCR** | ✅ Yes | ❌ No | Tool uses parse_success_rate only |
| **Chandra OCR** | ✅ Yes (markdown mode) | ❌ No | High-quality Markdown output |

When OCR confidence data is unavailable, the tool relies on `parse_success_rate` and column consistency for quality assessment.

### Example: Bank Statement with 1000+ Transactions

```yaml
# config.yaml
extraction:
  model: "us.anthropic.claude-sonnet-4-20250514-v1:0"
  agentic:
    enabled: true
    table_parsing:
      enabled: true
      max_empty_line_gap: 5  # Handle multi-page statements
      auto_merge_adjacent_tables: true

classes:
  - $id: BankStatement
    type: object
    properties:
      account_number:
        type: string
      statement_period:
        type: string
      transactions:
        type: array
        minItems: 1000  # Completeness validation
        items:
          type: object
          properties:
            date: {type: string}
            description: {type: string}
            amount: {type: number}
            balance: {type: number}
```

**Extraction flow**:
1. Agent identifies transaction table in OCR text
2. Calls `parse_table(table_text)` → Returns 1020 rows with quality metrics
3. Tool warnings: "ℹ️ Successfully recovered 3 gaps in table data"
4. Calls `map_table_to_schema(column_mapping={"Date": "date", "Description": "description", ...}, value_transforms={"amount": "strip_currency"})` → All 1020 rows transformed instantly
5. Calls `finalize_table_extraction(table_array_field="transactions", scalar_fields={"account_number": "12345678", "statement_period": "January 2024"})` → Validated against Pydantic model
6. Completeness check logs: "Extraction exceeds minimum constraint: 'transactions' has 1020 items (minimum: 1000)"

### Troubleshooting

**Problem**: Agent extracts only 900 records instead of 1020

**Root causes & solutions**:
1. **Table split by empty lines** → Increase `max_empty_line_gap` to 5
2. **Multiple table fragments** → Ensure `auto_merge_adjacent_tables: true`
3. **Agent stopped early** → Check extraction logs for timeout/retry issues
4. **Schema constraint too strict** → Reduce `minItems` or make it optional

**Problem**: Parse quality is low (< 0.90)

**Solutions**:
1. **Improve OCR quality** → Use Textract LAYOUT or Chandra OCR
2. **Complex table structure** → Use LLM extraction instead of parse_table
3. **Merged cells or nested headers** → Preprocess table or use LLM

**Problem**: Unrelated tables being merged

**Solutions**:
1. Reduce `max_empty_line_gap` to 1-2
2. Set `auto_merge_adjacent_tables: false`
3. Add more context to distinguish tables semantically

### Observability

Extraction results include table parsing metadata when the tool is used:

```json
{
  "metadata": {
    "extraction_method": "agentic",
    "table_parsing_tool_used": true,
    "table_parsing_stats": {
      "tables_parsed": 1,
      "rows_parsed": 1020,
      "parse_success_rate": 0.98,
      "avg_confidence": 96.5,
      "confidence_available": true,
      "invocation_count": 1
    }
  }
}
```

Use these metrics to:
- Identify documents where table parsing is working well
- Detect quality issues requiring configuration tuning
- Measure cost savings vs LLM-only extraction

## Future Enhancements

- ✅ Few-shot example support for improved accuracy and consistency
- ✅ Class-specific example filtering for targeted extraction guidance
- ✅ Multimodal example support with document images
- ✅ Enhanced imagePath support for multiple images from directories and S3 prefixes
- ✅ Agentic extraction with tool-based structured output
- ✅ Deterministic table parsing tool for robust tabular data extraction
- 🔲 Dynamic few-shot example selection based on document similarity
- 🔲 Confidence scoring for extracted attributes
- 🔲 Support for additional extraction backends (custom models)
- 🔲 Automatic example quality assessment and recommendations
- 🔲 Table structure detection for complex layouts (merged cells, nested headers)
