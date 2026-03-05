# Multi-Use-Case Sample Configuration

This sample demonstrates multi-use-case document handling with Pattern-2 (Textract + Bedrock).
It uses real document schemas from the lending-package-sample so that the existing
`samples/lending_package.pdf` can be processed end-to-end.

## Files

| File | Description |
|------|-------------|
| `config.yaml` | Global default configuration (Bank-Statement and Bank-checks) |
| `use_cases.json` | Two use case definitions with per-use-case document schemas and overrides |

## Use Cases

### retail-banking / mortgage-processing

- **Documents**: Payslip, Bank-Statement, W2 (financial verification docs for mortgage applications)
- **Confidence threshold**: 0.95 (high accuracy for financial docs)
- **HITL**: Enabled (human review for low-confidence extractions)
- **Extraction**: temperature=0.0, top_p=0.0 (deterministic for financial data)

### insurance / claims-processing

- **Documents**: US-drivers-licenses, Homeowners-Insurance-Application (identity + insurance docs)
- **Confidence threshold**: 0.80 (optimized for throughput)
- **HITL**: Disabled (automated processing)
- **Extraction**: temperature=0.1, top_p=0.1 (slightly relaxed for varied document formats)

## Document Type Distribution

All 6 document types from the lending package are covered:

| Document Type | Global Default | Mortgage Processing | Claims Processing |
|--------------|----------------|--------------------|--------------------|
| Bank-Statement | Yes | Yes | - |
| Bank-checks | Yes | - | - |
| Payslip | - | Yes | - |
| W2 | - | Yes | - |
| US-drivers-licenses | - | - | Yes |
| Homeowners-Insurance-Application | - | - | Yes |

## Deployment

### Option 1: CloudFormation Parameter

Pass `use_cases.json` as the `UseCaseConfigs` parameter during stack deployment:

```bash
# Read and compact the JSON file content (single-line JSON avoids shell parameter issues)
USE_CASE_CONFIGS=$(python3 -c "import json; print(json.dumps(json.load(open('config_library/unified/multi-use-case-sample/use_cases.json'))))")

# Deploy with use cases
aws cloudformation create-stack \
  --stack-name my-idp-stack \
  --template-body file://template.yaml \
  --parameters \
    ParameterKey=IDPPattern,ParameterValue="Pattern2 - Packet processing with Textract and Bedrock" \
    ParameterKey=Pattern2Configuration,ParameterValue=multi-use-case-sample \
    ParameterKey=UseCaseConfigs,ParameterValue="$USE_CASE_CONFIGS" \
    ...
```

### Option 2: CLI Script (Post-Deployment)

```bash
#!/bin/bash
set -euo pipefail  # Exit on error, undefined vars, and pipeline failures

# Get the config table name
TABLE=$(python3 scripts/manage_use_cases.py table-name --stack my-idp-stack)

# Verify JSON file exists
JSON_FILE="config_library/unified/multi-use-case-sample/use_cases.json"
if [[ ! -f "$JSON_FILE" ]]; then
  echo "Error: $JSON_FILE not found" >&2
  exit 1
fi

# Register use cases from the JSON file
python3 -c "
import json
with open('$JSON_FILE') as f:
    data = json.load(f)
for e in data:
    print(f\"{e['businessUnitId']} {e['useCaseId']}\")
" | while read -r bu uc; do
  echo "Registering: $bu / $uc"
  python3 scripts/manage_use_cases.py register \
    --table "$TABLE" \
    --bu "$bu" \
    --uc "$uc" || { echo "Failed to register $bu/$uc" >&2; exit 1; }
done
```

### Option 3: Web UI

Navigate to the Use Case Management page in the web UI to create and configure use cases interactively.

## Document Upload Structure

Upload documents using the S3 key prefix convention:

```text
s3://input-bucket/retail-banking/mortgage-processing/lending_package.pdf
s3://input-bucket/insurance/claims-processing/lending_package.pdf
s3://input-bucket/lending_package.pdf  # Uses global default config
```
