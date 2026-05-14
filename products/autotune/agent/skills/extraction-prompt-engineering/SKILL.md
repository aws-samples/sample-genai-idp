---
name: extraction-prompt-engineering
description: Improve extraction accuracy by enriching schema field descriptions with domain context, examples, formatting rules, and edge case instructions. Use when per-field accuracy is low despite correct classification and OCR.
---

# Extraction Prompt Engineering

## Problem

Extraction accuracy is low for specific fields because the schema field descriptions are too vague for the LLM to extract values correctly. The LLM needs domain context, formatting examples, and edge case handling to reliably extract complex or ambiguous fields.

## Symptoms

- Overall extraction accuracy is moderate but specific fields have very low accuracy
- Fields with domain-specific formats (dates, codes, legal descriptions, identifiers) score poorly
- LLM extracts values in wrong format or misidentifies which value to extract
- Similar-sounding fields are confused (e.g., "FileDate" vs "RecordDate" vs "InstDate")

## Diagnosis

Use `get_evaluation_summary(batch_id)` to see per-field accuracy and identify weak fields. Then investigate individual failing documents:

```
download_single_document_results(batch_id, 'failing-doc.pdf')
download_ground_truth(test_set_id, 'failing-doc.pdf')
```

Compare the extracted values against ground truth to understand *why* the field is wrong — wrong format? Wrong value selected? Missing entirely?

## Fix Strategy

The single most impactful optimization for extraction accuracy is enriching field descriptions in the schema. This has been shown to dramatically improve per-field F1 scores (e.g., a township field went from 0.28 to 0.59 F1 just by expanding its description).

### Principles

1. **Be specific about what the field contains** — don't just name it, explain what it represents in the domain
2. **Provide format examples** — show exactly what valid values look like
3. **Explain edge cases** — how to handle ambiguous or variant formats
4. **Distinguish similar fields** — explicitly contrast fields that could be confused
5. **Add domain knowledge** — if a field requires specialized knowledge to extract correctly, include that knowledge in the description

### Step 1: Identify Weak Fields

From evaluation results, find fields with low accuracy. Prioritize fields that:
- Have 0% or very low accuracy
- Are important to the use case (high weight)
- Appear across many documents

### Step 2: Enrich Field Descriptions

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.properties.township.description",
     "value": "The PLSS township designation indicating position north or south of the baseline. Townships are 6-mile x 6-mile squares containing 36 sections. Format includes the township number followed by directional indicator (N for North, S for South of baseline). Format as T[-]{digit}[-]{direction}, such as T5S or T-2-E. Extract the complete designation including direction."},
    {"op": "save"}
])
```

### Step 3: Distinguish Confusable Fields

When two fields are semantically similar, explicitly contrast them:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.properties.RecordDate.description",
     "value": "Date when the document was officially recorded by the county office. Look for keywords: \"Recorded\", \"duly Recorded\", \"e-Recorded for\". This is NOT the execution date or filing date. Format: YYYY-MM-DD."},
    {"op": "set", "field": "classes.0.properties.FileDate.description",
     "value": "Date when the document was initially submitted/filed, which may precede the recording date. Often identical to RecordDate when processed immediately. This is NOT the execution or acknowledgement date. Format: YYYY-MM-DD."},
    {"op": "set", "field": "classes.0.properties.ExecutedDate.description",
     "value": "Date when the document was signed/executed by the parties. This is typically the earliest date and precedes filing and recording. Format: YYYY-MM-DD."},
    {"op": "save"}
])
```

### Step 4: Handle Complex Nested/Array Fields

