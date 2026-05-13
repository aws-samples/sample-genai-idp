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

Use `get_evaluation_summary(batch_id)` to get classification metrics. Then check current classification config:

```
config_edit(config_path, operations=[
    {"op": "get", "field": "classification.classificationMethod"},
    {"op": "get", "field": "classification.contextPagesCount"},
    {"op": "get", "field": "classification.maxPagesForClassification"}
])
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

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classification.classificationMethod", "value": "textbasedHolisticClassification"},
    {"op": "save"}
])

# Or switch to page-level (default)
config_edit(config_path, operations=[
    {"op": "set", "field": "classification.classificationMethod", "value": "multimodalPageLevelClassification"},
    {"op": "save"}
])
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

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classification.contextPagesCount", "value": 1},
    {"op": "save"}
])

# Include 2 pages on each side for more context
config_edit(config_path, operations=[
    {"op": "set", "field": "classification.contextPagesCount", "value": 2},
    {"op": "save"}
])
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

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classification.maxPagesForClassification", "value": "3"},
    {"op": "save"}
])

# Classify all pages (default)
config_edit(config_path, operations=[
    {"op": "set", "field": "classification.maxPagesForClassification", "value": "ALL"},
    {"op": "save"}
])
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

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.document_name_regex", "value": "(?i).*(invoice|inv).*"},
    {"op": "set", "field": "classes.1.document_name_regex", "value": "(?i).*w-?2.*"},
    {"op": "save"}
])
```

### Page Content Regex

Matches against individual page text content during page-level classification. First matching pattern wins for that page.

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.document_page_content_regex", "value": "(?i)(invoice\\s+number|bill\\s+to|amount\\s+due)"},
    {"op": "set", "field": "classes.1.document_page_content_regex", "value": "(?i)(gross\\s+pay|net\\s+pay|employee\\s+id)"},
    {"op": "save"}
])
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

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.examples", "value": [
        {
            "classPrompt": "This is an example of the class 'Invoice'",
            "name": "InvoiceExample1",
            "attributesPrompt": "expected attributes are:\n    \"invoice_number\": \"INV-2024-001\",\n    \"vendor_name\": \"ACME Corp\",\n    \"total_amount\": \"$1,250.00\"",
            "imagePath": "path/to/example-invoice.jpg"
        }
    ]},
    {"op": "save"}
])
```

The `imagePath` field supports:
- Single image file: `'examples/invoice1.jpg'`
- Local directory (all images): `'examples/invoices/'`
- S3 URI: `'s3://bucket/examples/invoice1.jpg'`
- S3 prefix (all images): `'s3://bucket/examples/invoices/'`

### Step 2: Add Placeholder to Classification Prompt

The classification task prompt MUST include the `{FEW_SHOT_EXAMPLES}` placeholder for examples to be used:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classification.task_prompt", "value": "Classify this document into exactly one category from:\n{CLASS_NAMES_AND_DESCRIPTIONS}\n\nHere are examples of each document type:\n<few_shot_examples>\n{FEW_SHOT_EXAMPLES}\n</few_shot_examples>\n\nDocument text:\n{DOCUMENT_TEXT}\n\nReturn your classification in JSON format."},
    {"op": "save"}
])
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
   ```
   upload_config('workspace/updated-config.yaml', config_version='<version>', description='Classification strategy change')
   ```

2. Run evaluation:
   ```
   run_evaluation(test_set_id, context='Classification strategy change', config_version='<version>')
   ```

3. Compare classification metrics before/after using `get_evaluation_summary(batch_id)` on both the old and new batch IDs.

4. Success criteria:
   - Classification accuracy improved (or maintained with lower cost)
   - For regex bypass: verify matched documents are classified correctly and cost decreased
   - For few-shot: verify previously confused classes now have higher accuracy
