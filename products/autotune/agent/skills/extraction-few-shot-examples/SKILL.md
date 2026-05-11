---
name: extraction-few-shot-examples
description: Improve extraction accuracy by providing concrete example documents with expected outputs. Use when prompt engineering alone isn't achieving target accuracy, especially for rare attributes, complex layouts, or domain-specific documents.
---

# Extraction Few-Shot Examples

## Problem

Some extraction tasks remain inaccurate despite good field descriptions and prompt engineering. The LLM needs to see concrete examples of correct extractions — actual document images paired with expected JSON output — to understand the extraction patterns for complex or domain-specific documents.

Few-shot examples are especially effective for:
- Rare attributes that appear infrequently and have low accuracy
- Complex document layouts where field locations vary
- Domain-specific formats that are hard to describe in text alone
- Documents where visual context is critical for correct extraction

In past engagements, adding image-integrated few-shot examples was recommended as a key strategy for improving KIE accuracy on complex document types (e.g., regulatory forms, compliance documents, specialized industry records). Accuracy drops of 30-50% were observed when removing OCR, reinforcing that few-shot examples work best alongside OCR text — the combination of visual examples plus text context gives the LLM the strongest signal.

## Symptoms

- Per-field accuracy is low for specific attributes despite enriched field descriptions
- Rare or infrequent attributes consistently score poorly
- The LLM extracts values in the wrong format or from the wrong location on the page
- Documents have complex visual layouts that are hard to describe in prompt text
- Prompt engineering has plateaued — further description enrichment yields diminishing returns

## Diagnosis

```python
from idpac import IDPACClient, IDPConfig
from idpac.evaluations import EvaluationResult

client = IDPACClient('stack-name', region='us-east-1')
summary = client.get_evaluation_summary('batch-id', 'results/summary.json')

result = EvaluationResult.from_aggregated_file('results/summary.json')
result.print_aggregated_summary(top_bottom_n=5)

# Identify fields with low accuracy that might benefit from examples
# Then check if few-shot examples are already configured
config = IDPConfig('workspace/current-config.yaml')
for i, cls in enumerate(config.get('classes')):
    examples = cls.get('x-aws-idp-examples', [])
    print(f"Class '{cls.get('$id')}': {len(examples)} extraction examples")
```

If accuracy is low on specific fields and no few-shot examples are configured, adding examples is likely to help.

## Fix 1: Add Few-Shot Examples to a Document Class

Each example needs: a name, an attributes prompt showing expected extraction output, and optionally an image path.

```python
from idpac import IDPConfig

config = IDPConfig('workspace/current-config.yaml')

# Add few-shot examples to the class
config.set('classes.0.x-aws-idp-examples', [
    {
        'name': 'Example1',
        'attributesPrompt': '''expected attributes are:
    "invoice_number": "INV-2024-001",
    "invoice_date": "2024-01-15",
    "vendor_name": "ACME Corp",
    "total_amount": "1250.00",
    "line_items": [
        {"description": "Widget A", "quantity": "10", "unit_price": "100.00"},
        {"description": "Widget B", "quantity": "5", "unit_price": "50.00"}
    ]''',
        'imagePath': 'path/to/example-invoice1.jpg'
    },
    {
        'name': 'Example2',
        'attributesPrompt': '''expected attributes are:
    "invoice_number": "INV-2024-002",
    "invoice_date": "2024-02-20",
    "vendor_name": "Global Supplies Inc",
    "total_amount": "3400.00",
    "line_items": [
        {"description": "Service Fee", "quantity": "1", "unit_price": "3400.00"}
    ]''',
        'imagePath': 'path/to/example-invoice2.jpg'
    }
])

config.save('workspace/updated-config.yaml')
```

### Example Fields

| Field | Required for Extraction | Purpose |
|-------|------------------------|---------|
| `name` | Yes | Unique identifier for the example |
| `attributesPrompt` | Yes | Expected extraction output in JSON-like format. Examples without this field are skipped during extraction. |
| `imagePath` | No (but recommended) | Path to example document image. Supports single file, local directory, S3 URI, or S3 prefix. |
| `classPrompt` | No (classification only) | Description for classification. Not needed if you only want extraction examples. |

**Processing rule**: An example is only included in extraction prompts if it has a non-empty `attributesPrompt`. An example is only included in classification prompts if it has a non-empty `classPrompt`. An example with both fields is used for both tasks.

## Fix 2: Add the FEW_SHOT_EXAMPLES Placeholder to the Extraction Prompt

The extraction task prompt **must** include the `{FEW_SHOT_EXAMPLES}` placeholder for examples to be injected. Without this placeholder, examples are configured but never used.

```python
from idpac import IDPConfig

config = IDPConfig('workspace/current-config.yaml')

config.set('extraction.task_prompt', '''Extract the following fields from this {DOCUMENT_CLASS} document:

{ATTRIBUTE_NAMES_AND_DESCRIPTIONS}

Here are examples of correct extractions for this document type:
<few_shot_examples>
{FEW_SHOT_EXAMPLES}
</few_shot_examples>

Now extract the attributes from this document:
{DOCUMENT_TEXT}

{DOCUMENT_IMAGE}

Return your response as valid JSON.''')

config.save('workspace/updated-config.yaml')
```

Examples are class-specific — only examples from the same document class being processed are included in the prompt.

## Fix 3: Show Null Values Explicitly

When a field is absent from an example document, explicitly show it as null. This teaches the LLM when to return null vs. when to extract a value:

```python
config.set('classes.0.x-aws-idp-examples', [
    {
        'name': 'TaskCardExample1',
        'attributesPrompt': '''expected attributes are:
    "work_order_number": "WO-2024-1234",
    "equipment_id": "EQ-12345",
    "serial_number": "SN-98765",
    "equipment_model": "Model X-800",
    "operating_hours": "45230.5",
    "cycle_count": "22150",
    "compliance_date": "2024-03-15",
    "component_serial_no": null,
    "component_part_no": null''',
        'imagePath': 'examples/task-card-1.jpg'
    }
])
```

This is especially important for fields that are legitimately absent in some documents — it prevents the LLM from hallucinating values.

## Fix 4: Use Multiple Diverse Examples

Include examples that cover different variations within the document class:

```python
examples = [
    {
        'name': 'SimpleInvoice',
        'attributesPrompt': '''expected attributes are:
    "invoice_number": "INV-001",
    "line_items": [
        {"description": "Consulting", "quantity": "1", "unit_price": "5000.00"}
    ]''',
        'imagePath': 'examples/simple-invoice.jpg'
    },
    {
        'name': 'ComplexInvoice',
        'attributesPrompt': '''expected attributes are:
    "invoice_number": "2024-INV-0042",
    "line_items": [
        {"description": "Part A", "quantity": "100", "unit_price": "12.50"},
        {"description": "Part B", "quantity": "50", "unit_price": "25.00"},
        {"description": "Shipping", "quantity": "1", "unit_price": "45.00"}
    ]''',
        'imagePath': 'examples/complex-invoice.jpg'
    }
]

config.set('classes.0.x-aws-idp-examples', examples)
```

**Best practices for example selection:**
- Use 1-3 examples per class (more adds token cost with diminishing returns)
- Include a simple case and a complex case
- Cover different format variations (e.g., different date formats, different layouts)
- Choose clear, high-quality document images
- Ensure examples are representative of the class, not edge cases

## Fix 5: Image Path Options

The `imagePath` field supports multiple formats:

```python
# Single image file
'imagePath': 'examples/invoice1.jpg'

# Local directory (all images included, sorted alphabetically)
'imagePath': 'examples/invoice-pages/'

# S3 URI (single image)
'imagePath': 's3://my-bucket/examples/invoice1.jpg'

# S3 prefix (all images under prefix)
'imagePath': 's3://my-bucket/examples/invoices/'
```

For multi-page documents, use a directory or S3 prefix containing one image per page. The system discovers all image files (`.jpg`, `.jpeg`, `.png`, `.gif`, `.bmp`, `.tiff`, `.tif`, `.webp`) and includes them sorted alphabetically.

## Fix 6: Text-Only Examples (When Images Aren't Available)

If example images aren't available, you can include sample OCR text in the `attributesPrompt` to still provide context:

```python
config.set('classes.0.x-aws-idp-examples', [
    {
        'name': 'TextOnlyExample',
        'attributesPrompt': '''For a document containing:
    "INVOICE #: INV-2024-001
     Date: January 15, 2024
     Bill To: ACME Corp
     Total: $1,250.00"

    expected attributes are:
    "invoice_number": "INV-2024-001",
    "invoice_date": "2024-01-15",
    "vendor_name": null,
    "customer_name": "ACME Corp",
    "total_amount": "1250.00"'''
    }
])
```

Text-only examples are less effective than multimodal examples but still provide significant accuracy improvements over no examples.

## Fix 7: Combine with Prompt Caching

Few-shot examples with images are expensive in token cost. Combine with the `<<CACHEPOINT>>` delimiter to cache the examples across documents:

```python
config.set('extraction.task_prompt', '''Extract the following fields from this {DOCUMENT_CLASS} document:

{ATTRIBUTE_NAMES_AND_DESCRIPTIONS}

<few_shot_examples>
{FEW_SHOT_EXAMPLES}
</few_shot_examples>

<<CACHEPOINT>>

Now extract from this document:
{DOCUMENT_TEXT}

{DOCUMENT_IMAGE}

Return valid JSON.''')
```

See the `prompt-caching-optimization` skill for details on cachepoint placement and model compatibility.

## Interaction with Other Skills

- **`prompt-caching-optimization`**: Always combine few-shot examples with cachepoint to reduce the token cost of examples.
- **`extraction-prompt-engineering`**: Few-shot examples complement field description enrichment. Use both — descriptions tell the LLM what to extract, examples show it how.
- **`classification-strategy-selection`**: That skill covers few-shot for classification (Fix 5). This skill covers few-shot for extraction. An example can serve both purposes if it has both `classPrompt` and `attributesPrompt`.
- **`choosing-a-bedrock-model`**: Stronger models benefit more from few-shot examples. If using a weaker model, few-shot may have less impact.

## Verification

1. Run evaluation without few-shot examples as baseline
2. Add examples and the `{FEW_SHOT_EXAMPLES}` placeholder
3. Upload updated config and re-run evaluation
4. Compare per-field accuracy, focusing on the fields that were previously low:
   ```python
   old_result = EvaluationResult.from_aggregated_file('results/old-summary.json')
   new_result = EvaluationResult.from_aggregated_file('results/new-summary.json')
   
   old_result.print_aggregated_summary(top_bottom_n=5)
   new_result.print_aggregated_summary(top_bottom_n=5)
   ```
5. Check that adding examples didn't regress other fields
6. Monitor cost impact — few-shot examples increase input tokens (mitigate with cachepoint)
