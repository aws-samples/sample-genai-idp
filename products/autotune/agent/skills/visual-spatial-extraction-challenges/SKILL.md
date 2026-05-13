---
name: visual-spatial-extraction-challenges
description: Document known challenges with fields requiring complex visual parsing (checkboxes, damage diagrams, spatial alignment) and provide mitigation strategies within the current IDP architecture.
---

# Visual/Spatial Extraction Challenges

## Problem

Some document fields require complex visual parsing that LLMs struggle with, even with multimodal input. These include checkboxes, damage diagrams, spatial alignment of marks in tables, and handwritten annotations overlaying printed forms. The LLM may confuse marks on one side of a table with another, misinterpret spatial relationships, or fail to associate visual elements with the correct field.

## Symptoms

- Specific fields have very low accuracy (<60%) despite good overall extraction performance
- The failing fields involve visual elements: checkboxes, X-marks, diagrams, spatial tables
- The LLM confuses which mark corresponds to which field (e.g., left-side vs right-side check marks)
- Handwritten annotations are misread or ignored
- Fields requiring cross-referencing visual position with tabular structure fail consistently
- Prompt improvements for these fields yield minimal gains

## Common Visual Challenges

| Challenge | Example | Difficulty |
|-----------|---------|------------|
| Checkbox/X-mark parsing | Check marks in a grid of options | High — LLM confuses adjacent marks |
| Damage diagrams | Vehicle damage location markings | Very high — requires spatial reasoning |
| Spatial table alignment | Coded values where position determines meaning | High — LLM misaligns columns |
| Handwritten over printed | Handwritten notes overlaying form fields | Medium-High — OCR may miss, image may misread |
| Multi-section cross-reference | Value on page 1 determines meaning of mark on page 2 | High — requires multi-page reasoning |

## Diagnosis

### Step 1: Identify Visual Fields

From evaluation results, find fields with consistently low accuracy. Then examine the source documents to determine if these fields involve visual parsing:

Use `get_evaluation_summary(batch_id)` to identify low-accuracy fields, then `download_single_document_results(batch_id, 'failing-doc.pdf')` to inspect the extraction output.

Look at the source document pages where the failing fields appear. If the fields involve checkboxes, diagrams, spatial tables, or handwritten content, they are visual extraction challenges.

### Step 2: Confirm It's a Visual Issue (Not a Prompt Issue)

Check whether the LLM is extracting *something* for these fields (wrong value) vs nothing (empty). If it's extracting wrong values that correspond to adjacent visual elements, it's a spatial confusion issue. If it's extracting nothing, it may be a prompt issue instead.

## Mitigation Strategies

### Strategy 1: Write Highly Specific Spatial Prompts

For fields in complex visual layouts, add very specific location and parsing instructions to the field description:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.properties.TrafficControlType.description",
     "value": "The traffic control type code from the TRAFFIC CRASH CODING table on page 2. This field appears in the LEFT column of the coding table. Look for a check mark or X mark to the LEFT of the code value. Do NOT confuse with marks on the RIGHT side of the same row, which belong to a different field. The code is the number/letter immediately to the RIGHT of the check mark."},
    {"op": "save"}
])
```

### Strategy 2: Add Section Indicators to the Task Prompt

Tell the LLM exactly where on the page to look for visual fields. Read the current task prompt with `config_edit(config_path, [{"op": "get", "field": "extraction.task_prompt"}])`, then append visual guidance and save.

Example visual guidance to append:

```
VISUAL FIELD EXTRACTION NOTES:
- For fields in the TRAFFIC CRASH CODING section (typically page 2), pay careful
  attention to which side of the table a check mark appears on. Left-side marks
  and right-side marks correspond to DIFFERENT fields.
- For damage diagram fields, describe the marked areas using the vehicle outline
  as reference (front, rear, left side, right side).
- When a field value is determined by a checkbox or X-mark, extract the label
  text associated with the MARKED checkbox, not adjacent unmarked ones.
```

### Strategy 3: Improve Image Quality for Visual Fields

Higher resolution images give the LLM better visual input for spatial parsing:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "extraction.image.dpi", "value": 300},
    {"op": "set", "field": "extraction.image.target_width", "value": 2400},
    {"op": "set", "field": "extraction.image.target_height", "value": 1800},
    {"op": "save"}
])
```

### Strategy 4: Use a Stronger Multimodal Model

More capable models have better spatial reasoning. If visual fields are critical:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "extraction.model", "value": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"},
    {"op": "save"}
])
```

### Strategy 5: Exclude and Flag for Human Review

If visual fields remain below acceptable accuracy after trying the above strategies, recommend excluding them from automated evaluation and flagging them for human review:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.properties.DamageDiagram.x-aws-idp-evaluation-weight", "value": 0},
    {"op": "set", "field": "classes.0.properties.TrafficControlType.x-aws-idp-evaluation-weight", "value": 0},
    {"op": "save"}
])
```

**Always flag this to the human:**

> "The following fields require complex visual/spatial parsing that the LLM struggles with:
> - [Field names and descriptions]
>
> I've tried improving prompts and image quality, but accuracy remains at [X%].
> These fields may be better suited for human review. I recommend excluding them
> from the automated accuracy metric and flagging them for manual QA.
>
> Would you like me to proceed with this approach?"

## Current Architecture Limitation

The IDP Accelerator currently performs a single extraction call per document class. There is no built-in support for:
- Field-level extraction splitting (extracting visual fields in a separate, focused call)
- Targeted image cropping (sending only the relevant page region for a specific field)
- Multi-pass extraction (first pass for text fields, second pass for visual fields)

These would be valuable future enhancements. For now, the mitigation strategies above work within the existing single-call architecture.

## Verification

1. Apply spatial prompt improvements and image quality changes
2. Re-run evaluation on the same test set
3. Compare accuracy for the specific visual fields before and after
4. If accuracy is still unacceptable, apply Strategy 5 (exclude + flag for human review)
5. Document visual field limitations in the optimization log and final report
