---
name: confidence-threshold-tuning
description: Configure assessment confidence scoring and per-field thresholds for Human-in-the-Loop (HITL) routing. Use after extraction accuracy is stable to define automation boundaries — which documents are auto-accepted vs routed for human review.
---

# Confidence Threshold Tuning

## Problem

Even after optimizing extraction accuracy, some fields on some documents will be extracted incorrectly. In production, you need a strategy for deciding which extractions to trust automatically and which to route for human review. The IDP accelerator's assessment system generates per-field confidence scores (0.0–1.0) and routes low-confidence extractions to HITL review — but only if configured correctly.

Without confidence thresholding, you're forced to either trust all extractions (risking errors) or review all extractions (defeating the purpose of automation). With per-field thresholds tuned to the dataset, past engagements have demonstrated that 60–80% of entities can achieve 95%+ precision through confidence thresholding alone, with the remaining entities routed for human review.

## When to Use This Skill

- Extraction accuracy is stable and you're preparing for production deployment
- The business requires a specific precision target (e.g., 95% precision) with acceptable recall tradeoff
- You need to define which documents get auto-accepted vs. routed for human review
- You want to implement tiered automation (high confidence → auto-accept, low confidence → HITL)

**IMPORTANT**: Do NOT enable assessment during active optimization iterations. Assessment adds an LLM call per document (cost + latency). Get extraction accuracy right first using the other skills, then enable assessment as a final production-readiness step.

## How Assessment Works

The IDP pipeline has two separate systems that both use the config:

```
OCR → Classification → Extraction → ASSESSMENT → Process Results
                                        ↓
                                  LLM compares extraction
                                  results against source doc
                                        ↓
                                  Generates confidence scores
                                  (0.0–1.0) per field
                                        ↓
                                  Compares scores to thresholds
                                        ↓
                                  Fields below threshold →
                                  confidence_threshold_alerts
                                        ↓
                                  If HITL enabled + alerts exist →
                                  document routed to human review
```

**Assessment** (runtime, every document): LLM analyzes extraction results against the source document and generates confidence scores. Used for HITL routing in production.

**Evaluation** (test-time only): Compares extraction against ground truth baselines. Used during optimization to measure accuracy.

These are independent systems. Assessment doesn't need ground truth — it works on any document.

## Symptoms That Indicate You Need This Skill

- Extraction accuracy is good overall but the business needs guaranteed precision on critical fields
- You're transitioning from optimization to production deployment
- The business wants to define automation rates (e.g., "80% of documents auto-processed, 20% human review")
- Different fields have different criticality levels (e.g., SSN must be near-perfect, description fields can tolerate errors)

## Configuration

### Step 1: Enable Assessment

```
config_edit(config_path, operations=[
    {"op": "set", "field": "assessment.enabled", "value": true},
    {"op": "set", "field": "assessment.granular.enabled", "value": true},
    {"op": "set", "field": "assessment.hitl_enabled", "value": true},
    {"op": "save"}
])
```

### Step 2: Set the Global Default Confidence Threshold

The `default_confidence_threshold` applies to all fields that don't have a per-field override. Fields with confidence scores below this threshold generate alerts.

```
config_edit(config_path, operations=[
    {"op": "set", "field": "assessment.default_confidence_threshold", "value": 0.8},
    {"op": "save"}
])
```

**Choosing the default**: Start with 0.8. This is a reasonable balance — fields the LLM is less than 80% confident about get flagged for review. You'll tune per-field thresholds for critical fields in Step 4.

### Step 3: Choose an Assessment Model

The assessment LLM evaluates extraction quality. It doesn't need to be the same model used for extraction.

```
config_edit(config_path, operations=[
    {"op": "set", "field": "assessment.model", "value": "us.anthropic.claude-3-5-haiku-20241022-v1:0"},
    {"op": "set", "field": "assessment.temperature", "value": 0.0},
    {"op": "set", "field": "assessment.top_p", "value": 0.1},
    {"op": "save"}
])
```

A smaller/cheaper model often works well for assessment since it's comparing extracted values against visible document content, not performing the extraction itself.

### Step 4: Set Per-Field Confidence Thresholds

