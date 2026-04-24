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

1. Identify 0% accuracy documents:
```python
from idpac.evaluations import EvaluationResult

result = EvaluationResult.from_aggregated_file('results/<summary>.json')
result.print_aggregated_summary(top_bottom_n=5)
```

2. Download and examine extraction output:
```python
from idpac import IDPACClient

client = IDPACClient('<stack-name>', region='us-east-1')
client.download_single_document_results('<batch-id>', '<filename>.pdf', 'investigation/')
```

3. Check if JSON starts correctly but is truncated (incomplete structure)

4. Download ground truth to see expected line item count:
```python
client.download_ground_truth('<test-set-id>', '<filename>.pdf', 'investigation/gt.json')
```

## Fix

Add line item limit instructions to `extraction.task_prompt`:

```python
from idpac import IDPConfig

config = IDPConfig('idp-configs/current.yaml')
current_prompt = config.get('extraction.task_prompt')

token_fix = '''

IMPORTANT: Some documents contain extremely long lists with thousands of line items. To ensure valid JSON output:
- Never output more than 500 line items for any single array
- If a document has more than 500 items, extract the first 500 and add a field "truncated": true
- Always ensure you output complete, valid JSON with all closing braces and brackets'''

config.set('extraction.task_prompt', current_prompt + token_fix)
config.save('idp-configs/current-token-fix.yaml')
```

## Verification

1. Deploy updated config
2. Re-run evaluation
3. Confirm previously truncated documents now produce valid JSON
4. Check that `"truncated": true` appears for long documents
