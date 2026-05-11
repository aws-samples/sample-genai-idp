# idpac Package Usage Guide

Python utilities for IDP Accelerator configuration optimization.

## Classes Overview

| Class | Purpose |
|-------|---------|
| `IDPConfig` | Read, modify, and compare IDP config.yaml files |
| `IDPACClient` | Interact with a deployed IDP stack (evaluations, downloads) |
| `IDPACDeployer` | Deploy stacks and upload test sets |
| `EvaluationResult` | Parse and display evaluation results |
| `Discovery` | Generate document schemas from samples via idp-cli |
| `DatasetAnalyzer` | Analyze test datasets (detect single vs multi-class vs packet-splitting) |
| `PacketSplittingDiscovery` | Discover schemas from packet-splitting datasets |

---

## DatasetAnalyzer

Analyze test datasets to determine if they are single-class, multi-class, or packet-splitting.

- **Single-class**: All documents are the same type (e.g., all invoices). Classification not needed.
- **Multi-class**: Documents are different types. Both classification AND extraction must be configured.
- **Packet-splitting**: Each input file contains multiple concatenated documents. Page-level classification + splitting + extraction.

```python
from idpac import DatasetAnalyzer

analyzer = DatasetAnalyzer('/path/to/dataset')

# Check dataset mode
if analyzer.is_packet_splitting():
    print(f"Packet-splitting dataset: {analyzer.get_class_names()}")
    sections = analyzer.get_sections_per_document()
    # {'packet_0001.pdf': [1, 2, 3], 'packet_0002.pdf': [1, 2]}
elif analyzer.is_multi_class():
    print(f"Multi-class dataset: {analyzer.get_class_names()}")
else:
    print(f"Single-class dataset")

# Get samples for schema discovery
samples = analyzer.get_samples_by_class(n=2)  # 2 samples per class
gt_paths = analyzer.get_ground_truth_by_class(n=2)

# Validate ground truth format
errors = analyzer.validate_ground_truth_format()
if errors:
    print(f"Ground truth issues: {errors}")

# Packet-splitting specific: get page indices per section
page_indices = analyzer.get_page_indices_by_section('packet_0001.pdf')
# {1: [0], 2: [1, 2], 3: [3, 4, 5]}
```

---

## IDPConfig

Manipulate IDP Accelerator config.yaml files with dot-notation access.

```python
from idpac import IDPConfig

# Load a config file
config = IDPConfig('idp-configs/my-config.yaml')

# Get field values (dot notation, supports array indices)
model = config.get('extraction.model')
first_class = config.get('classes.0.$id')
prompt = config.get('extraction.task_prompt')

# Set field values (dot notation, supports array indices)
config.set('extraction.model', 'us.anthropic.claude-sonnet-4-5-20250929-v1:0')
config.set('extraction.max_tokens', 65535)
config.set('classes.0.properties.Amount.x-aws-idp-evaluation-method', 'NUMERIC_EXACT')

# Print specific fields (avoids dumping entire config)
config.print(['extraction.model', 'extraction.task_prompt'])

# Print entire config
config.print()

# Save to file (original path or new path)
config.save()  # overwrites original
config.save('idp-configs/my-config-v2.yaml')  # new file

# Compare two configs
IDPConfig.print_comparison('idp-configs/old.yaml', 'idp-configs/new.yaml')
IDPConfig.print_comparison('old.yaml', 'new.yaml', name1='baseline', name2='optimized')
```

### System Defaults Support

```python
from idpac import IDPConfig

# Create config from system defaults
defaults = IDPConfig.from_defaults('pattern-2')  # pattern-1, pattern-2

# Merge user config with system defaults (fills in missing fields)
config = IDPConfig('idp-configs/minimal-config.yaml')
full_config = config.merge_with_defaults('pattern-2')

# Convert verbose config to minimal format (only non-default values)
config = IDPConfig('idp-configs/verbose-config.yaml')
minimal = config.to_minimal('pattern-2')
minimal.save('idp-configs/minimal-config.yaml')

# Show what differs from defaults
diffs = config.diff_from_defaults('pattern-2')
for diff in diffs:
    print(f"{diff['setting']}: {diff['values']}")
```

### Schema Validation

Validate that document class schemas have required attributes for evaluation. Missing `x-aws-idp-document-type` is the most common cause of 0% accuracy.

