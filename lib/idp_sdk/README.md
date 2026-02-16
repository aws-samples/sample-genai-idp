# IDP SDK

Python SDK for programmatic access to IDP Accelerator capabilities.

## Installation

```bash
# From local development
pip install -e ./lib/idp_sdk

# Or with uv
uv pip install -e ./lib/idp_sdk
```

## Quick Start

```python
from idp_sdk import IDPClient

# Initialize client (stack_name optional for some operations)
client = IDPClient(stack_name="my-idp-stack", region="us-west-2")

# Process documents from a directory
result = client.run_inference(source="./documents/")
print(f"Batch ID: {result.batch_id}")

# Monitor progress
status = client.get_status(batch_id=result.batch_id)
print(f"Completed: {status.completed}/{status.total}")

# Download results
client.download_results(
    batch_id=result.batch_id,
    output_dir="./results"
)
```

## Configuration Version Management

The SDK supports configuration versioning for better deployment control:

```python
from idp_sdk import IDPClient

client = IDPClient(stack_name="my-idp-stack")

# Upload configuration to specific version
client.config_upload(
    config_file="config.yaml",
    config_version="production-v2",
    description="Updated model settings for new document types"
)

# Download specific configuration version
client.config_download(
    config_version="production-v2",
    output="downloaded-config.yaml"
)

# Process documents using specific version
result = client.run_inference(
    source="./documents/",
    config_version="production-v2"
)
```

## Stack-Independent Operations

Some operations don't require a deployed stack:

```python
from idp_sdk import IDPClient

client = IDPClient()  # No stack required

# Generate manifest
manifest = client.generate_manifest(
    directory="./documents/",
    output="manifest.csv"
)

# Create configuration template
config = client.config_create(
    features="min",
    pattern="pattern-2",
    output="config.yaml"
)

# Validate configuration
result = client.config_validate(config_file="./config.yaml")
if not result.valid:
    print(f"Errors: {result.errors}")
```

## Documentation

See [docs/idp-sdk.md](../../docs/idp-sdk.md) for complete documentation.

## Examples

- [basic_processing.py](examples/basic_processing.py) - Basic document processing workflow
- [config_operations.py](examples/config_operations.py) - Configuration management with versioning
- [lambda_function/](examples/lambda_function/) - Complete Lambda function example with SAM template