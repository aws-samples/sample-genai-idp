---
name: boolean-field-extraction
description: Improve extraction accuracy for boolean/yes-no fields. Handles the critical N/A vs No distinction, explicit vs implied values, and normalization. Use when boolean fields have low accuracy or inconsistent output values.
---

# Boolean Field Extraction

## Problem

Boolean fields (yes/no, true/false, permitted/not permitted) are deceptively difficult to extract accurately. The core challenges are:

1. **N/A vs No confusion**: "Not applicable" (the field doesn't apply to this document) and "No" (the answer is explicitly negative) are semantically different but LLMs frequently confuse them. This distinction is critical — marking a right as "No" when it's actually "N/A" changes the business meaning entirely.

2. **Explicit vs implied values**: Fields whose values are explicitly stated in the document (e.g., "Exclusivity: Yes") achieve much higher accuracy (~94%) than fields whose values must be inferred from context or absence of mention (~79-82%). When a right is not mentioned at all, the LLM must decide whether that means "No" or "N/A" — a judgment call that requires domain understanding.

3. **Normalization inconsistency**: Documents express boolean concepts in many ways ("Yes", "Y", "True", "Permitted", "Allowed", "Granted", "✓", etc.) and the LLM may output different representations across documents.

Past engagements have shown boolean fields consistently require specialized handling and are often the last category to reach acceptable accuracy.

## Symptoms

- Boolean fields have lower accuracy than string or date fields in the same schema
- Ground truth has "N/A" but extraction outputs "No" (or vice versa)
- Explicitly stated boolean fields (e.g., "Exclusivity?") score well but implied ones (e.g., "Simulcast Allowed?") score poorly
- Boolean field values are inconsistent across documents ("Yes", "True", "Y", "Allowed" for the same field)
- Evaluation uses EXACT matching and fails on equivalent representations ("Yes" vs "yes" vs "Y")

## Diagnosis

Use `get_evaluation_summary(batch_id)` to identify boolean fields with low accuracy. Then investigate individual documents:

```
download_single_document_results(batch_id, 'failing-doc.pdf')
download_ground_truth(test_set_id, 'failing-doc.pdf')
```

For each failing boolean field, categorize the error:
- **N/A vs No**: GT says "N/A", extraction says "No" (or vice versa)
- **Implied value wrong**: The right isn't explicitly mentioned, LLM guessed wrong
- **Format mismatch**: GT says "Yes", extraction says "True" or "Allowed"
- **Missed explicit value**: The value is clearly stated but LLM didn't find it

## Fix 1: Define the N/A vs No Distinction in Field Descriptions

This is the single most impactful fix for boolean fields. Every boolean field description should explicitly define when to output each possible value:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.properties.Exclusivity.description",
     "value": "Whether the licensee has been granted exclusive rights. Return \"Yes\" if the document explicitly grants exclusive rights. Return \"No\" if the document explicitly states rights are non-exclusive or shared. Return \"N/A\" if exclusivity is not discussed or not applicable to this document type. Do NOT return \"No\" simply because exclusivity is not mentioned — if the topic is not addressed, the correct answer is \"N/A\"."},
    {"op": "save"}
])
```

Apply this pattern to every boolean field in the schema.

## Fix 2: Add Boolean Extraction Rules to the Task Prompt

Add cross-cutting guidance that applies to all boolean fields:

Read the current prompt with `config_edit(config_path, [{"op": "get", "field": "extraction.task_prompt"}])`, then append boolean guidance:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "extraction.task_prompt", "value": "<existing prompt + appended text below>"},
    {"op": "save"}
])
```

Text to append:

```
BOOLEAN FIELD RULES:
- Boolean fields must return exactly one of: "Yes", "No", or "N/A".
- "Yes" = the document explicitly grants or confirms this.
- "No" = the document explicitly denies, prohibits, or negates this.
- "N/A" = the document does not address this topic, or it does not apply.
- CRITICAL: Do NOT confuse "N/A" with "No". If a right or permission is
  simply not mentioned in the document, return "N/A", not "No". Only return
  "No" when there is explicit language denying or prohibiting it.
- When a right must be inferred from broader language (e.g., "all media
  rights" implies simulcast is allowed), return "Yes" and note that it is
  implied by the broader grant.
```

## Fix 3: Handle Implied Values with Explicit Guidance

