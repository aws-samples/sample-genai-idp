# Testing Documentation

Comprehensive testing infrastructure for the FiscalShield IDP Core project.

## 📁 Test Structure

```
tests/
├── conftest.py                    # Global fixtures (Cognito, DynamoDB, Lambda context)
├── pytest.ini                     # Pytest configuration (in project root)
├── requirements-dev.txt           # Testing dependencies (in project root)
│
├── unit/                          # Fast, isolated unit tests
│   └── lambda/
│       └── create_document_resolver/
│           ├── conftest.py        # Lambda-specific fixtures
│           ├── test_handler.py    # Handler function tests
│           ├── test_user_id_extraction.py  # User ID logic tests
│           └── test_utilities.py  # Utility function tests
│
├── integration/                   # Integration tests (slower, may need AWS)
│   └── test_document_workflow.py
│
├── events/                        # Sample test events
│   ├── create_document_event.json
│   └── create_document_with_expiry_event.json
│
└── fixtures/                      # Shared test fixtures/data
```

## 🚀 Quick Start

### Install Dependencies

```bash
# Install test dependencies
pip install -r requirements-dev.txt
```

### Run Tests

```bash
# From project root
./run_tests.sh                                    # Run all unit tests
./run_tests.sh unit                               # Run unit tests
./run_tests.sh lambda create_document_resolver    # Test specific lambda
./run_tests.sh coverage                           # With coverage report
```

## 📊 Test Commands

### Basic Testing

```bash
# All unit tests
./run_tests.sh unit

# Integration tests
./run_tests.sh integration

# Specific lambda
./run_tests.sh lambda create_document_resolver

# All tests (unit + integration)
./run_tests.sh all
```

### Coverage Reports

```bash
# Terminal coverage report
./run_tests.sh coverage

# HTML coverage report
./run_tests.sh html
# Opens: htmlcov/index.html

# Coverage for specific lambda
./run_tests.sh lambda create_document_resolver --cov
```

### Advanced Options

```bash
# Parallel execution (faster)
./run_tests.sh parallel

# Verbose output
./run_tests.sh unit -v

# Watch mode (rerun on changes)
./run_tests.sh watch

# List available markers
./run_tests.sh markers
```

## 🏷️ Test Markers

Organize and filter tests using markers:

```bash
# Run only lambda tests
pytest -m lambda

# Run only unit tests
pytest -m unit

# Run smoke tests
pytest -m smoke

# Exclude slow tests
pytest -m "not slow"
```

### Available Markers

- `unit` - Fast, isolated unit tests
- `integration` - Integration tests (may require AWS)
- `slow` - Slow-running tests
- `lambda` - Lambda function tests
- `api` - API Gateway tests
- `dynamodb` - DynamoDB tests
- `s3` - S3 tests
- `cognito` - Cognito authentication tests
- `smoke` - Quick validation tests

## 📝 Writing Tests

### Test File Organization

Follow this naming convention:

```
tests/unit/lambda/<lambda_name>/
├── test_handler.py              # Main handler tests
├── test_<feature>.py            # Feature-specific tests
└── test_utilities.py            # Helper/utility tests
```

### Using Fixtures

Global fixtures are available from `tests/conftest.py`:

```python
def test_with_fixtures(mock_lambda_context, valid_cognito_uuid, mock_dynamodb_table):
    """Use fixtures from conftest.py"""
    # Fixtures are automatically available
    assert valid_cognito_uuid is not None
```

Lambda-specific fixtures from `tests/unit/lambda/<lambda_name>/conftest.py`:

```python
def test_document_creation(valid_create_document_event, mock_lambda_context):
    """Use lambda-specific fixtures"""
    result = handler(valid_create_document_event, mock_lambda_context)
    assert 'UserId' in result
```

### Test Event Files

Load test events from JSON files:

```python
def test_with_event_file(event_loader):
    """Load event from tests/events/"""
    event = event_loader('create_document_event')
    result = handler(event, context)
    assert result is not None
```

### Example Test Structure

```python
"""
Tests for <feature_name>.

Brief description of what this test module covers.
"""
import pytest
from unittest.mock import Mock, patch
import index


@pytest.mark.unit
@pytest.mark.lambda
class TestFeatureName:
    """Tests for specific feature."""
    
    def test_happy_path(self, valid_event, mock_context):
        """Should handle the happy path correctly."""
        # Arrange
        expected = "success"
        
        # Act
        result = index.function_under_test(valid_event, mock_context)
        
        # Assert
        assert result == expected
    
    def test_error_case(self, invalid_event):
        """Should raise error for invalid input."""
        with pytest.raises(ValueError, match="Expected error message"):
            index.function_under_test(invalid_event, {})
```

