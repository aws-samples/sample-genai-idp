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
  - [run-inference](#run-inference)
  - [rerun-inference](#rerun-inference)
  - [status](#status)
  - [download-results](#download-results)
  - [generate-manifest](#generate-manifest)
  - [validate-manifest](#validate-manifest)
  - [list-batches](#list-batches)
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

- Python 3.9 or higher
- AWS credentials configured (via AWS CLI or environment variables)
- An active IDP Accelerator CloudFormation stack

### Install from source

```bash
cd idp_cli
pip install -e .
```

### Install with test dependencies

```bash
cd idp_cli
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
idp-cli run-inference \
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
- `--pattern`: IDP pattern (`pattern-1`, `pattern-2`, or `pattern-3`)
- `--admin-email`: Admin user email

**Optional Parameters:**
- `--custom-config`: Path to local config file or S3 URI
- `--max-concurrent`: Maximum concurrent workflows (default: 100)
- `--log-level`: Logging level (`DEBUG`, `INFO`, `WARN`, `ERROR`)
- `--enable-hitl`: Enable Human-in-the-Loop (`true` or `false`)
- `--parameters`: Additional parameters as `key=value,key2=value2`
- `--wait`: Wait for stack operation to complete
- `--region`: AWS region (optional, auto-detected)

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
- `--wait / --no-wait`: Wait for deletion to complete (default: wait)
- `--region`: AWS region (optional)

**S3 Bucket Behavior:**
- **LoggingBucket**: `DeletionPolicy: Retain` - Always kept
- **All other buckets**: `DeletionPolicy: RetainExceptOnCreate` - Deleted if empty
- CloudFormation can ONLY delete S3 buckets if they're empty
- Use `--empty-buckets` to automatically empty buckets before deletion

**Examples:**

```bash
# Interactive deletion with confirmation
idp-cli delete --stack-name test-stack

# Automated deletion (CI/CD)
idp-cli delete --stack-name test-stack --force

# Delete with automatic bucket emptying
idp-cli delete --stack-name test-stack --empty-buckets --force

# Delete without waiting
idp-cli delete --stack-name test-stack --force --no-wait
```

**What you'll see:**
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

**Use Cases:**
- Cleanup test/development environments to avoid charges
- CI/CD pipelines that provision and teardown stacks
- Automated testing with temporary stack creation

**Note:** LoggingBucket is retained by design. To delete it manually:
```bash
aws s3 rb s3://<logging-bucket-name> --force
```

---

### `run-inference`

Process a batch of documents.

**Usage:**
```bash
idp-cli run-inference [OPTIONS]
```

**Document Source (choose ONE):**
- `--manifest`: Path to manifest file (CSV or JSON)
- `--dir`: Local directory containing documents
- `--s3-uri`: S3 URI in InputBucket

**Options:**
- `--stack-name` (required): CloudFormation stack name
- `--batch-id`: Custom batch ID (auto-generated if omitted)
- `--batch-prefix`: Prefix for auto-generated batch ID (default: `cli-batch`)
- `--file-pattern`: File pattern for directory/S3 scanning (default: `*.pdf`)
- `--recursive/--no-recursive`: Include subdirectories (default: recursive)
- `--monitor`: Monitor progress until completion
- `--refresh-interval`: Seconds between status checks (default: 5)
- `--region`: AWS region (optional)

**Examples:**

```bash
# Process from local directory
idp-cli run-inference \
    --stack-name my-stack \
    --dir ./documents/ \
    --monitor

# Process from manifest with baselines (enables evaluation)
idp-cli run-inference \
    --stack-name my-stack \
    --manifest documents-with-baselines.csv \
    --monitor

# Process S3 URI
idp-cli run-inference \
    --stack-name my-stack \
    --s3-uri archive/2024/ \
    --monitor
```

---

### `rerun-inference`

Reprocess existing documents from a specific pipeline step.

**Usage:**
```bash
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
idp-cli rerun-inference \
    --stack-name my-stack \
    --step classification \
    --document-ids "batch-123/doc1.pdf,batch-123/doc2.pdf" \
    --monitor

# Rerun extraction for entire batch
idp-cli rerun-inference \
    --stack-name my-stack \
    --step extraction \
    --batch-id cli-batch-20251015-143000 \
    --monitor

# Automated rerun (skip confirmation - perfect for CI/CD)
idp-cli rerun-inference \
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

Check batch processing status.

**Usage:**
```bash
idp-cli status [OPTIONS]
```

**Options:**
- `--stack-name` (required): CloudFormation stack name
- `--batch-id` (required): Batch identifier
- `--wait`: Wait for all documents to complete
- `--refresh-interval`: Seconds between status checks (default: 5)
- `--region`: AWS region (optional)

**Example:**

```bash
idp-cli status \
    --stack-name my-stack \
    --batch-id cli-batch-20251015-143000 \
    --wait
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

### `generate-manifest`

Generate a manifest file from directory or S3 URI.

**Usage:**
```bash
idp-cli generate-manifest [OPTIONS]
```

**Options:**
- **Source** (choose ONE):
  - `--dir`: Local directory to scan
  - `--s3-uri`: S3 URI to scan
- `--baseline-dir`: Baseline directory for automatic matching (only with --dir)
- `--output` (required): Output manifest file path (CSV)
- `--file-pattern`: File pattern (default: `*.pdf`)
- `--recursive/--no-recursive`: Include subdirectories (default: recursive)
- `--region`: AWS region (optional)

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

**⏱️ Important Timing Note:** Evaluation processing runs as a separate step after the main document processing completes. This takes an additional 2-3 minutes per document. If you download results immediately after the batch shows "Complete", the evaluation data may not be ready yet.

**Best practice:**
1. Wait 5-10 minutes after batch completion before downloading evaluation results
2. Check that the downloaded files include the `evaluation/` directory
3. If evaluation data is missing, wait a few more minutes and download again

```bash
# Wait for evaluation to complete (check status)
idp-cli status \
    --stack-name eval-testing \
    --batch-id eval-run-001

# Download evaluation results
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
cd idp_cli
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
