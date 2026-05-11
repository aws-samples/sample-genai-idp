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

1. Identify 0% accuracy documents from evaluation summary:
```python
from idpac.evaluations import EvaluationResult

result = EvaluationResult.from_aggregated_file('results/<summary>.json')
result.print_aggregated_summary(top_bottom_n=5)
```

2. Download extraction output for a failing document:
```python
from idpac import IDPACClient

client = IDPACClient('<stack-name>', region='us-east-1')
client.download_single_document_results('<batch-id>', '<filename>.pdf', 'investigation/')
```

3. Check if output starts with ` ```json ` or `<response>` instead of `{`

## Fix

Add explicit JSON formatting instructions to `extraction.task_prompt`:

```python
from idpac import IDPConfig

config = IDPConfig('idp-configs/current.yaml')
current_prompt = config.get('extraction.task_prompt')

json_fix = '''

CRITICAL: Output ONLY valid JSON. The very first character you generate must be an opening brace "{". Do not wrap the JSON in markdown code blocks, backticks, or XML tags. Do not include any text before or after the JSON object.'''

config.set('extraction.task_prompt', current_prompt + json_fix)
config.save('idp-configs/current-json-fix.yaml')
```

## Verification

1. Deploy updated config: `client.upload_config('idp-configs/current-json-fix.yaml', config_version='<version>', description='Applied JSON output fix')`
2. Re-run evaluation on same test set
3. Confirm previously failing documents now have non-zero accuracy
4. Verify extraction outputs start with `{`
