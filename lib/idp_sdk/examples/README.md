# IDP SDK Examples

This directory contains example scripts demonstrating how to use the IDP SDK.

## Prerequisites

1. Install the IDP SDK in development mode:
   ```bash
   cd lib/idp_sdk
   pip install -e .
   ```

2. Configure AWS credentials with access to your IDP stack.

## Available Examples

### 1. Basic Processing (`basic_processing.py`)

**Requires: Deployed IDP stack**

Demonstrates the most common workflow: submit documents, monitor progress, download results.

```bash
# Process local directory
python basic_processing.py \
    --stack-name idp-stack-01 \
    --directory ./samples \
    --output-dir /tmp/results

# Process from S3
python basic_processing.py \
    --stack-name idp-stack-01 \
    --s3-uri s3://my-bucket/documents/ \
    --output-dir /tmp/results

# Process from manifest
python basic_processing.py \
    --stack-name idp-stack-01 \
    --manifest ./my-manifest.csv \
    --output-dir /tmp/results
```

### 2. Manifest Operations (`manifest_operations.py`)

**Does NOT require a deployed stack**

Demonstrates manifest generation and validation.

```bash
# Generate manifest from directory
python manifest_operations.py --directory ./samples --output manifest.csv

# Generate with baselines for evaluation
python manifest_operations.py \
    --directory ./samples \
    --baseline-dir ./baselines \
    --output manifest.csv

# Validate existing manifest
python manifest_operations.py --validate-only ./manifest.csv
```

### 3. Configuration Operations (`config_operations.py`)

**Create/Validate: No stack required | Download/Upload: Requires stack**

Demonstrates configuration creation, validation, download, and upload.

```bash
# Create minimal configuration template
python config_operations.py create --features min --pattern pattern-2

# Create config with all features
python config_operations.py create --features all --output my-config.yaml

# Validate a configuration file
python config_operations.py validate my-config.yaml --pattern pattern-2

# Download config from deployed stack
python config_operations.py download --stack-name idp-stack-01 --output current-config.yaml

# Upload config to deployed stack
python config_operations.py upload my-config.yaml --stack-name idp-stack-01
```

### 4. Workflow Control (`workflow_control.py`)

**Requires: Deployed IDP stack**

Demonstrates workflow management: listing batches, getting status, rerunning documents, stopping workflows.

```bash
# List recent batches
python workflow_control.py --stack-name idp-stack-01 list --limit 10

# Get batch status
python workflow_control.py --stack-name idp-stack-01 status --batch-id my-batch-123

# Get single document status
python workflow_control.py --stack-name idp-stack-01 status --document-id "batch/doc.pdf"

# Rerun a batch from extraction step
python workflow_control.py --stack-name idp-stack-01 rerun --batch-id my-batch-123 --step extraction

# Stop all running workflows
python workflow_control.py --stack-name idp-stack-01 stop

# Show stack resources
python workflow_control.py --stack-name idp-stack-01 resources
```

### 5. Lambda Function (`lambda_function.py`)

Example Lambda function that uses the SDK for document processing automation.

See the file for deployment instructions and IAM requirements.

## SDK Quick Reference

```python
from idp_sdk import IDPClient

# Create client with default stack
client = IDPClient(stack_name="my-stack", region="us-west-2")

# Or create client and specify stack per-operation
client = IDPClient()

# Batch operations (require stack)
result = client.batch.run(source="./documents/")
status = client.batch.get_status(batch_id=result.batch_id)
client.batch.download_results(batch_id=result.batch_id, output_dir="./results")

# Config operations (no stack required)
config = client.config.create(features="min")
validation = client.config.validate(config_file="my-config.yaml")

# Manifest operations (no stack required)
manifest = client.manifest.generate(directory="./docs/")
```

## Common Patterns

### Wait for Processing to Complete

```python
import time
from idp_sdk import IDPClient

client = IDPClient(stack_name="my-stack")
result = client.batch.run(source="./documents/")

# Poll until complete
while True:
    status = client.batch.get_status(batch_id=result.batch_id)
    print(f"Progress: {status.completed}/{status.total}")
    
    if status.all_complete:
        print(f"Done! Success rate: {status.success_rate:.1%}")
        break
    
    time.sleep(10)

# Download results
client.batch.download_results(batch_id=result.batch_id, output_dir="./results")
```

### Process with Custom Configuration

```python
from idp_sdk import IDPClient

client = IDPClient(stack_name="my-stack")

# Upload custom config first
client.config.upload(config_file="my-config.yaml")

# Then process documents (they will use the uploaded config)
result = client.batch.run(directory="./documents/")
```

### Error Handling

```python
from idp_sdk import (
    IDPClient, 
    IDPConfigurationError,
    IDPProcessingError,
    IDPStackError,
    IDPResourceNotFoundError
)

client = IDPClient(stack_name="my-stack")

try:
    result = client.batch.run(source="./documents/")
except IDPConfigurationError as e:
    print(f"Configuration error: {e}")
except IDPProcessingError as e:
    print(f"Processing error: {e}")
except IDPStackError as e:
    print(f"Stack error: {e}")
except IDPResourceNotFoundError as e:
    print(f"Resource not found: {e}")
```

## Available Methods

| Method | Requires Stack | Description |
|--------|----------------|-------------|
| `batch.run()` | Yes | Submit documents for processing |
| `batch.get_status()` | Yes | Get batch/document status |
| `batch.list()` | Yes | List recent batch jobs |
| `batch.download_results()` | Yes | Download processing results |
| `batch.rerun()` | Yes | Rerun documents from a step |
| `batch.stop_workflows()` | Yes | Stop all running workflows |
| `document.get_status()` | Yes | Get single document status |
| `document.get_metadata()` | Yes | Get document metadata |
| `document.delete()` | Yes | Delete document and data |
| `stack.get_resources()` | Yes | Get stack resource details |
| `stack.deploy()` | Optional* | Deploy/update stack |
| `stack.delete()` | Yes | Delete stack |
| `config.create()` | No | Create config template |
| `config.validate()` | No | Validate config file |
| `config.download()` | Yes | Download configuration |
| `config.upload()` | Yes | Upload configuration |
| `manifest.generate()` | No | Generate manifest from files |
| `manifest.validate()` | No | Validate manifest file |
| `search.query()` | Yes | Query knowledge base |
| `evaluation.run()` | Yes | Run evaluation against baselines |
| `assessment.get_confidence()` | Yes | Get extraction confidence |
| `testing.load_test()` | Yes | Run load test |

*Deploy can create a new stack (no existing stack required)