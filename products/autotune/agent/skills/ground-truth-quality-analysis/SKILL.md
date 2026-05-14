---
name: ground-truth-quality-analysis
description: Diagnose ground truth quality issues that cause artificially low accuracy. Use when accuracy plateaus despite good prompts, or when manual inspection shows extractions look correct but don't match ground truth.
---

# Ground Truth Quality Analysis

## Problem

Reported accuracy is artificially low because the ground truth data contains errors, inconsistencies, or enriched values that don't match what appears in the source documents. The LLM may be extracting correctly, but the evaluation scores it as wrong because the ground truth itself is flawed.

This is a critical diagnostic skill. Without it, the optimizer will waste cycles trying to "fix" extraction that is already correct, chasing accuracy improvements that can only come from fixing the ground truth.

## Symptoms

- Accuracy plateaus despite multiple rounds of prompt engineering and model upgrades
- Manual inspection of failing documents shows the LLM extraction looks correct
- Specific field categories have systematically low accuracy across many documents
- The same fields fail consistently regardless of prompt changes
- Extraction output matches what's visible in the document but doesn't match ground truth

## Common Ground Truth Issues

### 1. Near-Empty / Placeholder Entries
Keying applications sometimes create entries with only one field populated (e.g., a Party_Id) when a keyer opens a new tab but doesn't fill in details. These near-empty entries inflate the expected count of objects, causing false negatives for every missing sub-field.

**Impact**: Can be massive. In one engagement, 1,317 bogus citation entries, 236 people entries, and 52 vehicle entries had to be cleaned, significantly improving reported accuracy.

### 2. Enriched Values from External Systems
Ground truth may contain values that were looked up from external databases rather than extracted from the document. For example, a vehicle make field might say "VOLKSWAGEN" in the ground truth (from a VIN lookup system) while the document only shows "VOLK" or "VW".

**Impact**: The LLM correctly extracts what's in the document, but it doesn't match the enriched ground truth. These fields may need to be excluded from evaluation or evaluated with LLM-based comparison.

### 3. Inconsistent Keying Patterns
Different keyers use different conventions:
- Missing value representations: "N/A", blank, "UNKNOWN", "UNK", "NONE", empty string
- Abbreviation styles: "ST" vs "STREET", "DR" vs "DRIVE"
- Capitalization: "John Smith" vs "JOHN SMITH"
- Date formats: "01/15/2024" vs "2024-01-15"

**Impact**: Evaluation may penalize correct extractions that use a different convention than the keyer used.

### 4. Missing Fields from Keyer Shortcuts
Keying applications may have shortcuts (e.g., "owner same as driver" button) that copy only some fields, leaving others blank. The ground truth then has systematically missing values for certain field combinations.

**Impact**: Creates a ceiling on achievable accuracy. If the ground truth is missing values that the LLM correctly extracts, those become false alarms.

### 5. Fields That Don't Reflect Document Content
Some ground truth fields contain:
- System metadata (report IDs, UI state) that isn't in the document
- Derived/calculated values not directly extractable
- Values from a different version of the document or schema

**Impact**: These fields should be excluded from evaluation entirely.

### 6. Multi-Part Field Concatenation Issues
For fields that span multiple pages or sections (e.g., narrative text), the ground truth may not properly concatenate all parts, resulting in incomplete ground truth that the LLM actually extracts more completely.

## Diagnosis

### Step 1: Identify Suspicious Patterns

Look for fields where accuracy is systematically low across many documents, not just a few:

Use `get_evaluation_summary(batch_id)` to get the aggregated metrics, then look at per-field accuracy. Fields with consistently low accuracy across many documents (not just outliers) are candidates for ground truth issues.

### Step 2: Compare Extraction vs Ground Truth for Failing Documents

Use `download_single_document_results(batch_id, 'failing-doc.pdf')` and `download_ground_truth(test_set_id, 'failing-doc.pdf')` to get both the extraction output and ground truth for failing documents.

For each mismatched field, ask:
1. Does the LLM output match what's visible in the source document?
2. Does the ground truth match what's visible in the source document?
3. If the LLM is right and the GT is wrong, it's a GT issue.

