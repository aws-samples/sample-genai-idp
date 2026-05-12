# Broken Config: Passes validation but extraction fails

## Config
`v1-passes-validation-but-extraction-fails.yaml`

## Failure
- **Error:** `ValidationException: The maximum tokens you requested exceeds the model limit of 10000. Try again with a maximum tokens value that is lower than 10000.`
- **Stage:** Extraction Lambda
- **Model:** `us.amazon.nova-lite-v1:0`
- **Config value:** `extraction.max_tokens: 16000`
- **Model limit:** 10000

## Root Cause
`idp-cli config-validate` does not check that `max_tokens` values are within the specified model's output token limits. The config passes all validation checks but fails at runtime when Bedrock rejects the Converse call.

## Reproduction
```bash
idp-cli config-validate --config-file v1-passes-validation-but-extraction-fails.yaml
# Output: "Config is valid!"

# Then upload and run evaluation — extraction fails with ValidationException
```

## Requested Fix
`config-validate` should cross-reference `max_tokens` against known model limits (from `config_library/pricing.yaml` or Bedrock API) for:
- `extraction.max_tokens`
- `classification.max_tokens`
- `assessment.max_tokens`
- `summarization.max_tokens`

## Session
- AutoTune session: `57b0afb0-5932-488a-aa71-361e442d9df5`
- Batch: `davids-test-dataset-20260512-143618`
- Document: `0899a914-dc55-4929-a970-2bd3cda61cf5.png`
- Step Functions execution: `b4f94e6e-bcba-4fa1-9f03-859f4979620c`
