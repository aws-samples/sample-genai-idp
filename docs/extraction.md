Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

# Customizing Extraction

Information extraction is a central capability of the GenAIIDP solution, transforming unstructured document content into structured data. This guide explains how to customize extraction for your specific use cases, including few-shot prompting and CachePoint optimization.

## Extraction Configuration

Configure extraction behavior through several components:

### Agentic Extraction (Preview)

The extraction service supports two modes: **traditional** and **agentic**. Agentic extraction provides superior accuracy and consistency, especially for complex documents with nested structures or strict schema requirements.

> **Preview Status**: Agentic extraction is currently in preview. While it demonstrates significant improvements in accuracy and reliability, we recommend thorough testing in your specific use case before production deployment.

#### When to Enable Agentic Extraction

Enable agentic extraction when you need:

- **Schema Compliance**: Guaranteed adherence to defined data structures
- **Data Validation**: Automatic validation with retry mechanisms
- **Complex Structures**: Proper handling of nested objects and arrays
- **Date Standardization**: Consistent date formatting (e.g., MM/DD/YYYY)
- **Self-Correction**: Automatic fixing of extraction errors
- **Production Reliability**: Higher accuracy for business-critical data
- **Extensibility**: Future integration with Model Context Protocol (MCP) servers for advanced validation, enrichment, and external data lookups during extraction

```yaml
extraction:
  agentic:
    enabled: true  # Enable for better consistency and accuracy
  model:anthropic.claude-3-haiku-20240307-v1:0
```

#### Cost Considerations

Agentic extraction may have slightly higher costs due to:

- Additional processing for validation and correction
- Tool-use capabilities requiring more sophisticated models
- Multiple retry attempts for error correction

However, the benefits typically outweigh the costs:

