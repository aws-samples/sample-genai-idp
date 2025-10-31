# FCC Invoice Processing - End-to-End Example

This directory contains a complete end-to-end example for processing FCC (Federal Communications Commission) political advertising invoices using the IDP accelerator with Stickler-based evaluation.

## Overview

This example demonstrates:
1. **Deployment** - Deploy the IDP stack with FCC invoice configuration
2. **Inference** - Run inference on sample FCC invoices
3. **Evaluation** - Evaluate extraction results using Stickler
4. **Review** - Analyze individual and aggregated metrics

## Directory Contents

```
config_library/pattern-2/fcc-invoices/
├── README.md                              # This file
├── config.yaml                            # Base IDP configuration
├── fcc_configured.yaml                    # Deployed stack configuration
├── stickler_config.json                   # Stickler evaluation rules
├── bulk_evaluate_fcc_invoices.py          # Legacy evaluation script (complex)
├── bulk_evaluate_fcc_invoices_simple.py   # Simplified evaluation script (recommended)
├── sample_labels_3.csv                    # Ground truth for 3 sample documents
└── sr_refactor_labels_5_5_25.csv          # Ground truth labels (full dataset)
```

## Sample Data

Sample documents are located in `samples/fcc-invoices/`:
- 3 sample PDF invoices
- `fcc_invoices_sample_3.csv` - Manifest for the 3 samples

## Prerequisites

1. **AWS Credentials**: Valid AWS credentials with appropriate permissions
2. **Python Environment**: Python 3.12+ with required packages
3. **IDP CLI**: Installed and configured
4. **Stickler**: Installed with `pip install stickler-eval`
5. **Dependencies**: `pip install pandas`

## Step 1: Deploy the Stack

Deploy the IDP stack with FCC invoice configuration:

```bash
idp-cli deploy \
  --stack-name fcc-inf-test \
  --custom-config config_library/pattern-2/fcc-invoices/config.yaml \
  --region us-west-2 \
  --wait \
  --template-url https://s3.us-west-2.amazonaws.com/bobs-artifacts-us-west-2/idp-wip/idp-main.yaml \
  --admin-email your-email@example.com \
  --pattern pattern-2
```

**What this does:**
- Creates CloudFormation stack with Lambda functions, S3 buckets, and DynamoDB tables
- Configures extraction model (Claude Sonnet 4)
- Sets up OCR with Textract (LAYOUT + TABLES features)
- Deploys with FCC-specific prompts and schema

**Expected output:**
- Stack creation takes ~5-10 minutes
- Stack status: `CREATE_COMPLETE`

## Step 2: Run Inference

Run inference on the sample documents:

```bash
idp-cli run-inference \
  --stack-name fcc-inf-test \
  --manifest samples/fcc-invoices/fcc_invoices_sample_3.csv \
  --region us-west-2
```

**What this does:**
- Uploads documents to S3 input bucket
- Triggers Lambda processing pipeline
- Performs OCR with Textract
- Extracts structured data using Claude
- Stores results in S3 output bucket

**Expected output:**
```
Validating manifest...
✓ Manifest validated successfully
Initializing batch processor for stack: fcc-inf-test
✓ Batch submitted successfully
Batch ID: batch-20251017-140000
Processing 3 documents...
```

**Monitor progress:**
```bash
idp-cli status \
  --stack-name fcc-inf-test \
  --batch-id <batch-id> \
  --region us-west-2 \
  --wait
```

## Step 3: Download Results

Download the inference results locally:

```bash
idp-cli download-results \
  --stack-name fcc-inf-test \
  --batch-id cli-batch-20251017-190516 \
  --output-dir fcc_results \
  --region us-west-2
```

**Note**: Replace `cli-batch-20251017-190516` with your actual batch ID from the inference step. You can specify any output directory name.

**What this does:**
- Downloads all result files from S3
- Creates directory structure: `fcc_results/<doc_id>/sections/1/result.json`
- Each result contains extracted fields and metadata

**Result structure:**
```json
{
  "document_class": {
    "type": "FCC-Invoice"
  },
  "inference_result": {
    "agency": "Agency Name",
    "advertiser": "Advertiser Name",
    "gross_total": "1,234.56",
    "net_amount_due": "1,234.56",
    "line_item__description": ["M-F 11a-12p", "M-F 12n-1p"],
    "line_item__days": ["MTWTF--", "MTWTF--"],
    "line_item__rate": ["100.00", "150.00"],
    "line_item__start_date": ["11/01/21", "11/01/21"],
    "line_item__end_date": ["11/07/21", "11/07/21"]
  }
}
```

