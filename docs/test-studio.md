---
title: "Test Studio"
---

# Test Studio

The Test Studio provides a comprehensive interface for managing test sets, running tests, and analyzing results directly from the web UI.

## Overview

The Test Studio consists of two main tabs:
1. **Test Sets**: Create and manage reusable collections of test documents
2. **Test Executions**: Execute tests, view results, and compare test runs

https://github.com/user-attachments/assets/7c5adf30-8d5c-4292-93b0-0149506322c7


## Pre-Deployed Test Sets

The accelerator automatically deploys **four benchmark datasets** from HuggingFace as ready-to-use test sets during stack deployment:

1. **RealKIE-FCC-Verified**: 75 FCC invoice documents
2. **OmniAI-OCR-Benchmark**: 293 diverse document images across 9 formats
3. **DocSplit-Poly-Seq**: 500 multi-page packets with 13 document types
4. **Fake-W2-Tax-Forms**: 2,000 synthetic US W-2 tax form images with 45-field ground truth

All datasets are deployed automatically with zero manual steps required. Each test set has a corresponding **managed configuration version** (e.g., `fake-w2`, `docsplit`) that is auto-selected in Test Studio when the test set is chosen. See [Configuration — Managed Configuration Versions](configuration.md#managed-configuration-versions) for details.

---

### RealKIE-FCC-Verified

**Source**: https://huggingface.co/datasets/amazon-agi/RealKIE-FCC-Verified

This dataset contains 75 invoice documents sourced from the Federal Communications Commission (FCC).

https://github.com/user-attachments/assets/d952fd37-1bd0-437f-8f67-5a634e9422e0

#### Deployment Details

During stack deployment, the system automatically:

1. **Downloads Dataset Metadata** from HuggingFace parquet file (75 documents)
2. **Downloads PDFs** directly from HuggingFace's `pdfs/` directory
3. **Uploads PDFs** to `s3://TestSetBucket/realkie-fcc-verified/input/`
4. **Extracts Ground Truth** from `json_response` field (already in accelerator format!)
5. **Uploads Baselines** to `s3://TestSetBucket/realkie-fcc-verified/baseline/`
6. **Registers Test Set** in DynamoDB with metadata

#### Key Features

### Key Features

- **Fully Automatic**: Complete deployment during stack creation with zero user effort
- **Direct PDF Downloads**: PDFs are downloaded directly from HuggingFace's repository (no image conversion needed)
- **Complete Ground Truth**: Structured invoice attributes (Agency, Advertiser, GrossTotal, PaymentTerms, AgencyCommission, NetAmountDue, LineItems)
- **Benchmark Ready**: 75 FCC invoice documents ideal for extraction evaluation

#### Corresponding Config

Use with: `config_library/unified/realkie-fcc-verified/config.yaml`

---

### OmniAI-OCR-Benchmark

**Source**: https://huggingface.co/datasets/getomni-ai/ocr-benchmark

This dataset contains 293 pre-selected document images across 9 diverse document formats, filtered from the OmniAI OCR benchmark dataset.

#### Document Classes

| Class | Count | Description |
|-------|-------|-------------|
| BANK_CHECK | 52 | Bank checks with MICR encoding |
| COMMERCIAL_LEASE_AGREEMENT | 52 | Commercial property leases |
| CREDIT_CARD_STATEMENT | 11 | Account statements with transactions |
| DELIVERY_NOTE | 8 | Shipping/delivery documents |
| EQUIPMENT_INSPECTION | 11 | Inspection reports with checkpoints |
| GLOSSARY | 31 | Alphabetized term lists |
| PETITION_FORM | 51 | Election petition forms |
| REAL_ESTATE | 59 | Real estate transaction data |
| SHIFT_SCHEDULE | 18 | Employee scheduling documents |

#### Deployment Details

During stack deployment, the system automatically:

1. **Downloads Metadata** from HuggingFace (metadata.jsonl)
2. **Downloads Images** for 293 pre-selected image IDs
3. **Converts to PNG** and uploads to `s3://TestSetBucket/ocr-benchmark/input/`
4. **Extracts Ground Truth** from `true_json_output` field
5. **Uploads Baselines** to `s3://TestSetBucket/ocr-benchmark/baseline/`
6. **Registers Test Set** in DynamoDB with format distribution metadata

#### Key Features

- **Multi-Format**: 9 different document types for comprehensive testing
- **Nested Schemas**: Complex JSON schemas with nested objects and arrays
- **Pre-Selected**: 293 images filtered for formats with >5 samples per schema
- **Deterministic**: Same images deployed every time for reproducible benchmarks

#### Corresponding Config

Use with: `config_library/unified/ocr-benchmark/config.yaml`

---

### Common Features

Both datasets share these deployment characteristics:

- **Fully Automatic**: Complete deployment during stack creation with zero user effort
- **Version Control**: Dataset version pinned in CloudFormation, updateable via parameter
- **Smart Updates**: Skips re-download on stack updates unless version changes
- **Single Public Source**: Everything from HuggingFace - fully reproducible anywhere

### Deployment Time

- **First Deployment**: Adds ~15-20 minutes to stack deployment (downloads all three datasets)
- **Stack Updates**: Near-instant (skips if versions unchanged)
- **Version Updates**: Re-downloads and re-processes when DatasetVersion changes

### Usage

All test sets are immediately available after stack deployment:

1. Navigate to **Test Executions** tab
2. Select the test set from the **Select Test Set** dropdown:
   - "RealKIE-FCC-Verified" for invoice extraction testing
   - "OmniAI-OCR-Benchmark" for multi-format document testing
   - "DocSplit-Poly-Seq" for document splitting and classification testing
   - "Fake-W2-Tax-Forms" for W-2 tax form extraction testing
3. Enter a description in the **Context** field
4. Click **Run Test** to start processing
5. Monitor progress and view results when complete

**RealKIE-FCC-Verified** is ideal for:
- Evaluating extraction accuracy on invoice documents
- Comparing different model configurations
- Testing prompt engineering improvements

**OmniAI-OCR-Benchmark** is ideal for:
- Testing classification across diverse document types
- Evaluating extraction on complex nested schemas
- Benchmarking multi-format document processing pipelines

**DocSplit-Poly-Seq** is ideal for:
- Evaluating document splitting and classification accuracy
- Testing multi-document packet processing capabilities
- Benchmarking page-level classification across diverse document types
- Assessing document boundary detection in complex packets

**OmniAI-OCR-Benchmark** is ideal for:
- Testing classification across diverse document types
- Evaluating extraction on complex nested schemas
- Benchmarking multi-format document processing pipelines

---

### DocSplit-Poly-Seq

**DocSplit Dataset**: https://huggingface.co/datasets/amazon/doc_split  
**Documents Source**: https://huggingface.co/datasets/jordyvl/rvl_cdip_n_mp

The DocSplit dataset contains 500 multi-page packet PDFs created by combining pages from 13 different document types. Documents are sourced from the RVL-CDIP-N-MP dataset. Each packet contains multiple subdocuments of different types to test classification and document splitting capabilities.

#### Benchmark Methodology

**DocSplit-Poly-Seq (Multi Category Documents Concatenation Sequentially):** Creates document packets by first determining a target page count (5-20 pages), then sequentially selecting documents from different categories without repetition. For each selected document, all of its pages are included while preserving the original page ordering, and this process continues until the target page count is reached.

This benchmark simulates the most common real-world scenario where heterogeneous documents are assembled into packets, as observed in medical claims processing where prescription records, laboratory results, and insurance forms are concatenated. The varying document types test models' ability to detect inter-document boundaries based on content and structural transitions, a fundamental requirement for accurate packet splitting.

#### Document Types

The dataset includes 13 document types spanning common business and administrative documents:
- **invoice**, **email**, **form**, **letter**, **memo**, **resume**
- **budget**, **news article**, **scientific publication**, **specification**
- **questionnaire**, **handwritten**, **language** (non-English documents)

#### Packet Statistics

| Metric | Value |
|--------|-------|
| Total Document Packets | 500 |
| Total Pages | 7,330 |
| Total Sections | 2,027 |
| Avg Pages/Packet | 14.7 |
| Avg Pages/Sections | 3.62 |
| Avg Sections/Packet | 4.1 |
| Avg Unique Document Type/Packet | 3.67 |

#### Deployment Details

During stack deployment, the system automatically:

1. **Downloads Dataset** from HuggingFace (data.tar.gz containing source PDFs)
2. **Creates Packet PDFs** by merging pages from source documents based on bundled manifest
3. **Uploads Packets** to `s3://TestSetBucket/docsplit/input/`
4. **Generates Ground Truth** with document class and page split information
5. **Uploads Baselines** to `s3://TestSetBucket/docsplit/baseline/`
6. **Registers Test Set** in DynamoDB with metadata and document type distribution

#### Key Features

- **Multi-Document Packets**: Each PDF contains 2-10 distinct documents of different types
- **Splitting Evaluation**: Tests ability to correctly split multi-document packets into individual sections
- **Classification Diversity**: 13 document types provide comprehensive classification testing
- **Variable Page Counts**: Packets range from 5 to 20 pages with varying complexity
- **Ground Truth Included**: Complete page-level classification and splitting information

#### Corresponding Config

Use with: `config_library/unified/rvl-cdip/config.yaml`

#### Evaluation Metrics

This test set enables evaluation of:
- **Page-Level Classification**: Accuracy of classifying each page to correct document type
- **Document Splitting**: Accuracy of identifying document boundaries within packets
- **Split Order**: Accuracy of maintaining correct page order within each split section

**DocSplit-Poly-Seq** is ideal for:
- Evaluating document splitting and classification accuracy
- Testing multi-document packet processing capabilities
- Benchmarking page-level classification across diverse document types
- Assessing document boundary detection in complex packets

---

### Fake-W2-Tax-Forms

**HuggingFace Source**: https://huggingface.co/datasets/singhsays/fake-w2-us-tax-form-dataset
**Original Source**: https://www.kaggle.com/datasets/mcvishnu1/fake-w2-us-tax-form-dataset (CC0: Public Domain)

This dataset contains 2,000 synthetically generated US W-2 tax form images with comprehensive structured ground truth. The forms contain fake data (names, IDs, addresses, financial figures) with only real city, state, and zip codes used.

#### Dataset Splits

| Split | Count | Description |
|-------|-------|-------------|
| Train | 1,800 | Training set images |
| Test | 100 | Test set images |
| Validation | 100 | Validation set images |

#### Ground Truth Fields (45 per document)

Each document includes structured ground truth in `gt_parse` JSON format covering all standard W-2 boxes:

| Category | Fields | Examples |
|----------|--------|----------|
| **Employer Info** | EIN, name, street address, city/state/zip | `box_b_employer_identification_number`, `box_c_employer_name` |
| **Employee Info** | SSN, name, street address, city/state/zip | `box_a_employee_ssn`, `box_e_employee_name` |
| **Control** | Control number | `box_d_control_number` |
| **Federal Wages** | Wages, SS wages, Medicare wages, SS tips, allocated tips | `box_1_wages`, `box_3_social_security_wages`, `box_5_medicare_wages` |
| **Federal Taxes** | Federal tax, SS tax, Medicare tax | `box_2_federal_tax_withheld`, `box_4_social_security_tax_withheld` |
| **Benefits** | Dependent care, nonqualified plans | `box_10_dependent_care_benefits`, `box_11_nonqualified_plans` |
| **Codes (12a-d)** | Code letter + value (4 entries) | `box_12a_code`, `box_12a_value` |
| **Checkboxes (13)** | Statutory employee, retirement plan, third-party sick pay | `box_13_statutary_employee`, `box_13_retirement_plan` |
| **State/Local (×2)** | State, state ID, state wages, state tax, local wages, local tax, locality | `box_15_1_state`, `box_16_1_state_wages`, `box_20_1_locality` |

#### Deployment Details

During stack deployment, the system automatically:

1. **Downloads Parquet Files** from HuggingFace (all 3 splits: train, test, validation)
2. **Extracts Images** from parquet `image` column (JPG format, 612×792px)
3. **Uploads Images** to `s3://TestSetBucket/fake-w2/input/`
4. **Converts Ground Truth** from `gt_parse` JSON to accelerator `inference_result` format
5. **Uploads Baselines** to `s3://TestSetBucket/fake-w2/baseline/`
6. **Registers Test Set** in DynamoDB with metadata

#### Key Features

- **Comprehensive Ground Truth**: 45 structured fields per document covering all W-2 boxes
- **Large Scale**: 2,000 documents enable statistically significant benchmarking
- **Synthetic = No PII**: Fake data eliminates privacy concerns for testing and sharing
- **Multiple Data Types**: Mix of string identifiers (SSN, EIN), monetary values (wages, taxes), codes, and checkboxes
- **Dual State/Local Entries**: Each form includes two state/local tax jurisdictions for array extraction testing
- **CC0 License**: Public domain — no attribution or redistribution restrictions

#### Corresponding Config

Use with: `config_library/unified/fake-w2/config.yaml`

**Fake-W2-Tax-Forms** is ideal for:
- Benchmarking W-2 tax form extraction accuracy at scale
- Evaluating numeric precision on monetary fields (wages, taxes)
- Testing structured form data extraction with nested/repeating sections
- Assessing image quality impact on OCR and extraction accuracy
- Comparing model performance across 2,000 documents for statistical significance

---

### Common Features

All datasets share these deployment characteristics:
**OmniAI-OCR-Benchmark** is ideal for:
- Testing classification across diverse document types
- Evaluating extraction on complex nested schemas
- Benchmarking multi-format document processing pipelines

**DocSplit-Poly-Seq** is ideal for:
- Evaluating document splitting and classification accuracy
- Testing multi-document packet processing capabilities
- Benchmarking page-level classification across diverse document types
- Assessing document boundary detection in complex packets

---

### Common Features

All datasets share these deployment characteristics:

### Backend Components

#### TestSetResolver Lambda
- **Location**: `src/lambda/test_set_resolver/index.py`
- **Purpose**: Handles GraphQL operations for test set management
- **Features**: Creates test sets, scans TestSetBucket for direct uploads, validates file matching, manages test set status

#### TestSetFileCopier Lambda
- **Location**: `src/lambda/test_set_file_copier/index.py`
- **Purpose**: Copies files from source buckets to the test set bucket
- **Features**: Pattern-based file matching, baseline validation, automatic baseline filtering for Input Bucket sources, time-based file filtering, file count recount, supports both create and append modes

#### TestSetZipExtractor Lambda
- **Location**: `src/lambda/test_set_zip_extractor/index.py`
- **Purpose**: Extracts and validates uploaded zip files
- **Features**: S3 event triggered extraction, file validation, status updates, file count recount for accurate totals

#### TestRunner Lambda
- **Location**: `src/lambda/test_runner/index.py`
- **Purpose**: Initiates test runs and queues file processing jobs
- **Features**: Test validation, SQS message queuing, fast response optimization

#### TestFileCopier Lambda
- **Location**: `src/lambda/test_file_copier/index.py`
- **Purpose**: Handles asynchronous file copying and processing initiation
- **Features**: SQS message processing, file copying, status management

#### TestResultsResolver Lambda
- **Location**: `src/lambda/test_results_resolver/index.py`
- **Purpose**: Handles GraphQL queries for test results and comparisons, plus asynchronous cache updates
- **Features**: 
  - Result retrieval with cached metrics
  - Comparison logic and metrics aggregation
  - Dual event handling (GraphQL + SQS)
  - Asynchronous cache update processing
  - Progress-aware status updates

#### TestResultCacheUpdateQueue
- **Type**: AWS SQS Queue
- **Purpose**: Decouples heavy metric calculations from synchronous API calls
- **Features**: 
  - Encrypted message storage
  - 15-minute visibility timeout for long-running calculations
  - Automatic retry handling

### GraphQL Schema
- **Location**: `src/api/schema.graphql`
- **Operations**: `getTestSets`, `addTestSet`, `addTestSetFromUpload`, `addDocumentsToTestSet`, `addDocumentsToTestSetFromUpload`, `deleteTestSets`, `getTestRuns`, `startTestRun`, `abortTestRuns`, `compareTestRuns`

### Frontend Components

#### TestStudioLayout
- **Location**: `src/ui/src/components/test-studio/TestStudioLayout.jsx`
- **Purpose**: Main container with two-tab navigation and global state management

#### TestSets
- **Location**: `src/ui/src/components/test-studio/TestSets.tsx`
- **Purpose**: Manage test set collections
- **Features**: Pattern-based creation, zip upload, direct upload detection, incremental document addition, time-based file filtering, dual polling (3s active, 60s discovery)

#### TestExecutions
- **Location**: `src/ui/src/components/test-studio/TestExecutions.jsx`
- **Purpose**: Unified interface combining TestRunner and TestResultsList
- **Features**: Test execution, results viewing, comparison, export, abort, delete operations

## Component Structure

```
components/
└── test-studio/
    ├── TestStudioLayout.jsx
    ├── TestSets.jsx
    ├── TestExecutions.jsx
    ├── TestRunner.jsx
    ├── TestResultsList.jsx
    ├── TestResults.jsx
    ├── TestComparison.jsx
    ├── TestRunnerStatus.jsx
    ├── DeleteTestModal.jsx
    └── index.js
```

## Test Sets

### Creating Test Sets
1. **Pattern-based**: Define file patterns (e.g., `*.pdf`) with bucket type selection
   - **Input Bucket**: Scan main processing bucket for matching files
   - **Test Set Bucket**: Scan dedicated test set bucket for matching files
   - **Description**: Optional description field (max 500 characters) to document the test set purpose
   - **Document Classification Type**: Optional metadata to categorize test set classification characteristics:
     - **Unspecified**: No classification type specified (default)
     - **Single Class**: All documents in test set belong to same document class
     - **Multi Class**: Documents span multiple document classes
     - **Packet Splitting**: Test set designed for document splitting evaluation (packets containing multiple sub-documents)
   - **Modified after filter**: Optional time filter to include only recently modified files — choose a preset (Last 1 hour, 24 hours, 7 days, etc.) or pick a custom date/time (useful for incremental workflows)
2. **Zip Upload**: Upload zip containing `input/` and `baseline/` folders
   - **Description**: Optional description field (max 500 characters) to document the test set purpose
   - **Document Classification Type**: Optional metadata (same values as pattern-based creation)
3. **Direct Upload**: Files uploaded directly to TestSetBucket are auto-detected

### Editing Test Sets

You can edit a test set's description and document classification type after creation:

1. Select a single test set in the table
2. Click **Edit** to open the edit modal
3. Update the **Description** (max 500 characters) or **Document Classification Type**
4. Click **Update** to save changes

### Adding Documents to Existing Test Sets

You can incrementally add documents to a COMPLETED test set — useful for building up test sets over time as new documents are processed and human-reviewed.

1. Select a single COMPLETED test set in the table
2. Click **Add Documents** and choose a source:
   - **From Existing Files**: Select a bucket, enter a file pattern, and optionally filter by modification time
   - **From Upload**: Upload a zip file containing new documents and their baselines
3. The test set shows an "Updating..." status while files are being added
4. After completion, the file count is updated and a result message is displayed

**Key behaviors:**
- **Automatic baseline filtering** (Input Bucket): Files without matching baseline data in the evaluation bucket are automatically excluded rather than failing. A result message reports the counts (e.g., "Added 8 of 12 files (4 excluded - no baseline data)").
- **Idempotent**: Adding a document that already exists overwrites it. File counts are always recounted from S3 for accuracy.
- **Prepopulated file pattern**: The file pattern field is pre-filled with the pattern used to create the test set, so you can reuse or adjust it.
- **Time filter**: Use the "Modified after" filter — choose a preset (Last 1 hour, 4 hours, 24 hours, 7 days, 30 days) or select "Custom date/time" with a date picker to specify an exact cutoff. This makes it easy to pick up recently reviewed documents without crafting complex patterns.

### File Structure Requirements
```
my-test-set/
├── input/
│   ├── document1.pdf
│   └── document2.pdf
└── baseline/
    ├── document1.pdf/
    │   └── [ground truth files]
    └── document2.pdf/
        └── [ground truth files]
```

### Validation Rules
- Each input file must have corresponding baseline folder
- Baseline folder name must match input filename exactly
- When using Input Bucket as source, files without baselines are automatically excluded (not treated as an error)
- Status: COMPLETED (valid), FAILED (validation errors), QUEUED/COPYING (creating), UPDATING (adding documents)

### Upload Methods
1. **UI Zip Upload**: S3 event → Lambda extraction → Validation → Status update
2. **Direct S3 Upload**: Detected via refresh button or automatic polling

## Test Executions

### Running Tests
1. Select test set from dropdown
2. **Optional**: Select configuration version to use for processing
3. **Optional**: Enter number of files to limit processing (useful for quick testing)
4. **Optional**: Add context description for the test run
5. Click "Run Test" (single test execution only)
6. Monitor progress via TestRunnerStatus
7. View results in integrated listing

### Configuration Versioning
The Test Studio supports running tests with specific configuration versions:
- **Version Selection**: Choose from available configuration versions (e.g., `default`, `Production`, `v1`)
- **Version Tracking**: Test results display which configuration version was used
- **Version Comparison**: Compare test runs across different configuration versions
- **Context Generation**: Test context automatically includes the selected version information

For full details on configuration versioning, see [configuration-versions.md](configuration-versions.md).

### Test States
- **QUEUED**: File copying jobs queued in SQS
- **RUNNING**: Files being copied and processed
- **EVALUATING**: Documents processed, evaluation in progress
- **COMPLETED**: Test finished successfully with all documents evaluated
- **PARTIAL_COMPLETE**: Test finished with some documents failed
- **FAILED**: Errors during processing
- **ABORTED**: Test run manually stopped before completion

### Aborting Test Runs
Test runs with status **QUEUED** or **RUNNING** can be aborted:
1. Click the "Abort" button next to the running test
2. The system will:
   - Stop all pending document processing workflows
   - Preserve results from already-completed documents
   - Update test run status to **ABORTED**
   - Calculate metrics for completed documents
3. View partial results including:
   - Accurate count of completed vs. total files (e.g., "48/50 files processed")
   - Evaluation metrics for completed documents
   - Cost breakdown for processed documents

**Note**: Test runs with status **EVALUATING**, **COMPLETED**, **PARTIAL_COMPLETE**, or **FAILED** cannot be aborted.

### Results Management
- Filter and paginate test runs
- Multi-select for comparison
- Navigate to detailed results view
- Abort running test runs
- Delete and export functionality

## Key Features

### Test Set Management
- Reusable collections with file patterns across multiple buckets
- Dual bucket support (Input Bucket and Test Set Bucket)
- Optional description field for documenting test set purpose
- Zip upload with automatic extraction
- Direct upload detection via dual polling
- File structure validation with error reporting

### Test Execution
- Single test concurrency prevention
- Optional file count limiting for quick testing
- Real-time status monitoring
- Global state persistence across navigation
- SQS-based asynchronous processing

### Results Analysis
- Comprehensive metrics display including:
  - **Test run metadata**: Configuration version, duration, context, file counts
  - **Overall accuracy and confidence metrics**
  - **Cost metrics**: Total cost and average cost per page
  - **Accuracy breakdown** (precision, recall, F1-score, false alarm rate, false discovery rate)
  - **Field-Level Metrics**: Per-field extraction performance table with columns: Field Name, Accuracy, Precision, Recall, TP, FP, TN, FN
  - **Average Document Split Classification Metrics**:
    - Page Level Accuracy (average across documents)
    - Split Accuracy Without Order (average across documents)
    - Split Accuracy With Order (average across documents)  
    - Total Pages, Total Splits (sums across documents)
    - Correctly Classified Pages, Correctly Split counts (sums across documents)
  - **Cost breakdown** by service and context
- Side-by-side test comparison with all metrics including configuration versions
- Export capabilities (JSON/CSV downloads include all metrics)
- Integrated delete operations

### Bulk Aggregation with Stickler

Test Studio uses Stickler's `BulkStructuredModelEvaluator` for accurate metric aggregation across multiple documents:

**How It Works:**
1. **Individual Evaluation**: Each document is evaluated with `include_confusion_matrix=True` to capture detailed field-level metrics
2. **Storage**: Raw Stickler comparison results are stored in S3 at `{doc_path}/evaluation/results.json` under the `stickler_comparison_result` field
3. **Aggregation**: When viewing test results, the system:
   - Scans DynamoDB for all documents in the test run (PK pattern: `doc#{test_run_id}*`)
   - Loads evaluation results from S3
   - Extracts `stickler_comparison_result` from each document
   - Uses `aggregate_from_comparisons()` to compute aggregate metrics
4. **Fallback**: Athena-based aggregation remains available for backward compatibility with older data

**Benefits:**
- **More Accurate**: Uses Stickler's confusion matrix for precise field-level metrics
- **Consistent**: Same evaluation engine for single documents and bulk aggregation
- **Efficient**: No Athena queries needed for new data
- **Cost Effective**: Reduces Athena query costs

### Field-Level Metrics

Test results include detailed per-field extraction performance metrics displayed in an interactive table with optional confidence calibration columns (Stickler v0.4.0+):

**Displayed Columns:**
1. **Field Name**: The name of the extracted field (hierarchical with expand/collapse)
2. **Accuracy**: `(TP + TN) / (TP + FP + TN + FN)` - Overall correctness
3. **Precision**: `TP / (TP + FP)` - Accuracy of positive predictions
4. **Recall**: `TP / (TP + FN)` - Coverage of actual positives
5. **AUROC** (when available): Area Under ROC Curve - how well confidence discriminates correct from incorrect (1.0 = perfect)
6. **ECE** (when available): Expected Calibration Error - measures calibration quality (0.0 = perfect)
7. **Brier** (when available): Brier Score - mean squared error between confidence and outcome (0.0 = perfect, 0.25 = random)
8. **ECARB@30** (when available): Error Capture at Budget 30% - practical metric showing % of errors caught when reviewing lowest-confidence 30% of data, with gain multiplier vs random (e.g., "89% (3.0x)")
9. **TP** (True Positives): Correctly extracted values
10. **FP** (False Positives): Incorrectly extracted values
11. **TN** (True Negatives): Correctly identified as absent
12. **FN** (False Negatives): Missed extractions

**Features:**
- **Hierarchical Display**: Nested fields with expand/collapse controls
- **Searchable**: Filter fields by name to quickly find specific metrics
- **Sortable**: Click any column header to sort by that metric (including confidence columns)
- **Column Preferences**: Show/hide columns via preferences menu (confidence columns auto-added when data available)
- **Expandable Section**: Collapsed by default to keep results view clean
- **Paginated**: 10 fields per page for easy navigation
- **Resizable Columns**: Adjust column widths as needed
- **Backward Compatible**: Confidence columns only shown for test runs with Stickler v0.4.0+ data
- **Interactive Help**: Info icons next to metric names provide explanatory tooltips with links to documentation (Wikipedia for standard metrics, Stickler docs for ECARB@30). Available for all accuracy metrics, confidence metrics, confusion matrix components, error rates, and split classification metrics

**How It Works:**
- Backend stores confusion matrix values (TP, FP, TN, FN) from Stickler aggregation
- Backend computes confidence calibration metrics (AUROC, ECE, Brier) using Stickler v0.4.0+ ConfidenceCalculator
- UI calculates Accuracy, Precision, and Recall on-the-fly from confusion matrix values
- Confidence columns dynamically appear only when `confidenceMetrics` data is present
- Metrics displayed with 3 decimal precision (e.g., 0.850)

**Use Cases:**
- **Extraction Quality**: Identify which fields have low extraction accuracy
- **Confidence Calibration**: Discover poorly calibrated confidence predictions (high ECE = overconfident or underconfident)
- **Confidence Discrimination**: Check if confidence separates correct from incorrect predictions (low AUROC = poor discrimination)
- **Comparison**: Compare field-level performance across test runs
- **Prioritization**: Prioritize prompt engineering efforts on problematic fields or fields with poor confidence calibration
- **Tracking**: Track improvement in specific fields after configuration changes

#### Confidence Calibration Metrics (Stickler v0.4.0+)

https://github.com/user-attachments/assets/1d17ea33-f098-4d9e-a461-1113b9dc3ce9

The evaluation engine uses **Stickler v0.4.0** to compute confidence calibration metrics alongside traditional accuracy metrics. These metrics assess how well the model's confidence scores reflect actual correctness.

**What Are Confidence Calibration Metrics?**

When a model extracts a field with 90% confidence, ideally 90% of such predictions should be correct. Calibration metrics measure how closely confidence aligns with accuracy:

| Metric | What It Measures | Perfect Score | Interpretation |
|--------|------------------|---------------|----------------|
| **AUROC** | Discrimination: Can confidence separate correct from incorrect predictions? | 1.0 | 0.5 = random guessing, 1.0 = perfect discrimination |
| **ECE** | Calibration: How far off is confidence from actual accuracy? | 0.0 | 0.0 = perfectly calibrated, >0.1 = poorly calibrated |
| **Brier** | Overall quality: Mean squared error between confidence and correctness | 0.0 | 0.0 = perfect, 0.25 = random guessing, 1.0 = worst |
| **ECARB@30** | **The business metric**: Errors caught when reviewing 30% of data (sorted by confidence) | 100% (high gain) | Shows practical value - e.g., "89% (3.0x)" = reviewing lowest-confidence 30% catches 89% of errors, 3x better than random sampling |

**Example Scenarios:**

- **Good AUROC (0.95), Low ECE (0.03)**: Model confidences are well-calibrated and discriminate errors effectively
- **Good AUROC (0.92), High ECE (0.18)**: Model can distinguish errors but is systematically overconfident or underconfident
- **Poor AUROC (0.62), Any ECE**: Confidence scores don't correlate with correctness — unreliable even if calibrated
- **ECARB@30 = 89% (3.0x)**: **The business metric** - If you can only manually review 30% of extracted data, sorting by confidence (lowest first) lets you catch 89% of errors with 3x better efficiency than random sampling. This answers the practical question: "How much value does confidence-guided review provide?"

**How Calibration Metrics Are Computed:**

1. **Document Evaluation**: For each document, the evaluation service:
   - Flattens confidence scores from extraction results (unwraps wrapper keys like `Item_N`, `Record_N`)
   - Patches Stickler's comparison results with `field_path` for matching
   - Stores `stickler_comparison_result` with confidences in `results.json`

2. **Test Aggregation**: When viewing test results, the aggregation function:
   - Loads all `stickler_comparison_result` records for the test run
   - Computes calibration metrics (AUROC, ECE, Brier) using Stickler's `ConfidenceMetricsCalculator`
   - Computes ECAB (Error Capture at Budget) metrics using `BulkStructuredModelEvaluator` with `ErrorCaptureAtBudgetMetric`
   - Aggregates path-based keys (e.g., `LineItems[0].Rate`) to pattern-based keys (`LineItems.Rate`)
   - Merges ECAB metrics into the confidence metrics structure
   - Returns `confidence_metrics` field with overall and per-field calibration data

3. **UI Display**: The test results table:
   - Displays AUROC, ECE, Brier, and ECARB@30 columns alongside accuracy metrics
   - ECARB@30 shows as "XX% (Y.Yx)" format (e.g., "89% (3.0x)")
   - Shows metrics for both leaf fields (e.g., `LineItems.Rate`) and parent fields (e.g., `LineItems`)
   - Dynamically hides columns when no confidence data is available
   - Shows "N/A" for fields lacking confidence data

**Known Limitations:**

- **Overall Brier Score**: Stickler v0.4.0's bulk aggregator returns `null` for overall Brier score (implementation pending). However, **field-level Brier scores are computed** via scikit-learn in the test aggregation function and are available in the field metrics table.
- **Coverage**: Confidence metrics only available for fields where extraction service provided confidence scores
- **Backward Compatibility**: Test runs executed before Stickler v0.4.0 upgrade will not have confidence calibration data

**Architecture:**

- **Evaluation Service**: `lib/idp_common_pkg/idp_common/evaluation/service.py`
  - Flattens confidence scores and patches field_comparisons
- **Confidence Integration**: `lib/idp_common_pkg/idp_common/evaluation/confidence_integration.py`
  - Wrapper for Stickler's ConfidenceMetricsCalculator
- **Test Aggregation**: `patterns/unified/src/test_execution_aggregation_function/index.py`
  - Computes and aggregates calibration metrics across test run
- **UI Display**: `src/ui/src/components/test-studio/TestResults.tsx`
  - Renders confidence columns in field metrics table
