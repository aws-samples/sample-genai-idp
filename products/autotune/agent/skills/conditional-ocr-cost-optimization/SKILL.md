---
name: conditional-ocr-cost-optimization
description: Identify opportunities to reduce processing costs by skipping OCR or extraction for document classes that don't need them. Use when processing cost is high in multi-class datasets and some classes only need classification.
---

# Conditional OCR Cost Optimization

## Problem

In multi-class datasets, not all document classes require the same processing depth. Some classes may only need classification (e.g., routing to the correct queue), while others need full OCR + extraction. Running the complete pipeline on every document wastes money on classes where the extra processing adds no value.

In a past engagement processing documents across 14 document classes, implementing conditional OCR — skipping OCR for 3 classes that only needed classification — reduced annual processing costs by approximately 21%.

## Symptoms

- High processing costs in a multi-class dataset
- Some document classes don't require data extraction (e.g., "other", "procedures", "cover pages")
- Some classes only need classification for routing/archival purposes
- Cost per page is high relative to the value extracted from certain document types
- Historical document backlogs need classification but not extraction

## Diagnosis

### Step 1: Identify Classes That Don't Need Extraction

Review the document classes and determine which ones actually need extraction vs. classification-only:

```python
from idpac import IDPConfig
from idpac.evaluations import EvaluationResult

config = IDPConfig('workspace/current-config.yaml')

# List all classes and their extraction schemas
for i, cls in enumerate(config.get('classes')):
    class_name = cls.get('$id', f'class_{i}')
    num_fields = len(cls.get('properties', {}))
    print(f"  {class_name}: {num_fields} extraction fields")
```

Classes with few or no meaningful extraction fields, or classes where extraction results aren't used downstream, are candidates for OCR/extraction bypass.

### Step 2: Estimate Cost Impact

```python
from idpac import IDPACClient
from idpac.evaluations import EvaluationResult

client = IDPACClient('stack-name', region='us-east-1')
summary = client.get_evaluation_summary('batch-id', 'results/summary.json')

print(f"Total cost: ${summary.get('totalCost')}")
print(f"Cost breakdown: {summary.get('costBreakdown')}")

# Check per-class document counts to estimate savings
result = EvaluationResult.from_aggregated_file('results/summary.json')
result.print_classification_summary()
```

Estimate savings by calculating what percentage of documents belong to classes that don't need extraction, and multiplying by the per-document OCR + extraction cost.

## Current Architecture Limitation

The IDP Accelerator's Pattern 2 pipeline runs OCR **before** classification:

```
OCR → Classification → Extraction
```

This means OCR runs on every document regardless of its class. There is no built-in configuration option to skip OCR or extraction for specific document classes. Implementing conditional processing requires custom pipeline modifications (e.g., modifying the Step Functions workflow or adding a post-classification routing Lambda).

**What the IDPAC agent can do:**
- Identify which classes are candidates for OCR/extraction bypass
- Estimate the cost savings
- Document the recommendation in the optimization log
- Flag the opportunity to the human for implementation

**What requires custom engineering work:**
- Modifying the Step Functions workflow to conditionally skip OCR based on classification result
- Adding a routing Lambda between classification and extraction
- Creating a separate processing queue for classification-only documents

## Action: Flag to Human

When you identify classes that don't need full processing, document this in the optimization log and flag it to the human:

> "I've identified a cost optimization opportunity for this multi-class dataset.
> The following document classes appear to only need classification, not full
> OCR + extraction:
>
> - [Class name]: [Reason — e.g., 'No extraction fields defined', 'Only used for routing']
> - [Class name]: [Reason]
>
> These classes represent approximately [X%] of documents in the dataset.
> Based on current processing costs, skipping OCR and extraction for these
> classes could save approximately $[amount] per [time period].
>
> This optimization requires custom pipeline modifications to the Step Functions
> workflow (conditional OCR/extraction based on classification result). It cannot
> be achieved through configuration changes alone.
>
> In a similar past engagement, this approach reduced annual processing costs
> by ~21% by bypassing OCR for 3 of 14 document classes.
>
> Would you like me to document this recommendation in the final report?"

### Log Template

```markdown
## Cost Optimization Opportunity: Conditional OCR

### Classes Identified for Classification-Only Processing
| Class | Documents (%) | Reason |
|-------|--------------|--------|
| [class1] | [X%] | [reason] |
| [class2] | [Y%] | [reason] |

### Estimated Savings
- Current cost per document (full pipeline): $[amount]
- Cost per document (classification only): $[amount]
- Documents eligible for bypass: [N] ([X%] of total)
- Estimated annual savings: $[amount]

### Implementation Requirements
This requires custom pipeline modification (Step Functions workflow change).
Not achievable through IDP configuration alone.

STATUS: Flagged to human for decision.
```

## Related Configuration Options

While per-class conditional OCR isn't supported, these global options exist:

### Global OCR Disable

If NO classes need OCR (all extraction is multimodal image-only), you can disable OCR globally:

```python
config.set('ocr.backend', 'none')
```

**Warning**: This typically causes a 30-50% accuracy drop for extraction. Only use if you've benchmarked and confirmed acceptable accuracy without OCR. See the `ocr-configuration` skill.

### Assessment and Summarization Disable

If cost is a concern, disable optional pipeline features that add LLM calls:

```python
config.set('assessment.enabled', False)
config.set('summarization.enabled', False)
```

These features add per-document LLM costs for confidence scoring and document summarization. Disabling them during optimization reduces cost without affecting extraction accuracy.

## Interaction with Other Skills

- **`ocr-configuration`**: Covers OCR backend selection and feature tuning for all classes. This skill addresses the per-class bypass question.
- **`choosing-a-bedrock-model`**: Using cheaper models for classification-only classes is another cost lever.
- **`prompt-caching-optimization`**: Reduces per-document cost for classes that DO need full processing.

## Verification

This skill produces a recommendation, not a configuration change. Verification happens after the human implements the custom pipeline modification:

1. Compare total processing cost before and after the pipeline change
2. Verify classification accuracy is maintained for bypassed classes
3. Verify extraction accuracy is maintained for classes that still get full processing
4. Monitor cost over time to confirm sustained savings
