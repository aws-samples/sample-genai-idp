---
name: iterative-schema-refinement
description: "META-SKILL: Orchestrates other skills into a systematic process for iteratively improving document class schemas. Read this skill first to plan your optimization strategy — it tells you which other skills to apply, in what order, based on field category performance patterns. Use after initial evaluation or when accuracy improvements plateau."
---

# Iterative Schema Refinement

## Problem

Schema quality is the single most impactful factor in extraction accuracy. Small errors or omissions in schema design cascade into larger inaccuracies downstream. Past engagements have demonstrated dramatic accuracy jumps from schema refinements alone — individual documents going from 40% to 91% accuracy just by improving field definitions.

However, schemas often have dozens of fields, and it's not obvious which fields to improve first or what kind of improvement each field needs. Without a systematic approach, optimization effort is wasted on low-impact changes while high-impact fields remain unaddressed.

## Symptoms

- Initial evaluation shows moderate overall accuracy (50-75%) with high variance across fields
- Some field categories (dates, identifiers) score well while others (free text, booleans, context-dependent fields) score poorly
- Accuracy improves in early iterations but plateaus quickly
- No clear strategy for which fields to optimize next

## The Refinement Process

### Step 1: Establish Baseline and Categorize Fields

After the first evaluation run, categorize every field by its accuracy AND its type:

```python
from idpac import IDPACClient, IDPConfig
from idpac.evaluations import EvaluationResult

client = IDPACClient('stack-name', region='us-east-1')
summary = client.get_evaluation_summary('batch-id', 'results/summary.json')
result = EvaluationResult.from_aggregated_file('results/summary.json')
result.print_aggregated_summary(top_bottom_n=10)

config = IDPConfig('workspace/current-config.yaml')
```

Build a mental model of field performance by category:

| Category | Expected Accuracy | Why |
|----------|------------------|-----|
| Dates (execution date, effective date) | >90% | Well-structured, unambiguous format |
| Identifiers (contract number, ID) | >90% | Unique, clearly labeled |
| Simple categories (contract type, status) | >85% | Finite set of values |
| Names (parties, entities) | 75-85% | Format variation, multiple candidates |
| Boolean fields | 70-85% | N/A vs No confusion, implied values |
| Free text (descriptions, limitations) | 60-80% | Subjective boundaries, paraphrasing |
| Context-dependent fields | 50-75% | Require cross-referencing or inference |
| Per-entity array fields | 50-75% | Count mismatches, cross-entity confusion |

Fields significantly below their category's expected range are the highest-priority targets.

### Step 2: Prioritize by Impact

Not all fields are equally worth optimizing. Prioritize based on:

1. **Accuracy gap**: Fields furthest below their category's expected accuracy
2. **Evaluation weight**: Higher-weighted fields have more impact on overall score
3. **Document coverage**: Fields that appear in many documents (high density) affect more results than sparse fields
4. **Fixability**: Some issues are addressable via schema changes, others require architecture changes

```python
# Check field weights to understand impact
cls = config.get('classes.0')
for field_name, field_def in cls.get('properties', {}).items():
    weight = field_def.get('x-aws-idp-evaluation-weight', 1.0)
    method = field_def.get('x-aws-idp-evaluation-method', 'EXACT')
    print(f"{field_name}: weight={weight}, method={method}")
```

### Step 3: Apply Category-Specific Fixes

For each priority field, apply the appropriate fix based on its category:

**Dates scoring below 90%:**
- Check evaluation method — use `LLM` evaluation to handle format equivalence ("January 1, 2024" vs "01/01/2024" vs "2024-01-01")
- Add format instructions to field description
- See `evaluation-method-tuning` skill

**Identifiers scoring below 90%:**
- Check if multiple candidate values exist in the document — add disambiguation to description
- See `extraction-prompt-engineering` skill (disambiguation section)

**Categories/enums scoring below 85%:**
- List all valid values in the field description
- See `extraction-prompt-engineering` skill (Step 5: valid values)

**Boolean fields scoring below 80%:**
- Apply the full `boolean-field-extraction` skill

**Names scoring below 75%:**
- Use `FUZZY` evaluation method
- Add format guidance (e.g., "Full legal name as it appears in the document header")
- See `evaluation-method-tuning` skill

**Free text scoring below 70%:**
- Use `LLM` or `SEMANTIC` evaluation method
- Add boundary guidance ("Extract only the text from section X, not including...")
- See `evaluation-method-tuning` skill

