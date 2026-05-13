---
name: nested-schema-design
description: Design nested document class schemas using $defs/$ref for grouped fields and arrays. Use when ground truth has nested object structure, or when flat schemas produce poor extraction for documents with logical field groupings.
---

# Nested Schema Design

## Problem

The schema discovery process generates flat schemas by default, but many documents have logically grouped fields (e.g., PatientInformation, PaymentDetails, ServiceLineItems). When ground truth uses nested structure, the schema must match. Even when ground truth is flat, grouping related fields into nested objects can improve extraction accuracy by giving the LLM structural context.

## Symptoms

- Ground truth has nested objects but schema is flat — evaluation fails or shows 0% on grouped fields
- Extraction output has flat fields that should be grouped (e.g., `Patient-Name`, `Patient-DOB` instead of `PatientInformation.Patient-Name`)
- Array fields (line items, charges) are extracted as single strings instead of structured arrays
- Evaluation shows 0% on array fields despite correct-looking extraction
- **Evaluation crashes with `unhashable type: 'list'`** — caused by nullable types like `type: ["string", "null"]` in the schema (see Critical Rule below)

## Critical Rule: No Nullable Type Lists

**NEVER** use JSON Schema nullable syntax `type: ["string", "null"]` in IDP schemas. The evaluator cannot hash Python lists, causing `unhashable type: 'list'` errors and 0% accuracy on any class containing such a field.

```yaml
# BAD — causes evaluator crash
hours:
  type: ["string", "null"]

# GOOD — use plain type instead
hours:
  type: string
```

If ground truth has `null` values for a field, still use `type: string` — the LLM will output `null` naturally and the evaluator handles null values, just not list-typed schema definitions.

Use `config.validate()` to detect this issue and `config.auto_fix(['fix_nullable_types'])` to fix it automatically.

## When to Use Nested Schemas

| Document Pattern | Schema Approach |
|-----------------|-----------------|
| Simple form with ~10 independent fields | Flat schema (no nesting needed) |
| Form with logical sections (patient info, payment info, etc.) | Group fields into nested objects |
| Document with repeating line items (services, charges, items) | Array with structured item schema |
| Ground truth already has nested structure | Schema MUST match the nesting |

## Fix 1: Create Grouped Fields with `$defs` and `$ref`

Use `$defs` to define reusable sub-object types, then reference them with `$ref` from the top-level `properties`. Use `config_edit` to read the current class, then set the `$defs` and update `properties`:

```
# First read the current class schema
config_edit(config_path, operations=[{"op": "get", "field": "classes.0"}])

# Add a $defs section with a group definition
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.$defs.PatientInformationDef", "value": {
        "type": "object",
        "description": "Information about the patient.",
        "properties": {
            "Patient-Name": {
                "type": "string",
                "description": "Full name of the patient.",
                "x-aws-idp-evaluation-method": "FUZZY"
            },
            "Patient-DOB": {
                "type": "string",
                "format": "date",
                "description": "Date of birth of the patient.",
                "x-aws-idp-evaluation-method": "EXACT"
            },
            "Patient-ID": {
                "type": "string",
                "description": "Patient identification number.",
                "x-aws-idp-evaluation-method": "EXACT"
            }
        }
    }},
    {"op": "set", "field": "classes.0.properties.PatientInformation", "value": {
        "description": "Information about the patient.",
        "$ref": "#/$defs/PatientInformationDef",
        "x-aws-idp-evaluation-method": "LLM"
    }},
    {"op": "save"}
])
```

**Key rules:**
- Each `$defs` entry must have `type: object` and `properties`
- The top-level property must have both `$ref` AND its own `x-aws-idp-evaluation-method`
- Leaf fields inside `$defs` get their own specific evaluation methods (EXACT, FUZZY, etc.)
- Do not nest groups within groups — all groups should be directly under the top-level `properties`

## Fix 2: Create Array Fields with Structured Items

