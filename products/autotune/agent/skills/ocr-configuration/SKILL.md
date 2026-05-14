---
name: ocr-configuration
description: Configure OCR settings including backend selection (Textract vs Bedrock), features, and image processing. Use when setting up OCR or troubleshooting text extraction issues.
---

# OCR Configuration

## Why OCR Exists in Pattern-2

Pattern-2 is **multimodal** - prompts contain both `{DOCUMENT_TEXT}` (OCR) and `{DOCUMENT_IMAGE}`:

```
<document-ocr-data> {DOCUMENT_TEXT} </document-ocr-data>
<document-image> {DOCUMENT_IMAGE} </document-image>
```

**Why both?**
- **OCR text**: Clean, searchable text for finding values/keywords. Fast for LLM to parse.
- **Image**: Visual context - layout, logos, signatures, checkboxes, spatial relationships.
- **Together**: Better accuracy than either alone. LLM gets clean text + visual disambiguation. In practice, adding OCR text to image-only extraction has been observed to improve F1 by ~7 percentage points (e.g., 0.63 → 0.70), at the cost of only 1,000–2,000 additional input tokens per document.

**When to disable OCR (`backend: none`)**:
- Simple documents where visual-only is sufficient
- Using highly capable multimodal model that can read images directly
- Want to reduce pipeline complexity/cost and accept potential accuracy tradeoff

**Important**: Disabling OCR to save cost is rarely worth it. The token overhead of OCR text is small relative to image tokens, and the accuracy gain is substantial. Always benchmark with and without OCR on your dataset before deciding to disable it.

**Note on category-level variation**: While Image+OCR is best overall, specific field categories may behave differently. In some datasets, fields that rely heavily on structured tabular data perform better with OCR-only than with Image+OCR, because images can introduce visual ambiguity for fields that are purely text-based. If a specific field category underperforms with the hybrid approach, experiment with the OCR-only modality for comparison.

For most production use cases, keep OCR enabled (hybrid approach).

## OCR Backends

| Backend | Speed | Cost | Language Support | Use Case |
|---------|-------|------|------------------|----------|
| `textract` | Fast | Low | 6 languages | Default for English/European docs |
| `bedrock` | Slow | High | All languages | Non-Latin scripts, complex layouts |
| `none` | N/A | N/A | N/A | Multimodal LLM extraction (no OCR) |

## Checking Current Config

```
config_edit(config_path, operations=[
    {"op": "get", "field": "ocr.backend"},
    {"op": "get", "field": "ocr.features"}
])
```

## Backend Selection

### Textract (Default)
For: English, Spanish, German, French, Italian, Portuguese.
```
config_edit(config_path, operations=[
    {"op": "set", "field": "ocr.backend", "value": "textract"},
    {"op": "set", "field": "ocr.features", "value": [{"name": "LAYOUT"}]},
    {"op": "save"}
])
```

### Bedrock LLM OCR
Required for: Chinese, Japanese, Korean, Arabic, Hebrew, Hindi, Thai, Vietnamese, Russian.
```
config_edit(config_path, operations=[
    {"op": "set", "field": "ocr.backend", "value": "bedrock"},
    {"op": "set", "field": "ocr.model_id", "value": "us.amazon.nova-2-lite-v1:0"},
    {"op": "set", "field": "ocr.system_prompt", "value": "You are an expert OCR system. Extract all text accurately, preserving layout."},
    {"op": "set", "field": "ocr.task_prompt", "value": "Extract all text from this document image. Preserve layout, paragraphs, and tables."},
    {"op": "save"}
])
```

### None (Skip OCR)
For multimodal extraction where LLM reads images directly.
```
config_edit(config_path, operations=[
    {"op": "set", "field": "ocr.backend", "value": "none"},
    {"op": "save"}
])
```

## Textract Features

| Feature | Purpose |
|---------|---------|
| `LAYOUT` | Preserves document structure (recommended default) |
| `TABLES` | Extracts table structures |
| `FORMS` | Extracts key-value pairs |
| `SIGNATURES` | Detects signatures |

```
config_edit(config_path, operations=[
    {"op": "set", "field": "ocr.features", "value": [{"name": "LAYOUT"}, {"name": "TABLES"}]},
    {"op": "save"}
])
```

## Image Settings

```
config_edit(config_path, operations=[
    {"op": "set", "field": "ocr.image.dpi", "value": 150},
    {"op": "set", "field": "ocr.image.target_width", "value": 1200},
    {"op": "set", "field": "ocr.image.target_height", "value": 900},
    {"op": "set", "field": "ocr.image.preprocessing", "value": true},
    {"op": "save"}
])
```

## Decision Tree

```
Document language?
├─ English/European → Textract (default)
├─ Chinese/Japanese/Korean/Arabic/etc → Bedrock (required)
└─ Mixed/unsure → Bedrock (safest)
```

## Textract Feature Selection Guide

Textract offers two modes: basic text detection (`DetectDocumentText`) and full analysis (`AnalyzeDocument` with features like LAYOUT, TABLES, FORMS). Choosing the right feature combination balances accuracy against token cost.