## Step 4: Run Evaluation

### Option A: Single Source of Truth (Recommended)

Use the IDP config directly - no separate Stickler config needed:

```bash
cd config_library/pattern-2/fcc-invoices

python bulk_evaluate_from_idp_config.py \
  --results-dir ../../../fcc_results/cli-batch-20251017-190516 \
  --csv-path sample_labels_3.csv \
  --idp-config-path sr_FCC_config.json \
  --output-dir evaluation_output
```

**Benefits:**
- Single source of truth - evaluation config comes from IDP config
- Extracts Stickler settings from `x-aws-stickler-*` extensions in JSON Schema
- No need to maintain separate `stickler_config.json`
- Guarantees evaluation matches deployment configuration

### Option B: Separate Stickler Config

Use the simplified script with standalone Stickler config:

```bash
python bulk_evaluate_fcc_invoices_simple.py \
  --results-dir ../../../fcc_results/cli-batch-20251017-190516 \
  --csv-path sample_labels_3.csv \
  --config-path stickler_config.json \
  --output-dir evaluation_output
```

**Benefits:**
- 260 lines vs 671 lines (61% less code)
- Easier to understand and modify
- No temporary file overhead
- Direct integration with SticklerEvaluationService

### Option C: Legacy Script

Use the original complex script (not recommended):

```bash
python bulk_evaluate_fcc_invoices.py \
  --results-dir ../../../fcc_results/cli-batch-20251017-190516 \
  --csv-path sample_labels_3.csv \
  --config-path stickler_config.json \
  --output-dir evaluation_output
```

**Note**: The `sample_labels_3.csv` contains ground truth for 3 sample documents. For full dataset evaluation, use `sr_refactor_labels_5_5_25.csv`.

**What evaluation does:**
- Loads ground truth labels from CSV
- Matches documents by doc_id
- Performs doc-by-doc comparison using SticklerEvaluationService
- Saves individual comparison results
- Aggregates metrics across all documents
- Generates comprehensive evaluation report

**Expected output:**
```
================================================================================
BULK FCC INVOICE EVALUATION
================================================================================

📊 Loading ground truth from sr_refactor_labels_5_5_25.csv...
✓ Loaded 221 documents with ground truth labels

📁 Loading inference results from ../../../fcc_results...
✓ Loaded 3 inference results

🔗 Matching ground truth to inference results...
✓ Matched 3 document pairs

⚙️  Evaluating 3 documents...
✓ Completed evaluation
  Individual results saved to: evaluation_output

================================================================================
AGGREGATED EVALUATION RESULTS
================================================================================

📊 Processing Summary:
  Documents processed:  3
  Errors encountered:   0
  Non-matches found:    23

📈 Overall Metrics:
  Precision:    0.7341
  Recall:       0.4637
  F1 Score:     0.5684
  Accuracy:     0.3993

  Confusion Matrix:
    TP:    530  |  FP:    192
    FN:    613  |  TN:      5
    FP1 (False Alarm):     11
    FP2 (Wrong Value):    181

📋 Field-Level Metrics (Top 10 by F1 Score):
  Field                                     Precision     Recall         F1
  ---------------------------------------- ---------- ---------- ----------
  line_item__description                       0.9236     0.8261     0.8721
  gross_total                                  1.0000     0.7500     0.8571
  net_amount_due                               1.0000     0.7500     0.8571
  line_item__rate                              0.8169     0.7117     0.7607
  ...

💾 Aggregated results saved to evaluation_output/aggregated_metrics.json

================================================================================
✅ Evaluation complete!
   Individual results: evaluation_output
   Aggregated metrics: evaluation_output/aggregated_metrics.json
================================================================================
```

## Step 5: Review Results

### Individual Document Results

Each document has a detailed comparison result:

```bash
cat evaluation_output/0492b95bc342870920c480040bc33513.json | python -m json.tool | less
```

**Contains:**
- Field-by-field scores
- Confusion matrix (overall and per-field)
- Non-matches with details
- Similarity scores

### Aggregated Metrics

View the overall performance:

```bash
cat evaluation_output/aggregated_metrics.json | python -m json.tool | less
```