```python
from idpac import IDPConfig

config = IDPConfig('idp-configs/my-config.yaml')
result = config.validate()

print(result)  # Shows errors and warnings
print(f"Valid: {result.is_valid}")

# Example output for a bad config:
# ERRORS (1):
#   - classes[0] (Invoice): Missing 'x-aws-idp-document-type' - evaluation will skip this class (0% accuracy)
# WARNINGS (3):
#   - classes[0] (Invoice): Missing 'type: object'
#   - classes[0] (Invoice): Missing '$schema' declaration
#   - assessment.enabled=true with granular.enabled=true and array fields: May cause timeouts...
```

### Auto-Fix Common Issues

Automatically fix missing schema attributes. Only adds missing fields, never modifies existing values.

```python
from idpac import IDPConfig

config = IDPConfig('idp-configs/my-config.yaml')

# Fix all common schema issues (returns new instance, original unchanged)
fixed = config.auto_fix()
fixed.save('idp-configs/my-config-fixed.yaml')

# Or selectively apply fixes
fixed = config.auto_fix(['add_document_type'])  # only add x-aws-idp-document-type

# Available fixes (default = schema fixes only):
# - 'add_document_type': copies $id to x-aws-idp-document-type
# - 'add_schema': adds $schema declaration
# - 'add_type_object': adds type: object
# - 'fix_nullable_types': replaces type: ["string", "null"] with type: "string"
# - 'add_data_type': adds data_type annotation to leaf fields based on type
# - 'disable_assessment': sets assessment.enabled: false (not in default)
# - 'disable_summarization': sets summarization.enabled: false (not in default)

# For initial testing, disable assessment to avoid timeouts on large documents:
fixed = config.auto_fix(['add_document_type', 'add_schema', 'add_type_object', 
                         'disable_assessment', 'disable_summarization'])
```

### Schema Best Practices

See the module docstring in `idpac/config.py` for comprehensive documentation on:
- Required schema attributes (`x-aws-idp-document-type`, etc.)
- Per-field evaluation methods (`EXACT`, `NUMERIC_EXACT`, `FUZZY`, `LEVENSHTEIN`, etc.)
- Evaluation thresholds and weights
- Assessment vs Evaluation (runtime confidence vs accuracy measurement)
- Recommended starting configuration

### Multi-Class Support

Manage multiple document classes in a config:

```python
from idpac import IDPConfig

config = IDPConfig('idp-configs/my-config.yaml')

# List configured classes
class_names = config.get_class_names()  # ['INVOICE', 'RECEIPT', ...]

# Get a specific class schema
invoice_schema = config.get_class_by_name('INVOICE')

# Add a new class
config.add_class({
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    '$id': 'NEW_CLASS',
    'x-aws-idp-document-type': 'NEW_CLASS',
    'description': 'Description to help classifier distinguish this class',
    'type': 'object',
    'properties': { ... }
})

# Note: classification is automatically enabled when multiple classes are defined.
# Use classification.classificationMethod and classification.sectionSplitting to control behavior.
```

### Processing Mode (v0.5.0+ Unified Pattern)

Switch between BDA and Pipeline processing modes at runtime — no redeployment needed:

```python
from idpac import IDPConfig

config = IDPConfig('idp-configs/my-config.yaml')

# Pipeline mode (default): OCR with Textract, then classification + extraction with Bedrock LLM
config.set('use_bda', False)

# BDA mode: End-to-end processing with Bedrock Data Automation
config.set('use_bda', True)
```

### Classification Configuration

Classification settings for multi-class and packet-splitting datasets:

```python
from idpac import IDPConfig

config = IDPConfig('idp-configs/my-config.yaml')

# Classification method (default: multimodalPageLevelClassification)
# - 'multimodalPageLevelClassification': Per-page classification with images+text, BIO-like boundary detection
# - 'textbasedHolisticClassification': Sends all pages' text at once, LLM returns segment ranges (no images)
config.set('classification.classificationMethod', 'multimodalPageLevelClassification')

# Section splitting strategy (default: llm_determined)
# - 'llm_determined': LLM detects document boundaries via Start/Continue signals (default)
# - 'page': Each page becomes a separate section (use for multiple same-type forms)
# - 'disabled': Entire document as one section with majority voting
config.set('classification.sectionSplitting', 'llm_determined')

# Classification model (default: us.amazon.nova-pro-v1:0)
config.set('classification.model', 'us.amazon.nova-pro-v1:0')

# Context pages for page-level method (default: 0)
# Includes N pages before/after target page as context. Improves boundary detection but increases token cost.
config.set('classification.contextPagesCount', 1)

# Max pages to classify (default: 'ALL'). Values: 'ALL', '1', '2', '3', '5', '10'
# Limits how many pages are classified. Use for cost savings on large single-document files.
# Do NOT limit for packet-splitting (need all pages classified for boundary detection).
config.set('classification.maxPagesForClassification', 'ALL')

# NOTE: classification.enabled is NOT a valid field - classification is always
# enabled when multiple classes are defined. There is no way to disable it.
```

