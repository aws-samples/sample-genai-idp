<!-- Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved. -->
<!-- SPDX-License-Identifier: MIT-0 -->

# Multi-Use-Case Document Handling

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
  - [Document Routing](#document-routing)
  - [Configuration Merge](#configuration-merge)
- [Getting Started](#getting-started)
  - [Creating Use Cases](#creating-use-cases)
  - [Uploading Documents](#uploading-documents)
- [Configuration](#configuration)
  - [Use-Case-Scoped Configuration](#use-case-scoped-configuration)
  - [Configuration Merge Layers](#configuration-merge-layers)
  - [Configuration Overrides](#configuration-overrides)
- [Management Tools](#management-tools)
  - [Web UI](#web-ui)
  - [CLI Script](#cli-script)
  - [CloudFormation](#cloudformation)
- [Roles & Permissions](#roles--permissions)
  - [Admin](#admin)
  - [Supervisor](#supervisor)
  - [Reviewer](#reviewer)
- [Backward Compatibility](#backward-compatibility)
- [Testing](#testing)
  - [Unit Tests](#unit-tests)
  - [Integration Testing with a Deployed Stack](#integration-testing-with-a-deployed-stack)
- [Processing Mode Support](#processing-mode-support)
- [Troubleshooting](#troubleshooting)

## Overview

The multi-use-case feature allows a single GenAIIDP deployment to serve multiple business units and use cases with independent configurations. Each use case can have its own classification model, extraction prompts, confidence thresholds, HITL settings, and more -- while sharing the same infrastructure.

**Key Features:**
- Route documents to specific use cases via S3 key prefixes (`{business_unit}/{use_case}/{filename}`)
- Independent configuration per use case with automatic inheritance from global defaults
- Backward compatible -- existing deployments and flat S3 keys continue to work unchanged
- Use case management via Web UI, CLI script, or CloudFormation

**Supported Processing Modes (Unified Workflow):**
- Pipeline mode (legacy Pattern 2 behavior): use-case-scoped classification, extraction, HITL, confidence thresholds
- BDA mode (legacy Pattern 1 behavior): use-case-scoped ProcessResults, summarization, evaluation, HITL

## Architecture

### Document Routing

Documents are routed to use cases based on their S3 key structure:

```text
s3://input-bucket/{business_unit_id}/{use_case_id}/{filename}
```

When a document is uploaded with this key structure:

1. **Queue Sender** parses the S3 key and extracts `business_unit_id` and `use_case_id`
2. **Queue Processor** builds a `use_case_context` object and passes it to the Step Functions workflow
3. **Each Lambda function** in the workflow receives the `use_case_context` and calls `get_config()` with the business unit and use case IDs
4. **Configuration Manager** returns the merged use-case-scoped configuration

```text
S3 Upload: retail-banking/mortgage/application.pdf
    │
    ▼
Queue Sender → Document.from_s3_event()
    │           business_unit_id = "retail-banking"
    │           use_case_id = "mortgage"
    ▼
Queue Processor → use_case_context = {"business_unit_id": "retail-banking", "use_case_id": "mortgage"}
    │
    ▼
Step Functions Workflow
    │
    ├─ OCR → get_config(bu="retail-banking", uc="mortgage")
    ├─ Classification → get_config(bu="retail-banking", uc="mortgage")
    ├─ Extraction → get_config(bu="retail-banking", uc="mortgage")
    └─ ProcessResults → get_config(bu="retail-banking", uc="mortgage")
```

For flat S3 keys (e.g., `s3://input-bucket/document.pdf`), the `use_case_context` is empty and the global default configuration is used -- identical to pre-feature behavior.

### Configuration Merge

Each use case can override any subset of the global configuration. Unspecified settings are inherited from the Global Default through a layered merge (see [Configuration Merge Layers](#configuration-merge-layers)).

## Getting Started

### Creating Use Cases

Before uploading documents with use-case routing, register the use case. There are three ways to do this:

#### Option 1: Web UI (Admin only)

1. Log in as an Admin user
2. Navigate to **Use Case Management** in the left navigation
3. Click **Create Use Case**
4. Enter the business unit ID, use case ID, display name, and description
5. Click **Create**

#### Option 2: CLI Script

```bash
# Get the Configuration table name from your stack
TABLE=$(python3 scripts/manage_use_cases.py --region us-east-1 \
  table-name --stack <your-stack-name>)

# Register a use case
python3 scripts/manage_use_cases.py --region us-east-1 register \
  --table "$TABLE" \
  --bu retail-banking \
  --uc mortgage-processing \
  --name "Mortgage Processing" \
  --description "Handles mortgage document packages"
```

#### Option 3: Programmatic (Python)

```python
from idp_common.config.configuration_manager import ConfigurationManager

mgr = ConfigurationManager(table_name="<ConfigurationTableName>")
mgr.register_use_case(
    "retail-banking", "mortgage-processing",
    "Mortgage Processing", "Handles mortgage document packages"
)
```

### Uploading Documents

Upload documents with the `{business_unit}/{use_case}/` prefix:

```bash
# Upload to a specific use case
aws s3 cp document.pdf s3://<input-bucket>/retail-banking/mortgage-processing/document.pdf

# Upload without use-case routing (backward compatible)
aws s3 cp document.pdf s3://<input-bucket>/document.pdf
```

In the Web UI, when use cases are registered, the upload panel requires selecting a specific use case before uploading. Documents are automatically uploaded with the correct S3 prefix.

## Configuration

### Use-Case-Scoped Configuration

Each use case can have its own configuration that overrides global defaults. Configuration is stored in DynamoDB with keys following the pattern:

| DynamoDB Key | Description | Layer |
|-------------|-------------|-------|
| `Default` | Global default configuration (from config preset) | 1 |
| `Custom` | Global custom overrides (user changes via UI/CLI) | 2 |
| `UC#<bu>#<uc>#Default` | Use-case default configuration (sparse delta) | 3 |
| `UC#<bu>#<uc>#Custom` | Use-case custom overrides (sparse delta) | 4 |

### Configuration Merge Layers

Configuration is resolved differently depending on whether a use case is specified:

**Global path** (no use case, or flat S3 key):

1. **Global Default** -- Pattern-specific defaults from `config_library/` (includes built-in `IDPConfig` system defaults)
2. **Global Custom** -- User overrides applied via the Web UI or CLI

**Use-case-scoped path** (document uploaded with `{bu}/{uc}/` prefix):

1. **Global Default** -- Same baseline as above
2. **Global Custom** -- User overrides (same as the global path -- inherited as part of the baseline)
3. **UC Default** -- Use-case-specific defaults (set at registration time, sparse delta)
4. **UC Custom** -- Use-case-specific overrides (set via UI or API, sparse delta)

Each layer deep-merges into the previous one, so later layers override earlier ones.

> **📝 Note:** You only need to specify the settings that differ from the global configuration. All unspecified settings are inherited from the merged Global Default + Global Custom baseline. This means that Global Custom overrides (e.g., changes made in the Web UI configuration page) **are** inherited by use-case-scoped configs. To override a specific setting for a single use case without affecting others, use UC Default or UC Custom.

### Configuration Overrides

Register a use case with custom configuration:

```bash
# With inline JSON (only specify overrides)
python3 scripts/manage_use_cases.py --region us-east-1 register \
  --table "$TABLE" \
  --bu retail-banking \
  --uc mortgage-processing \
  --name "Mortgage Processing" \
  --config '{"extraction": {"temperature": 0.3}, "assessment": {"hitl_enabled": true}}'

# With a YAML config file
python3 scripts/manage_use_cases.py --region us-east-1 register \
  --table "$TABLE" \
  --bu retail-banking \
  --uc mortgage-processing \
  --name "Mortgage Processing" \
  --config-file path/to/config.yaml
```

View the merged configuration for a use case:

```bash
python3 scripts/manage_use_cases.py --region us-east-1 get-config \
  --table "$TABLE" \
  --bu retail-banking \
  --uc mortgage-processing
```

## Management Tools

### Web UI

The Web UI provides use case management for Admin users:

- **Use Case Management**: Create, view, and manage use cases
- **Document Upload**: Select a use case before uploading (when use cases are registered)
- **Document Filtering**: Filter the document list by use case
- **Configuration**: View and edit use-case-specific configuration (via `updateUseCaseConfiguration` mutation)

### CLI Script

The `scripts/manage_use_cases.py` script provides command-line management:

```bash
# List all use cases
python3 scripts/manage_use_cases.py --region us-east-1 list --table "$TABLE"

# Register a use case (with optional config)
python3 scripts/manage_use_cases.py --region us-east-1 register \
  --table "$TABLE" --bu <bu-id> --uc <uc-id> --name "Name"

# View merged configuration
python3 scripts/manage_use_cases.py --region us-east-1 get-config \
  --table "$TABLE" --bu <bu-id> --uc <uc-id>

# Delete a use case
python3 scripts/manage_use_cases.py --region us-east-1 delete \
  --table "$TABLE" --bu <bu-id> --uc <uc-id>

# Look up table name from a stack
python3 scripts/manage_use_cases.py --region us-east-1 table-name --stack <stack-name>
```

**Prerequisites:**
- AWS credentials configured
- `idp_common` library installed: `cd lib/idp_common_pkg && pip install -e ".[core]"`

### CloudFormation

Use cases can be provisioned at deploy time via the `UseCaseConfigs` CloudFormation parameter. Pass a JSON array of use case definitions:

```json
[
  {
    "businessUnitId": "retail-banking",
    "useCaseId": "mortgage-processing",
    "name": "Mortgage Processing",
    "description": "Handles mortgage document packages",
    "config": {
      "extraction": {"temperature": 0.3}
    }
  }
]
```

The `config` field can also be an S3 URI pointing to a YAML or JSON configuration file:

```json
{
  "config": "s3://my-bucket/configs/mortgage-config.yaml"
}
```

**Deploying with use cases:**

```bash
# Read and compact the use cases JSON file (single-line JSON is CLI-safe)
USE_CASE_CONFIGS=$(python3 -c "import json; print(json.dumps(json.load(open('config_library/unified/multi-use-case-sample/use_cases.json'))))")

# Deploy the stack with use cases
aws cloudformation create-stack \
  --stack-name my-idp-stack \
  --template-body file://template.yaml \
  --parameters \
    ParameterKey=ConfigurationPreset,ParameterValue=multi-use-case-sample \
    ParameterKey=UseCaseConfigs,ParameterValue="$USE_CASE_CONFIGS" \
    ParameterKey=AdminEmail,ParameterValue=your-email@example.com
```

A sample configuration preset is provided at `config_library/unified/multi-use-case-sample/` with:

- **`config.yaml`** -- Global default with Bank-Statement and Bank-checks document schemas
- **`use_cases.json`** -- Two use cases with real lending-package document schemas:
  - `retail-banking/mortgage-processing`: Payslip, Bank-Statement, W2 (confidence=0.95, HITL=enabled)
  - `insurance/claims-processing`: US-drivers-licenses, Homeowners-Insurance-Application (confidence=0.80, HITL=disabled)

These schemas match the sample PDFs at `samples/lending_package.pdf` (for the mortgage use case) and `samples/insurance_package_single.pdf` (for the insurance use case), enabling end-to-end testing out of the box.

> **📝 Note:** The `multi-use-case-sample` preset provides sample use cases for Pipeline mode (classification + extraction). For BDA mode, use any standard preset (e.g., `lending-package-sample`) and register use cases post-deployment via the CLI or Web UI. Both modes in the unified workflow fully support use-case-scoped configuration at runtime.
>
> **📝 Note:** The `UseCaseConfigs` CloudFormation parameter has a 4096-byte limit. Since the full `use_cases.json` with complete JSON Schema definitions exceeds this limit, use the CLI script (`scripts/manage_use_cases.py`) to register use cases post-deployment, or reference per-use-case configs via S3 URIs in the `config` field.

## Roles & Permissions

Multi-use-case deployments support three user roles with different levels of access. Roles are managed as Cognito User Pool Groups and assigned via the **User Management** page in the Web UI.

### Admin

Full platform-wide access. Admins can manage configurations, users, use cases, upload documents, and perform all HITL actions. Admins automatically have access to **all use cases** (wildcard `*`).

| Capability | Allowed |
|-----------|---------|
| Document List (all statuses) | Yes |
| Document KB | Yes |
| Agent Companion Chat | Yes |
| Upload Documents | Yes |
| View/Edit Configuration | Yes |
| View/Edit Pricing | Yes |
| User Management | Yes |
| Use Case Management | Yes |
| Test Studio | Yes |
| Discovery | Yes |
| Claim/Release/Skip HITL Reviews | Yes |
| Delete/Reprocess/Abort Documents | Yes |
| "All Use Cases" selector | Yes |

### Supervisor

Designed for **LOB leaders** who need visibility into all documents and HITL management within their assigned use cases, without platform administration powers. Supervisors are scoped to specific use cases assigned by an Admin in User Management.

| Capability | Allowed |
|-----------|---------|
| Document List (all statuses) | Yes (scoped to assigned use cases) |
| Document KB | Yes |
| Agent Companion Chat | Yes |
| Upload Documents | No |
| View/Edit Configuration | No |
| View/Edit Pricing | No |
| User Management | No |
| Use Case Management | No |
| Test Studio | No |
| Discovery | No |
| Claim/Release/Skip HITL Reviews | Yes |
| Delete/Reprocess/Abort Documents | Yes |
| "All Use Cases" selector | No |

**Key differences from Reviewer:**
- Sees **all** documents in assigned use cases (completed, failed, in-progress, HITL-pending) -- not just HITL-pending
- Can **skip** HITL section reviews (Reviewers cannot)
- Can **release** any review (Reviewers can only release their own)
- Can **delete, reprocess, and abort** documents (Reviewers cannot)

**Key differences from Admin:**
- Scoped to assigned use cases only (no wildcard access)
- No access to configuration, user management, use case management, upload, test studio, discovery, or pricing

### Reviewer

Limited access focused on HITL document review. Reviewers only see documents with pending HITL reviews in their assigned use cases.

| Capability | Allowed |
|-----------|---------|
| Document List (HITL-pending only) | Yes (scoped to assigned use cases) |
| Document KB | No |
| Agent Companion Chat | No |
| Upload Documents | No |
| View/Edit Configuration | No |
| Claim HITL Reviews | Yes |
| Release HITL Reviews | Yes (own reviews only) |
| Skip HITL Reviews | No |
| Delete/Reprocess/Abort Documents | No |

### Assigning Roles and Use Cases

1. Log in as an **Admin** user
2. Navigate to **User Management** in the left navigation
3. Click **Create User**
4. Select the desired **Role** (Admin, Supervisor, or Reviewer)
5. For Supervisor and Reviewer roles, select the **Allowed Use Cases**
6. Click **Create**

> **Note:** Admin users automatically receive wildcard access to all use cases. Supervisor users **must** have at least one use case explicitly assigned (creation will fail otherwise). Reviewer users may optionally have use cases assigned; a Reviewer with no assigned use cases will not see any HITL-pending documents in a multi-use-case deployment.

## Backward Compatibility

The multi-use-case feature is fully backward compatible:

| Scenario | Behavior |
|----------|----------|
| No use cases registered | `isMultiUseCaseEnabled = false`; UI and processing work exactly as before |
| Flat S3 key (`document.pdf`) | `business_unit_id` and `use_case_id` are `None`; global config used |
| Single-prefix key (`prefix/document.pdf`) | Treated as flat key (needs 3+ segments for routing) |
| Existing deployments | No use cases in registry; all behavior unchanged |
| CLI/API uploads without prefix | Global config used; no use-case routing |

**How it works:** The UI checks `useCases.length > 0` to determine `isMultiUseCaseEnabled`. When no use cases are registered (the default), the feature is invisible and all behavior is identical to pre-feature deployments.

## Testing

### Unit Tests

The multi-use-case feature has comprehensive unit tests that run locally without AWS resources:

```bash
# Install dependencies
cd lib/idp_common_pkg
pip install -e ".[all]"

# Run use-case config tests
python -m pytest tests/unit/config/test_use_case_config.py -v

# Run processresults use-case routing tests
python -m pytest tests/unit/config/test_processresults_use_case.py -v

# Run end-to-end multi-use-case tests
python -m pytest tests/unit/config/test_multi_use_case_e2e.py -v

# Run all unit tests (includes use-case tests)
python -m pytest -m "unit" tests/ -v
```

**What the tests cover:**
- Document model `business_unit_id` / `use_case_id` fields (to_dict, from_dict, from_s3_event)
- S3 key parsing for use-case routing (flat keys, 3-part keys, URL-encoded keys)
- ConfigurationManager use-case CRUD (save, get, list, register)
- Configuration merge layers (Global Default -> Global Custom -> UC Default -> UC Custom)
- Backward compatibility (no use-case params = existing behavior)
- Pattern-1 and Pattern-2 handler use_case_context extraction and validation
- Pattern-2 fallback to document-level BU/UC when use_case_context is empty
- End-to-end config routing (use_case_context -> get_config -> correct merged config)
- Per-use-case HITL and confidence threshold overrides

### Integration Testing with a Deployed Stack

To test the full end-to-end flow with a deployed stack:

#### 1. Deploy the Stack

```bash
# Build
python3 publish.py <bucket-basename> idp <region>

# Deploy with multi-use-case-sample config preset
aws cloudformation create-stack \
  --stack-name idp-uc-test \
  --template-url "https://s3.<region>.amazonaws.com/<bucket>-<region>/idp/idp-main.yaml" \
  --parameters \
    ParameterKey=AdminEmail,ParameterValue=your@email.com \
    ParameterKey=ConfigurationPreset,ParameterValue=multi-use-case-sample \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
  --region <region>
```

#### 2. Register Use Cases

Since the full `use_cases.json` exceeds the CloudFormation parameter size limit, register use cases post-deployment using the CLI:

```bash
# Get the config table name
TABLE=$(python3 scripts/manage_use_cases.py --region <region> \
  table-name --stack idp-uc-test)

# Extract per-use-case configs from use_cases.json and register each
python3 -c "
import json
with open('config_library/unified/multi-use-case-sample/use_cases.json') as f:
    data = json.load(f)
for i, uc in enumerate(data):
    with open(f'/tmp/uc_config_{i}.json', 'w') as f:
        json.dump(uc['config'], f)
    print(f'{uc[\"businessUnitId\"]} {uc[\"useCaseId\"]} {uc.get(\"name\",\"\")} /tmp/uc_config_{i}.json')
"

# Register mortgage-processing use case
python3 scripts/manage_use_cases.py --region <region> register \
  --table "$TABLE" \
  --bu retail-banking --uc mortgage-processing \
  --name "Mortgage Document Processing" \
  --config-file /tmp/uc_config_0.json

# Register claims-processing use case
python3 scripts/manage_use_cases.py --region <region> register \
  --table "$TABLE" \
  --bu insurance --uc claims-processing \
  --name "Insurance Claims Processing" \
  --config-file /tmp/uc_config_1.json

# Verify registration
python3 scripts/manage_use_cases.py --region <region> list --table "$TABLE"
```

#### 3. Upload Test Documents

```bash
INPUT_BUCKET=$(aws cloudformation describe-stacks --stack-name idp-uc-test \
  --query "Stacks[0].Outputs[?OutputKey=='S3InputBucketName'].OutputValue" \
  --output text --region <region>)

# Upload with use-case routing (mortgage use case)
aws s3 cp samples/lending_package.pdf \
  "s3://$INPUT_BUCKET/retail-banking/mortgage-processing/lending_package.pdf"

# Upload with use-case routing (insurance use case)
aws s3 cp samples/insurance_package_single.pdf \
  "s3://$INPUT_BUCKET/insurance/claims-processing/insurance_single.pdf"

# Upload without routing (backward compat test -- uses global default config)
aws s3 cp samples/lending_package.pdf \
  "s3://$INPUT_BUCKET/lending_package_flat.pdf"
```

#### 4. Verify Results

Wait for all Step Functions executions to reach `SUCCEEDED` status:

```bash
# Get state machine ARN
STATE_MACHINE_ARN=$(aws cloudformation describe-stacks --stack-name idp-uc-test \
  --query "Stacks[0].Outputs[?OutputKey=='StateMachineArn'].OutputValue" \
  --output text --region <region>)

# Check execution statuses (wait until all show SUCCEEDED)
aws stepfunctions list-executions \
  --state-machine-arn "$STATE_MACHINE_ARN" --max-items 5 \
  --region <region> --query "executions[*].{name:name,status:status}" --output table
```

**Verify use_case_context routing** -- each execution should have the correct context:

```bash
# For each recent execution, check the use_case_context in the input
for EXEC_ARN in $(aws stepfunctions list-executions \
  --state-machine-arn "$STATE_MACHINE_ARN" --max-items 3 \
  --region <region> --query "executions[*].executionArn" --output text); do
  echo "=== $(basename $EXEC_ARN) ==="
  aws stepfunctions describe-execution --execution-arn "$EXEC_ARN" \
    --region <region> --query "input" --output text | \
    python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(f'use_case_context: {json.dumps(d.get(\"use_case_context\",{}))}')"
done
```

Expected output:
- Mortgage doc: `use_case_context: {"business_unit_id": "retail-banking", "use_case_id": "mortgage-processing"}`
- Insurance doc: `use_case_context: {"business_unit_id": "insurance", "use_case_id": "claims-processing"}`
- Flat doc: `use_case_context: {}`

**Verify output routing in S3:**

```bash
OUTPUT_BUCKET=$(aws cloudformation describe-stacks --stack-name idp-uc-test \
  --query "Stacks[0].Outputs[?OutputKey=='S3OutputBucketName'].OutputValue" \
  --output text --region <region>)

# Use-case document output should be under retail-banking/mortgage-processing/
aws s3 ls "s3://$OUTPUT_BUCKET/retail-banking/mortgage-processing/" --recursive | head -5

# Insurance output should be under insurance/claims-processing/
aws s3 ls "s3://$OUTPUT_BUCKET/insurance/claims-processing/" --recursive | head -5

# Flat document output should be at root
aws s3 ls "s3://$OUTPUT_BUCKET/lending_package_flat.pdf/" --recursive | head -5
```

**Verify use-case-scoped classification** -- each use case should classify documents using its own doc types:

```bash
# Mortgage sections should classify as Payslip, Bank-Statement, W2
for i in 1 2 3; do
  aws s3 cp "s3://$OUTPUT_BUCKET/retail-banking/mortgage-processing/lending_package.pdf/sections/$i/result.json" - \
    --region <region> 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Mortgage Section $i: {d[\"document_class\"][\"type\"]}')"
done

# Flat key sections should classify as Bank-Statement, Bank-checks (global config)
for i in 1 2 3; do
  aws s3 cp "s3://$OUTPUT_BUCKET/lending_package_flat.pdf/sections/$i/result.json" - \
    --region <region> 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Flat Section $i: {d[\"document_class\"][\"type\"]}')"
done
```

**What to verify:**
- Use-case document has the correct `use_case_context` in the Step Functions execution input
- Flat document has `use_case_context: {}` in the execution input
- The `use_case_context` is propagated through all workflow steps (OCR, Classification, Extraction, ProcessResults)
- Classification uses the use-case-scoped document types (e.g., Payslip, Bank-Statement, W2 for mortgage; Bank-Statement, Bank-checks for global default)
- Output files land under the correct S3 prefix matching the input routing
- All documents complete the full workflow successfully

#### 5. Verify in Web UI

1. Open the **ApplicationWebURL** from the stack outputs
2. Log in with the Admin email configured during deployment
3. Navigate to **Use Case Management** -- verify both use cases appear
4. Navigate to **Documents** -- use the use-case selector dropdown to filter by use case
5. Select `retail-banking / mortgage-processing` and verify the mortgage document appears
6. Select `insurance / claims-processing` and verify the insurance document appears
7. Select `All Use Cases` and verify all documents appear (Admin only)
8. Click on a completed document to view extraction results -- verify correct document types were extracted

## Processing Mode Support

| Feature | BDA Mode (legacy Pattern 1) | Pipeline Mode (legacy Pattern 2) |
|---------|------------------------------|----------------------------------|
| S3 key routing | Supported | Supported |
| `use_case_context` propagation | Supported | Supported |
| Use-case-scoped classification | N/A (BDA handles internally) | Supported |
| Use-case-scoped extraction | N/A (BDA handles internally) | Supported |
| Use-case-scoped config in ProcessResults | Supported | Supported |
| Use-case-scoped config in Summarization | Supported | Supported |
| Use-case-scoped config in Evaluation | Supported | Supported |
| HITL per use case | Supported | Supported |
| `multi-use-case-sample` config preset | Not available | Available |

> **📝 Note:** Both modes in the unified workflow propagate `use_case_context` through the full workflow. The Queue Processor adds `use_case_context` to the Step Functions input, the state machine forwards it to every step, and each Lambda handler uses it to load use-case-scoped configuration via `get_config()`. When `use_case_context` is empty (flat S3 key uploads), all handlers fall back to the global default configuration.

## Troubleshooting

**Documents not routing to use case:**
- Verify the S3 key has at least 3 segments: `{bu}/{uc}/{filename}`
- Keys with only 1 or 2 segments are treated as flat keys (no use-case routing)
- Business unit and use case IDs cannot contain `#` or `/` characters
- IDs matching `DEFAULT` or starting with `DEFAULT_` are rejected **case-insensitively** (e.g., `DEFAULT`, `default`, `DeFaUlT`, `DEFAULT_FOO` are all blocked), including variants with leading underscores (e.g., `_DEFAULT`, `__default_`). The internal system identifier `_default` is a separate convention used for global/default configuration keys and is likewise not available as a user-facing ID.

**Use case not appearing in UI:**
- Use cases are data-driven: `isMultiUseCaseEnabled` is `true` only when `useCases.length > 0`
- Verify the use case is registered: `python3 scripts/manage_use_cases.py list --table <table>`
- Check browser console for GraphQL errors

**Configuration not applying to use case:**
- Registering a use case only creates metadata; configuration must be added separately
- Use `get-config` to verify the merged configuration
- If no UC-specific config exists, the global default is used (which is correct behavior)

**"Upload requires selecting a use case" error:**
- When use cases are registered, the UI requires selecting one before uploading
- Select a specific use case (not "All Use Cases") in the upload panel
- To upload without use-case routing, delete all use cases or use the AWS CLI directly