**Contains:**
- Overall precision, recall, F1, accuracy
- Per-field performance metrics
- Confusion matrix breakdown
- Non-match summary

## Understanding the Results

### Confusion Matrix Metrics

- **TP (True Positive)**: Correctly extracted field with correct value
- **FP (False Positive)**: Extracted field with incorrect value or shouldn't exist
- **TN (True Negative)**: Correctly didn't extract a field that shouldn't exist
- **FN (False Negative)**: Failed to extract a field that should exist
- **FP1 (False Alarm)**: Extracted a field that shouldn't exist
- **FP2 (Wrong Value)**: Extracted a field with wrong value

### Derived Metrics

- **Precision**: TP / (TP + FP) - How many extracted values are correct
- **Recall**: TP / (TP + FN) - How many ground truth values were found
- **F1 Score**: Harmonic mean of precision and recall
- **Accuracy**: (TP + TN) / Total - Overall correctness

## Stickler Configuration

The `stickler_config.json` defines validation rules:

### Simple Fields (Lists)
- `agency`: FuzzyComparator (threshold 0.8) - Allows minor name variations
- `advertiser`: FuzzyComparator (threshold 0.8)
- `gross_total`: ExactComparator (threshold 1.0) - Requires exact match
- `net_amount_due`: ExactComparator (threshold 1.0)

### Line Item Fields (Lists)
- `line_item__description`: LevenshteinComparator (threshold 0.7) - Allows typos
- `line_item__days`: ExactComparator (threshold 1.0)
- `line_item__rate`: ExactComparator (threshold 1.0)
- `line_item__start_date`: ExactComparator (threshold 1.0)
- `line_item__end_date`: ExactComparator (threshold 1.0)

**Note**: All fields are configured as lists to match the flat format used by both ground truth and predictions.

## Data Format

### Ground Truth (CSV)
The `sr_refactor_labels_5_5_25.csv` contains:
- `doc_id`: Document identifier (without .pdf extension)
- `refactored_labels`: JSON string with ground truth in flat list format

### Inference Results
Directory structure: `results_dir/{doc_id}.pdf/sections/1/result.json`

The flat format uses `line_item__` prefix for list fields, where each field is a list of values.

## Troubleshooting

### No matched pairs found
- Verify `doc_id` in CSV matches directory names in results
- Check if doc_id has `.pdf` extension mismatch

### AWS Token Expired
```bash
# Refresh your AWS credentials
aws sso login --profile your-profile
```

### Stack not found
```bash
# Verify stack exists
idp-cli list-stacks --region us-west-2
```

### Large matrix warnings
- Normal for documents with many line items (>100)
- Stickler uses Hungarian algorithm for optimal matching
- May be slower but produces accurate results

## Next Steps

1. **Scale Up**: Process more documents by creating a larger manifest
2. **Tune Configuration**: Adjust Stickler thresholds based on results
3. **Analyze Errors**: Review non-matches to identify extraction issues
4. **Iterate**: Update prompts or schema based on evaluation findings

## Update Log

### 10/31/2024 - Flat Schema Migration

Updated the FCC invoice configuration to use a flat array schema structure for better evaluation compatibility.

**Configuration Changes:**
- Created `sr_FCC_config.json` with flat schema (arrays for all fields)
- Updated field names: `agency_name` → `agency`, `advertiser_name` → `advertiser`, etc.
- Changed line items from nested objects to parallel arrays with `line_item__` prefix
- Added Stickler ex31, 2ten - Flat Schema Testing

sionConfiguration Changess (`x-aws-stickler-*`) to JSON Schema
- Updated extraction prompts to use `{ATTRIBUTE_NAMES_AND_DESCRIPTIONS}` placeholder
- Disag with updbled `sr_FCCed assessson` that uses a flme array stnt and  for all fields:
- Simple fisummarigency, advertiserzation steps , net_amount_due) afor faster pment arrays
- Linerocessings with `lineprefix as parallel rays
- Stickler evaluation eons added to a
- Aessment and summariion steps disabled for fssing

###t Run Commands

**Deploy with ated configura**
```b
**Commi deploy \
  -ands Run:**c-inf-tes
  --custom-config config_library/patternFCC_config.json 
1. Dregion us-west-2 \
  --wait eploy stack with updated configuration:
