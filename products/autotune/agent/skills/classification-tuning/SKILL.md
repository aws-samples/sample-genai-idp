---
name: classification-tuning
description: Improve classification accuracy for multi-class datasets. Use when documents are being misclassified, causing extraction to use the wrong schema.
---

# Classification Tuning

## Problem

Documents are being classified incorrectly, causing extraction to use wrong schema and produce 0% accuracy.

## Symptoms

- Low `splitClassificationMetrics.accuracy` in evaluation results
- Some classes have high extraction accuracy, others have 0%
- Individual document results show wrong `document_class`

## Diagnosis

Use `get_evaluation_summary(batch_id)` to get classification metrics. Check which classes have low accuracy — if extraction accuracy is 0% but other classes are high, it's likely misclassification.

## Fix

### 1. Improve Class Descriptions

Add clear, discriminative descriptions to each class schema. The `{CLASS_NAMES_AND_DESCRIPTIONS}` placeholder in the classification prompt pulls from these.
*CRITICAL* Do NOT make any assumptions about what is in the class based on the name of the class. For all intents and purposes, the class names could be randomized. In order to build a better description, you should look at a few sample documents of that class if they are available and try to write descriptions which balance being specific to that class without overfitting to those specific documents. If you do not have access to those documents, stop and ask for a human's advice by prompting them that you need to improve the description of a certain class of document and asking them how they would do it.

**Template:**
```
[Document type] with [key structural feature]. Contains [distinctive content].
Distinguished from similar documents by [unique characteristic].
```

**Example:**
```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.description",
     "value": "Invoice requesting payment - shows amount DUE, has payment terms, includes line items with quantities and prices, no payment confirmation"},
    {"op": "set", "field": "classes.1.description",
     "value": "Receipt confirming payment - shows amount PAID, has transaction/confirmation ID, marked as paid/complete, may show payment method used"},
    {"op": "save"}
])
```

**For confusable classes**, explicitly contrast them:
```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.2.description",
     "value": "Delivery note documenting shipped items - focuses on quantities delivered and shipping details. Unlike invoices, does NOT include prices or payment terms"},
    {"op": "save"}
])
```

### 2. Use Stronger Classification Model

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classification.model", "value": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"},
    {"op": "save"}
])
```

### 3. Apply Negative Prompting

When two classes are frequently confused, positive descriptions alone may not be enough. Negative prompting explicitly tells the classifier what a class is NOT. In past engagements, adding negative prompts resolved persistent misclassification between similar document types (e.g., request forms being misclassified as result reports because both contain similar terminology).

**In class descriptions** — add "this is NOT" statements:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.description",
     "value": "A test request form submitted by a physician to order a specific test. Contains patient demographics, ordering physician info, and test selections. This is NOT a test results report — it does not contain test outcomes, findings, or diagnostic conclusions."},
    {"op": "set", "field": "classes.1.description",
     "value": "A test results report containing diagnostic findings and conclusions. This is NOT a request form — it does not contain test order checkboxes or ordering physician signature blocks."},
    {"op": "save"}
])
```

**In the classification task prompt** — add cross-cutting negative instructions. Read the current prompt with `config_edit(config_path, [{"op": "get", "field": "classification.task_prompt"}])`, then append negative guidance and save.

**When to use negative prompting:**
- Two specific classes are consistently confused in the classification summary
- The confused classes share terminology or subject matter but serve different purposes
- Positive descriptions have already been improved but confusion persists

### 4. Use Structure-Based Differentiation

When document content overlaps between classes, describe the document's physical structure and format as a classification signal.

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classes.0.description",
     "value": "Clinical notes written in free-form narrative style. Typically has a dated header with patient name, followed by unstructured paragraphs of clinical observations. No formal letter formatting — no recipient address block, no salutation line, no signature block with credentials."},
    {"op": "set", "field": "classes.1.description",
     "value": "A formal letter of medical necessity in standard business letter format. Has a recipient address block at the top, a salutation line (e.g., \"Dear...\", \"To Whom It May Concern\"), structured body paragraphs, and a closing with physician signature and credentials. Unlike clinical notes, this is addressed TO someone."},
    {"op": "save"}
])
```

**Structural features to describe:**
- Document format (form with fields, letter with address block, narrative text, table-heavy)
- Header/footer patterns (letterhead, page numbers, document ID stamps)
- Section organization (numbered sections, free-form, tabular)
- Signature/authentication elements (signature blocks, notary stamps, checkboxes)
- Visual layout (multi-column, single column, form grid)

**When to use:**
- Classes share similar terminology but have different physical formats
- Content-based descriptions aren't sufficient to distinguish classes
- Documents have strong visual/structural differences that are easy to describe in words

### 5. Customize Classification Prompt

If default prompt isn't working, customize while keeping the placeholder:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "classification.task_prompt",
     "value": "Classify this document into exactly one category from:\n{CLASS_NAMES_AND_DESCRIPTIONS}\n\nExamine the document's header, structure, and key terminology.\nReturn your classification in the specified JSON format."},
    {"op": "save"}
])
```

## Verification

1. Deploy updated config
2. Re-run evaluation
3. Compare `splitClassificationMetrics.accuracy` before/after
4. Check that previously misclassified documents now have correct class