## 🎯 Adding Tests for New Lambdas

When creating a new lambda, follow this structure:

```bash
# 1. Create test directory
mkdir -p tests/unit/lambda/<new_lambda_name>

# 2. Create test files
touch tests/unit/lambda/<new_lambda_name>/__init__.py
touch tests/unit/lambda/<new_lambda_name>/conftest.py
touch tests/unit/lambda/<new_lambda_name>/test_handler.py

# 3. Add sample event
touch tests/events/<new_lambda_name>_event.json

# 4. Run tests
./run_tests.sh lambda <new_lambda_name>
```

### Template for New Lambda Tests

**conftest.py:**
```python
"""Fixtures for <lambda_name> tests."""
import pytest
import sys
from pathlib import Path

# Add lambda to path
LAMBDA_DIR = Path(__file__).parent.parent.parent.parent.parent / 'src' / 'lambda' / '<lambda_name>'
sys.path.insert(0, str(LAMBDA_DIR))


@pytest.fixture
def valid_event():
    """Valid event for this lambda."""
    return {
        # Your event structure
    }
```

**test_handler.py:**
```python
"""Tests for <lambda_name> handler."""
import pytest
from unittest.mock import Mock, patch
import index


@pytest.mark.unit
@pytest.mark.lambda
class TestHandler:
    """Tests for main handler function."""
    
    @patch('index.boto3')
    def test_handler_success(self, mock_boto3, valid_event, mock_lambda_context):
        """Should process event successfully."""
        # Your test here
        pass
```

## 📈 Coverage Requirements

- **Minimum coverage:** 80% (configured in pytest.ini)
- **Target coverage:** 90%+
- **View coverage:** Open `htmlcov/index.html` after running coverage tests

```bash
# Generate coverage report
./run_tests.sh coverage

# View in browser
xdg-open htmlcov/index.html  # Linux
open htmlcov/index.html      # macOS
```

## 🔍 Debugging Tests

### Run Single Test

```bash
pytest tests/unit/lambda/create_document_resolver/test_handler.py::TestHandlerDocumentCreation::test_creates_user_scoped_partition_key -v
```

### Show Print Statements

```bash
pytest tests/unit/ -v -s
```

### Drop into Debugger on Failure

```bash
pytest tests/unit/ --pdb
```

### Show Local Variables

```bash
pytest tests/unit/ -l
```

## 🚦 CI/CD Integration

Add to your CI/CD pipeline:

```yaml
# GitHub Actions example
- name: Install dependencies
  run: pip install -r requirements-dev.txt

- name: Run unit tests
  run: ./run_tests.sh unit

- name: Run coverage
  run: ./run_tests.sh coverage

- name: Upload coverage
  uses: codecov/codecov-action@v3
  with:
    file: ./coverage.xml
```

## 📚 Best Practices

1. **Fast Tests**: Unit tests should run in milliseconds
2. **Isolated**: Each test should be independent
3. **Descriptive**: Use clear test names that describe behavior
4. **Arrange-Act-Assert**: Follow AAA pattern
5. **Mock External Services**: Always mock AWS services in unit tests
6. **Use Fixtures**: Reuse common test setup via fixtures
7. **Test Error Paths**: Don't just test happy paths
8. **Coverage ≠ Quality**: Aim for meaningful tests, not just coverage

## 🆘 Troubleshooting

### Import Errors

```bash
# Ensure pytest is run from project root
cd /home/josian/git/fiscalshield-idp-core
./run_tests.sh unit
```

### Module Not Found

Check that `pytest.ini` has correct `pythonpath`:
```ini
[pytest]
pythonpath = src/lambda
```

### Fixture Not Found

Ensure fixture is in:
- `tests/conftest.py` (global)
- `tests/unit/lambda/<name>/conftest.py` (lambda-specific)

### Slow Tests

```bash
# Run with timing info
pytest tests/unit/ --durations=10

# Run in parallel
./run_tests.sh parallel
```

## 📖 Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Moto (AWS Mocking)](https://docs.getmoto.org/)
- [Coverage.py](https://coverage.readthedocs.io/)
