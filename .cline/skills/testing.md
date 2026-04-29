# Testing & QA — GenAI IDP Accelerator

## Test Framework
- **Framework**: pytest
- **Markers**: `@pytest.mark.unit`, `@pytest.mark.integration`
- **Default**: Unit tests only (`addopts = -m "not integration"`)
- **AWS Mocking**: `moto` (`@mock_aws` decorator)
- **Mocking**: `unittest.mock` (`MagicMock`, `patch`)
- **Coverage**: `pytest-cov` for coverage reports

## Test Locations
| Package | Test Directory | Command |
|---------|---------------|---------|
| `idp_common` | `lib/idp_common_pkg/tests/` | `cd lib/idp_common_pkg && make test` |
| `idp_cli` | `lib/idp_cli_pkg/tests/` | `cd lib/idp_cli_pkg && pytest -v` |
| `idp_sdk` | `lib/idp_sdk/tests/` | `cd lib/idp_sdk && pytest -m "not integration" -v` |
| Capacity Lambda | `src/lambda/calculate_capacity/` | `make test-capacity` |
| Config Library | `config_library/test_config_library.py` | `make test-config-library` |

## Test File Structure
Tests mirror the module structure:
```
tests/
├── conftest.py              # Global setup (AWS creds, module mocks)
├── unit/
│   ├── agents/              # Mirrors idp_common/agents/
│   ├── assessment/          # Mirrors idp_common/assessment/
│   ├── classification/      # Mirrors idp_common/classification/
│   ├── config/              # Mirrors idp_common/config/
│   ├── extraction/          # Mirrors idp_common/extraction/
│   ├── ocr/                 # Mirrors idp_common/ocr/
│   └── ...                  # 50+ test files
├── integration/             # Integration tests (require AWS)
└── resources/               # Test data / fixtures
```

## conftest.py Pattern
The global conftest.py does critical setup:
```python
import os, sys
from unittest.mock import MagicMock

# Set AWS credentials BEFORE any boto3 imports
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

# Mock heavy external dependencies that aren't needed in unit tests
sys.modules["strands"] = MagicMock()
sys.modules["strands.agent"] = MagicMock()
sys.modules["bedrock_agentcore"] = MagicMock()
# ... more module mocks
```

## Writing Unit Tests
### Class-Based Pattern (preferred)
```python
import pytest
import boto3
from moto import mock_aws
from idp_common.models import Document, Status

class TestMyFeature:
    def setup_method(self):
        """Set up test fixtures."""
        self.document = Document(
            id="test-doc-123",
            input_bucket="input-bucket",
            input_key="test.pdf",
            status=Status.QUEUED,
        )
        self.bucket = "test-working-bucket"

    @pytest.mark.unit
    @mock_aws
    def test_happy_path(self):
        """Test the normal processing flow."""
        s3_client = boto3.client("s3", region_name="us-east-1")
        s3_client.create_bucket(Bucket=self.bucket)
        # ... test logic
        assert result["status"] == "success"

    @pytest.mark.unit
    def test_error_handling(self):
        """Test error cases."""
        with pytest.raises(ValueError, match="Invalid document"):
            process_document(None)
```

### Function-Based Tests
```python
@pytest.mark.unit
def test_specific_function():
    result = my_function(input_data)
    assert result == expected
```

## Moto Usage
Always use `@mock_aws` decorator:
```python
from moto import mock_aws

@mock_aws
def test_s3_operation():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")
    # ... operations happen against moto mock
```

## Local Lambda Testing
```bash
cd patterns/unified/
sam build
sam local invoke OCRFunction -e ../../testing/OCRFunction-event.json --env-vars ../../testing/env.json
```

## Sample Documents
Available in `samples/` directory for testing document processing.

## Evaluation Framework
For document processing accuracy:
- Baseline data in S3 Evaluation Baseline bucket
- Per-field evaluation methods: `EXACT`, `NUMERIC_EXACT`, `FUZZY`
- `stickler-eval` library for metrics
- Run via CLI: `idp-cli run-evaluation --stack-name <name>`

## Test Studio (Web UI)
Interactive testing via the web UI — upload documents, compare results across config versions.

## Commands Reference
```bash
make test                    # All tests
make test-cli                # CLI tests only
make test-config-library     # Config validation only
make test-capacity           # Capacity planning tests
make test-capacity-coverage  # With coverage report

# Direct pytest invocations
cd lib/idp_common_pkg
make test-unit               # Unit tests only
make test-integration        # Integration tests (needs AWS)
pytest -m "unit" -k "test_extraction"   # Filter by name
pytest -v --tb=short         # Verbose with short tracebacks
pytest --cov=idp_common --cov-report=html   # Coverage report
```
