---
name: data-completeness-analysis
description: Analyze field population rates across a dataset to identify ground truth quality issues, distinguish missing annotations from intentionally empty fields, and prioritize optimization effort. Use before starting optimization or when accuracy plateaus unexpectedly.
---

# Data Completeness Analysis

## Problem

Before optimizing extraction, you need to understand the dataset's field population patterns. Fields that are empty in most documents (high null rate) may be:

1. **Intentionally empty**: The field genuinely doesn't apply to that document (e.g., "Waiver Type" on a Contract document). These should be marked "N/A" or null in ground truth.
2. **Missing annotations**: The keyer/annotator skipped the field or didn't fill it in. These are ground truth errors that will cause false negatives.
3. **Conditionally populated**: The field only applies in certain scenarios (e.g., "Sublicense Allowed?" only when sublicensing is discussed). These are legitimately sparse.

Without this analysis, the optimizer will waste cycles trying to improve extraction for fields where the ground truth itself is incomplete, or will misinterpret high null rates as extraction failures.

Past engagements have found this analysis critical — SMEs reviewing data completeness charts identified truly missing values that needed to be provided, and explicitly confirmed intentionally empty fields. This distinction between missing annotations and confirmed empty fields directly impacted the accuracy of the evaluation pipeline.

## When to Use

- **Before starting optimization**: Run this as part of initial dataset exploration (Step 5 in the IDPAC workflow) to understand the dataset before tuning anything.
- **When accuracy plateaus**: If accuracy stops improving despite prompt/schema changes, check whether ground truth completeness is the bottleneck.
- **When null rates seem suspicious**: If a field you expect to be populated in most documents has a high null rate, investigate.

## Diagnosis

### Step 1: Compute Field Density

Use `analyze_dataset(dataset_path)` after downloading the test set with `download_test_set(test_set_id)`. This reports field density information including sparse fields.

For more detailed per-field density analysis, use `execute_python_analysis` with the downloaded ground truth files to compute exact population rates per field.

### Step 2: Analyze Per-Class Density (Multi-Class Datasets)

For multi-class datasets, null rates vary by class. A field that's always populated for Contracts may be always empty for Waivers. Use `execute_python_analysis` with the downloaded ground truth files to compute per-class density.

### Step 3: Identify Suspicious Patterns

Look for these red flags:

| Pattern | Likely Cause | Action |
|---------|-------------|--------|
| Field is 0% populated across ALL classes | Field doesn't exist in documents, or GT is systematically missing it | Flag to human — is this field extractable? |
| Field is 0% populated in one class but >50% in another | Field doesn't apply to that class | Normal — ensure schema handles this correctly |
| Field is 5-15% populated but you expect it in most documents | Missing annotations in GT | Flag to human — GT may need correction |
| Core field (e.g., "Contract Type") has <100% density | GT errors on specific documents | Investigate those specific documents |
| Boolean field has very low density | May be confused with N/A handling | See `boolean-field-extraction` skill |

### Step 4: Spot-Check Suspicious Fields

For fields with unexpected null rates, examine a few documents. Use `download_ground_truth(test_set_id, filename)` to get the ground truth for specific documents, then use `execute_python_analysis` to inspect which fields are empty.

Then download and visually inspect those documents to determine if the field is genuinely absent or if the annotation was missed.

## Actions

### Action 1: Flag Findings to Human

Present the data completeness analysis clearly:

> "I've analyzed field population rates across the dataset. Key findings:
>
> - **[N] fields are always empty** (0% populated across all documents).
>   These may not be extractable from the documents, or the ground truth
>   annotations may be incomplete.
> - **[N] fields are sparsely populated** (<10%). This is expected for
>   conditional fields but may indicate missing annotations for others.
> - **[Field X]** is only [Y%] populated but seems like it should appear
>   in most documents. This may be a ground truth gap.
>
> Can you confirm:
> 1. Are the always-empty fields expected to be empty, or should they have values?
> 2. For [Field X], is the low population rate correct or are annotations missing?
> 3. For fields that are intentionally empty, should the ground truth use 'N/A'
>    or null to distinguish from missing annotations?"

### Action 2: Record in Optimization Log

Document the analysis in the OPTIMIZATION-LOG.md:

```markdown
## Data Completeness Analysis

Field population density across [N] documents:
- Dense (>50%): [N] fields
- Medium (10-50%): [N] fields  
- Sparse (<10%): [N] fields
- Always empty (0%): [N] fields

### Always-Empty Fields (require human confirmation)
- [field1]: 0% across all classes
- [field2]: 0% across all classes

### Suspicious Low Density (may be GT gaps)
- [field3]: 8% populated, expected higher
- [field4]: 12% populated in Contract class, 0% in Amendment class

ACTION REQUIRED: Human review needed to confirm whether empty fields
are intentionally empty or missing annotations.
```

### Action 3: Adjust Optimization Strategy Based on Findings

- **Always-empty fields**: Set `x-aws-idp-evaluation-weight: 0` until human confirms whether they should be populated. Don't waste optimization effort on them.
- **Sparse fields**: Consider using Accuracy rather than F1 as the primary metric (see `sparse-field-metric-selection` skill).
- **Missing annotations confirmed**: Work with human to fix ground truth before continuing optimization.
- **Intentionally empty fields confirmed**: Ensure the schema and prompts handle the empty case correctly (return null or "N/A" as appropriate).

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.properties.<field1>.x-aws-idp-evaluation-weight", "value": 0},
    {"op": "set", "field": "classes.0.properties.<field2>.x-aws-idp-evaluation-weight", "value": 0},
    {"op": "save"}
])
```

## Interaction with Other Skills

- **`ground-truth-quality-analysis`**: This skill is proactive (run before optimization); that skill is reactive (run when accuracy is unexpectedly low). They complement each other.
- **`sparse-field-metric-selection`**: If many fields are sparse, use that skill to choose the right primary metric.
- **`boolean-field-extraction`**: Boolean fields with low density often have N/A vs No confusion — apply that skill's guidance.
- **`evaluation-method-tuning`**: Fields confirmed as intentionally empty may need adjusted evaluation methods.

## Verification

1. Run the density analysis and present findings to human
2. Get human confirmation on always-empty and suspicious fields
3. Apply any ground truth corrections the human provides
4. Re-run density analysis to confirm corrections
5. Proceed with optimization using the corrected dataset and adjusted field weights