For fields where the value is often implied rather than stated, add inference rules to the field description:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.properties.SimulcastAllowed.description",
     "value": "Whether simultaneous broadcast (simulcast) is permitted. Return \"Yes\" if simulcast is explicitly allowed, OR if the document grants \"all media rights\" or \"all distribution rights\" without excluding simulcast. Return \"No\" only if simulcast is explicitly prohibited or excluded. Return \"N/A\" if the document does not address media distribution rights at all."},
    {"op": "set", "field": "classes.0.properties.SublicenseAllowed.description",
     "value": "Whether the licensee may sublicense the rights to third parties. Return \"Yes\" if sublicensing is explicitly permitted. Return \"No\" if sublicensing is explicitly prohibited or restricted. Return \"N/A\" if sublicensing is not discussed. Note: the absence of a sublicensing clause does NOT mean sublicensing is allowed — it means the topic is not addressed (\"N/A\")."},
    {"op": "save"}
])
```

## Fix 4: Set Appropriate Evaluation Methods

Boolean fields need evaluation methods that handle normalization:

```
# Option A: Use LLM evaluation to handle semantic equivalence
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.properties.Exclusivity.x-aws-idp-evaluation-method", "value": "LLM"},
    {"op": "save"}
])

# Option B: Use EXACT if ground truth is already normalized to Yes/No/N/A
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.properties.Exclusivity.x-aws-idp-evaluation-method", "value": "EXACT"},
    {"op": "save"}
])

# Option C: Use FUZZY with a moderate threshold for minor variations
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.properties.Exclusivity.x-aws-idp-evaluation-method", "value": "FUZZY"},
    {"op": "set", "field": "classes.0.properties.Exclusivity.x-aws-idp-evaluation-threshold", "value": 0.8},
    {"op": "save"}
])
```

**Recommendation**: Use `LLM` evaluation for boolean fields during optimization (most forgiving, catches semantic equivalence). Once the extraction is stable and output format is consistent, switch to `EXACT` for faster, cheaper evaluation. See the `evaluation-method-tuning` skill for details on changing evaluation methods.

## Fix 5: Normalize Output Format in the Task Prompt

If the ground truth uses a specific format (e.g., always "Yes"/"No"/"N/A"), constrain the LLM output:

Read the current prompt and append normalization guidance:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "extraction.task_prompt", "value": "<existing prompt + appended text below>"},
    {"op": "save"}
])
```

Text to append:

```
OUTPUT FORMAT FOR BOOLEAN FIELDS:
- Use exactly "Yes", "No", or "N/A" (with this exact capitalization).
- Do NOT use: "True"/"False", "Y"/"N", "Allowed"/"Not Allowed",
  "Permitted"/"Not Permitted", or any other variation.
- Do NOT add qualifiers like "Yes (implied)" or "No (not mentioned)".
  Return only the single word.
```

## Common Boolean Field Patterns

| Pattern | Correct Output | Why It's Tricky |
|---------|---------------|-----------------|
| Right explicitly granted | "Yes" | Straightforward |
| Right explicitly denied/prohibited | "No" | Straightforward |
| Right not mentioned at all | "N/A" | LLMs often default to "No" |
| Broad grant implies the right (e.g., "all media") | "Yes" | Requires inference |
| Right mentioned but with conditions | "Yes" | Conditions go in a separate field |
| Document type doesn't have this concept | "N/A" | LLMs may guess "No" |

## Interaction with Other Skills

- **`extraction-prompt-engineering`**: Apply the description enrichment template to boolean fields, with special attention to the three-way Yes/No/N/A distinction.
- **`evaluation-method-tuning`**: Choose the right evaluation method for boolean fields (LLM during optimization, EXACT once stable).
- **`ground-truth-quality-analysis`**: If ground truth inconsistently uses "N/A", blank, "No", "None", etc. for the same concept, fix the ground truth first.
- **`sparse-field-metric-selection`**: Boolean fields that are "N/A" in most documents are effectively sparse fields — consider metric implications.

## Verification

1. Deploy updated config with boolean-specific prompt guidance and field descriptions
2. Re-run evaluation on the same test set
3. Compare boolean field accuracy before and after
4. Specifically check N/A vs No confusion rate — this should improve the most
5. Check that explicitly stated boolean fields maintain high accuracy
6. Check that implied boolean fields show improvement
