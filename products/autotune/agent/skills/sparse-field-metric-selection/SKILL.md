---
name: sparse-field-metric-selection
description: Guide metric selection based on field population density. Use when the dataset has many fields that are legitimately empty in most documents, which makes F1 misleading and Accuracy more appropriate.
---

# Sparse Field Metric Selection

## Problem

When a dataset has many sparse fields (fields populated in <10% of documents), the choice of primary reporting metric significantly affects how accuracy is perceived. F1-score ignores true negatives (correctly identifying empty fields), making it unstable and misleading for sparse fields. Accuracy includes true negatives, providing a more complete and stable picture.

Choosing the wrong primary metric can lead to:
- Misleading accuracy reports to stakeholders
- Wasted optimization effort on fields that appear to perform poorly under F1 but are actually fine
- Incorrect conclusions about extraction quality

## Symptoms

- Large gap between reported Accuracy and F1 scores (Accuracy much higher than F1)
- F1 scores are unstable — small changes in a few documents cause large F1 swings
- Fields with very few positive samples show extreme F1 values (0% or 100%)
- Stakeholders question why F1 is low when manual review shows extractions look correct

## Understanding Field Density

**Field density** = proportion of documents where a field has a non-empty value.

| Density | Category | Example |
|---------|----------|---------|
| >50% | High density | Invoice number, vendor name, total amount |
| 10-50% | Medium density | Discount amount, PO number, special instructions |
| <10% | Sparse | Conditional fields, rare attributes, edge-case flags |

Sparse fields are common in real-world datasets. A schema with 150 fields might have 60+ fields populated in fewer than 10% of documents. These are fields that only apply in specific scenarios (e.g., injury details only when injuries occur, citation fields only when citations are issued).

## Why F1 Is Misleading for Sparse Fields

Consider a field that appears in only 5% of documents (50 out of 1000):

- **True Positives**: 45 (correctly extracted when present)
- **True Negatives**: 940 (correctly identified as empty when absent)
- **False Negatives**: 5 (missed when present)
- **False Positives**: 10 (hallucinated when absent)

| Metric | Formula | Score |
|--------|---------|-------|
| **Accuracy** | (45+940)/(45+940+5+10) = 985/1000 | **98.5%** |
| **F1** | 2×45/(2×45+5+10) = 90/105 | **85.7%** |

F1 ignores the 940 true negatives entirely. The system correctly handles 98.5% of all cases, but F1 reports 85.7% because it only looks at the 60 cases where the field was involved in a positive prediction or ground truth.

For stakeholders who care about "how often is the output correct," Accuracy is the right metric. For stakeholders who care about "when this field has a value, how well do we extract it," F1 is more relevant.

## Diagnosis

### Step 1: Analyze Field Density

Use `analyze_dataset(dataset_path)` after downloading the test set. This reports field density information. For more detailed analysis, use `execute_python_analysis` with the downloaded ground truth files.

### Step 2: Compare Accuracy vs F1 in Evaluation Results

Use `get_evaluation_summary(batch_id)` to see both overallAccuracy and overallF1. Look at the gap between them — a large gap (>5 points) suggests significant field sparsity impact.

## Recommendation

| Dataset Characteristic | Primary Metric | Rationale |
|----------------------|----------------|-----------|
| >30% sparse fields | Accuracy | F1 ignores the majority of correct predictions (true negatives) |
| Few sparse fields | F1 or Accuracy | Both are reasonable; F1 focuses on extraction quality |
| Stakeholder wants "overall correctness" | Accuracy | Includes both correct extractions and correct empties |
| Stakeholder wants "extraction quality when field exists" | F1 | Focuses on positive cases only |

**Default recommendation**: Use Accuracy as the primary reporting metric, with F1 as a secondary metric for understanding precision/recall tradeoffs on populated fields.

## Communicating to Stakeholders

When reporting metrics, always clarify what they measure:

> "Overall Accuracy is 90%, meaning 90% of all field values (both populated and empty) are correctly handled. F1-score is 82%, which measures extraction quality only for fields that have values, excluding the correctly identified empty fields. The gap reflects the dataset's field sparsity — many fields are legitimately empty in most documents."

## Interaction with Other Skills

- **evaluation-method-tuning**: That skill covers HOW to compare values (EXACT, FUZZY, etc.). This skill covers WHICH metric to report as primary.
- **ground-truth-quality-analysis**: Sparse fields with inconsistent GT (e.g., sometimes "N/A", sometimes blank) compound the sparsity problem. Fix GT consistency first, then assess metric choice.