### Regex-Based Classification Bypass

Skip LLM calls for documents with predictable filenames or distinctive text markers:

```python
from idpac import IDPConfig

config = IDPConfig('idp-configs/my-config.yaml')

# Document name regex: if filename matches, ALL pages classified as this class (no LLM call)
config.set('classes.0.document_name_regex', '(?i).*(invoice|inv).*')

# Page content regex: if page text matches, that page classified as this class (page-level only)
config.set('classes.0.document_page_content_regex', '(?i)(invoice\\s+number|amount\\s+due)')
```

### Few-Shot Examples for Classification

Provide example documents to improve classification accuracy:

```python
from idpac import IDPConfig

config = IDPConfig('idp-configs/my-config.yaml')

# Add examples to a class (imagePath supports: file, directory, s3:// URI or prefix)
config.set('classes.0.examples', [
    {
        'classPrompt': "This is an example of the class 'Invoice'",
        'name': 'InvoiceExample1',
        'attributesPrompt': 'expected attributes are:\n    "invoice_number": "INV-001"',
        'imagePath': 'path/to/example-invoice.jpg'
    }
])

# Classification task_prompt MUST include {FEW_SHOT_EXAMPLES} placeholder to use examples
```

---

## IDPACClient

Interact with a deployed IDP Accelerator stack.

```python
from idpac import IDPACClient

# Connect to stack
client = IDPACClient('my-stack-name', region='us-east-1')
# With AWS profile:
client = IDPACClient('my-stack-name', region='us-east-1', profile='my-profile')
```

### Run Evaluations

```python
# Run inference WITHOUT ground truth (no test set needed)
result = client.run_inference(
    documents_dir='/path/to/documents/',
    config_version='v1',
    monitor=True,
    file_pattern='*.pdf',
    number_of_files=10  # optional: limit for quick testing
)
print(f"Batch ID: {result['batch_id']}")

# Download extraction results (works without ground truth)
result = client.download_results(
    batch_id='cli-batch-20260305-120000',
    output_dir='results/inference-output/',
    file_types='sections'  # 'sections', 'pages', 'summary', 'evaluation', or 'all'
)

# Upload config as a named version (fast - DynamoDB write, seconds not minutes)
result = client.upload_config(
    'idp-configs/my-config.yaml',
    config_version='v1',
    description='Switched to Claude Sonnet for extraction'
)
print(f"Status: {result['status']}")

# List recent evaluation runs (default: last 7 days)
evaluations = client.list_evaluations(time_period_hours=168)
for ev in evaluations:
    print(f"{ev['testRunId']}: {ev['status']} - {ev.get('overallAccuracy', 'N/A')}")

# Run evaluation on a test set with a specific config version
result = client.run_evaluation(
    test_set_id='my-test-set',
    context='Testing optimized extraction prompts',
    config_version='v1',
    monitor=True  # wait for completion
)
print(f"Batch ID: {result['batch_id']}")

# Get evaluation summary
# WARNING: Response is very large (100KB+) - use output_file or access specific keys
summary = client.get_evaluation_summary(
    batch_id='my-test-set-20260115-160907',
    output_file='results/summary.json'  # recommended: save to file
)
# Access only the keys you need - don't print the whole response!
print(f"Overall Accuracy: {summary.get('overallAccuracy')}")
print(f"Total Cost: ${summary.get('totalCost')}")
print(f"Status: {summary.get('status')}")
# Status values:
#   COMPLETE          - all files processed successfully (terminal)
#   PARTIAL_COMPLETE  - run finished but some files failed; check failedFiles (terminal)
#   FAILED            - entire run failed (terminal)
#   RUNNING           - still processing files (non-terminal, only state that means "in progress")
print(f"Files: {summary.get('completedFiles')}/{summary.get('filesCount')} ({summary.get('failedFiles')} failed)")

# Full response keys:
# - testRunId, testSetId, testSetName, status
# - filesCount, completedFiles, failedFiles
# - overallAccuracy (0.0-1.0), averageConfidence
# - weightedOverallScores (dict: filename -> accuracy) - LARGE for big test sets
# - accuracyBreakdown (per-class), splitClassificationMetrics
# - totalCost, costBreakdown
# - createdAt, completedAt, context
# - config (NOTE: this is the schema definition, NOT the test run config - VERY LARGE)

# Compare multiple evaluation runs
comparison = client.compare_evaluations(
    batch_ids=['batch-1', 'batch-2', 'batch-3'],
    output_file='results/comparison.json'
)

# Download all evaluation results for a batch
result = client.download_evaluation_results(
    batch_id='my-test-set-20260115-160907',
    output_dir='results/batch-output/'
)
print(f"Downloaded {result['stdout']}")
```