Agentic extraction helps improve model performance significantly on tasks, for example Claude Sonnet 3.5 increases over 20% in accuracy on [getomni-ai benchmark](https://getomni.ai/blog/ocr-benchmark).

- **100% schema compliance** vs frequent validation failures
- **Reduced manual review** and correction efforts
- **Automatic caching**: For supported models, prompt and tool caching is automatically enabled, reducing costs for repeated extractions with the same configuration

#### Supported Models for Agentic Extraction

Agentic extraction requires models with tool-use support:

- **Anthropic Claude Sonnet** models (recommended for optimal performance)
  - `anthropic.claude-3-5-sonnet-20241022-v2:0` - Best balance of speed and accuracy
  - `anthropic.claude-3-7-sonnet-20250219-v1:0` - Latest with enhanced capabilities
- **Anthropic Claude Opus** models (for highest accuracy requirements)
- **Amazon Nova Pro** (AWS native alternative)
- **Amazon Nova Premier** (for complex multi-modal extraction)

> **Note on Future Enhancements**: The full power of agentic extraction will become available when Pydantic models are fully supported in the configuration. This will enable:
>
> - Custom field validators
> - Complex type definitions
> - Nested model hierarchies
> - Advanced data transformations
> - Business logic validation
> - **MCP Server Integration**: Connect to external validation services, databases, or APIs to enrich extraction with real-time data lookups (e.g., validate addresses, verify company names, check product codes)
>
> **Current Implementation**: Agentic extraction automatically converts your document class configuration (classes, attributes, descriptions, types) into Pydantic models internally. This means improving your configuration directly improves extraction accuracy. The agent uses these Pydantic models to validate extracted data and ensure schema compliance.
>
> **Future Enhancement**: You'll be able to define custom Pydantic models directly in your configuration with advanced validators, custom types, and complex business logic. This will provide even more powerful extraction capabilities while maintaining the same ease of use.

#### Automatic Retry Handling

Agentic extraction automatically handles throttling and transient errors:

- **Automatic retries**: Up to 7 retry attempts with exponential backoff (matching bedrock client behavior)
- **Adaptive retry mode**: Intelligently adjusts retry timing based on error types
- **Step Functions integration**: If retries are exhausted, ThrottlingException is propagated to Step Functions for workflow-level retry handling
- **No configuration needed**: Retry logic is transparent and matches the standard bedrock client behavior

This ensures reliable extraction even in accounts with low service quotas, with no manual configuration required.

### Document Classes and Attributes

Specify document classes and the fields to extract from each:

```yaml
classes:
  - name: "invoice"
    description: "A billing document listing items/services, quantities, prices, payment terms, and transaction totals"
    attributes:
      - name: "invoice_number"
        description: "The unique identifier for this invoice, typically labeled as 'Invoice #', 'Invoice Number', or similar"
      - name: "invoice_date"
        description: "The date when the invoice was issued, typically labeled as 'Date', 'Invoice Date', or similar"
      - name: "due_date"
        description: "The date by which payment is due, typically labeled as 'Due Date', 'Payment Due', or similar"
```

### Extraction Instructions

### Model and Prompt Configuration

Configure the extraction model and prompting strategy:

#### Configuration for Agentic Extraction (Recommended)

```yaml
extraction:
  # Enable agentic extraction for better accuracy
  agentic:
    enabled: true # Turn on for production use

  # Model selection - must support tool use for agentic
  model: anthropic.claude-3-5-sonnet-20241022-v2:0 # Recommended for best results
  # Alternative models:
  # - anthropic.claude-3-7-sonnet-20250219-v1:0  # Latest Sonnet with enhanced capabilities
  # - us.amazon.nova-pro-v1:0  # AWS native option
  temperature: 0.0 # Keep low for consistency
  top_p: 0.1
  top_k: 5
  max_tokens: 4096

  # Prompts for extraction
  system_prompt: |
    You are an expert in extracting structured information from documents.
    Focus on accuracy in identifying key fields based on their descriptions.
    For each field, look for both the field label and the associated value.
    Pay attention to formatting patterns common in business documents.
    When a field is not present, indicate this explicitly rather than guessing.

  task_prompt: |
    Extract the following fields from this {DOCUMENT_CLASS} document:

    {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}

    <few_shot_examples>
    {FEW_SHOT_EXAMPLES}
    </few_shot_examples>

    <<CACHEPOINT>>

    Here is the document to analyze:
    {DOCUMENT_TEXT}

    Format your response as valid JSON:
    {
      "field_name": "extracted value",
      ...
    }
```

##### How Prompts Work in Agentic vs Traditional Extraction

Both extraction modes use the same `system_prompt` and `task_prompt` configuration, but they are applied differently:

**Traditional Extraction:**

- `system_prompt` → Sent directly to Bedrock as the system message
- `task_prompt` → Sent as the user message with document content
- Model responds with JSON text that requires parsing
- No validation or retry mechanism

**Agentic Extraction:**

- `system_prompt` → Passed via `custom_instruction` parameter and appended to the agentic system prompt
- `task_prompt` → Sent as user message with document content (text/images as content blocks)
- Uses Strands agent framework with tools for structured output
- Returns validated Pydantic model (no JSON parsing needed)
- Automatic retry and self-correction on validation failures

**Key Difference:** The agentic system prompt (in `agentic_idp.py`) provides extraction guidelines and tool usage instructions. Your existing `system_prompt` and `task_prompt` are incorporated as custom instructions to guide the extraction without changing the core agent behavior.

**How Agentic Uses Your Configuration:** Agentic extraction automatically transforms your document class configuration (classes, attributes, and descriptions) into Pydantic models. These models define the exact structure, types, and field descriptions that the agent must follow. As you improve your attribute descriptions and add more detailed field definitions in your configuration, the agentic extraction becomes more accurate because the Pydantic models provide stronger type validation and clearer extraction targets.

**Result:** The same prompt configuration works for both methods, just applied differently under the hood. You don't need separate prompts for agentic extraction. The better you define your document classes and attributes, the more accurate your agentic extraction will be.

#### Configuration for Traditional Extraction (Legacy/Testing)

```yaml
extraction:
  # Disable agentic for traditional extraction
  agentic:
    enabled: false # Only for testing or legacy compatibility

  # Model selection - any Bedrock model
  model: anthropic.claude-3-haiku-20240307-v1:0 # Can use simpler models
  temperature: 0.0
  max_tokens: 4096

  # Note: Traditional extraction has limitations:
  # - No automatic validation or retry
  # - Inconsistent date/number formatting
  # - Poor handling of nested structures
  # - Lower overall accuracy (~70% vs 95%)
```

The extraction service automatically detects and parses both JSON and YAML responses from the LLM, making the structured data available for downstream processing.

## Image Placement with {DOCUMENT_IMAGE} Placeholder

The extraction service supports precise control over where document images are positioned within your extraction prompts using the `{DOCUMENT_IMAGE}` placeholder. This feature allows you to specify exactly where images should appear in your prompt template, enabling better multimodal extraction by strategically positioning visual content relative to text instructions.

### How {DOCUMENT_IMAGE} Works

**Without Placeholder (Default Behavior):**

```yaml
extraction:
  task_prompt: |
    Extract the following fields from this {DOCUMENT_CLASS} document:

    {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}

    Document text:
    {DOCUMENT_TEXT}

    Respond with valid JSON.
```

Images are automatically appended after the text content.

**With Placeholder (Controlled Placement):**

```yaml
extraction:
  task_prompt: |
    Extract the following fields from this {DOCUMENT_CLASS} document:

    {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}

    Examine this document image:
    {DOCUMENT_IMAGE}

    Text content:
    {DOCUMENT_TEXT}

    Respond with valid JSON containing the extracted values.
```

Images are inserted exactly where `{DOCUMENT_IMAGE}` appears in the prompt.

### Usage Examples

**Visual-First Extraction:**

```yaml
task_prompt: |
  You are extracting data from a {DOCUMENT_CLASS}. Here are the fields to find:
  {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}

  First, examine the document layout and visual structure:
  {DOCUMENT_IMAGE}

  Now analyze the extracted text:
  {DOCUMENT_TEXT}

  Extract the requested fields as JSON:
```

**Image for Context and Verification:**

```yaml
task_prompt: |
  Extract these fields from a {DOCUMENT_CLASS}:
  {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}

  Document text (may contain OCR errors):
  {DOCUMENT_TEXT}

  Use this image to verify and correct any unclear information:
  {DOCUMENT_IMAGE}

  Extracted data (JSON format):
```

**Mixed Content Analysis:**

```yaml
task_prompt: |
  You are processing a {DOCUMENT_CLASS} that may contain both text and visual elements like tables, stamps, or signatures.

  Target fields: {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}

  Document image (shows full layout):
  {DOCUMENT_IMAGE}

  Extracted text (may miss visual-only elements):
  {DOCUMENT_TEXT}

  Extract all available information as JSON:
```

### Integration with Few-Shot Examples

The `{DOCUMENT_IMAGE}` placeholder works seamlessly with few-shot examples:

```yaml
extraction:
  task_prompt: |
    Extract fields from {DOCUMENT_CLASS} documents. Here are examples:

    {FEW_SHOT_EXAMPLES}

    Now process this new document:

    Visual layout:
    {DOCUMENT_IMAGE}

    Text content:
    {DOCUMENT_TEXT}

    Fields to extract: {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}

    JSON response:
```

### Benefits for Extraction

- **🎯 Enhanced Accuracy**: Visual context helps identify field locations and correct OCR errors
- **📊 Table and Form Handling**: Better extraction from structured layouts like tables and forms
- **✍️ Handwritten Content**: Improved handling of signatures, handwritten notes, and annotations
- **🖼️ Visual-Only Elements**: Extract information from stamps, logos, checkboxes, and visual indicators
- **🔍 Verification**: Use images to verify and correct text extraction results
- **📱 Layout Understanding**: Better comprehension of document structure and field relationships

### Multi-Page Document Handling

For documents with multiple pages, the system provides robust image management:

- **Automatic Pagination**: Images are processed in page order
- **Bedrock Compliance**: Maximum 20 images per request (automatically enforced)
- **Smart Truncation**: Excess images are dropped with warning logs
- **Performance Optimization**: Large image sets are efficiently handled

```yaml
# Example configuration for multi-page invoices
extraction:
  task_prompt: |
    Extract data from this multi-page {DOCUMENT_CLASS}:

    {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}

    Document pages (up to 20 images):
    {DOCUMENT_IMAGE}

    Combined text from all pages:
    {DOCUMENT_TEXT}

    Return JSON with extracted fields:
```

### Best Practices for Image Placement

1. **Place Images Before Complex Instructions**: Show the document before giving detailed extraction rules
2. **Use Images for Verification**: Position images after text to help verify and correct extractions
3. **Leverage Visual Context**: Use images when extracting from tables, forms, or structured layouts
4. **Handle OCR Limitations**: Use images to fill gaps where OCR may miss visual-only content
5. **Consider Document Types**: Different document types benefit from different image placement strategies

## Custom Prompt Generator Lambda Functions

The extraction service supports custom Lambda functions for advanced prompt generation, allowing you to inject custom business logic into the extraction process while leveraging the existing IDP infrastructure.

### Overview

Custom prompt generator Lambda functions enable:

- **Document type-specific processing** with specialized extraction logic
- **Integration with external systems** for dynamic configuration retrieval
- **Conditional processing** based on document content analysis
- **Regulatory compliance** with industry-specific prompt requirements
- **Multi-tenant customization** for different customer requirements

### Configuration

Add the `custom_prompt_lambda_arn` field to your extraction configuration:

```yaml
extraction:
  model: us.amazon.nova-pro-v1:0
  temperature: 0.0
  system_prompt: "Your default system prompt..."
  task_prompt: "Your default task prompt..."
  # Custom Lambda function for prompt generation
  custom_prompt_lambda_arn: "arn:aws:lambda:us-east-1:123456789012:function:GENAIIDP-my-extractor"
```

**Lambda Function Requirements:**

- Function name must start with `GENAIIDP-` (required for IAM permissions)
- Must return valid JSON with `system_prompt` and `task_prompt_content` fields
- Available in Patterns 2 and 3 only

### Lambda Interface

Your Lambda function receives a comprehensive payload with all context needed for prompt generation:

**Input Payload:**

```json
{
  "config": {
    "extraction": {...},
    "classes": [...],
    "assessment": {...}
  },
  "prompt_placeholders": {
    "DOCUMENT_TEXT": "Full OCR extracted text from all pages",
    "DOCUMENT_CLASS": "Invoice",
    "ATTRIBUTE_NAMES_AND_DESCRIPTIONS": "Invoice Number\t[Unique identifier]...",
    "DOCUMENT_IMAGE": ["s3://bucket/document/pages/1/image.jpg", "s3://bucket/document/pages/2/image.jpg"]
  },
  "default_task_prompt_content": [
    {"text": "Resolved default task prompt with placeholders replaced"},
    {"image_uri": "<image_placeholder>"},
    {"cachePoint": true}
  ],
  "serialized_document": {
    "id": "document-123",
    "input_bucket": "my-bucket",
    "input_key": "documents/invoice.pdf",
    "pages": {...},
    "sections": [...],
    "status": "EXTRACTING"
  }
}
```

**Required Output:**

```json
{
  "system_prompt": "Your custom system prompt based on document analysis",
  "task_prompt_content": [
    { "text": "Your custom task prompt with business logic applied" },
    { "image_uri": "<preserved_placeholder>" },
    { "cachePoint": true }
  ]
}
```

### Implementation Examples

**Document Type Detection:**

```python
def lambda_handler(event, context):
    placeholders = event.get('prompt_placeholders', {})
    document_class = placeholders.get('DOCUMENT_CLASS', '')

    if 'bank statement' in document_class.lower():
        return generate_banking_prompts(event)
    elif 'invoice' in document_class.lower():
        return generate_invoice_prompts(event)
    else:
        return use_default_prompts(event)
```

**Content-Based Analysis:**

```python
def lambda_handler(event, context):
    placeholders = event.get('prompt_placeholders', {})
    document_text = placeholders.get('DOCUMENT_TEXT', '')
    image_uris = placeholders.get('DOCUMENT_IMAGE', [])

    # Multi-page processing logic
    if len(image_uris) > 3:
        return generate_multi_page_prompts(event)

    # International document detection
    if any(term in document_text.lower() for term in ['vat', 'gst', 'euro']):
        return generate_international_prompts(event)

    return use_standard_prompts(event)
```

**External System Integration:**

```python
import boto3

def lambda_handler(event, context):
    document = event.get('serialized_document', {})
    customer_id = document.get('customer_id')  # Custom field

    # Retrieve customer-specific rules
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('customer-extraction-rules')

    customer_rules = table.get_item(Key={'customer_id': customer_id}).get('Item', {})

    # Apply customer-specific customization
    if customer_rules.get('enhanced_validation'):
        return generate_enhanced_validation_prompts(event)

    return use_standard_prompts(event)
```

### Error Handling

The system implements **fail-fast error handling** for custom Lambda functions:

- **Lambda invocation failures** cause extraction to fail with detailed error messages
- **Invalid response format** results in extraction failure with validation errors
- **Function errors** propagate with Lambda error details
- **Timeout scenarios** fail with timeout information

**Example Error Messages:**

```
Failed to invoke custom prompt Lambda arn:aws:lambda:...: Connection timeout
Custom prompt Lambda failed: KeyError: 'system_prompt' not found in response
Custom prompt Lambda returned invalid response format: expected dict, got str
```

### Performance Considerations

- **Lambda Overhead**: Adds latency from Lambda cold starts and execution time
- **JSON Serialization**: Optimized with URI-based image handling to minimize payload size
- **Efficient Interface**: Avoids sending large image bytes, uses S3 URIs instead
- **Monitoring**: Comprehensive logging for performance analysis and troubleshooting

### Deployment and Testing

**1. Demo Lambda Function:**
Deploy the provided demo Lambda for testing:

```bash
cd notebooks/examples/demo-lambda
sam deploy --guided
```

**2. Interactive Testing:**
Use the demo notebook for hands-on experimentation:

```bash
jupyter notebook notebooks/examples/step3_extraction_with_custom_lambda.ipynb
```

**3. Production Deployment:**
Create your production Lambda with business-specific logic and deploy with appropriate IAM permissions.

### Use Cases

**Financial Services:**

- Regulatory compliance prompts for different financial products
- Multi-currency transaction handling with exchange rate awareness
- Customer-specific formatting for different banking institutions

**Healthcare:**

- HIPAA compliance with privacy-focused prompts
- Medical terminology enhancement for clinical documents
- Provider-specific templates for different healthcare systems

**Legal:**

- Jurisdiction-specific legal language processing
- Contract type specialization (NDAs, service agreements, etc.)
- Compliance requirements for regulatory documents

**Insurance:**

- Policy type customization for different insurance products
- Claims processing with adjuster-specific requirements
- Risk assessment integration with underwriting systems

### Security and Compliance

- **Scoped IAM Permissions**: Only Lambda functions with `GENAIIDP-*` naming can be invoked
- **Audit Trail**: All Lambda invocations are logged for security monitoring
- **Input Validation**: Lambda response structure is validated before use
- **Fail-Safe Operation**: Lambda failures cause extraction to fail rather than continue with potentially incorrect prompts

For complete examples and deployment instructions, see `notebooks/examples/demo-lambda/README.md`.

## Using CachePoint for Extraction

CachePoint is a feature of select Bedrock models that caches partial computations to improve performance and reduce costs. When used with extraction, it provides:

- Cached processing for portions of the prompt
- Improved consistency across similar document types
- Reduced processing costs and latency
- Faster inference times

### Enabling CachePoint

CachePoint is enabled by placing special `<<CACHEPOINT>>` tags in your prompt templates. These indicate where the model should cache preceding components of the prompt:

```yaml
extraction:
  model: us.amazon.nova-pro-v1:0 # Must be a CachePoint-compatible model
  task_prompt: |
    <background>
    You are an expert in business document analysis and information extraction.
    </background>

    <<CACHEPOINT>>  # Cache the instruction portion

    Here is the document to analyze:
    {DOCUMENT_TEXT}
```

### Supported Models

CachePoint is currently supported by the following models:

- `us.anthropic.claude-3-5-haiku-20241022-v1:0`
- `us.anthropic.claude-3-7-sonnet-20250219-v1:0`
- `us.amazon.nova-lite-v1:0`
- `us.amazon.nova-pro-v1:0`

### Cost Benefits

CachePoint significantly reduces token costs for cached portions:

```yaml
pricing:
  - name: bedrock/us.anthropic.claude-3-5-haiku-20241022-v1:0
    units:
      - name: inputTokens
        price: "8.0E-7"
      - name: outputTokens
        price: "4.0E-6"
      - name: cacheReadInputTokens # Reduced rate for cached content
        price: "8.0E-8" # 10x cheaper than standard input tokens
      - name: cacheWriteInputTokens
        price: "1.0E-6"
```

### Optimal CachePoint Placement

For extraction tasks, place CachePoint tags to separate:

1. **Static content** (system instructions, few-shot examples) - cacheable
2. **Dynamic content** (document text, specific attributes) - not cacheable

This ensures the expensive parts of your prompt that remain unchanged across documents are efficiently cached.

## Extraction Attributes

The solution comes with predefined extraction attributes for common document types:

### Invoice Documents

- `invoice_number`: Unique invoice identifier
- `invoice_date`: Date of invoice issuance
- `vendor_name`: Name of the invoicing company
- `vendor_address`: Full address of vendor
- `customer_name`: Name of customer/account holder
- `customer_address`: Full address of customer
- `total_amount`: Final amount due
- `subtotal`: Amount before tax/shipping
- `tax_amount`: Tax or VAT amount
- `due_date`: Payment deadline
- `payment_terms`: Payment term details
- `line_items`: Individual items with quantity, description, and price

### Form Documents

- `form_type`: Type or title of the form
- `applicant_name`: Name of person filling the form
- `application_date`: Date form was completed
- `date_submitted`: Form submission date
- `reference_number`: Form tracking number
- `form_status`: Current status of the form
- `signature_present`: Whether form is signed

### Letter Documents

- `sender_name`: Name of letter writer
- `sender_address`: Address of sender
- `recipient_name`: Name of letter recipient
- `recipient_address`: Address of recipient
- `date`: Letter date
- `subject`: Letter subject or topic
- `greeting`: Opening greeting
- `closing`: Closing phrase
- `signature`: Signature information

### Bank Statements

- `account_number`: Bank account identifier
- `account_holder`: Name of account owner
- `statement_period`: Date range of statement
- `opening_balance`: Balance at start of period
- `closing_balance`: Balance at end of period
- `total_deposits`: Sum of all credits
- `total_withdrawals`: Sum of all debits
- `transactions`: List of individual transactions

## Adding Custom Attributes

You can define custom extraction attributes through the Web UI:

1. Navigate to the Configuration section
2. Select the Extraction Attributes tab
3. Choose the document class to modify
4. Click "Add New Attribute"
5. Provide:
   - Attribute name (machine-readable identifier)
   - Display name (human-readable name)
   - Detailed description (to guide extraction)
   - Optional formatting hints (e.g., date format)
6. Save changes

## Advanced Extraction Techniques

### Few-Shot Extraction

Improve extraction accuracy by providing examples within each document class configuration:

```yaml
classes:
  - name: "invoice"
    description: "A billing document for goods or services"
    attributes:
      - name: "invoice_number"
        description: "The unique identifier for this invoice"
      # Other attributes...
    examples:
      - name: "SampleInvoice1"
        attributesPrompt: |
          Expected attributes are:
            "invoice_number": "INV-12345"
            "invoice_date": "2023-04-15"
            "total_amount": "$1,234.56"
        imagePath: "config_library/pattern-2/examples/invoice-samples/invoice1.jpg"
      # Additional examples...
```

The extraction service will use these examples as context when processing similar documents. To use few-shot examples in your extraction prompts, include the `{FEW_SHOT_EXAMPLES}` placeholder:

```yaml
extraction:
  task_prompt: |
    Extract the following fields from this {DOCUMENT_CLASS} document:

    {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}

    <few_shot_examples>
    {FEW_SHOT_EXAMPLES}
    </few_shot_examples>

    Now extract the attributes from this document:
    {DOCUMENT_TEXT}
```

Examples are class-specific - only examples from the same document class being processed will be included in the prompt.

## Image Processing Configuration

The extraction service supports configurable image dimensions for optimal performance and quality:

### New Default Behavior (Preserves Original Resolution)

**Important Change**: Empty strings or unspecified image dimensions now preserve the original document resolution for maximum extraction accuracy:

```yaml
extraction:
  model: us.amazon.nova-pro-v1:0
  # Image processing settings - preserves original resolution
  image:
    target_width: "" # Empty string = no resizing (recommended)
    target_height: "" # Empty string = no resizing (recommended)
```

### Custom Image Dimensions

Configure specific dimensions when performance optimization is needed:

```yaml
# For high-accuracy extraction with controlled dimensions
extraction:
  image:
    target_width: "1200"   # Resize to 1200 pixels wide
    target_height: "1600"  # Resize to 1600 pixels tall

# For fast processing with standard resolution
extraction:
  image:
    target_width: "800"    # Smaller for faster processing
    target_height: "1000"  # Maintains good quality
```

### Image Resizing Features

- **Original Resolution Preservation**: Empty strings preserve full document resolution for maximum extraction accuracy
- **Aspect Ratio Preservation**: Images are resized proportionally without distortion when dimensions are specified
- **Smart Scaling**: Only downsizes images when necessary (scale factor < 1.0)
- **High-Quality Resampling**: Better visual quality after resizing for improved field detection
- **Performance Optimization**: Configurable dimensions allow balancing accuracy vs. speed

### Configuration Benefits for Extraction

- **Maximum Extraction Accuracy**: Empty strings preserve full document resolution for best field detection
- **Enhanced Field Detection**: Original resolution improves accuracy for table and form extraction
- **Visual Element Processing**: Better handling of signatures, stamps, checkboxes, and visual indicators at full resolution
- **OCR Error Correction**: Higher quality images help verify and correct text extraction results
- **Service-Specific Tuning**: Optimize image dimensions for different document types and extraction complexity
- **Runtime Configuration**: Adjust image processing without code changes
- **Resource Optimization**: Choose between accuracy (original resolution) and performance (smaller dimensions)

### Migration from Previous Versions

**Previous Behavior**: Empty strings defaulted to 951x1268 pixel resizing
**New Behavior**: Empty strings preserve original image resolution

If you were relying on the previous default resizing behavior, explicitly set dimensions:

```yaml
# To maintain previous default behavior
extraction:
  image:
    target_width: "951"
    target_height: "1268"
```

### Best Practices for Extraction

1. **Use Empty Strings for High Accuracy**: For critical data extraction, use empty strings to preserve original resolution
2. **Consider Document Complexity**: Forms and tables benefit significantly from higher resolution
3. **Test with Representative Documents**: Evaluate extraction accuracy with your specific document types
4. **Monitor Resource Usage**: Higher resolution images consume more memory and processing time
5. **Balance Accuracy vs Performance**: Choose appropriate settings based on your accuracy requirements and processing volume

## JSON and YAML Output Support

The extraction service supports both JSON and YAML output formats from LLM responses, with automatic format detection and parsing:

### Automatic Format Detection

The system automatically detects whether the LLM response is in JSON or YAML format:

```yaml
# JSON response (traditional)
extraction:
  task_prompt: |
    Extract the following fields and respond with JSON:
    {
      "invoice_number": "extracted value",
      "total_amount": "extracted value"
    }

# YAML response (more token-efficient)
extraction:
  task_prompt: |
    Extract the following fields and respond with YAML:
    invoice_number: extracted value
    total_amount: extracted value
```

### Token Efficiency Benefits

YAML format provides significant token savings for extraction tasks:

- **10-30% fewer tokens** than equivalent JSON
- No quotes required around keys
- More compact syntax for nested structures
- Natural support for multiline content
- Cleaner representation of complex extracted data

### Example Prompt Configurations

**JSON-focused extraction prompt:**

```yaml
extraction:
  system_prompt: |
    You are a document assistant. Respond only with JSON. Never make up data, only provide data found in the document being provided.
  task_prompt: |
    Extract the following fields from this {DOCUMENT_CLASS} document and return a JSON object:

    {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}

    Document text: {DOCUMENT_TEXT}

    JSON response:
```

**YAML-focused extraction prompt:**

```yaml
extraction:
  system_prompt: |
    You are a document assistant. Respond only with YAML. Never make up data, only provide data found in the document being provided.
  task_prompt: |
    Extract the following fields from this {DOCUMENT_CLASS} document and return YAML:

    {ATTRIBUTE_NAMES_AND_DESCRIPTIONS}

    Document text: {DOCUMENT_TEXT}

    YAML response:
```

### Complex Data Structure Examples

**JSON format for nested extraction:**

```json
{
  "vendor_info": {
    "name": "ACME Corporation",
    "address": "123 Main St, City, State 12345"
  },
  "line_items": [
    {
      "description": "Widget A",
      "quantity": 5,
      "unit_price": 10.0
    },
    {
      "description": "Widget B",
      "quantity": 2,
      "unit_price": 25.0
    }
  ]
}
```

**Equivalent YAML format (more compact):**

```yaml
vendor_info:
  name: ACME Corporation
  address: 123 Main St, City, State 12345
line_items:
  - description: Widget A
    quantity: 5
    unit_price: 10.00
  - description: Widget B
    quantity: 2
    unit_price: 25.00
```

### Backward Compatibility

- All existing JSON-based extraction prompts continue to work unchanged
- The system automatically detects and parses both formats
- No configuration changes required for existing deployments
- Intelligent fallback between formats if parsing fails

### Implementation Details

The extraction service uses the new `extract_structured_data_from_text()` function which:

- Automatically detects JSON vs YAML format
- Provides robust parsing with multiple extraction strategies
- Handles malformed content gracefully
- Returns both parsed data and detected format for logging
- Supports complex nested structures and arrays

### Token Efficiency Example

For a typical invoice extraction with 10 fields:

**JSON format (traditional):**

```json
{
  "invoice_number": "INV-2024-001",
  "invoice_date": "2024-03-15",
  "vendor_name": "ACME Corp",
  "total_amount": "1,234.56",
  "tax_amount": "123.45",
  "subtotal": "1,111.11",
  "due_date": "2024-04-15",
  "payment_terms": "Net 30",
  "customer_name": "John Smith",
  "customer_address": "456 Oak Ave, City, State 67890"
}
```

**YAML format (more efficient):**

```yaml
invoice_number: INV-2024-001
invoice_date: 2024-03-15
vendor_name: ACME Corp
total_amount: 1,234.56
tax_amount: 123.45
subtotal: 1,111.11
due_date: 2024-04-15
payment_terms: Net 30
customer_name: John Smith
customer_address: 456 Oak Ave, City, State 67890
```

The YAML version uses approximately 25% fewer tokens while maintaining the same information content.

## Traditional vs Agentic Extraction Comparison

The main performance difference is in the schema adherence over multiple invocations as the agent is required to validate against a
pydantic model and has a retry and review mechanisms over the single invocation of the traditional method.

## Best Practices

1. **Enable Agentic**:

2. **Clear Attribute Descriptions**: Include detail on where and how information appears in the document. More specific descriptions lead to better extraction results.

3. **Balance Precision and Recall**: Decide whether false positives or false negatives are more problematic for your use case and adjust the prompt accordingly.

4. **Optimize Few-Shot Examples**: Select diverse, representative examples that cover common variations in your document formats and challenging edge cases.

5. **Use CachePoint Strategically**: Position CachePoint tags to maximize caching of static content while isolating dynamic content, placing them right before document text is introduced.

6. **Leverage Image Examples**: When providing few-shot examples with `imagePath`, ensure the images highlight the key fields to extract, especially for visually complex documents.

7. **Monitor Evaluation Results**: Use the evaluation framework to identify extraction issues and iteratively refine your prompts and examples.

8. **Choose Appropriate Models**: Select models based on your task requirements:
   - `us.amazon.nova-pro-v1:0` - Best for complex extraction with few-shot learning
   - `us.anthropic.claude-3-5-haiku-20241022-v1:0` - Good balance of performance vs. cost
   - `us.anthropic.claude-3-7-sonnet-20250219-v1:0` - Highest accuracy for specialized tasks

For agentic extraction claude sonnet models are recommended.

9. **Handle Document Variations**: Consider creating separate document classes for significantly different layouts of the same document type rather than trying to handle all variations with a single class.

10. **Test Extraction Pipeline End-to-End**: Validate your extraction configuration with the full pipeline including OCR, classification, and extraction to ensure components work together effectively.

11. **Optimize Image Dimensions**: Configure image dimensions based on document complexity - use higher resolution for forms and tables, standard resolution for simple text documents.

12. **Balance Quality vs Performance**: Higher resolution images provide better extraction accuracy but consume more resources and processing time.
