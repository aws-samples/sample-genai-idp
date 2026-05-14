---
name: token-limit-fix
description: Fix truncated JSON output for documents with many line items. Use when extraction output is cut off mid-JSON, documents have hundreds/thousands of line items, or you see incomplete JSON with missing closing braces
---

# Token Limit Fix

## Problem

Documents with many line items (e.g., invoices with 1000+ items) exceed the LLM's max_tokens limit, resulting in truncated JSON output that fails parsing.

## Symptoms

- Documents show 0% accuracy despite correct JSON formatting at start
- Extraction output JSON is incomplete (missing closing `}` or `]`)
- Documents have hundreds or thousands of line items
- Output ends abruptly mid-field or mid-array

## Diagnosis

1. Identify 0% accuracy documents using `get_evaluation_summary(batch_id)`.

2. Download and examine extraction output:
```
download_single_document_results(batch_id, '<filename>.pdf')
```

3. Check if JSON starts correctly but is truncated (incomplete structure)

4. Download ground truth to see expected line item count:
```
download_ground_truth(test_set_id, '<filename>.pdf')
```

## Fix

Read the current prompt with `config_edit(config_path, [{"op": "get", "field": "extraction.task_prompt"}])`, then append token limit guidance:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "extraction.task_prompt", "value": "<existing prompt + appended text below>"},
    {"op": "save"}
])
```

Text to append:

```
IMPORTANT: Some documents contain extremely long lists with thousands of line items. To ensure valid JSON output:
- Never output more than 500 line items for any single array
- If a document has more than 500 items, extract the first 500 and add a field "truncated": true
- Always ensure you output complete, valid JSON with all closing braces and brackets
```

## Verification

1. Deploy updated config
2. Re-run evaluation
3. Confirm previously truncated documents now produce valid JSON
4. Check that `"truncated": true` appears for long documents
