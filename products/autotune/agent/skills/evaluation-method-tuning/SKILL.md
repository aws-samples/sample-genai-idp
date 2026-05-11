---
name: evaluation-method-tuning
description: Tune per-field evaluation methods, thresholds, and weights to get accurate accuracy measurements. Use when reported accuracy seems artificially low due to overly strict matching, or when different fields need different comparison strategies.
---

# Evaluation Method Tuning

## Problem

Reported accuracy is artificially low because the default evaluation method (EXACT match) is too strict for certain field types. The extraction may be correct but scored as wrong due to formatting differences, equivalent representations, or domain-specific matching needs.

## Symptoms

- Overall accuracy is low but manual inspection shows extractions look correct
- Numeric fields fail because of formatting differences ("$1,500.00" vs "1500")
- Name fields fail due to minor spelling variations or OCR artifacts
- Domain-specific fields fail because equivalent representations aren't recognized (e.g., "T5S" vs "T-5-S")
- Array/list fields score 0% because one sub-field mismatch causes the entire object to fail matching

## Diagnosis

```python
from idpac import IDPACClient
from idpac.evaluations import EvaluationResult

client = IDPACClient('stack-name', region='us-east-1')
summary = client.get_evaluation_summary('batch-id', 'results/summary.json')

result = EvaluationResult.from_aggregated_file('results/summary.json')
result.print_aggregated_summary(top_bottom_n=5)

# Investigate individual documents to see what's being marked wrong
client.download_single_document_results('batch-id', 'failing-doc.pdf', 'investigation/')
client.download_ground_truth('test-set-id', 'failing-doc.pdf', 'investigation/gt.json')
```

Look at the mismatches: is the extracted value actually wrong, or is it a valid equivalent that strict matching rejects?

## Available Evaluation Methods

| Method | Use For | Example |
|--------|---------|---------|
| `EXACT` | IDs, codes, enum values | Invoice number, document type |
| `NUMERIC_EXACT` | Monetary amounts, quantities | Prices, acreage, totals |
| `FUZZY` | Text with minor variations | Names, addresses, descriptions |
| `LEVENSHTEIN` | Text with OCR errors/typos | Scanned document fields |
| `SEMANTIC` | Meaning-equivalent text | Descriptions, summaries |
| `LLM` | Domain-specific equivalence | Legal descriptions, formatted codes |
| `HUNGARIAN` | Arrays of objects | Line items, list of entities |

## Fix

### Step 1: Set Appropriate Methods Per Field

```python
from idpac import IDPConfig

config = IDPConfig('workspace/current-config.yaml')

# Monetary/numeric fields → NUMERIC_EXACT
config.set('classes.0.properties.Amount.x-aws-idp-evaluation-method', 'NUMERIC_EXACT')
config.set('classes.0.properties.TotalArea.x-aws-idp-evaluation-method', 'NUMERIC_EXACT')

# Fields with formatting variations → FUZZY or LEVENSHTEIN
config.set('classes.0.properties.CompanyName.x-aws-idp-evaluation-method', 'FUZZY')

# Domain fields with equivalent representations → LLM
config.set('classes.0.properties.Township.x-aws-idp-evaluation-method', 'LLM')

# Strict identifier fields → EXACT (default, but explicit is better)
config.set('classes.0.properties.InvoiceNumber.x-aws-idp-evaluation-method', 'EXACT')

config.save('workspace/updated-config.yaml')
```

### Step 2: Tune Thresholds for Fuzzy/Similarity Methods

The threshold controls how similar values must be to count as a match (0.0–1.0):

```python
# Strict: must be very similar (good for IDs with minor OCR errors)
config.set('classes.0.properties.RecordNumber.x-aws-idp-evaluation-threshold', 0.9)

# Lenient: allow more variation (good for names, descriptions)
config.set('classes.0.properties.CustomerName.x-aws-idp-evaluation-threshold', 0.7)
```

### Step 3: Set Field Weights by Business Importance

Not all fields are equally important. Weight critical fields higher:

```python
# Critical fields: full weight
config.set('classes.0.properties.InvoiceNumber.x-aws-idp-evaluation-weight', 1.0)
config.set('classes.0.properties.TotalAmount.x-aws-idp-evaluation-weight', 1.0)

# Important but less critical
config.set('classes.0.properties.CustomerName.x-aws-idp-evaluation-weight', 0.5)

# Nice-to-have fields
config.set('classes.0.properties.Notes.x-aws-idp-evaluation-weight', 0.25)
```

### Step 4: Tune Array Matching Threshold