### Download Individual Files

```python
# Download results for a single document
result = client.download_single_document_results(
    batch_id='my-test-set-20260115-160907',
    filename='invoice-001.pdf',
    output_dir='investigation/'
)
print(f"Downloaded {result['count']} files")

# Download ground truth for a document
client.download_ground_truth(
    test_set_id='my-test-set',
    filename='invoice-001.pdf',
    output_path='investigation/invoice-001_gt.json'
)

# Download ground truth for all sections (packet-splitting)
result = client.download_ground_truth_all_sections(
    test_set_id='docsplit',
    filename='packet_0001.pdf',
    output_dir='investigation/'
)
print(f"Downloaded {result['count']} sections")
# result['sections'] = {1: 'path/to/1/result.json', 2: 'path/to/2/result.json', ...}

# Download raw input document from S3
client.download_input_document(
    document_id='my-test-set-20260115-160907/invoice-001.pdf',
    local_path='investigation/invoice-001.pdf'
)
```

### Config Operations (v0.4.12+)

```python
# Generate a config template
result = client.config_create(
    output='template.yaml',
    features='min',  # 'min', 'core', 'all'
    pattern='pattern-2',
    include_prompts=False
)

# Validate a config file
result = client.config_validate('idp-configs/my-config.yaml')
print(f"Valid: {result['valid']}")
print(result['stdout'])

# Download a specific config version from deployed stack
result = client.config_download(
    output='downloaded-config.yaml',
    config_version='v1',
    format='minimal'  # 'minimal' or 'full'
)

# Upload config as a named version (fast DynamoDB write)
result = client.upload_config(
    'idp-configs/my-config.yaml',
    config_version='v1',
    description='Initial config with Nova Pro extraction'
)
print(f"Status: {result['status']}")

# List all config versions on the stack
result = client.config_list()
print(result['stdout'])

# Activate a config version (sets it as default for new processing)
result = client.config_activate('v2')

# Delete a config version (cannot delete 'default' or active version)
result = client.config_delete('old-experiment')
```

---

## IDPACDeployer

Deploy IDP stacks and manage test sets.

```python
from idpac import IDPACDeployer

deployer = IDPACDeployer(region='us-east-1')
# With AWS profile:
deployer = IDPACDeployer(region='us-east-1', profile='my-profile')
```

### Deploy Stack

```python
result = deployer.deploy_stack(
    stack_name='my-idp-stack',
    admin_email='admin@example.com',
    wait=True
)
print(f"Status: {result['status']}")
if result['status'] == 'failed':
    print(f"Error: {result['stderr']}")
```

### Upload Test Set

```python
result = deployer.upload_test_set(
    stack_name='my-idp-stack',
    test_set_name='my-test-set',
    documents_dir='/path/to/documents/',
    baselines_dir='/path/to/baselines/',
    file_pattern='*.png'  # default: '*.pdf'
)
print(f"Status: {result['status']}")
```

### Destroy Stack

```python
result = deployer.destroy_stack(stack_name='my-idp-stack', wait=True)
print(f"Status: {result['status']}")
```

---

## EvaluationResult

Parse and display evaluation results.

```python
from idpac.evaluations import EvaluationResult

# Load aggregated test set summary
result = EvaluationResult.from_aggregated_file('results/summary.json')

# Print summary with top/bottom N documents by accuracy
result.print_aggregated_summary(top_bottom_n=5)

# Load individual document evaluation
result = EvaluationResult.from_individual_file('results/invoice-001/evaluation.json')

# Print individual document results
result.print_individual_summary(show_matched=False)  # only show mismatches
result.print_individual_summary(show_matched=True, max_value_len=100)
```

### Multi-Class Metrics

For multi-class datasets, analyze classification and per-class extraction accuracy:

```python
from idpac.evaluations import EvaluationResult

result = EvaluationResult.from_aggregated_file('results/summary.json')

# Print classification + per-class extraction accuracy
result.print_classification_summary()

# Get metrics programmatically
classification_acc = result.get_classification_accuracy()  # 0.0-1.0 or None
per_class = result.get_per_class_accuracy()  # {'INVOICE': 0.85, 'RECEIPT': 0.92, ...}
```

### Packet-Splitting Metrics

For packet-splitting datasets, analyze page-level and split accuracy:

```python
from idpac.evaluations import EvaluationResult

result = EvaluationResult.from_aggregated_file('results/summary.json')

# Print packet splitting metrics
result.print_split_summary()
# Packet Splitting Metrics:
#   Page Level Accuracy: 85.0%
#   Split Accuracy (without order): 75.0%
#   Split Accuracy (with order): 60.0%

# Get metrics programmatically
metrics = result.get_split_metrics()
# {'page_level_accuracy': 0.85, 'split_accuracy_without_order': 0.75, 'split_accuracy_with_order': 0.60}
```

Metric interpretation:
- **page_level_accuracy**: % of individual pages classified correctly
- **split_accuracy_without_order**: % of sections with correct pages + class (order ignored)
- **split_accuracy_with_order**: Above + correct page order within sections

---

## Discovery

Generate document class schemas from sample documents using `idp-cli discover` (local mode, no stack required).

```python
from idpac import Discovery

discovery = Discovery(region='us-east-1')
# With AWS profile:
discovery = Discovery(region='us-east-1', profile='my-profile')
# With custom model (defaults to Claude Opus for best schema quality):
discovery = Discovery(region='us-east-1', model_id='us.anthropic.claude-sonnet-4-6')
```

### Discover Schema

```python
# Discover schema from document (no ground truth)
schema = discovery.discover(document_path='samples/invoice.pdf')
print(f"Discovered {len(schema.get('properties', {}))} properties")

# Discover with ground truth (more accurate)
schema = discovery.discover(
    document_path='samples/invoice.pdf',
    ground_truth_path='baselines/invoice.pdf/sections/1/result.json'
)

# Discover and save to file
schema = discovery.discover_and_save(
    document_path='samples/invoice.pdf',
    output_path='schemas/invoice-schema.json',
    ground_truth_path='baselines/invoice.pdf/sections/1/result.json'
)
```

### Create Config from Discovery Output

Discovery outputs a complete JSON Schema with all required IDP attributes (`$schema`, `$id`, `x-aws-idp-document-type`, `type: object`). To create a config:

```python
from idpac import IDPConfig, Discovery

# 1. Discover schema from sample document
discovery = Discovery(region='us-east-1')
schema = discovery.discover(
    document_path='samples/invoice.pdf',
    ground_truth_path='baselines/invoice.pdf/sections/1/result.json'
)

# 2. Create config from defaults and add the schema
config = IDPConfig.from_defaults('pattern-2')
config.set('classes', [schema])

# 3. Validate before saving
result = config.validate()
if not result.is_valid:
    print(result)
    config = config.auto_fix()  # fix minor issues

config.save('idp-configs/my-config.yaml')
```

### Multi-Class Discovery

Discover schemas for multiple document classes at once:

```python
from idpac import DatasetAnalyzer, Discovery, IDPConfig

# 1. Analyze dataset to get samples per class
analyzer = DatasetAnalyzer('/path/to/dataset')
samples = analyzer.get_samples_by_class(n=1)
gt_paths = analyzer.get_ground_truth_by_class(n=1)

# 2. Discover schemas for all classes
discovery = Discovery(region='us-east-1')
schemas = discovery.discover_multi_class(samples, gt_paths)

# 3. Create multi-class config
config = IDPConfig.from_defaults('pattern-2')
for schema in schemas:
    config.add_class(schema)
config.save('idp-configs/multi-class-config.yaml')
```

---

## PacketSplittingDiscovery

Discover schemas from packet-splitting datasets where each input file contains multiple concatenated documents.

```python
from idpac.packet_discovery import PacketSplittingDiscovery

discovery = PacketSplittingDiscovery('/path/to/docsplit-dataset', region='us-east-1')
# With AWS profile:
discovery = PacketSplittingDiscovery('/path/to/docsplit-dataset', region='us-east-1', profile='my-profile')

# See what classes are in the dataset
classes = discovery.get_classes_with_samples()
print(f"Found {len(classes)} classes: {list(classes.keys())}")

# Discover schemas for all classes and create config (main entry point)
config = discovery.discover_and_create_config(
    output_path='workspace/config-discovered.yaml',
    samples_per_class=1
)
print(f"Created config with {len(config.get_class_names())} classes")
```

