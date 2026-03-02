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

All datasets are deployed automatically with zero manual steps required.

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

Use with: `config_library/pattern-2/realkie-fcc-verified/config.yaml`

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

Use with: `config_library/pattern-2/ocr-benchmark/config.yaml`

---

### Common Features

Both datasets share these deployment characteristics:

- **Fully Automatic**: Complete deployment during stack creation with zero user effort
- **Version Control**: Dataset version pinned in CloudFormation, updateable via parameter
- **Smart Updates**: Skips re-download on stack updates unless version changes
- **Single Public Source**: Everything from HuggingFace - fully reproducible anywhere

- **First Deployment**: Adds ~5-10 minutes to stack deployment (downloads PDFs and metadata)
- **Stack Updates**: Near-instant (skips if version unchanged)
>>>>>>> develop
- **Version Updates**: Re-downloads and re-processes when DatasetVersion changes
### Deployment Time

- **First Deployment**: Adds ~15-20 minutes to stack deployment (downloads all three datasets)
- **Stack Updates**: Near-instant (skips if versions unchanged)
- **Version Updates**: Re-downloads and re-processes when DatasetVersion changes
=======
- **First Deployment**: Adds ~5-10 minutes to stack deployment (downloads PDFs and metadata)
- **Stack Updates**: Near-instant (skips if version unchanged)
>>>>>>> develop
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

Use with: `config_library/pattern-2/rvl-cdip/config.yaml`

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

Use with: `config_library/pattern-2/fake-w2/config.yaml`

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

#### TestSetZipExtractor Lambda
- **Location**: `src/lambda/test_set_zip_extractor/index.py`
- **Purpose**: Extracts and validates uploaded zip files
- **Features**: S3 event triggered extraction, file validation, status updates

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
- **Operations**: `getTestSets`, `addTestSet`, `addTestSetFromUpload`, `deleteTestSets`, `getTestRuns`, `startTestRun`, `compareTestRuns`

### Frontend Components

#### TestStudioLayout
- **Location**: `src/ui/src/components/test-studio/TestStudioLayout.jsx`
- **Purpose**: Main container with two-tab navigation and global state management

#### TestSets
- **Location**: `src/ui/src/components/test-studio/TestSets.jsx`
- **Purpose**: Manage test set collections
- **Features**: Pattern-based creation, zip upload, direct upload detection, dual polling (3s active, 30s discovery)

#### TestExecutions
- **Location**: `src/ui/src/components/test-studio/TestExecutions.jsx`
- **Purpose**: Unified interface combining TestRunner and TestResultsList
- **Features**: Test execution, results viewing, comparison, export, delete operations

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
   - **Description**: Optional description field to document the test set purpose
2. **Zip Upload**: Upload zip containing `input/` and `baseline/` folders
   - **Description**: Optional description field to document the test set purpose
3. **Direct Upload**: Files uploaded directly to TestSetBucket are auto-detected

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
- Status: COMPLETED (valid), FAILED (validation errors), PROCESSING (uploading)

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
- **COMPLETED**: Test finished successfully
- **FAILED**: Errors during processing

### Results Management
- Filter and paginate test runs
- Multi-select for comparison
- Navigate to detailed results view
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
  - **Accuracy breakdown** (precision, recall, F1-score, false alarm rate, false discovery rate)
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
