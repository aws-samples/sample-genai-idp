---
name: no-ground-truth-optimization
description: Best-effort config optimization when no ground truth baselines are available
---

# No Ground Truth Optimization

## Problem

The user has documents but no ground truth (baseline) data. Without ground truth, you cannot:
- Upload a test set to the test studio
- Run evaluations or compute accuracy metrics
- Use `compare_evaluations()` to objectively measure improvement
- Know the "correct" extraction output for any document

You must create the best possible configuration using qualitative analysis only.

## When This Applies

- User sets "Ground truth available: NO" in the OPTIMIZATION-LOG
- This is common for new engagements where the customer hasn't labeled any data yet

## Workflow

### 1. Schema Discovery (without ground truth)

`Discovery` works without ground truth — it examines the document and infers a schema:

```python
from idpac import Discovery, IDPConfig

discovery = Discovery(region='us-east-1')

# Discover schema from document only (no ground_truth_path argument)
schema = discovery.discover(document_path='samples/invoice.pdf')

config = IDPConfig.from_defaults('pattern-2')
config.set('classes', [schema])
config = config.auto_fix()
config.save('workspace/config-v1.yaml')
```

For multi-class datasets, discover from one sample per class. If the user has told you the class names, ask them to point you to one representative document per class.

### 2. Run Inference (not evaluation)

Use `run_inference()` instead of `run_evaluation()`. This processes documents through the full IDP pipeline without needing a test set:

```python
from idpac import IDPACClient

client = IDPACClient('my-stack', region='us-east-1')
client.upload_config('workspace/config-v1.yaml', config_version='v1', description='Initial discovery')

result = client.run_inference(
    documents_dir='/path/to/documents/',
    config_version='v1',
    number_of_files=10  # start with a small subset
)
batch_id = result['batch_id']
```

### 3. Download and Inspect Results

Download extraction output (not evaluation output):

```python
client.download_results(batch_id, 'workspace/results-v1/', file_types='sections')
```

This gives you `sections/1/result.json` per document — the raw extraction output.

You can also download OCR output for comparison:

```python
client.download_results(batch_id, 'workspace/results-v1/', file_types='all')
```

This includes `pages/N/rawText.json` (OCR text) and `pages/N/image.jpg` (page images).

### 4. Qualitative Analysis Checklist

For each document's extraction result, check:

1. **Field population**: Are all schema fields present in the output? Are any consistently null/empty that shouldn't be?
2. **Value plausibility**: Do extracted values look reasonable? (e.g., dates look like dates, amounts look like amounts, names look like names)
3. **OCR comparison**: Compare extracted values against the raw OCR text. If a value is clearly visible in the OCR text but missing or wrong in extraction, the schema description or prompt needs improvement.
4. **JSON integrity**: Is the output valid JSON? Any truncation (check for incomplete arrays or missing closing braces)?
5. **Classification** (multi-class only): Is the `document_class` field reasonable for each document?
6. **Consistency**: Do similar documents produce similar extraction patterns? Inconsistency suggests the prompt is ambiguous.

### 5. Common Issues and Fixes (without metrics)

| Observation | Likely Cause | Fix |
|---|---|---|
| Field consistently empty | Schema description too vague | Add specific description with examples of expected values |
| Wrong value extracted | Field name ambiguous | Add `description` with context: "The invoice number, usually in format INV-XXXX at top right" |
| JSON parse error | LLM wrapping output | Apply `json-output-fix` skill |
| Truncated output | Too many fields / line items | Apply `token-limit-fix` skill |
| Wrong document class | Class descriptions too similar | Improve `description` on each class schema to highlight distinguishing features |
| Values look hallucinated | Model too creative | Lower temperature via `inference-parameter-tuning` skill, or switch to a more grounded model |

### 6. Convergence Signals

Without accuracy metrics, stop iterating when:
- Extraction output is **consistent** across similar documents
- All expected fields are **populated** with plausible values
- No **JSON errors** or truncation
- Classification (if applicable) routes documents to **correct classes**
- You've done 3+ iterations with no observable improvement in output quality

### 7. Final Output Disclaimer

The final config MUST include a clear note in the OPTIMIZATION-LOG that:
- This config was created **without ground truth validation**
- No accuracy metrics are available — output quality was assessed qualitatively only
- The user should create ground truth baselines and run a proper evaluation to measure actual accuracy before using this config in production

## Skills That Still Apply Without Ground Truth

These skills are useful in no-GT mode:
- `extraction-prompt-engineering` — enriching schema descriptions
- `json-output-fix` — fixing JSON parse failures
- `token-limit-fix` — fixing truncated output
- `choosing-a-bedrock-model` — model selection
- `inference-parameter-tuning` — temperature, top_p, max_tokens
- `classification-tuning` — improving class descriptions and prompts
- `classification-strategy-selection` — choosing classification method
- `ocr-configuration` — OCR backend and settings
- `multilingual-documents` — non-English document handling
- `nested-schema-design` — schema structure
- `boolean-field-extraction` — boolean field handling
- `prompt-caching-optimization` — cost reduction

## Skills That Do NOT Apply Without Ground Truth

These skills require accuracy metrics and are not useful:
- `evaluation-method-tuning` — requires evaluation scores
- `sparse-field-metric-selection` — requires field-level metrics
- `ground-truth-quality-analysis` — no ground truth to analyze
- `data-completeness-analysis` — requires ground truth field population data
- `iterative-schema-refinement` — orchestrates based on accuracy patterns
- `confidence-threshold-tuning` — requires accuracy baselines
