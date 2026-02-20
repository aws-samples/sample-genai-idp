# IDP CLI - Command Line Interface for Batch Document Processing

A command-line tool for batch document processing with the GenAI IDP Accelerator.

## Features

✨ **Batch Processing** - Process multiple documents from CSV/JSON manifests  
📊 **Live Progress Monitoring** - Real-time updates with rich terminal UI  
🔄 **Resume Monitoring** - Stop and resume monitoring without affecting processing  
📁 **Flexible Input** - Support for local files and S3 references  
🔍 **Comprehensive Status** - Track queued, running, completed, and failed documents  
📈 **Batch Analytics** - Success rates, durations, and detailed error reporting  
🎯 **Evaluation Framework** - Validate accuracy against baselines with detailed metrics

Demo:

https://github.com/user-attachments/assets/3d448a74-ba5b-4a4a-96ad-ec03ac0b4d7d



## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Commands Reference](#commands-reference)
  - [deploy](#deploy)
  - [delete](#delete)
  - [process](#process)
  - [reprocess](#reprocess)
  - [status](#status)
  - [download-results](#download-results)
  - [delete-documents](#delete-documents)
  - [generate-manifest](#generate-manifest)
  - [validate-manifest](#validate-manifest)
  - [list-batches](#list-batches)
  - [stop-workflows](#stop-workflows)
  - [load-test](#load-test)
  - [remove-deleted-stack-resources](#remove-deleted-stack-resources)
  - [config-create](#config-create)
  - [config-validate](#config-validate)
  - [config-download](#config-download)
  - [config-upload](#config-upload)
  - [config-list](#config-list)
  - [config-activate](#config-activate)
  - [config-delete](#config-delete)
- [Complete Evaluation Workflow](#complete-evaluation-workflow)
  - [Step 1: Deploy Your Stack](#step-1-deploy-your-stack)
  - [Step 2: Initial Processing from Local Directory](#step-2-initial-processing-from-local-directory)
  - [Step 3: Download Extraction Results](#step-3-download-extraction-results)
  - [Step 4: Manual Validation & Baseline Preparation](#step-4-manual-validation--baseline-preparation)
  - [Step 5: Create Manifest with Baseline References](#step-5-create-manifest-with-baseline-references)
  - [Step 6: Process with Evaluation Enabled](#step-6-process-with-evaluation-enabled)
  - [Step 7: Download and Review Evaluation Results](#step-7-download-and-review-evaluation-results)
- [Evaluation Analytics](#evaluation-analytics)
  - [Query Aggregated Results with Athena](#query-aggregated-results-with-athena)
  - [Use Agent Analytics in the Web UI](#use-agent-analytics-in-the-web-ui)
- [Manifest Format Reference](#manifest-format-reference)
- [Advanced Usage](#advanced-usage)
- [Troubleshooting](#troubleshooting)

## Installation

### Prerequisites

- Python 3.10 or higher
- AWS credentials configured (via AWS CLI or environment variables)
- An active IDP Accelerator CloudFormation stack

### Install from source

```bash
cd lib/idp_cli_pkg
pip install -e .
```

### Install with test dependencies

```bash
cd lib/idp_cli_pkg
pip install -e ".[test]"
```

## Quick Start

### Deploy a stack and process documents in 3 commands:

```bash
# 1. Deploy stack (10-15 minutes)
idp-cli deploy \
    --stack-name my-idp-stack \
    --pattern pattern-2 \
    --admin-email your.email@example.com \
    --wait

# 2. Process documents from a local directory
idp-cli process \
    --stack-name my-idp-stack \
    --dir ./my-documents/ \
    --monitor

# 3. Download results
idp-cli download-results \
    --stack-name my-idp-stack \
    --batch-id <batch-id-from-step-2> \
    --output-dir ./results/
```

**That's it!** Your documents are processed with OCR, classification, extraction, assessment, and summarization.

For evaluation workflows with accuracy metrics, see the [Complete Evaluation Workflow](#complete-evaluation-workflow) section.

---

## Commands Reference

### `deploy`

Deploy or update an IDP CloudFormation stack.

**Usage:**
```bash
idp-cli deploy [OPTIONS]
```

**Required for New Stacks:**
- `--stack-name`: CloudFormation stack name
- `--pattern`: IDP pattern architecture to deploy (`pattern-1`, `pattern-2`, or `pattern-3`)
- `--admin-email`: Admin user email

**Optional Parameters:**
- `--from-code`: Deploy from local code by building with publish.py (path to project root)
- `--template-url`: URL to CloudFormation template in S3 (optional, auto-selected based on region)
- `--custom-config`: Path to local config file or S3 URI
- `--max-concurrent`: Maximum concurrent workflows (default: 100)
- `--log-level`: Logging level (`DEBUG`, `INFO`, `WARN`, `ERROR`) (default: INFO)
- `--enable-hitl`: Enable Human-in-the-Loop (`true` or `false`)
- `--pattern-config`: Pattern-specific configuration preset (optional, distinct from --pattern)
- `--parameters`: Additional parameters as `key=value,key2=value2`
- `--wait`: Wait for stack operation to complete
- `--no-rollback`: Disable rollback on stack creation failure
- `--region`: AWS region (optional, auto-detected)
- `--role-arn`: CloudFormation service role ARN (optional)

**Note:** `--from-code` and `--template-url` are mutually exclusive. Use `--from-code` for development/testing from local source, or `--template-url` for production deployments.

**Auto-Monitoring for In-Progress Operations:**

If you run `deploy` on a stack that already has an operation in progress (CREATE, UPDATE, ROLLBACK), the command automatically switches to monitoring mode instead of failing. This is useful if you forgot to use `--wait` on the initial deploy - simply run the same command again to monitor progress:

```bash
# First run without --wait starts the deployment
$ idp-cli deploy --stack-name my-stack --pattern pattern-2 --admin-email user@example.com
✓ Stack CREATE initiated successfully!

# Second run - automatically monitors the in-progress operation
$ idp-cli deploy --stack-name my-stack
Stack 'my-stack' has an operation in progress
Current status: CREATE_IN_PROGRESS

Switching to monitoring mode...

[Live progress display...]

✓ Stack CREATE completed successfully!
```

Supported in-progress states: `CREATE_IN_PROGRESS`, `UPDATE_IN_PROGRESS`, `DELETE_IN_PROGRESS`, `ROLLBACK_IN_PROGRESS`, `UPDATE_ROLLBACK_IN_PROGRESS`, and cleanup states.

**Examples:**

```bash
# Create new stack
idp-cli deploy \
    --stack-name my-idp \
    --pattern pattern-2 \
    --admin-email user@example.com \
    --wait

# Update with custom config
idp-cli deploy \
    --stack-name my-idp \
    --custom-config ./updated-config.yaml \
    --wait

# Update parameters
idp-cli deploy \
    --stack-name my-idp \
    --max-concurrent 200 \
    --log-level DEBUG \
    --wait

# Deploy with custom template URL (for regions not auto-supported)
idp-cli deploy \
    --stack-name my-idp \
    --pattern pattern-2 \
    --admin-email user@example.com \
    --template-url https://s3.eu-west-1.amazonaws.com/my-bucket/idp-main.yaml \
    --region eu-west-1 \
    --wait

# Deploy with CloudFormation service role and permissions boundary
idp-cli deploy \
    --stack-name my-idp \
    --pattern pattern-2 \
    --admin-email user@example.com \
    --role-arn arn:aws:iam::123456789012:role/IDP-Cloudformation-Service-Role \
    --parameters "PermissionsBoundaryArn=arn:aws:iam::123456789012:policy/MyPermissionsBoundary" \
    --wait

# Deploy from local source code (for development/testing)
idp-cli deploy \
    --stack-name my-idp-dev \
    --from-code . \
    --pattern pattern-2 \
    --admin-email user@example.com \
    --wait

# Update existing stack from local code changes
idp-cli deploy \
    --stack-name my-idp-dev \
    --from-code . \
    --wait

# Deploy with rollback disabled (useful for debugging failed deployments)
idp-cli deploy \
    --stack-name my-idp \
    --pattern pattern-2 \
    --admin-email user@example.com \
    --no-rollback \
    --wait
```

---

### `delete`

Delete an IDP CloudFormation stack.

**⚠️ WARNING:** This permanently deletes all stack resources.

**Usage:**
```bash
idp-cli delete [OPTIONS]
```

**Options:**
- `--stack-name` (required): CloudFormation stack name
- `--force`: Skip confirmation prompt
- `--empty-buckets`: Empty S3 buckets before deletion (required if buckets contain data)
- `--force-delete-all`: Force delete ALL remaining resources after CloudFormation deletion (S3 buckets, CloudWatch logs, DynamoDB tables)
- `--wait / --no-wait`: Wait for deletion to complete (default: wait)
- `--region`: AWS region (optional)

**S3 Bucket Behavior:**
- **LoggingBucket**: `DeletionPolicy: Retain` - Always kept (unless using `--force-delete-all`)
- **All other buckets**: `DeletionPolicy: RetainExceptOnCreate` - Deleted if empty
- CloudFormation can ONLY delete S3 buckets if they're empty
- Use `--empty-buckets` to automatically empty buckets before deletion
- Use `--force-delete-all` to delete ALL remaining resources after CloudFormation completes

**Force Delete All Behavior:**

The `--force-delete-all` flag performs a comprehensive cleanup AFTER CloudFormation deletion completes:

1. **CloudFormation Deletion Phase**: Standard stack deletion
2. **Additional Resource Cleanup Phase** (happens with `--wait` on all deletions and always with `--force-delete-all`): Removes stack-specific resources not tracked by CloudFormation:
   - CloudWatch Log Groups (Lambda functions, Glue crawlers)
   - AppSync APIs and their log groups
   - CloudFront distributions (two-phase cleanup - initiates disable, takes 15-20 minutes to propagate globally)
   - CloudFront Response Headers Policies (from previously deleted stacks)
   - IAM custom policies and permissions boundaries
   - CloudWatch Logs resource policies
3. **Retained Resource Cleanup Phase** (only with `--force-delete-all`): Deletes remaining resources in order:
   - DynamoDB tables (disables PITR, then deletes)
   - CloudWatch Log Groups (matching stack name pattern)
   - S3 buckets (regular buckets first, LoggingBucket last)

**Resources Always Cleaned Up (with `--wait` or `--force-delete-all`):**
- IAM custom policies (containing stack name)
- IAM permissions boundary policies
- CloudFront response header policies (custom)
- CloudWatch Logs resource policies (stack-specific)
- AppSync log groups
- Additional log groups containing stack name
- Gracefully handles missing/already-deleted resources

**Resources Deleted Only by --force-delete-all:**
- All DynamoDB tables from stack
- All CloudWatch Log Groups (retained by CloudFormation)
- All S3 buckets including LoggingBucket
- Handles nested stack resources automatically

**Examples:**

```bash
# Interactive deletion with confirmation
idp-cli delete --stack-name test-stack

# Automated deletion (CI/CD)
idp-cli delete --stack-name test-stack --force

# Delete with automatic bucket emptying
idp-cli delete --stack-name test-stack --empty-buckets --force

# Force delete ALL remaining resources (comprehensive cleanup)
idp-cli delete --stack-name test-stack --force-delete-all --force

# Delete without waiting
idp-cli delete --stack-name test-stack --force --no-wait
```

**What you'll see (standard deletion):**
```
⚠️  WARNING: Stack Deletion
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Stack: test-stack
Region: us-east-1

S3 Buckets:
  • InputBucket: 20 objects (45.3 MB)
  • OutputBucket: 20 objects (123.7 MB)
  • WorkingBucket: empty

⚠️  Buckets contain data!
This action cannot be undone.

Are you sure you want to delete this stack? [y/N]: _
```

**What you'll see (force-delete-all):**
```
⚠️  WARNING: FORCE DELETE ALL RESOURCES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Stack: test-stack
Region: us-east-1

S3 Buckets:
  • InputBucket: 20 objects (45.3 MB)
  • OutputBucket: 20 objects (123.7 MB)
  • LoggingBucket: 5000 objects (2.3 GB)

⚠️  FORCE DELETE ALL will remove:
  • All S3 buckets (including LoggingBucket)
  • All CloudWatch Log Groups
  • All DynamoDB Tables
  • Any other retained resources

This happens AFTER CloudFormation deletion completes

This action cannot be undone.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Are you ABSOLUTELY sure you want to force delete ALL resources? [y/N]: y

Deleting CloudFormation stack...
✓ Stack deleted successfully!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Starting force cleanup of retained resources...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Analyzing retained resources...
Found 4 retained resources:
  • DynamoDB Tables: 0
  • CloudWatch Logs: 0
  • S3 Buckets: 3

⠋ Deleting S3 buckets... 3/3

✓ Cleanup phase complete!

Resources deleted:
  • S3 Buckets: 3
    - test-stack-inputbucket-abc123
    - test-stack-outputbucket-def456
    - test-stack-loggingbucket-ghi789

Stack 'test-stack' and all resources completely removed.
```

**Use Cases:**
- Cleanup test/development environments to avoid charges
- CI/CD pipelines that provision and teardown stacks
- Automated testing with temporary stack creation
- Complete removal of failed stacks with retained resources
- Cleanup of stacks with LoggingBucket and CloudWatch logs

**Important Notes:**
- `--force-delete-all` automatically includes `--empty-buckets` behavior
- Cleanup phase runs even if CloudFormation deletion fails
- Includes resources from nested stacks automatically
- Safe to run - only deletes resources that weren't deleted by CloudFormation
- Progress bars show real-time deletion status

**Auto-Monitoring for In-Progress Deletions:**

If you run `delete` on a stack that already has a DELETE operation in progress, the command automatically switches to monitoring mode instead of failing. This is useful if you started a deletion without `--wait` - simply run the command again to monitor:

```bash
# First run without --wait starts the deletion
$ idp-cli delete --stack-name test-stack --force --no-wait
✓ Stack DELETE initiated successfully!

# Second run - automatically monitors the in-progress deletion
$ idp-cli delete --stack-name test-stack
Stack 'test-stack' is already being deleted
Current status: DELETE_IN_PROGRESS

Switching to monitoring mode...

[Live progress display...]

✓ Stack deleted successfully!
```

**Canceling In-Progress Operations:**

If a non-delete operation is in progress (CREATE, UPDATE), the delete command offers options to handle it:

```bash
$ idp-cli delete --stack-name test-stack
Stack 'test-stack' has an operation in progress: CREATE_IN_PROGRESS

Options:
  1. Wait for CREATE to complete first
  2. Cancel the CREATE and proceed with deletion

Do you want to cancel the CREATE and delete the stack? [yes/no/wait]: _
```

- **yes**: Cancel the operation (if possible) and proceed with deletion
- **no**: Exit without making changes
- **wait**: Wait for the current operation to complete, then delete

With `--force` flag, the command automatically cancels the operation and proceeds with deletion:

```bash
# Force mode - automatically cancels and deletes
$ idp-cli delete --stack-name test-stack --force
Force mode: Canceling operation and proceeding with deletion...

✓ Stack reached stable state: ROLLBACK_COMPLETE

Proceeding with stack deletion...
```

**Note:** CREATE operations cannot be cancelled directly - they must complete or roll back naturally. UPDATE operations can be cancelled immediately.

---

### `process` / `run-inference`

Process a batch of documents.

**Usage:**
```bash
idp-cli process [OPTIONS]
# or (deprecated alias)
idp-cli run-inference [OPTIONS]
```

**Document Source (choose ONE):**
- `--manifest`: Path to manifest file (CSV or JSON)
- `--dir`: Local directory containing documents
- `--s3-uri`: S3 URI in InputBucket
- `--test-set`: Test set ID from test set bucket

**Options:**
- `--stack-name` (required): CloudFormation stack name
- `--batch-id`: Custom batch ID (auto-generated if omitted, ignored with --test-set)
- `--batch-prefix`: Prefix for auto-generated batch ID (default: `cli-batch`)
- `--file-pattern`: File pattern for directory/S3 scanning (default: `*.pdf`)
- `--recursive/--no-recursive`: Include subdirectories (default: recursive)
- `--number-of-files`: Limit number of files to process
- `--config`: Path to configuration YAML file (optional)
- `--config-version`: Configuration version to use for processing (e.g., v1, v2)
- `--context`: Context description for test run (used with --test-set, e.g., "Model v2.1", "Production validation")
- `--monitor`: Monitor progress until completion
- `--refresh-interval`: Seconds between status checks (default: 5)
- `--region`: AWS region (optional)

**Test Set Integration:**
For test runs to appear properly in the Test Studio UI, use either:
- `--test-set`: Process test set directly by ID (recommended for test sets)
- `--manifest`: Use manifest file with populated baseline_source column for evaluation tracking

Other options (`--dir`, `--s3-uri`) are for general document processing but won't integrate with test studio tracking.

**Examples:**

```bash
# Process from local directory
idp-cli process \
    --stack-name my-stack \
    --dir ./documents/ \
    --monitor

# Process from manifest with baselines (enables evaluation)
idp-cli process \
    --stack-name my-stack \
    --manifest documents-with-baselines.csv \
    --monitor

# Process from manifest with limited files
idp-cli process \
    --stack-name my-stack \
    --manifest documents-with-baselines.csv \
    --number-of-files 10 \
    --monitor

# Process test set (integrates with Test Studio UI - use test set ID)
idp-cli process \
    --stack-name my-stack \
    --test-set fcc-example-test \
    --monitor

# Process test set with limited files for quick testing
idp-cli process \
    --stack-name my-stack \
    --test-set fcc-example-test \
    --number-of-files 5 \
    --monitor

# Process test set with custom context (for tracking in Test Studio)
idp-cli process \
    --stack-name my-stack \
    --test-set fcc-example-test \
    --context "Model v2.1 - improved prompts" \
    --monitor

# Process S3 URI
idp-cli process \
    --stack-name my-stack \
    --s3-uri archive/2024/ \
    --monitor

# Process with specific configuration version
idp-cli process \
    --stack-name my-stack \
    --dir ./documents/ \
    --config-version v2 \
    --monitor

# Process test set with configuration version
idp-cli process \
    --stack-name my-stack \
    --test-set fcc-example-test \
    --config-version v1 \
    --context "Testing with config v1" \
    --monitor
```

---

### `reprocess` / `rerun-inference`

Reprocess existing documents from a specific pipeline step.

**Usage:**
```bash
idp-cli reprocess [OPTIONS]
# or (deprecated alias)
idp-cli rerun-inference [OPTIONS]
```

**Use Cases:**
- Test different classification or extraction configurations without re-running OCR
- Fix classification errors and reprocess extraction
- Iterate on prompt engineering rapidly

**Options:**
- `--stack-name` (required): CloudFormation stack name
- `--step` (required): Pipeline step to rerun from (`classification` or `extraction`)
- **Document Source** (choose ONE):
  - `--document-ids`: Comma-separated document IDs
  - `--batch-id`: Batch ID to get all documents from
- `--force`: Skip confirmation prompt (useful for automation)
- `--monitor`: Monitor progress until completion
- `--refresh-interval`: Seconds between status checks (default: 5)
- `--region`: AWS region (optional)

**Step Behavior:**
- `classification`: Clears page classifications and sections, reruns classification → extraction → assessment
- `extraction`: Keeps classifications, clears extraction data, reruns extraction → assessment

**Examples:**

```bash
# Rerun classification for specific documents
idp-cli reprocess \
    --stack-name my-stack \
    --step classification \
    --document-ids "batch-123/doc1.pdf,batch-123/doc2.pdf" \
    --monitor

# Rerun extraction for entire batch
idp-cli reprocess \
    --stack-name my-stack \
    --step extraction \
    --batch-id cli-batch-20251015-143000 \
    --monitor

# Automated rerun (skip confirmation - perfect for CI/CD)
idp-cli reprocess \
    --stack-name my-stack \
    --step classification \
    --batch-id test-set \
    --force \
    --monitor
```

**What Gets Cleared:**

| Step | Clears | Keeps |
|------|--------|-------|
| `classification` | Page classifications, sections, extraction results | OCR data (pages, images, text) |
| `extraction` | Section extraction results, attributes | OCR data, page classifications, section structure |

**Benefits:**
- Leverages existing OCR data (saves time and cost)
- Rapid iteration on classification/extraction configurations
- Perfect for prompt engineering experiments

**Demo:**

https://github.com/user-attachments/assets/28deadbb-378b-42b7-a5e2-f929af9b0e41


---

### `status`

Check status of a batch or single document.

**Usage:**
```bash
idp-cli status [OPTIONS]
```

**Document Source (choose ONE):**
- `--batch-id`: Batch identifier (check all documents in batch)
- `--document-id`: Single document ID (check individual document)

**Options:**
- `--stack-name` (required): CloudFormation stack name
- `--wait`: Wait for all documents to complete
- `--refresh-interval`: Seconds between status checks (default: 5)
- `--format`: Output format - `table` (default) or `json`
- `--region`: AWS region (optional)

**Examples:**

```bash
# Check batch status
idp-cli status \
    --stack-name my-stack \
    --batch-id cli-batch-20251015-143000

# Check single document status
idp-cli status \
    --stack-name my-stack \
    --document-id batch-123/invoice.pdf

# Monitor single document until completion
idp-cli status \
    --stack-name my-stack \
    --document-id batch-123/invoice.pdf \
    --wait

# Get JSON output for scripting
idp-cli status \
    --stack-name my-stack \
    --document-id batch-123/invoice.pdf \
    --format json
```

**Programmatic Use:**

The command returns exit codes for scripting:
- `0` - Document(s) completed successfully
- `1` - Document(s) failed
- `2` - Document(s) still processing

**JSON Output Format:**

```bash
# Single document
$ idp-cli status --stack-name my-stack --document-id batch-123/invoice.pdf --format json
{
  "document_id": "batch-123/invoice.pdf",
  "status": "COMPLETED",
  "duration": 125.4,
  "start_time": "2025-01-01T10:30:45Z",
  "end_time": "2025-01-01T10:32:50Z",
  "num_sections": 2,
  "exit_code": 0
}

# Table output includes final status summary
$ idp-cli status --stack-name my-stack --document-id batch-123/invoice.pdf
[status table]

FINAL STATUS: COMPLETED | Duration: 125.4s | Exit Code: 0
```

**Scripting Examples:**

```bash
#!/bin/bash
# Wait for document completion and check result
idp-cli status --stack-name prod --document-id batch-001/invoice.pdf --wait
exit_code=$?

if [ $exit_code -eq 0 ]; then
  echo "Document processed successfully"
  # Proceed with downstream processing
else
  echo "Document processing failed"
  exit 1
fi
```

```bash
#!/bin/bash
# Poll document status in script
while true; do
  status=$(idp-cli status --stack-name prod --document-id batch-001/invoice.pdf --format json)
  state=$(echo "$status" | jq -r '.status')
  
  if [ "$state" = "COMPLETED" ]; then
    echo "Processing complete!"
    break
  elif [ "$state" = "FAILED" ]; then
    echo "Processing failed!"
    exit 1
  fi
  
  sleep 5
done
```

---

### `download-results`

Download processing results to local directory.

**Usage:**
```bash
idp-cli download-results [OPTIONS]
```

**Options:**
- `--stack-name` (required): CloudFormation stack name
- `--batch-id` (required): Batch identifier
- `--output-dir` (required): Local directory to download to
- `--file-types`: File types to download (default: `all`)
  - Options: `pages`, `sections`, `summary`, `evaluation`, or `all`
- `--region`: AWS region (optional)

**Examples:**

```bash
# Download all results
idp-cli download-results \
    --stack-name my-stack \
    --batch-id cli-batch-20251015-143000 \
    --output-dir ./results/

# Download only extraction results
idp-cli download-results \
    --stack-name my-stack \
    --batch-id cli-batch-20251015-143000 \
    --output-dir ./results/ \
    --file-types sections

# Download evaluation results only
idp-cli download-results \
    --stack-name my-stack \
    --batch-id eval-batch-20251015 \
    --output-dir ./eval-results/ \
    --file-types evaluation
```

**Output Structure:**

```
./results/
└── cli-batch-20251015-143000/
    └── invoice.pdf/
        ├── pages/
        │   └── 1/
        │       ├── image.jpg
        │       ├── rawText.json
        │       └── result.json
        ├── sections/
        │   └── 1/
        │       ├── result.json          # Extracted structured data
        │       └── summary.json
        ├── summary/
        │   ├── fulltext.txt
        │   └── summary.json
        └── evaluation/                  # Only present if baseline provided
            ├── report.json              # Detailed metrics
            └── report.md                # Human-readable report
```

---

### `delete-documents`

Delete documents and all associated data from the IDP system.

**⚠️ WARNING:** This action cannot be undone.

**Usage:**
```bash
idp-cli delete-documents [OPTIONS]
```

**Document Selection (choose ONE):**
- `--document-ids`: Comma-separated list of document IDs (S3 object keys) to delete
- `--batch-id`: Delete all documents in this batch

**Options:**
- `--stack-name` (required): CloudFormation stack name
- `--status-filter`: Only delete documents with this status (use with --batch-id)
  - Options: `FAILED`, `COMPLETED`, `PROCESSING`, `QUEUED`
- `--dry-run`: Show what would be deleted without actually deleting
- `--force`, `-y`: Skip confirmation prompt
- `--region`: AWS region (optional)

**What Gets Deleted:**
- Source files from input bucket
- Processed outputs from output bucket
- DynamoDB tracking records
- List entries in tracking table

**Examples:**

```bash
# Delete specific documents by ID
idp-cli delete-documents \
    --stack-name my-stack \
    --document-ids "batch-123/doc1.pdf,batch-123/doc2.pdf"

# Delete all documents in a batch
idp-cli delete-documents \
    --stack-name my-stack \
    --batch-id cli-batch-20250123

# Delete only failed documents in a batch
idp-cli delete-documents \
    --stack-name my-stack \
    --batch-id cli-batch-20250123 \
    --status-filter FAILED

# Dry run to see what would be deleted
idp-cli delete-documents \
    --stack-name my-stack \
    --batch-id cli-batch-20250123 \
    --dry-run

# Force delete without confirmation
idp-cli delete-documents \
    --stack-name my-stack \
    --document-ids "batch-123/doc1.pdf" \
    --force
```

**Output Example:**
```
Connecting to stack: my-stack
Getting documents for batch: cli-batch-20250123
Found 15 document(s) in batch
  (filtered by status: FAILED)

⚠️  Documents to be deleted:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  • cli-batch-20250123/doc1.pdf
  • cli-batch-20250123/doc2.pdf
  • cli-batch-20250123/doc3.pdf
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Delete 3 document(s) permanently? [y/N]: y

✓ Successfully deleted 3 document(s)
```

**Use Cases:**
- Clean up failed documents after fixing issues
- Remove test documents from a batch
- Free up storage by removing old processed documents
- Prepare for reprocessing by removing previous results

---

### `generate-manifest`

Generate a manifest file from directory or S3 URI, or create a test set in the test set bucket.

**Usage:**
```bash
idp-cli generate-manifest [OPTIONS]
```

**Options:**
- **Source** (choose ONE):
  - `--dir`: Local directory to scan
  - `--s3-uri`: S3 URI to scan
- `--baseline-dir`: Baseline directory for automatic matching (only with --dir)
- `--output`: Output manifest file path (CSV) - optional when using --test-set
- `--file-pattern`: File pattern (default: `*.pdf`)
- `--recursive/--no-recursive`: Include subdirectories (default: recursive)
- `--region`: AWS region (optional)
- **Test Set Creation:**
  - `--test-set`: Test set name - creates folder in test set bucket and uploads files
  - `--stack-name`: CloudFormation stack name (required with --test-set)

**Examples:**

```bash
# Generate from directory
idp-cli generate-manifest \
    --dir ./documents/ \
    --output manifest.csv

# Generate with automatic baseline matching
idp-cli generate-manifest \
    --dir ./documents/ \
    --baseline-dir ./validated-baselines/ \
    --output manifest-with-baselines.csv

# Create test set and upload files (no manifest needed - use test set name)
idp-cli generate-manifest \
    --dir ./documents/ \
    --baseline-dir ./baselines/ \
    --test-set "fcc example test" \
    --stack-name IDP

# Create test set with manifest output
idp-cli generate-manifest \
    --dir ./documents/ \
    --baseline-dir ./baselines/ \
    --test-set "fcc example test" \
    --stack-name IDP \
    --output test-manifest.csv
```

**Test Set Creation:**
When using `--test-set`, the command:
1. Requires `--stack-name`, `--baseline-dir`, and `--dir`
2. Uploads input files to `s3://test-set-bucket/{test-set-id}/input/`
3. Uploads baseline files to `s3://test-set-bucket/{test-set-id}/baseline/`
4. Creates proper test set structure for evaluation workflows
5. Test set will be auto-detected by the Test Studio UI

Process the created test set:
```bash
# Using test set ID (from UI or after creation)
idp-cli process --stack-name IDP --test-set fcc-example-test --monitor

# Or using S3 URI to process input files directly
idp-cli run-inference --stack-name IDP --s3-uri s3://test-set-bucket/fcc-example-test/input/

# Or using manifest if generated
idp-cli run-inference --stack-name IDP --manifest test-manifest.csv
```

---

### `validate-manifest`

Validate a manifest file without processing.

**Usage:**
```bash
idp-cli validate-manifest --manifest documents.csv
```

---

### `list-batches`

List recent batch processing jobs.

**Usage:**
```bash
idp-cli list-batches --stack-name my-stack --limit 10
```

---

## Complete Evaluation Workflow

This workflow demonstrates how to process documents, manually validate results, and then reprocess with evaluation to measure accuracy.

### Step 1: Deploy Your Stack

Deploy an IDP stack if you haven't already:

```bash
idp-cli deploy \
    --stack-name eval-testing \
    --pattern pattern-2 \
    --admin-email your.email@example.com \
    --max-concurrent 50 \
    --wait
```

**What happens:** CloudFormation creates ~120 resources including S3 buckets, Lambda functions, Step Functions, and DynamoDB tables. This takes 10-15 minutes.

---

### Step 2: Initial Processing from Local Directory

Process your test documents to generate initial extraction results:

```bash
# Prepare test documents
mkdir -p ~/test-documents
cp /path/to/your/invoice.pdf ~/test-documents/
cp /path/to/your/w2.pdf ~/test-documents/
cp /path/to/your/paystub.pdf ~/test-documents/

# Process documents
idp-cli run-inference \
    --stack-name eval-testing \
    --dir ~/test-documents/ \
    --batch-id initial-run \
    --monitor
```

**What happens:** Documents are uploaded to S3, processed through OCR, classification, extraction, assessment, and summarization. Results are stored in OutputBucket.

**Monitor output:**
```
✓ Uploaded 3 documents to InputBucket
✓ Sent 3 messages to processing queue

Monitoring Batch: initial-run
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Status Summary
 ─────────────────────────────────────
 ✓ Completed      3     100%
 ⏸ Queued         0       0%
 ✗ Failed         0       0%
```

---

### Step 3: Download Extraction Results

Download the extraction results (sections) for manual review:

```bash
idp-cli download-results \
    --stack-name eval-testing \
    --batch-id initial-run \
    --output-dir ~/initial-results/ \
    --file-types sections
```

**Result structure:**
```
~/initial-results/initial-run/
├── invoice.pdf/
│   └── sections/
│       └── 1/
│           └── result.json      # Extracted data to validate
├── w2.pdf/
│   └── sections/
│       └── 1/
│           └── result.json
└── paystub.pdf/
    └── sections/
        └── 1/
            └── result.json
```

---

### Step 4: Manual Validation & Baseline Preparation

Review and correct the extraction results to create validated baselines.

**4.1 Review extraction results:**

```bash
# View extracted data for invoice
cat ~/initial-results/initial-run/invoice.pdf/sections/1/result.json | jq .

# Example output:
{
  "attributes": {
    "Invoice Number": "INV-2024-001",
    "Invoice Date": "2024-01-15",
    "Total Amount": "$1,250.00",
    "Vendor Name": "Acme Corp"
  }
}
```

**4.2 Validate and correct:**

Compare extracted values against the actual documents. If you find errors, create corrected baseline files:

```bash
# Create baseline directory structure
mkdir -p ~/validated-baselines/invoice.pdf/sections/1/
mkdir -p ~/validated-baselines/w2.pdf/sections/1/
mkdir -p ~/validated-baselines/paystub.pdf/sections/1/

# Copy and edit result files
cp ~/initial-results/initial-run/invoice.pdf/sections/1/result.json \
   ~/validated-baselines/invoice.pdf/sections/1/result.json

# Edit the baseline to correct any errors
vi ~/validated-baselines/invoice.pdf/sections/1/result.json

# Repeat for other documents...
```

**Baseline directory structure:**
```
~/validated-baselines/
├── invoice.pdf/
│   └── sections/
│       └── 1/
│           └── result.json      # Corrected/validated data
├── w2.pdf/
│   └── sections/
│       └── 1/
│           └── result.json
└── paystub.pdf/
    └── sections/
        └── 1/
            └── result.json
```

---

### Step 5: Create Manifest with Baseline References

Create a manifest that links each document to its validated baseline:

```bash
cat > ~/evaluation-manifest.csv << EOF
document_path,baseline_source
/home/user/test-documents/invoice.pdf,/home/user/validated-baselines/invoice.pdf/
/home/user/test-documents/w2.pdf,/home/user/validated-baselines/w2.pdf/
/home/user/test-documents/paystub.pdf,/home/user/validated-baselines/paystub.pdf/
EOF
```

**Manifest format:**
- `document_path`: Path to original document
- `baseline_source`: Path to directory containing validated sections

**Alternative using auto-matching:**

```bash
# Generate manifest with automatic baseline matching
idp-cli generate-manifest \
    --dir ~/test-documents/ \
    --baseline-dir ~/validated-baselines/ \
    --output ~/evaluation-manifest.csv
```

---

### Step 6: Process with Evaluation Enabled

Reprocess documents with the baseline-enabled manifest. The accelerator will automatically run evaluation:

```bash
idp-cli run-inference \
    --stack-name eval-testing \
    --manifest ~/evaluation-manifest.csv \
    --batch-id eval-run-001 \
    --monitor
```

**What happens:** 
1. Documents are processed through the pipeline as before
2. **Evaluation step is automatically triggered** because baselines are provided
3. The evaluation module compares extracted values against baseline values
4. Detailed metrics are calculated per attribute and per document

**Processing time:** Similar to initial run, plus ~5-10 seconds per document for evaluation.

---

### Step 7: Download and Review Evaluation Results

Download the evaluation results to analyze accuracy:

**✓ Synchronous Evaluation:** Evaluation runs as the final step in the workflow before completion. When a document shows status "COMPLETE", all processing including evaluation is finished - results are immediately available for download.

```bash
# Download evaluation results (no waiting needed)
idp-cli download-results \
    --stack-name eval-testing \
    --batch-id eval-run-001 \
    --output-dir ~/eval-results/ \
    --file-types evaluation

# Verify evaluation data is present
ls -la ~/eval-results/eval-run-001/invoice.pdf/evaluation/
# Should show: report.json and report.md
```

**Review evaluation report:**

```bash
# View detailed evaluation metrics
cat ~/eval-results/eval-run-001/invoice.pdf/evaluation/report.json | jq .


**View human-readable report:**

```bash
# Markdown report with visual formatting
cat ~/eval-results/eval-run-001/invoice.pdf/evaluation/report.md


---

## Evaluation Analytics

The IDP Accelerator provides multiple ways to analyze evaluation results across batches and at scale.

### Query Aggregated Results with Athena

The accelerator automatically stores evaluation metrics in Athena tables for SQL-based analysis.

**Available Tables:**
- `evaluation_results` - Per-document evaluation metrics
- `evaluation_attributes` - Per-attribute scores
- `evaluation_summary` - Aggregated statistics

**Example Queries:**

```sql
-- Overall accuracy across all batches
SELECT 
    AVG(overall_accuracy) as avg_accuracy,
    COUNT(*) as total_documents,
    SUM(CASE WHEN overall_accuracy >= 0.95 THEN 1 ELSE 0 END) as high_accuracy_count
FROM evaluation_results
WHERE batch_id LIKE 'eval-run-%';

-- Attribute-level accuracy
SELECT 
    attribute_name,
    AVG(score) as avg_score,
    COUNT(*) as total_occurrences,
    SUM(CASE WHEN match = true THEN 1 ELSE 0 END) as correct_count
FROM evaluation_attributes
GROUP BY attribute_name
ORDER BY avg_score DESC;

-- Compare accuracy across different configurations
SELECT 
    batch_id,
    AVG(overall_accuracy) as accuracy,
    COUNT(*) as doc_count
FROM evaluation_results
WHERE batch_id IN ('config-v1', 'config-v2', 'config-v3')
GROUP BY batch_id;
```

**Access Athena:**
```bash
# Get Athena database name from stack outputs
aws cloudformation describe-stacks \
    --stack-name eval-testing \
    --query 'Stacks[0].Outputs[?OutputKey==`ReportingDatabase`].OutputValue' \
    --output text

# Query via AWS Console or CLI
aws athena start-query-execution \
    --query-string "SELECT * FROM evaluation_results LIMIT 10" \
    --result-configuration OutputLocation=s3://your-results-bucket/
```

**For detailed Athena table schemas and query examples, see:**
- [`../docs/reporting-database.md`](../docs/reporting-database.md) - Complete Athena table reference
- [`../docs/evaluation.md`](../docs/evaluation.md) - Evaluation methodology and metrics

---

### Use Agent Analytics in the Web UI

The IDP web UI provides an Agent Analytics feature for visual analysis of evaluation results.

**Access the UI:**

1. Get web UI URL from stack outputs:
```bash
aws cloudformation describe-stacks \
    --stack-name eval-testing \
    --query 'Stacks[0].Outputs[?OutputKey==`ApplicationWebURL`].OutputValue' \
    --output text
```

2. Login with admin credentials (from deployment email)

3. Navigate to **Analytics** → **Agent Analytics**

**Available Analytics:**
- **Accuracy Trends** - Track accuracy over time across batches
- **Attribute Heatmaps** - Visualize which attributes perform best/worst
- **Batch Comparisons** - Compare different configurations side-by-side
- **Error Analysis** - Identify common error patterns
- **Confidence Correlation** - Analyze relationship between assessment confidence and accuracy

**Key Features:**
- Interactive charts and visualizations
- Filter by batch, date range, document type, or attribute
- Export results to CSV for further analysis
- Drill-down to individual document details

**For complete Agent Analytics documentation, see:**
- [`../docs/agent-analysis.md`](../docs/agent-analysis.md) - Agent Analytics user guide

---

## Manifest Format Reference

### CSV Format

**Required Field:**
- `document_path`: Local file path or full S3 URI (s3://bucket/key)

**Optional Field:**
- `baseline_source`: Path or S3 URI to validated baseline for evaluation

**Note:** Document IDs are auto-generated from filenames (e.g., `invoice.pdf` → `invoice`)

**Examples:**

```csv
document_path
/home/user/docs/invoice.pdf
/home/user/docs/w2.pdf
s3://external-bucket/statement.pdf
```

```csv
document_path,baseline_source
/local/invoice.pdf,s3://baselines/invoice/
/local/w2.pdf,/local/validated-baselines/w2/
s3://docs/statement.pdf,s3://baselines/statement/
```

### JSON Format

```json
[
  {
    "document_path": "/local/invoice.pdf",
    "baseline_source": "s3://baselines/invoice/"
  },
  {
    "document_path": "s3://bucket/w2.pdf",
    "baseline_source": "/local/baselines/w2/"
  }
]
```

### Path Rules

**Document Type (Auto-detected):**
- `s3://...` → S3 file (copied to InputBucket)
- Absolute/relative path → Local file (uploaded to InputBucket)

**Document ID (Auto-generated):**
- From filename without extension
- Example: `invoice-2024.pdf` → `invoice-2024`
- Subdirectories preserved: `W2s/john.pdf` → `W2s/john`

**Important:**
- ⚠️ Duplicate filenames not allowed
- ✅ Use directory structure for organization (e.g., `clientA/invoice.pdf`, `clientB/invoice.pdf`)
- ✅ S3 URIs can reference any bucket (automatically copied)

---

## Advanced Usage

### Iterative Configuration Testing

Test different extraction prompts or configurations:

```bash
# Test with configuration v1
idp-cli deploy --stack-name my-stack --custom-config ./config-v1.yaml --wait
idp-cli run-inference --stack-name my-stack --dir ./test-set/ --batch-id config-v1 --monitor

# Download and analyze results
idp-cli download-results --stack-name my-stack --batch-id config-v1 --output-dir ./results-v1/

# Test with configuration v2
idp-cli deploy --stack-name my-stack --custom-config ./config-v2.yaml --wait
idp-cli run-inference --stack-name my-stack --dir ./test-set/ --batch-id config-v2 --monitor

# Compare in Athena
# SELECT batch_id, AVG(overall_accuracy) FROM evaluation_results 
# WHERE batch_id IN ('config-v1', 'config-v2') GROUP BY batch_id;
```

### Large-Scale Batch Processing

Process thousands of documents efficiently:

```bash
# Generate manifest for large dataset
idp-cli generate-manifest \
    --dir ./production-documents/ \
    --output large-batch-manifest.csv

# Validate before processing
idp-cli validate-manifest --manifest large-batch-manifest.csv

# Process in background (no --monitor flag)
idp-cli run-inference \
    --stack-name production-stack \
    --manifest large-batch-manifest.csv \
    --batch-id production-batch-001

# Check status later
idp-cli status \
    --stack-name production-stack \
    --batch-id production-batch-001
```

### CI/CD Integration

Integrate into automated pipelines:

```bash
#!/bin/bash
# ci-test.sh - Automated accuracy testing

# Run processing with evaluation
idp-cli run-inference \
    --stack-name ci-stack \
    --manifest test-suite-with-baselines.csv \
    --batch-id ci-test-$BUILD_ID \
    --monitor

# Download evaluation results
idp-cli download-results \
    --stack-name ci-stack \
    --batch-id ci-test-$BUILD_ID \
    --output-dir ./ci-results/ \
    --file-types evaluation

# Parse results and fail if accuracy below threshold
python check_accuracy.py ./ci-results/ --min-accuracy 0.90

# Exit code 0 if passed, 1 if failed
exit $?
```

---

### `stop-workflows`

Stop all running workflows for a stack. Useful for halting processing during development or when issues are detected.

**Usage:**
```bash
idp-cli stop-workflows [OPTIONS]
```

**Options:**
- `--stack-name` (required): CloudFormation stack name
- `--skip-purge`: Skip purging the SQS queue
- `--skip-stop`: Skip stopping Step Function executions
- `--region`: AWS region (optional)

**Examples:**

```bash
# Stop all workflows (purge queue + stop executions)
idp-cli stop-workflows --stack-name my-stack

# Only purge the queue (don't stop running executions)
idp-cli stop-workflows --stack-name my-stack --skip-stop

# Only stop executions (don't purge queue)
idp-cli stop-workflows --stack-name my-stack --skip-purge
```

---

### `load-test`

Run load tests by copying files to the input bucket at specified rates.

**Usage:**
```bash
idp-cli load-test [OPTIONS]
```

**Options:**
- `--stack-name` (required): CloudFormation stack name
- `--source-file` (required): Source file to copy (local path or s3://bucket/key)
- `--rate`: Files per minute (default: 100)
- `--duration`: Duration in minutes (default: 1)
- `--schedule`: CSV schedule file (minute,count) - overrides --rate and --duration
- `--dest-prefix`: Destination prefix in input bucket (default: load-test)
- `--region`: AWS region (optional)

**Examples:**

```bash
# Constant rate: 100 files/minute for 5 minutes
idp-cli load-test --stack-name my-stack --source-file samples/invoice.pdf --rate 100 --duration 5

# High volume: 2500 files/minute for 1 minute
idp-cli load-test --stack-name my-stack --source-file samples/invoice.pdf --rate 2500

# Use schedule file for variable rates
idp-cli load-test --stack-name my-stack --source-file samples/invoice.pdf --schedule schedule.csv

# Use S3 source file
idp-cli load-test --stack-name my-stack --source-file s3://my-bucket/test.pdf --rate 500
```

**Schedule File Format (CSV):**
```csv
minute,count
1,100
2,200
3,500
4,1000
5,500
```

See `lib/idp_cli_pkg/examples/load-test-schedule.csv` for a sample schedule file.

---

### `remove-deleted-stack-resources`

Remove residual AWS resources left behind from deleted IDP CloudFormation stacks.

**⚠️ CAUTION:** This command permanently deletes AWS resources. Always run with `--dry-run` first.

> **Intended Use:** This command is designed for **development and test accounts** where IDP stacks are frequently created and deleted, and where the consequences of accidentally deleting resources or data are low. **Do not use this command in production accounts** where data retention is critical. For production cleanup, manually review and delete resources through the AWS Console.

**Usage:**
```bash
idp-cli remove-deleted-stack-resources [OPTIONS]
```

**How It Works:**

This command safely identifies and removes ONLY resources belonging to IDP stacks that have been deleted:

1. **Multi-region Stack Discovery** - Scans CloudFormation in multiple regions (us-east-1, us-west-2, eu-central-1 by default)
2. **IDP Stack Identification** - Identifies IDP stacks by their Description ("AWS GenAI IDP Accelerator") or naming patterns (IDP-*, PATTERN1/2/3)
3. **Active Stack Protection** - Tracks both ACTIVE and DELETED stacks; resources from active stacks are NEVER touched
4. **Safe Cleanup** - Only targets resources belonging to stacks in DELETE_COMPLETE state

**Safety Features:**
- Resources from ACTIVE stacks are protected and skipped
- Resources from UNKNOWN stacks (not verified as IDP) are skipped
- Interactive confirmation for each resource (unless --yes)
- Options: y=yes, n=no, a=yes to all of type, s=skip all of type
- --dry-run mode shows exactly what would be deleted

**Resources Cleaned:**
- CloudFront distributions and response header policies
- CloudWatch log groups  
- AppSync APIs
- IAM policies
- CloudWatch Logs resource policy entries
- S3 buckets (automatically emptied before deletion)
- DynamoDB tables (PITR disabled before deletion)

> **Note:** This command targets resources that remain in AWS after IDP stacks have already been deleted. These are typically resources with RetainOnDelete policies or non-empty S3 buckets that CloudFormation couldn't delete. All resources are identified by their naming pattern and verified against the deleted stack registry before deletion.

**Options:**
- `--region`: Primary AWS region for regional resources (default: us-west-2)
- `--profile`: AWS profile to use
- `--dry-run`: Preview changes without making them **(RECOMMENDED first step)**
- `--yes`, `-y`: Auto-approve all deletions (skip confirmations)
- `--check-stack-regions`: Comma-separated regions to check for stacks (default: us-east-1,us-west-2,eu-central-1)

**Examples:**

```bash
# RECOMMENDED: Always dry-run first to see what would be deleted
idp-cli remove-deleted-stack-resources --dry-run

# Interactive cleanup with confirmations for each resource
idp-cli remove-deleted-stack-resources

# Use specific AWS profile
idp-cli remove-deleted-stack-resources --profile my-profile

# Auto-approve all deletions (USE WITH CAUTION)
idp-cli remove-deleted-stack-resources --yes

# Check additional regions for stacks
idp-cli remove-deleted-stack-resources --check-stack-regions us-east-1,us-west-2,eu-central-1,eu-west-1
```

**CloudFront Two-Phase Cleanup:**

CloudFront requires distributions to be disabled before deletion:
1. **First run:** Disables orphaned distributions (you confirm each)
2. **Wait 15-20 minutes** for CloudFront global propagation
3. **Second run:** Deletes the previously disabled distributions

**Interactive Confirmation:**

```
Delete orphaned CloudFront distribution?
  Resource: E1H6W47Z36CQE2 (exists in AWS)
  Originally from stack: IDP-P2-DevTest1
  Stack status: DELETE_COMPLETE (stack no longer exists)
  Stack was in region: us-west-2

  Options: y=yes, n=no, a=yes to all CloudFront distribution, s=skip all CloudFront distribution
Delete? [y/n/a/s]: 
```

**Important Limitation - 90-Day Window:**

CloudFormation only retains deleted stack information for approximately 90 days. After this period, stacks in `DELETE_COMPLETE` status are removed from the CloudFormation API.

This means:
- Resources from stacks deleted **within the past 90 days** → Identified and offered for cleanup
- Resources from stacks deleted **more than 90 days ago** → Not identified (silently skipped)

**Best Practice:** Run `remove-deleted-stack-resources` promptly after deleting IDP stacks to ensure complete cleanup. For maximum effectiveness, run this command within 90 days of stack deletion.

---

### `config-create`

Generate an IDP configuration template from system defaults.

**Usage:**
```bash
idp-cli config-create [OPTIONS]
```

**Options:**
- `--features`: Feature set (default: `min`)
  - `min`: classification, extraction, classes only (simplest)
  - `core`: min + ocr, assessment
  - `all`: all sections with full defaults
  - Or comma-separated list: `"classification,extraction,summarization"`
- `--pattern`: Pattern to use for defaults (default: `pattern-2`)
- `--output`, `-o`: Output file path (default: stdout)
- `--include-prompts`: Include full prompt templates (default: stripped for readability)
- `--no-comments`: Omit explanatory header comments

**Examples:**

```bash
# Generate minimal config to stdout
idp-cli config-create

# Generate minimal config for Pattern-1
idp-cli config-create --pattern pattern-1 --output config.yaml

# Generate full config with all sections
idp-cli config-create --features all --output full-config.yaml

# Custom section selection
idp-cli config-create --features "classification,extraction,summarization" --output config.yaml
```

---

### `config-validate`

Validate a configuration file against system defaults and Pydantic models.

**Usage:**
```bash
idp-cli config-validate [OPTIONS]
```

**Options:**
- `--custom-config` (required): Path to configuration file to validate
- `--pattern`: Pattern to validate against (default: `pattern-2`)
- `--show-merged`: Show the full merged configuration

**Examples:**

```bash
# Validate a config file
idp-cli config-validate --custom-config ./my-config.yaml

# Validate against Pattern-1 defaults
idp-cli config-validate --custom-config ./config.yaml --pattern pattern-1

# Show full merged config
idp-cli config-validate --custom-config ./config.yaml --show-merged
```

---

### `config-download`

Download configuration from a deployed IDP stack.

**Usage:**
```bash
idp-cli config-download [OPTIONS]
```

**Options:**
- `--stack-name` (required): CloudFormation stack name
- `--output`, `-o`: Output file path (default: stdout)
- `--format`: Output format - `full` (default) or `minimal` (only differences from defaults)
- `--pattern`: Pattern for minimal diff (auto-detected if not specified)
- `--config-version`: Configuration version to download (e.g., v1, v2). If not specified, downloads active version
- `--region`: AWS region (optional)

**Examples:**

```bash
# Download full config from active version
idp-cli config-download --stack-name my-stack --output config.yaml

# Download specific version
idp-cli config-download --stack-name my-stack --config-version v2 --output config.yaml

# Download minimal config (only customizations)
idp-cli config-download --stack-name my-stack --format minimal --output config.yaml

# Print to stdout
idp-cli config-download --stack-name my-stack
```

---

### `config-upload`

Upload a configuration file to a deployed IDP stack.

**Usage:**
```bash
idp-cli config-upload [OPTIONS]
```

**Options:**
- `--stack-name` (required): CloudFormation stack name
- `--config-file`, `-f` (required): Path to configuration file (YAML or JSON)
- `--validate/--no-validate`: Validate config before uploading (default: validate)
- `--pattern`: Pattern for validation (auto-detected if not specified)
- `--config-version`: Configuration version to update (e.g., v1, v2). If version doesn't exist, it will be created
- `--version-description`: Description for the configuration version (used when creating new versions)
- `--region`: AWS region (optional)

**Examples:**

```bash
# Upload config to active version
idp-cli config-upload --stack-name my-stack --config-file ./config.yaml

# Update existing version
idp-cli config-upload --stack-name my-stack --config-file ./config.yaml --config-version Production

# Create new version with description
idp-cli config-upload --stack-name my-stack --config-file ./config.yaml --config-version NewVersion --version-description "Test configuration for new feature"

# Skip validation (use with caution)
idp-cli config-upload --stack-name my-stack --config-file ./config.yaml --no-validate

# Explicit pattern for validation
idp-cli config-upload --stack-name my-stack --config-file ./config.yaml --pattern pattern-2
```

---

### `config-list`

List all configuration versions in a deployed IDP stack.

**Usage:**
```bash
idp-cli config-list [OPTIONS]
```

**Options:**
- `--stack-name` (required): CloudFormation stack name
- `--region`: AWS region (optional)

**Examples:**
```bash
# List all configuration versions
idp-cli config-list --stack-name my-stack
```

**Output:**
Shows a table with version names, active status, creation/update timestamps, and descriptions.

---

### `config-activate`

Activate a configuration version in a deployed IDP stack.

**Usage:**
```bash
idp-cli config-activate [OPTIONS]
```

**Options:**
- `--stack-name` (required): CloudFormation stack name
- `--config-version` (required): Configuration version to activate
- `--region`: AWS region (optional)

**Examples:**
```bash
# Activate a specific version
idp-cli config-activate --stack-name my-stack --config-version v2

# Activate default version
idp-cli config-activate --stack-name my-stack --config-version default
```

**Notes:**
- Sets the specified version as active for all new document processing
- Version must exist (use `config-list` to see available versions)

---

### `config-delete`

Delete a configuration version from a deployed IDP stack.

**Usage:**
```bash
idp-cli config-delete [OPTIONS]
```

**Options:**
- `--stack-name` (required): CloudFormation stack name
- `--config-version` (required): Configuration version to delete
- `--force`: Skip confirmation prompt
- `--region`: AWS region (optional)

**Examples:**
```bash
# Delete a version with confirmation
idp-cli config-delete --stack-name my-stack --config-version old-version

# Delete without confirmation prompt
idp-cli config-delete --stack-name my-stack --config-version old-version --force
```

**Restrictions:**
- Cannot delete the 'default' configuration version
- Cannot delete currently active versions (activate another version first)
- Includes confirmation prompt unless `--force` is used

**What Happens:**
1. Loads and parses your YAML or JSON config file
2. Validates against system defaults (unless `--no-validate`)
3. If version exists: Updates the existing version with the uploaded configuration (saved as a complete snapshot)
4. If version doesn't exist: Creates a new version with the uploaded configuration
5. Uploads to the stack's ConfigurationTable in DynamoDB
6. Configuration is immediately available for document processing

**Configuration Versioning:**
- **No version specified**: Updates the currently active version
- **Existing version**: Saves the uploaded configuration as the full version snapshot
- **New version**: Creates a new independent version with the uploaded configuration
- **Version descriptions**: Can be added to new versions for better organization

For full details on configuration versioning, see [configuration-versions.md](configuration-versions.md).

This uses the same mechanism as the Web UI configuration management system.

---

## Troubleshooting

### Stack Not Found

**Error:** `Stack 'my-stack' is not in a valid state`

**Solution:**
```bash
# Verify stack exists
aws cloudformation describe-stacks --stack-name my-stack
```

### Permission Denied

**Error:** `Access Denied` when uploading files

**Solution:** Ensure AWS credentials have permissions for:
- S3: PutObject, GetObject on InputBucket/OutputBucket
- SQS: SendMessage on DocumentQueue
- Lambda: InvokeFunction on LookupFunction
- CloudFormation: DescribeStacks, ListStackResources

### Manifest Validation Failed

**Error:** `Duplicate filenames found`

**Solution:** Ensure unique filenames or use directory structure:
```csv
document_path
./clientA/invoice.pdf
./clientB/invoice.pdf
```

### Evaluation Not Running

**Issue:** Evaluation results missing even with baselines

**Checklist:**
1. Verify `baseline_source` column exists in manifest
2. Confirm baseline paths are correct and accessible
3. Check baseline directory has correct structure (`sections/1/result.json`)
4. Review CloudWatch logs for EvaluationFunction

### Monitoring Shows "UNKNOWN" Status

**Issue:** Cannot retrieve document status

**Solution:**
```bash
# Verify LookupFunction exists
aws lambda get-function --function-name <LookupFunctionName>

# Check CloudWatch logs
aws logs tail /aws/lambda/<LookupFunctionName> --follow
```

---

## Testing

Run the test suite:

```bash
cd lib/idp_cli_pkg
pytest
```

Run specific tests:

```bash
pytest tests/test_manifest_parser.py -v
```

---

## Support

For issues or questions:
- Check CloudWatch logs for Lambda functions
- Review AWS Console for resource status
- Open an issue on GitHub