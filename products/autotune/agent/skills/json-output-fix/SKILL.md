---
name: json-output-fix
description: Fix JSON parsing failures caused by LLMs wrapping output in markdown or XML. Use when documents show 0% accuracy and extraction output doesn't start with the "{" character.
---

# JSON Output Parsing Fix

## Problem

LLMs sometimes wrap JSON output in markdown code blocks or XML tags, causing the IDP backend to fail parsing.

## Symptoms

- Documents show 0% accuracy in evaluation results
- Extraction output contains valid JSON but wrapped in formatting
- Error logs mention JSON parsing failures

## Diagnosis

1. Identify 0% accuracy documents from evaluation summary using `get_evaluation_summary(batch_id)`.

2. Download extraction output for a failing document:
```
download_single_document_results(batch_id, '<filename>.pdf')
```

3. Check if output starts with ` ```json ` or `<response>` instead of `{`

## Fix

Add explicit JSON formatting instructions to `extraction.task_prompt`. First read the current prompt with `config_edit(config_path, [{"op": "get", "field": "extraction.task_prompt"}])`, then append:

```
config_edit(config_path, operations=[
    {"op": "set", "field": "extraction.task_prompt", "value": "<existing prompt + appended text below>"},
    {"op": "save", "output_path": "configs/current-json-fix.yaml"}
])
```

Text to append:

```
CRITICAL: Output ONLY valid JSON. The very first character you generate must be an opening brace "{". Do not wrap the JSON in markdown code blocks, backticks, or XML tags. Do not include any text before or after the JSON object.
```

## Verification

1. Deploy updated config: `upload_config('configs/current-json-fix.yaml', config_version='<version>', description='Applied JSON output fix')`
2. Re-run evaluation on same test set
3. Confirm previously failing documents now have non-zero accuracy
4. Verify extraction outputs start with `{`