For repeating records (line items, charges, services), use `type: array` with `items` referencing a `$defs` entry.

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.$defs.ServiceLineItem", "value": {
        "type": "object",
        "properties": {
            "Date-of-Service": {
                "type": "string",
                "format": "date",
                "description": "Date the service was provided.",
                "x-aws-idp-evaluation-method": "EXACT"
            },
            "Procedure-Code": {
                "type": "string",
                "description": "CPT or procedure code for the service.",
                "x-aws-idp-evaluation-method": "EXACT"
            },
            "Charges": {
                "type": "string",
                "description": "Dollar amount charged for this service.",
                "x-aws-idp-evaluation-method": "EXACT"
            }
        }
    }},
    {"op": "set", "field": "classes.0.properties.ServiceInformation", "value": {
        "description": "List of services provided to the patient.",
        "type": "array",
        "x-aws-idp-list-item-description": "Each item represents one service line from the claim form.",
        "items": {
            "$ref": "#/$defs/ServiceLineItem"
        },
        "x-aws-idp-evaluation-method": "LLM"
    }},
    {"op": "save"}
])
```

**Key rules:**
- The array property needs `type: array`, `items` with `$ref`, and `x-aws-idp-evaluation-method`
- Add `x-aws-idp-list-item-description` to describe what each array element represents — this is used by the assessment service
- Set evaluation methods on the individual item properties inside `$defs`, not on the array itself
- The array-level `x-aws-idp-evaluation-method: LLM` controls how the array as a whole is compared to ground truth

## Fix 3: Evaluation Method Layering

Nested schemas require evaluation methods at two levels:

| Level | Where | Method | Purpose |
|-------|-------|--------|---------|
| Parent property | Top-level `properties` entry with `$ref` | Usually `LLM` | Compares the entire group/array as a unit |
| Leaf fields | Inside `$defs` on each property | `EXACT`, `FUZZY`, `LLM`, etc. | Compares individual field values |

```yaml
# Parent level — on the $ref property
properties:
  PatientInformation:
    description: Information about the patient.
    $ref: '#/$defs/PatientInformationDef'
    x-aws-idp-evaluation-method: LLM          # ← evaluates the group as a whole

# Leaf level — inside $defs
$defs:
  PatientInformationDef:
    type: object
    properties:
      Patient-Name:
        type: string
        x-aws-idp-evaluation-method: FUZZY     # ← evaluates this specific field
      Patient-ID:
        type: string
        x-aws-idp-evaluation-method: EXACT     # ← evaluates this specific field
```

If you omit `x-aws-idp-evaluation-method` on the parent property, evaluation may not work correctly for that group.

## Converting Flat Schema to Nested

When you have a flat schema and ground truth is nested, restructure by:

1. Identify logical field groups from the ground truth structure
2. Create a `$defs` entry for each group
3. Move the relevant flat fields into the group's `properties`
4. Replace the flat fields in top-level `properties` with a single `$ref` entry
5. Add `x-aws-idp-evaluation-method` at both levels

Use `config_edit` to read the current class, then restructure. For example, to group patient fields:

```
# Read current class to see flat fields
config_edit(config_path, operations=[{"op": "get", "field": "classes.0.properties"}])

# Create the $defs group and update properties
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.$defs.PatientInfoDef", "value": {
        "type": "object",
        "description": "Patient demographic information.",
        "properties": {
            "Patient-Name": {"type": "string", "description": "...", "x-aws-idp-evaluation-method": "FUZZY"},
            "Patient-DOB": {"type": "string", "format": "date", "description": "...", "x-aws-idp-evaluation-method": "EXACT"}
        }
    }},
    {"op": "set", "field": "classes.0.properties.PatientInformation", "value": {
        "description": "Patient demographic information.",
        "$ref": "#/$defs/PatientInfoDef",
        "x-aws-idp-evaluation-method": "LLM"
    }},
    {"op": "save"}
])
```

Note: You'll also need to remove the old flat fields (`Patient-Name`, `Patient-DOB`) from the top-level properties. Read the full class, restructure it, and save.

## Verification

1. Run `config.validate()` to check for schema errors
2. Deploy and run evaluation
3. Confirm grouped fields show non-zero accuracy
4. Confirm array fields are extracted as structured arrays, not flat strings
5. Compare overall accuracy before/after restructuring

## Leaf Field Annotations

When building nested schemas, always include these annotations on every leaf field (string, number, boolean):

- **`data_type`**: Must match the field type (`string`, `number`, or `boolean`). Improves extraction accuracy by telling the pipeline how to parse values. Run `config.auto_fix(['add_data_type'])` to add automatically.
- **`enum`**: For categorical fields with known valid values, add an `enum` list to constrain LLM output. This is especially important inside `$defs` where fields like status codes, types, or categories appear.

```yaml
# Example: leaf fields inside a $defs entry with proper annotations
$defs:
  CheckpointItem:
    type: object
    properties:
      status:
        type: string
        data_type: string
        description: Inspection result
        enum: [functional, needsService, defective]
        x-aws-idp-evaluation-method: EXACT
      notes:
        type: string
        data_type: string
        description: Inspector notes
        x-aws-idp-evaluation-method: LEVENSHTEIN
        x-aws-idp-evaluation-threshold: '0.7'
```
