---
name: classification-strategy-selection
description: Choose and configure the optimal classification strategy for multi-class and packet-splitting datasets. Covers method selection (holistic vs page-level), context pages, max pages limit, regex bypass, and few-shot examples. Use when classification accuracy plateaus despite prompt tuning, or when optimizing classification cost.
---

# Classification Strategy Selection

## Problem

The IDP accelerator supports multiple classification strategies and advanced parameters beyond just prompts and class descriptions. Choosing the wrong method or missing available optimizations leads to suboptimal accuracy, unnecessary cost, or both.

## Symptoms

- Classification accuracy plateaus despite good class descriptions and prompt tuning
- High classification cost on large documents (many pages classified unnecessarily)
- Boundary detection errors in packet-splitting (pages merged or split incorrectly)
- Documents with predictable naming or content patterns still incur full LLM classification cost
- Confusable classes remain confused despite description improvements

## Diagnosis

```python
from idpac import IDPACClient, IDPConfig
from idpac.evaluations import EvaluationResult

client = IDPACClient('stack-name', region='us-east-1')
summary = client.get_evaluation_summary('batch-id', 'results/summary.json')
result = EvaluationResult.from_aggregated_file('results/summary.json')

# Check current classification config
config = IDPConfig('workspace/current-config.yaml')
method = config.get('classification.classificationMethod')
context = config.get('classification.contextPagesCount')
max_pages = config.get('classification.maxPagesForClassification')
print(f"Method: {method}, Context pages: {context}, Max pages: {max_pages}")

# Check classification metrics
result.print_classification_summary()  # multi-class
result.print_split_summary()           # packet-splitting
```

Use this decision table to identify which fix to apply:

| Situation | Fix |
|-----------|-----|
| Page-level accuracy low, documents are text-heavy with weak visual cues | Try holistic method |
| Holistic accuracy low, documents have strong visual/layout differences | Try page-level method |
| Page-level boundary detection poor (split_accuracy << page_accuracy) | Increase `contextPagesCount` |
| High classification cost, large documents | Reduce `maxPagesForClassification` |
| Documents have predictable filenames or distinctive text markers | Add regex bypass |
| Confusable classes despite good descriptions | Add few-shot examples |

---

## Fix 1: Choose Classification Method

IDP supports two classification methods. The default is page-level, but holistic may be better depending on the document characteristics.

### Page-Level (`multimodalPageLevelClassification`) — Default
- Classifies each page independently, then groups pages into sections using BIO-like start/continue boundary signals
- Sends both page image AND OCR text to the LLM
- Pages classified in parallel (fast for large documents)
- Best for: visually distinct document types, image-heavy documents, large page counts, packet-splitting

### Holistic (`textbasedHolisticClassification`)
- Sends ALL pages' text at once with `<page-number>` tags, LLM returns segment ranges
- Text-only (no images sent to LLM)
- Single LLM call for entire document
- Best for: text-heavy documents where cross-page context matters, documents with weak per-page visual cues, smaller documents (<50 pages)

```python
from idpac import IDPConfig

config = IDPConfig('workspace/current-config.yaml')

# Switch to holistic method
config.set('classification.classificationMethod', 'textbasedHolisticClassification')

# Or switch to page-level (default)
config.set('classification.classificationMethod', 'multimodalPageLevelClassification')

config.save('workspace/updated-config.yaml')
```

**Decision guide:**

| Factor | Page-Level | Holistic |
|--------|-----------|----------|
| Document visual cues | Strong (logos, layouts, headers) | Weak (similar formatting) |
| Page count | Any (parallelized) | <50 recommended (single call) |
| Image importance | High (images sent to LLM) | Low (text-only) |
| Cross-page context needed | No (or use contextPagesCount) | Yes (sees all pages at once) |
| Packet-splitting | Recommended default | Can work, but no image support |
| Cost profile | Per-page LLM calls | Single LLM call (but large input) |

---

## Fix 2: Tune Context Pages (Page-Level Only)

When using page-level classification, `contextPagesCount` includes neighboring pages as context to improve boundary detection. The LLM sees the target page plus N pages before and after it.

Context is wrapped in XML tags:
- `<context-pages-before>` — text from preceding pages
- `<current-page>` — the page being classified
- `<context-pages-after>` — text from following pages

Both text AND images are included for context pages.

```python
from idpac import IDPConfig

config = IDPConfig('workspace/current-config.yaml')

# Include 1 page before and after as context (default: 0)
config.set('classification.contextPagesCount', 1)

# Include 2 pages on each side for more context
config.set('classification.contextPagesCount', 2)

config.save('workspace/updated-config.yaml')
```

**When to use:**
- `split_accuracy` is significantly lower than `page_level_accuracy` (boundary detection failing)
- Documents have ambiguous boundaries that require seeing adjacent pages
- Start with 1, increase to 2 only if needed — each increment multiplies token cost

**When NOT to use:**
- Page-level accuracy is already high
- Documents have clear visual boundaries (different layouts per type)
- Cost is a primary concern (context pages multiply input tokens)

---

## Fix 3: Limit Max Pages for Classification

For large documents where the first few pages are sufficient to determine the document type, limit how many pages are classified to reduce cost.

```python
from idpac import IDPConfig

config = IDPConfig('workspace/current-config.yaml')

# Only classify first 3 pages (default: 'ALL')
config.set('classification.maxPagesForClassification', '3')

# Classify all pages (default)
config.set('classification.maxPagesForClassification', 'ALL')

config.save('workspace/updated-config.yaml')
```