Critical fields can have stricter thresholds than the global default. Set `x-aws-idp-confidence-threshold` on individual schema properties:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.properties.social_security_number.x-aws-idp-confidence-threshold", "value": 0.6},
    {"op": "set", "field": "classes.0.properties.employee_name.x-aws-idp-confidence-threshold", "value": 0.85},
    {"op": "save"}
])
```

**Understanding the threshold value**: The threshold is the minimum confidence score required for auto-acceptance. A *lower* threshold means more documents are auto-accepted (higher recall, lower precision). A *higher* threshold means fewer documents are auto-accepted (lower recall, higher precision).

| Threshold | Effect | Use When |
|-----------|--------|----------|
| 0.5–0.6 | Lenient — most extractions auto-accepted | Field has high baseline accuracy, errors are low-cost |
| 0.7–0.8 | Moderate — balanced automation | Default for most fields |
| 0.85–0.95 | Strict — many extractions routed to HITL | Field is business-critical, errors are costly |

### Step 5: Configure Granular Assessment Settings

Granular assessment processes fields individually rather than the entire extraction at once. This gives more accurate per-field confidence scores but takes longer.

```
config_edit(config_path, operations=[
    {"op": "set", "field": "assessment.granular.enabled", "value": true},
    {"op": "set", "field": "assessment.granular.simple_batch_size", "value": 3},
    {"op": "set", "field": "assessment.granular.list_batch_size", "value": 1},
    {"op": "set", "field": "assessment.granular.max_workers", "value": 20},
    {"op": "save"}
])
```

**WARNING**: Granular assessment with `list_batch_size=1` on documents with large arrays (100+ items) can cause Lambda timeouts. For documents with many array items, either:
- Increase `list_batch_size` to process more items per call
- Disable granular assessment and use regular assessment
- Ensure the assessment Lambda has sufficient timeout configured

## The Precision/Recall Tradeoff

Confidence thresholding trades recall for precision. At any given threshold:

- **Precision** = Of the extractions we auto-accept, what % are correct?
- **Recall** = Of all correct extractions, what % do we auto-accept?

```
Higher threshold → Higher precision, Lower recall → More human review
Lower threshold  → Lower precision, Higher recall → Less human review
```

In practice, the relationship looks like this for a typical field:

| Threshold | Precision | Recall | Interpretation |
|-----------|-----------|--------|----------------|
| 0.00 | ~87% | ~97% | Accept everything — baseline precision |
| 0.58 | ~95% | ~79% | Good balance for critical fields |
| 0.70 | ~98% | ~66% | Very strict — significant HITL volume |
| 0.90 | ~99% | ~50% | Near-perfect precision, half go to HITL |

The optimal threshold depends on the business cost of errors vs. the cost of human review.

## Tuning Strategy

### Approach 1: Business-Target-Driven

Start from the business requirement and find the threshold that meets it:

1. Business says "95% precision required for SSN"
2. Run evaluation with assessment enabled
3. Analyze confidence score distribution for SSN across the test set
4. Find the threshold where precision ≥ 95%
5. Check the recall at that threshold — is the HITL volume acceptable?
6. Set `x-aws-idp-confidence-threshold` to that value

### Approach 2: Tiered Automation

Categorize fields by criticality and set thresholds accordingly:

```
# Tier 1: Critical fields — strict thresholds
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.properties.social_security_number.x-aws-idp-confidence-threshold", "value": 0.85},
    {"op": "set", "field": "classes.0.properties.date_of_birth.x-aws-idp-confidence-threshold", "value": 0.85},
    {"op": "set", "field": "classes.0.properties.plan_number.x-aws-idp-confidence-threshold", "value": 0.85},
    {"op": "save"}
])

# Tier 2: Important fields — moderate thresholds
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.properties.employee_name.x-aws-idp-confidence-threshold", "value": 0.75},
    {"op": "set", "field": "classes.0.properties.employer_name.x-aws-idp-confidence-threshold", "value": 0.75},
    {"op": "set", "field": "classes.0.properties.work_state.x-aws-idp-confidence-threshold", "value": 0.75},
    {"op": "save"}
])

# Tier 3: Low-criticality fields — use global default (0.8) or lenient
# No per-field override needed — falls back to default_confidence_threshold
```

### Approach 3: Complexity-Driven

Fields with different extraction complexity need different thresholds:

| Field Complexity | Baseline Precision | Recommended Threshold | Expected Outcome |
|-----------------|-------------------|----------------------|------------------|
| Low (dates, IDs, codes) | >95% | 0.0 (no threshold needed) | Already meets target without thresholding |
| Medium (names, numbers) | 80–95% | 0.6–0.85 | Meets target with moderate recall impact |
| High (addresses, free text) | 70–85% | 0.85–0.95 | Meets target but significant recall drop |
| Very High (inferred fields) | <70% | May not achieve target | Flag for human review or business process change |

## Cost and Latency Implications

Assessment adds processing overhead to every document:

- **One additional LLM call** per document (or per field in granular mode)
- **Latency**: Adds seconds to per-document processing time
- **Cost**: Depends on assessment model and prompt length

To minimize cost:
- Use a smaller model for assessment (e.g., Haiku instead of Sonnet)
- Keep assessment prompts concise
- Use regular (non-granular) assessment if per-field scores aren't needed
- Combine with `<<CACHEPOINT>>` in assessment prompts (see `prompt-caching-optimization` skill)

**During optimization**: Keep `assessment.enabled: false` to avoid unnecessary cost. Enable it only when you're ready to tune thresholds for production.

## Interaction with Other Skills

- **All extraction/classification skills**: Do extraction optimization FIRST. Assessment is a production-readiness step, not an accuracy improvement tool.
- **`iterative-schema-refinement`**: Complete the schema refinement process before enabling assessment. Every prompt change during optimization would add unnecessary assessment cost.
- **`prompt-caching-optimization`**: Assessment prompts can use `<<CACHEPOINT>>` to reduce per-document cost.
- **`choosing-a-bedrock-model`**: The assessment model can be different (typically cheaper) than the extraction model.
- **`conditional-ocr-cost-optimization`**: Classes that only need classification don't need assessment either.

## Verification

1. Enable assessment on the optimized config:
   ```
   config_edit(config_path, operations=[
       {"op": "set", "field": "assessment.enabled", "value": true},
       {"op": "set", "field": "assessment.granular.enabled", "value": true},
       {"op": "set", "field": "assessment.hitl_enabled", "value": true},
       {"op": "save", "output_path": "workspace/config-with-assessment.yaml"}
   ])
   ```

2. Upload and run evaluation:
   ```
   upload_config('workspace/config-with-assessment.yaml', config_version='vN-assessment', description='Enabled assessment with confidence thresholds')
   run_evaluation(test_set_id, context='Assessment tuning', config_version='vN-assessment')
   ```

3. Verify extraction accuracy is unchanged (assessment should not affect extraction results)

4. Review confidence score distributions and threshold alerts in the evaluation output

5. Adjust per-field thresholds based on the precision/recall tradeoff for each critical field

6. Document the threshold configuration and expected automation rate in the optimization log