### Step 3: Look for Systematic Patterns

Check multiple failing documents for the same field. If the pattern is consistent (e.g., GT always has enriched values, GT always missing certain sub-fields), it's a ground truth quality issue, not an extraction issue.

### Step 4: Check for Near-Empty Entries in Array Fields

For array fields (people, vehicles, line items), compare the count of entries in GT vs extraction. If GT consistently has more entries than the LLM extracts, use `execute_python_analysis` to check whether the extra GT entries are near-empty placeholders:

```python
# Pass the ground truth file via the `files` parameter, then analyze:
import json

with open('gt/result.json') as f:
    gt = json.load(f)

# Check for near-empty entries in an array field
for i, entry in enumerate(gt.get('inference_result', {}).get('People', [])):
    populated = sum(1 for v in entry.values() if v not in [None, '', []])
    total = len(entry)
    print(f"Entry {i}: {populated}/{total} fields populated")
    if populated <= 1:
        print(f"  ⚠️ Near-empty entry — likely a placeholder")
```

## Actions

**CRITICAL**: The IDPAC agent must NEVER silently exclude fields, modify ground truth, or change evaluation scope without explicit human approval. Ground truth issues must always be flagged to the human for decision.

### Action 1: Flag to Human

When you identify a ground truth quality issue, report it clearly:

> "I've identified a potential ground truth quality issue with the following fields:
> - [Field name]: [Description of the issue, e.g., 'GT contains VIN-lookup values like VOLKSWAGEN but documents show abbreviated forms like VOLK']
> - [Field name]: [Description]
>
> These issues may be causing artificially low accuracy scores. I recommend:
> - [Specific recommendation per field]
>
> Would you like me to proceed with any of these adjustments?"

### Action 2: Adjust Evaluation Methods (with human approval)

For enriched values or format inconsistencies, changing the evaluation method may be more appropriate than excluding the field. Use `config_edit` to modify the config:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.properties.VehicleMake.x-aws-idp-evaluation-method", "value": "LLM"},
    {"op": "set", "field": "classes.0.properties.Address.x-aws-idp-evaluation-method", "value": "FUZZY"},
    {"op": "set", "field": "classes.0.properties.Address.x-aws-idp-evaluation-threshold", "value": 0.7},
    {"op": "save"}
])
```

### Action 3: Exclude Systematically Broken Fields (with human approval)

For fields where the ground truth is fundamentally wrong (system metadata, enriched values with no document source), recommend excluding them from evaluation by setting weight to 0:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.properties.systemReportId.x-aws-idp-evaluation-weight", "value": 0},
    {"op": "set", "field": "classes.0.properties.VehicleModel.x-aws-idp-evaluation-weight", "value": 0},
    {"op": "save"}
])
```

### Action 4: Document GT Issues in Optimization Log

Always record ground truth issues in the OPTIMIZATION-LOG.md so they are visible to the human and to future optimization runs:

```
## Ground Truth Quality Issues Identified

The following ground truth issues were found during investigation:

1. **Near-empty People entries**: GT contains 236 placeholder entries with only
   Party_Id populated. These inflate false negative counts.
   Recommendation: Clean GT to remove placeholder entries.

2. **VehicleMake enrichment**: GT contains full manufacturer names from VIN
   lookup ("VOLKSWAGEN") while documents show abbreviations ("VOLK").
   Recommendation: Switch to LLM evaluation method for this field.

3. **Narrative concatenation**: GT does not concatenate multi-page narrative
   sections. LLM extracts more complete text than GT contains.
   Recommendation: Exclude from automated evaluation; manual review confirms
   extraction quality is acceptable.

ACTION REQUIRED: Human review needed before applying any of these changes.
```

## Verification

After the human approves and changes are applied:

1. Re-run evaluation on the same test set
2. Confirm that fields with GT issues now show improved scores
3. Verify that the improvements reflect actual GT quality fixes, not masking of real extraction errors
4. Document all changes prominently in the optimization log with clear distinction between "GT quality fix" and "extraction improvement"