Valid values: `'ALL'`, `'1'`, `'2'`, `'3'`, `'5'`, `'10'`

**When to use:**
- Single-document files (not packet-splitting) where type is clear from first pages
- Cost optimization on large documents (50+ pages)
- Document type is always identifiable from the cover page or first few pages

**When NOT to use:**
- Packet-splitting datasets (need all pages classified for boundary detection)
- Documents where type-identifying content appears later in the document

---

## Fix 4: Add Regex Bypass for Known Patterns

When documents have predictable filenames or distinctive text markers, regex bypass provides instant, zero-cost, deterministic classification without any LLM call.

### Document Name Regex

Matches against the document filename/ID. If matched, ALL pages are classified as that class instantly.

```python
from idpac import IDPConfig

config = IDPConfig('workspace/current-config.yaml')

# Add regex to match filenames containing "invoice" (case-insensitive)
config.set('classes.0.document_name_regex', '(?i).*(invoice|inv).*')

# Match W-2 tax forms by filename
config.set('classes.1.document_name_regex', '(?i).*w-?2.*')

config.save('workspace/updated-config.yaml')
```

### Page Content Regex

Matches against individual page text content during page-level classification. First matching pattern wins for that page.

```python
from idpac import IDPConfig

config = IDPConfig('workspace/current-config.yaml')

# Match pages containing invoice-specific terms
config.set('classes.0.document_page_content_regex',
    '(?i)(invoice\\s+number|bill\\s+to|amount\\s+due)')

# Match pages containing payslip-specific terms
config.set('classes.1.document_page_content_regex',
    '(?i)(gross\\s+pay|net\\s+pay|employee\\s+id)')

config.save('workspace/updated-config.yaml')
```

**Regex best practices:**
- Use `(?i)` for case-insensitive matching
- Use `\\s+` for flexible whitespace
- Use `|` for multiple alternative terms
- Be specific enough to avoid false matches across classes
- Test patterns against sample document text before deploying

**When to use:**
- Documents have reliable naming conventions
- Document types have distinctive, unique text markers
- High-volume processing where cost savings matter
- You want deterministic, reproducible classification

**When NOT to use:**
- Document names are generic (e.g., `scan001.pdf`)
- Text markers overlap between classes
- Document content varies significantly within a class

---

## Fix 5: Add Few-Shot Examples

Few-shot examples provide concrete reference documents with known classifications, helping the LLM understand what each class looks like. This is especially effective for confusable classes.

### Step 1: Add Examples to Class Definitions

Each example needs: a class prompt, a name, an attributes prompt, and an image path.

```python
from idpac import IDPConfig

config = IDPConfig('workspace/current-config.yaml')

# Add few-shot example to first class
config.set('classes.0.examples', [
    {
        'classPrompt': "This is an example of the class 'Invoice'",
        'name': 'InvoiceExample1',
        'attributesPrompt': 'expected attributes are:\n    "invoice_number": "INV-2024-001",\n    "vendor_name": "ACME Corp",\n    "total_amount": "$1,250.00"',
        'imagePath': 'path/to/example-invoice.jpg'
    }
])

config.save('workspace/updated-config.yaml')
```

The `imagePath` field supports:
- Single image file: `'examples/invoice1.jpg'`
- Local directory (all images): `'examples/invoices/'`
- S3 URI: `'s3://bucket/examples/invoice1.jpg'`
- S3 prefix (all images): `'s3://bucket/examples/invoices/'`

### Step 2: Add Placeholder to Classification Prompt

The classification task prompt MUST include the `{FEW_SHOT_EXAMPLES}` placeholder for examples to be used:

```python
config.set('classification.task_prompt', '''Classify this document into exactly one category from:
{CLASS_NAMES_AND_DESCRIPTIONS}

Here are examples of each document type:
<few_shot_examples>
{FEW_SHOT_EXAMPLES}
</few_shot_examples>

Document text:
{DOCUMENT_TEXT}

Return your classification in JSON format.''')

config.save('workspace/updated-config.yaml')
```

**Best practices:**
- Use 1-3 high-quality, representative examples per class
- Include diverse examples that cover different variations within a class
- Ensure example images are clear and readable
- Show null values explicitly for fields that are absent in the example
- For confusable classes, choose examples that highlight the distinguishing features

**When to use:**
- Two or more classes are frequently confused despite good descriptions
- Classification accuracy is below target after tuning descriptions and model
- Documents have subtle visual or structural differences between classes

**When NOT to use:**
- Classification accuracy is already high
- No representative example images are available
- Adding examples would exceed the model's context window

---

## Verification

After applying any fix:

1. Upload updated config:
   ```python
   client.upload_config('workspace/updated-config.yaml', config_version='<version>', description='Classification strategy change')
   ```

2. Run evaluation:
   ```python
   result = client.run_evaluation('test-set-id', context='Classification strategy change', config_version='<version>')
   ```

3. Compare classification metrics before/after:
   ```python
   new_result = EvaluationResult.from_aggregated_file('results/new-summary.json')
   new_result.print_classification_summary()  # multi-class
   new_result.print_split_summary()           # packet-splitting
   ```

4. Success criteria:
   - Classification accuracy improved (or maintained with lower cost)
   - For regex bypass: verify matched documents are classified correctly and cost decreased
   - For few-shot: verify previously confused classes now have higher accuracy