For array fields containing structured objects, describe both the array purpose and each sub-field:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.properties.line_items.description",
     "value": "List of all line items in order of appearance. Extract ALL items — do not skip or summarize."},
    {"op": "set", "field": "classes.0.properties.line_items.items.properties.quantity.description",
     "value": "Numeric quantity ordered. Extract only the number, not units. Example: \"5\" from \"5 boxes\"."},
    {"op": "set", "field": "classes.0.properties.line_items.items.properties.unit_price.description",
     "value": "Price per single unit before tax/discount. Extract as decimal number without currency symbol. Example: \"12.50\" not \"$12.50\"."},
    {"op": "save"}
])
```

### Step 5: Include Valid Values for Enum/Dropdown Fields

When a field has a fixed set of valid values (codes, categories, dropdown options), listing those values in the field description is one of the highest-impact improvements you can make. In past engagements, adding dropdown values to field descriptions was a major factor in achieving ~40% accuracy improvement across iterative prompt refinements.

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.properties.CrashType.Code.description",
     "value": "The crash type classification code. Must be one of the following values: \"A\" (Head-On), \"B\" (Sideswipe-Same Direction), \"C\" (Rear End), \"D\" (Broadside), \"E\" (Hit Object), \"F\" (Overturned), \"G\" (Vehicle/Pedestrian), \"H\" (Other). Extract the code letter only, not the description."},
    {"op": "set", "field": "classes.0.properties.CrashType.Description.description",
     "value": "The human-readable description of the crash type. Must be exactly one of: \"Head-On\", \"Sideswipe-Same Direction\", \"Rear End\", \"Broadside\", \"Hit Object\", \"Overturned\", \"Vehicle/Pedestrian\", \"Other\". Use the description that corresponds to the code value."},
    {"op": "save"}
])
```

**Tradeoffs to consider:**
- Including all valid options significantly improves accuracy for enum fields
- For fields with many options (e.g., 50+ vehicle type codes), the token cost of listing all values may be significant
- For very large option sets, consider extracting only the code value and mapping to descriptions via post-processing (see the `post-processing-task-decomposition` skill)
- When options are included, the LLM can reason about which value best matches the document content, which often outperforms extracting raw text and mapping later

**When to include valid values:**
- The field is a code, category, status, or type with a known finite set of options
- The ground truth uses standardized values that may differ from how they appear in the document
- The LLM is extracting wrong or inconsistent values for the field

### Step 6: Prevent Hallucination on Absent Fields

LLMs have a strong tendency to fill in fields from contextually related but semantically wrong content when the actual field is absent from the document. For example, a "work state" field might be filled from a mailing address state, or an "employer phone" might be filled from an employee's phone number. The LLM finds nearby plausible-looking content and uses it rather than returning null.

This is distinct from the general "return null for missing fields" instruction — the LLM genuinely believes it found the value because similar content exists in the document. You need to explicitly tell it where NOT to look.

**How to detect**: A field has low accuracy, and manual inspection shows extracted values come from a different part of the document than intended. The values are real data from the document, just from the wrong field or section.

**Fix via field description** — explicitly state what the field is NOT and where NOT to look:

```
# BAD: Vague — LLM will grab any state it finds
# "work_state": { "description": "The employee's work state", "type": "string" }

# GOOD: Explicitly disambiguates from nearby similar content
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.properties.work_state.description",
     "value": "The state where the employee performs their work duties. This must be explicitly labeled as \"work state\" or \"state of employment\" in the document. Do NOT extract the state from the employee mailing address, employer address, or any other address field. If no explicitly labeled work state field exists in the document, return null."},
    {"op": "save"}
])
```

**Fix via task prompt** — add a cross-cutting instruction for all fields:

```
# First read the current prompt:
config_edit(config_path, operations=[{"op": "get", "field": "extraction.task_prompt"}])

# Then append anti-hallucination guidance:
config_edit(config_path, operations=[
    {"op": "set", "field": "extraction.task_prompt", "value": "<current_prompt + the following appended>\n- CRITICAL: Only extract a value for a field if the document contains content that specifically corresponds to that field. Do not infer or fill in a field from nearby similar-looking content. If a field is not explicitly present in the document, return null rather than guessing from related fields."},
    {"op": "save"}
])
```