**Context-dependent fields scoring below 60%:**
- Enrich description with explicit reasoning instructions
- See `extraction-prompt-engineering` skill and `visual-spatial-extraction-challenges` skill

**Array fields with count mismatches:**
- See `stepwise-extraction-strategy` skill
- See `nested-schema-design` skill

### Step 4: Make One Category of Changes Per Iteration

Don't change everything at once. Each iteration should focus on one type of improvement so you can measure its impact:

**Iteration pattern:**
1. Change one category of fields (e.g., all boolean fields, or all date fields)
2. Save as a new numbered config version
3. Run evaluation
4. Compare results — did the targeted fields improve? Did anything regress?
5. Log findings in OPTIMIZATION-LOG.md
6. Move to the next category

```python
# Example: Iteration focused on boolean fields
config = IDPConfig('workspace/config-v2-fixed-schemas.yaml')

# Apply boolean-specific fixes to all boolean fields
# (see boolean-field-extraction skill for details)
# ...

config.save('workspace/config-v3-boolean-fixes.yaml')
```

### Step 5: Check for Regressions

After each iteration, verify that improving one set of fields didn't degrade others. This can happen when:
- Task prompt changes affect all fields, not just the targeted ones
- Schema restructuring changes how the LLM interprets the overall document
- Model changes have different strengths/weaknesses

```python
# Compare two evaluation runs
old_result = EvaluationResult.from_aggregated_file('results/eval-v2.json')
new_result = EvaluationResult.from_aggregated_file('results/eval-v3.json')

old_result.print_aggregated_summary(top_bottom_n=5)
new_result.print_aggregated_summary(top_bottom_n=5)

# Also compare configs to see exactly what changed
IDPConfig.print_comparison(
    'workspace/config-v2-fixed-schemas.yaml',
    'workspace/config-v3-boolean-fixes.yaml',
    name1='v2', name2='v3'
)
```

### Step 6: Know When to Stop

Stop iterating when:
- Overall accuracy meets the target specified in the OPTIMIZATION-LOG
- Per-field accuracy gains are <1% per iteration
- Remaining low-accuracy fields are in categories that require architecture changes (flag to human)
- Remaining low-accuracy fields have ground truth quality issues (see `ground-truth-quality-analysis` skill)

## Recommended Iteration Order

Based on typical impact and ease of implementation:

1. **Evaluation methods first** — Fix how you measure before trying to improve what you measure. Wrong evaluation methods (e.g., EXACT on dates) create artificial accuracy floors. See `evaluation-method-tuning` skill.
2. **Schema structure** — Ensure nested schemas match ground truth structure. See `nested-schema-design` skill.
3. **Field descriptions for high-weight fields** — Enrich descriptions for the fields that matter most. See `extraction-prompt-engineering` skill.
4. **Boolean fields** — Apply specialized boolean handling. See `boolean-field-extraction` skill.
5. **Enum/category fields** — Add valid values lists. See `extraction-prompt-engineering` skill.
6. **Model upgrade** — If accuracy is still below target after schema improvements, try a stronger model. See `choosing-a-bedrock-model` skill.
7. **Task prompt refinement** — Add cross-cutting extraction guidance.
8. **Inference parameters** — Tune temperature/top_p for consistency. See `inference-parameter-tuning` skill.

## Interaction with Other Skills

This skill is a **meta-skill** that orchestrates the use of other skills. It references:

- **`extraction-prompt-engineering`**: For enriching field descriptions (the primary mechanism for schema refinement)
- **`evaluation-method-tuning`**: For ensuring measurements are accurate before optimizing
- **`boolean-field-extraction`**: For the specific category of boolean fields
- **`nested-schema-design`**: For structural schema issues
- **`choosing-a-bedrock-model`**: For model selection when schema changes aren't enough
- **`inference-parameter-tuning`**: For fine-tuning after schema is stable
- **`ground-truth-quality-analysis`**: For when accuracy plateaus due to GT issues, not extraction issues
- **`data-completeness-analysis`**: For understanding field density before prioritizing
- **`stepwise-extraction-strategy`**: For complex documents where single-pass extraction is the bottleneck

## Verification

After each iteration:
1. Compare overall accuracy to previous iteration
2. Compare per-field accuracy for the targeted fields
3. Check for regressions in non-targeted fields
4. Log the iteration results in OPTIMIZATION-LOG.md with:
   - What was changed and why
   - Which fields improved and by how much
   - Any regressions observed
   - Next planned iteration focus