For arrays of structured objects (e.g., line items, land descriptions), the matching algorithm pairs predicted objects with ground truth objects. The match threshold determines how similar two objects must be to be considered a match. A threshold of 1.0 means every sub-field must match perfectly — this is often too strict.

Lowering the threshold (e.g., to 0.7) allows objects to match even if some sub-fields differ, which gives a more realistic accuracy picture when most fields are correct but a few are wrong:

```python
# For array fields, set threshold on the array property
config.set('classes.0.properties.line_items.x-aws-idp-evaluation-threshold', 0.7)
```

## Decision Guide

| Field Type | Recommended Method | Threshold |
|------------|-------------------|-----------|
| Identifiers (IDs, codes) | EXACT | 1.0 |
| Dates | EXACT | 1.0 |
| Monetary amounts | NUMERIC_EXACT | 1.0 |
| Quantities/measurements | NUMERIC_EXACT | 1.0 |
| Person/company names | FUZZY | 0.8 |
| Addresses | FUZZY or LEVENSHTEIN | 0.7 |
| Free-text descriptions | SEMANTIC | 0.7 |
| Domain-specific formatted values | LLM | 1.0 |
| Enum/category fields | EXACT or FUZZY | 0.4–1.0 |
| Arrays of objects | HUNGARIAN | 0.7 |

## CRITICAL: You Are Changing the Definition of Accuracy

Tuning evaluation methods does NOT change what the LLM extracts — it changes how you *measure* accuracy. This means accuracy numbers before and after an evaluation method change **are not comparable**. A score of 0.75 under EXACT matching and 0.85 under FUZZY matching do not mean you improved extraction — they mean you changed what "correct" means.

**You MUST clearly communicate this to the human.** When you change evaluation methods, thresholds, or weights:

1. **State explicitly in the OPTIMIZATION-LOG** that you are changing metric definitions, not improving extraction
2. **Report both the old and new metric definitions** so the human can understand what changed
3. **Never present evaluation method changes as accuracy improvements** in the same breath as extraction improvements — keep them clearly separated
4. **Ask the human before making these changes** if there is any indication they have strict metric requirements. Some users have contractual or business-defined accuracy thresholds using specific comparison methods, and changing those methods would invalidate the measurement.

Example log entry:
```
## Evaluation Method Change (NOT an extraction improvement)
Changed evaluation methods for the following fields:
- Township: EXACT → LLM (to recognize equivalent formats like "T5S" and "T-5-S")
- Amount: EXACT → NUMERIC_EXACT (to handle "$1,500" vs "1500")
- line_items match threshold: 1.0 → 0.7

IMPORTANT: Accuracy numbers from this point forward are measured differently
than previous runs. Direct comparison of scores across this boundary is misleading.

Scores under OLD metrics: 0.72 overall
Scores under NEW metrics: 0.84 overall
Estimated accuracy gain from metric change alone: ~0.10
Estimated accuracy gain from actual extraction improvements: ~0.02
```

If the human has not specified their metric requirements, **ask them** before changing evaluation methods:
> "I've noticed some fields may be scored too strictly (e.g., numeric amounts compared as exact strings). I can adjust the evaluation methods to better reflect actual extraction quality, but this would change how accuracy is measured. Would you like me to proceed, or do you have specific metric definitions that must be preserved?"

## Choosing a Primary Reporting Metric: Accuracy vs F1

The IDP evaluation pipeline reports multiple metrics (Accuracy, Precision, Recall, F1). Which metric you use as the primary reporting metric matters, especially when the dataset has many fields that are legitimately empty (null/absent) in most documents.

**Accuracy** counts correct identification of both present AND absent values (true positives + true negatives). **F1** only considers present values (ignores true negatives).

For datasets with many **sparse fields** (fields populated in <10% of documents), F1 can be misleading:
- A field appearing in only 5% of documents has 95% true negatives that F1 ignores entirely
- F1 scores will be unstable and based on very few positive samples
- Accuracy provides a more stable and complete picture by crediting correct identification of empty fields

**Recommendation**: Use Accuracy as the primary metric when the dataset has significant field sparsity. Use F1 as a secondary metric to understand precision/recall tradeoffs for populated fields. See the `sparse-field-metric-selection` skill for detailed guidance on analyzing field density and choosing metrics.

## Verification

1. Deploy updated config with new evaluation methods
2. Re-run evaluation on same test set
3. Compare accuracy before and after — **clearly labeling that metric definitions changed**
4. Manually verify that the new scores reflect actual extraction quality
5. Check that loosened thresholds aren't hiding real extraction errors
6. **Document the metric change prominently** in the optimization log and final report