**Common patterns to watch for:**
- Address components (work state vs mailing state vs employer state)
- Phone numbers (employee phone vs employer phone vs emergency contact)
- Dates (execution date vs filing date vs effective date — also covered in Step 3)
- Names (employee name vs employer contact name vs physician name)
- ID numbers (employee ID vs plan number vs group number)

### Step 7: Add Extraction Instructions to Task Prompt

For cross-cutting concerns that apply to all fields, add instructions to the extraction task prompt rather than individual field descriptions:

```
# Read current prompt first:
config_edit(config_path, operations=[{"op": "get", "field": "extraction.task_prompt"}])

# Then set the updated prompt with appended guidelines:
config_edit(config_path, operations=[
    {"op": "set", "field": "extraction.task_prompt", "value": "<existing prompt + appended extraction guidelines>"},
    {"op": "save"}
])
```

Example extraction guidelines to append:

```
EXTRACTION GUIDELINES:
- Extract values exactly as they appear in the document unless a specific format is requested in the field description.
- For fields with no matching value in the document, return null.
- For date fields, convert to YYYY-MM-DD format regardless of how the date appears in the document.
- For numeric fields, extract only the numeric value without currency symbols or units.
- For name fields, preserve the original casing and spelling from the document.
- When multiple candidate values exist for a field, use the field description to determine which is correct.
```

## Description Enrichment Template

When writing or improving a field description, include as many of these elements as relevant:

```
[What it is] — one sentence defining the field in domain terms
[Where to find it] — location cues (header, margin, stamp, table column)
[Format] — expected output format with regex or pattern
[Examples] — 2-3 concrete examples of valid values
[Valid values] — if the field is an enum/dropdown, list all acceptable values
[Edge cases] — how to handle variants, abbreviations, missing values
[Disambiguation] — how this differs from similar fields
```

Example applying the template:

```
"The unique sequential identifier assigned by the county recorder's office
when the document was officially filed (what). This number appears in the
document header or clerk's stamp (where). Always preserve leading zeros
exactly as shown (format). Examples: '202401485', '2023-012345' (examples).
When multiple formats are present, prioritize the version that includes
the year prefix (edge case). This is the filing number for THIS document,
not for prior referenced documents (disambiguation)."
```

## Schema-Level Annotations: `data_type` and `enum`

Beyond field descriptions, two schema-level annotations significantly improve extraction accuracy:

### `data_type` — Always Add to Leaf Fields

Every leaf field (string, number, boolean) should have a `data_type` annotation matching its type. This tells the extraction pipeline how to parse and validate the value. Missing `data_type` can cause subtle extraction issues.

```
# You can add data_type automatically to all leaf fields:
auto_fix_config(config_path, fixes=["add_data_type"])
```

### `enum` — Use for Categorical Fields

When a field has a known finite set of valid values, add an `enum` constraint directly on the schema property. This is more effective than listing values only in the description because the LLM sees the constraint as a hard requirement, not a suggestion.

Use `config_edit` to add enum constraints:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.properties.status.enum",
     "value": ["functional", "needsService", "defective", "pass", "fail", "na"]},
    {"op": "set", "field": "classes.0.properties.status.description",
     "value": "Inspection status. Must be one of the enum values."},
    {"op": "save"}
])
```

**When to add `enum`:**
- Status fields (pass/fail, active/inactive, approved/rejected)
- Category/type fields with known options
- Code fields with a fixed set of valid values
- Any field where the ground truth uses a standardized set of values

**Combine `enum` with description** for best results — the `enum` constrains the output, while the description helps the LLM choose the right value when the document text doesn't exactly match an enum option.

## Verification

1. Deploy updated config
2. Re-run evaluation on same test set
3. Compare per-field accuracy before and after
4. Focus on the specific fields you enriched — expect significant gains on those fields
5. Check that enriching descriptions didn't regress other fields