### How It Works

1. Scans ground truth to find all unique document classes across all packets
2. For each class, selects a representative section with its page range
3. Extracts pages from source PDF into temporary single-document files (using pypdfium2)
4. Transforms ground truth from packet format to flat discovery format
5. Runs `Discovery` on each temporary file
6. Aggregates schemas into a multi-class IDP config

### Lower-Level Methods

```python
# Extract specific pages from a packet into a new PDF
discovery.extract_section_as_document(
    packet_name='packet_0001.pdf',
    page_indices=[3, 4, 5],
    output_path='extracted_section.pdf'
)

# Transform section ground truth to discovery format
discovery.extract_section_ground_truth(
    packet_name='packet_0001.pdf',
    section_id=2,
    output_path='section_gt.json'
)

# Discover schemas without creating config
schemas = discovery.discover_all_classes(samples_per_class=1)
```

---

## Common Workflows

### Optimization Loop

```python
from idpac import IDPACClient, IDPConfig
from idpac.evaluations import EvaluationResult

client = IDPACClient('my-stack', region='us-east-1')

# 1. Upload baseline config and run evaluation
client.upload_config('idp-configs/baseline.yaml', config_version='v1', description='Baseline')
result = client.run_evaluation(test_set_id='test-set', context='Baseline', config_version='v1')
baseline_batch = result['batch_id']

# 2. Analyze results
summary = client.get_evaluation_summary(baseline_batch, 'results/baseline.json')
result = EvaluationResult.from_aggregated_file('results/baseline.json')
result.print_aggregated_summary(top_bottom_n=5)

# 3. Investigate failures
client.download_single_document_results(baseline_batch, 'failing-doc.pdf', 'investigation/')
client.download_ground_truth('test-set', 'failing-doc.pdf', 'investigation/gt.json')

# 4. Create optimized config
config = IDPConfig('idp-configs/baseline.yaml')
config.set('extraction.model', 'us.anthropic.claude-sonnet-4-5-20250929-v1:0')
# Modify prompts, schemas, etc.
config.save('idp-configs/optimized.yaml')

# 5. Upload optimized config and run evaluation (no stack reconfiguration needed!)
client.upload_config('idp-configs/optimized.yaml', config_version='v2', description='Sonnet extraction')
result = client.run_evaluation(test_set_id='test-set', context='Optimized model', config_version='v2')
optimized_batch = result['batch_id']

# 6. Compare results
comparison = client.compare_evaluations([baseline_batch, optimized_batch])
```

### Convert Verbose Config to Minimal

```python
from idpac import IDPConfig

# Load verbose config and strip to minimal
config = IDPConfig('idp-configs/verbose-config.yaml')
minimal = config.to_minimal('pattern-2')
minimal.save('idp-configs/minimal-config.yaml')

# Verify it's equivalent when merged with defaults
full = minimal.merge_with_defaults('pattern-2')
diffs = IDPConfig._compare(config, full, 'original', 'reconstructed')
print(f"Differences: {len(diffs)}")  # Should be 0 or minimal
```

### No Ground Truth Optimization Loop

When ground truth is not available, use `run_inference()` instead of `run_evaluation()`:

```python
from idpac import IDPACClient, IDPConfig, Discovery

client = IDPACClient('my-stack', region='us-east-1')

# 1. Discover schema from sample document (no ground truth needed)
discovery = Discovery(region='us-east-1')
schema = discovery.discover(document_path='samples/invoice.pdf')
config = IDPConfig.from_defaults('pattern-2')
config.set('classes', [schema])
config = config.auto_fix()
config.save('workspace/config-v1.yaml')

# 2. Upload config and run inference (no test set needed)
client.upload_config('workspace/config-v1.yaml', config_version='v1', description='Initial discovery')
result = client.run_inference(
    documents_dir='samples/',
    config_version='v1',
    number_of_files=10
)

# 3. Download extraction results for inspection
client.download_results(result['batch_id'], 'workspace/results-v1/', file_types='sections')

# 4. Inspect results qualitatively, improve config, repeat
config = IDPConfig('workspace/config-v1.yaml')
# ... make improvements based on inspection ...
config.save('workspace/config-v2.yaml')

client.upload_config('workspace/config-v2.yaml', config_version='v2', description='Improved prompts')
result = client.run_inference(documents_dir='samples/', config_version='v2', number_of_files=10)
client.download_results(result['batch_id'], 'workspace/results-v2/', file_types='sections')
```