```-template-url https://s3.ubashst-2.amazonaartifacts-us-west/idp-wip/idp-maiyaml \
  --min-email sazon.com \
  --patt
```

*erence:**
```bash
idn-inference \
  --staame fcc-inf-\
  --manifples/fcc-s/fcc_invoic.csv \
  ion us-west-2


**Monitor idp-cli deploy \
```bash
idp-  --stacus \
  --stack-k-namfcc-inf-tee fc \
  --batch-ic-inf-test-220251031-164 \6 \
 -wait
```

 *Download results --custom-config config_library/pattern-2/fcc-invoices/sr_FCC_config.json \
 ``bash
idp-cli d -nload-results \
  --stack-name fcc-inf-test-2 \
  --batch-id cli-batch-20251031-164416 \
  --output-dir fcc_results-updated-2 \
  --region us-west-2
```

**Run evaluation:**
```bash
cd config_library/pattern-2/fcc-invoices

python bulk_evaluate_fcc_invoices_simple.py \
  --results-dir ../../../fcc_results-updated-2/cli-batch-20251031-164416 \
  --csv-path sample_labels_3.csv \
  --config-path stickler_config.json \
  --output-dir evaluation_output-2
```

### Evaluation with IDP Config

New evaluation script that uses IDP config directly:

```bash
python bulk_evaluate_from_idp_config.py \
  --results-dir ../../../fcc_results-updated-2/cli-batch-20251031-164416 \
  --csv-path sample_labels_3.csv \
  --idp-config-path sr_FCC_config.json \
  --output-dir evaluation_output-idp-config
```

**Results:**
```
📈 Overall Metrics:
  Precision: 0.5185
  Recall:    1.0000
  F1 Score:  0.6829
  Accuracy:  0.5185

  Confusion Matrix:
    TP:     14  |  FP:     13
    FN:      0  |  TN:      0
    FP1:      2  |  FP2:     11

📋 Field-Level Metrics (Top Fields):
  agency                 F1: 0.8000
  gross_total            F1: 0.8000
  net_amount_due         F1: 0.8000
  line_item__days        F1: 0.8000
  line_item__start_date  F1: 0.8000
  line_item__end_date    F1: 0.8000
```

### Notes

- Multiple deploy/inference cycles were run to iterate on the configuration
- Final batch ID: `cli-batch-20251031-164416`
- Evaluation successfully produced results with the simplified script
- Configuration now properly uses `{ATTRIBUTE_NAMES_AND_DESCRIPTIONS}` placeholder for automatic schema injection
- New `bulk_evaluate_from_idp_config.py` extracts Stickler config from `x-aws-stickler-*` extensions
- Single source of truth: IDP config contains both extraction schema and evaluation settings

-region us-west-2 \
  --wait \
  --template-url https://s3.us-west-2.amazonaws.com/bobs-artifacts-us-west-2/idp-wip/idp-main.yaml \
  --admin-email sromo@amazon.com \
  --pattern pattern-2
```

2. Run inference on sample documents:
```bash
idp-cli run-inference \
  --stack-name fcc-inf-test-2 \
  --manifest samples/fcc-invoices/fcc_invoices_sample_3.csv \
  --region us-west-2
```

3. Monitor processing status:
```bash
idp-cli status \
  --stack-name fcc-inf-test-2 \
  --batch-id cli-batch-20251031-164416 \
  --wait
```

4. Download results:
```bash
idp-cli download-results \
  --stack-namest-2 \
  --bation us-wesch-id cli-batch-20251031-164416 \
  `md)
--output-dir fcc_results-updated-2 ommon_pkg/idp_common/README_ST
October valuation with slified script:
cd confertion Guide](../../../lin 2 Architecture]ig_librapatmd)
- [Evapdated-2t../../../stickern-2EADME.md)
- /fcc-ine_fcc_invoicle.py \ identicalsults
d) Documentation
- [Sti
  --re ..onal Resntation](../ources
/ [IDPation scrip../../fct (260 l/c251031-71 lines) prod164416 \marking)
- Simplifi
  --cmple_labels_3.cpctath stickler_con\
  --outt-dir evaluation_outpsults:**ring (disabled for
- Sloyedipt produced with fl metrics using Sat scurEvaluationSece completield names aay format
uation s:**tion fl
- JSON Scma iLMn `clasows  calls for coinTE_NAsired ouMES_ANDS}` placeholdtpert
- Assessment 
- Extompts must exprequest the 