### Feature Combination Performance

Ablation studies on real-world document datasets show all Textract feature combinations achieve comparable overall accuracy (within ~1-2 percentage points). However, category-level differences can be significant:

| Configuration | Overall | Structured/Tabular Fields | Form Key-Value Fields | Tokens/Page |
|---------------|---------|---------------------------|----------------------|-------------|
| Layout+Tables+Forms | ~84-85% | Best | Best (+5-7pp over Layout-only) | ~4,400 |
| Layout+Tables | ~84-85% | Good (+2pp over Layout-only) | Comparable to Layout-only | ~4,400 |
| Layout only | ~83-84% | Baseline | Baseline | ~3,900 |
| Tables only | ~83-84% | Good for tabular data | No form support | ~4,400 |

Key findings:
- **Layout+Tables is the recommended default** — it provides the best balance of accuracy and cost
- **Tables feature** specifically helps fields that live in tabular structures (e.g., citation data, line items). In one study, Tables improved tabular field accuracy from 66.7% to 73.7%
- **Forms feature** adds minimal value over Layout+Tables (only ~0.16 percentage points improvement) despite higher processing cost. Only add Forms if form key-value pair extraction is critical to your use case
- **Tables+Forms for checkbox extraction**: When documents contain checkboxes, tick marks, or form fields with selectable options, enabling both TABLES and FORMS features substantially improves OCR discrimination between selected and unselected checkboxes. In past engagements, this was a prerequisite for accurate checkbox attribute extraction — without these features, the LLM struggled to distinguish checked vs unchecked boxes from the OCR text alone
- **Layout-only** uses ~11% fewer input tokens than Layout+Tables+Forms, which matters at scale

### Decision Guide

```
What field types matter most?
├─ Tabular data (line items, citations, coded fields)
│   └─ Use Layout+Tables (recommended default)
├─ Checkboxes, tick marks, or selectable form fields
│   └─ Use Layout+Tables+Forms (critical for checkbox discrimination)
├─ Form key-value pairs are business-critical
│   └─ Use Layout+Tables+Forms
├─ Simple text extraction, cost-sensitive
│   └─ Use Layout-only or detect-text-only
└─ Unsure
    └─ Start with Layout+Tables, benchmark, then adjust
```

```
# Recommended default: Layout+Tables
config_edit(config_path, operations=[{"op": "set", "field": "ocr.features", "value": [{"name": "LAYOUT"}, {"name": "TABLES"}]}, {"op": "save"}])

# Cost-optimized: Layout only (~11% fewer tokens)
config_edit(config_path, operations=[{"op": "set", "field": "ocr.features", "value": [{"name": "LAYOUT"}]}, {"op": "save"}])

# Maximum features (rarely needed)
config_edit(config_path, operations=[{"op": "set", "field": "ocr.features", "value": [{"name": "LAYOUT"}, {"name": "TABLES"}, {"name": "FORMS"}]}, {"op": "save"}])

# Detect text only (lowest cost, often sufficient for simple documents)
config_edit(config_path, operations=[{"op": "set", "field": "ocr.features", "value": []}, {"op": "save"}])
```

Always benchmark different feature combinations on your specific dataset before finalizing. The optimal configuration depends on which field categories are most important to business requirements.

## Long and Low-Quality Documents

### Image Quality Settings

For documents with poor scan quality, small text, or historical/degraded documents, tune image settings to give the LLM better visual input:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "ocr.image.dpi", "value": 300},
    {"op": "set", "field": "ocr.image.target_width", "value": 2400},
    {"op": "set", "field": "ocr.image.target_height", "value": 1800},
    {"op": "set", "field": "ocr.image.preprocessing", "value": true},
    {"op": "save"}
])
```

These same settings apply per-task (`extraction.image.*`, `classification.image.*`) if you need different image quality for different pipeline stages.

### Long Documents

IDP uses image blocks (converting each PDF page to an image) for LLM calls. This is the most reliable approach — it avoids JSON parsing failures and format compliance issues that can occur with alternative document representation methods. There is no page limit in the current Bedrock API.

For very long documents (20+ pages), be aware of:
- **Token usage**: Each page image consumes significant input tokens. Monitor costs.
- **max_tokens**: Ensure `extraction.max_tokens` is large enough for the expected output size. Long documents with many fields/line items need higher limits.
- **OCR text length**: Long documents produce large OCR text blocks. The combined OCR text + images may approach model context limits.

```
# For long documents, ensure sufficient output tokens
config_edit(config_path, operations=[
    {"op": "set", "field": "extraction.max_tokens", "value": 65535},
    {"op": "save"}
])
```

## Troubleshooting

**Garbled text**: Using Textract on unsupported language → switch to Bedrock.

**Tables extracted wrong**: Enable TABLES feature.

**Small text missing**: Increase DPI and image size.

**Poor accuracy on old/degraded scans**: Increase DPI to 300, enable preprocessing, increase image dimensions.
