# Testing Best Practices for FiscalShield IDP Core

## MLOps Testing Philosophy

As an MLOps-oriented project, we follow these testing principles:

1. **Test Early, Test Often**: Write tests as you discover bugs or add features
2. **Regression Prevention**: Every bug fix should include a test that would have caught it
3. **Layered Testing**: Unit → Integration → End-to-End
4. **Fast Feedback**: Unit tests run in milliseconds, enabling rapid iteration
5. **CI/CD Integration**: All tests run automatically in the pipeline

## Test Organization Strategy

### Directory Structure

```
├── lib/idp_common_pkg/tests/          # Shared library tests
│   ├── unit/                          # Fast, isolated tests
│   │   ├── test_models.py            # Core data models
│   │   ├── test_document_user_id_extraction.py  # User ID handling
│   │   ├── classification/
│   │   ├── extraction/
│   │   └── ocr/
│   └── integration/                   # Tests requiring AWS services
│
├── tests/                             # Project-level tests
│   ├── unit/                          
│   │   └── lambda/                    # Lambda-specific tests
│   │       ├── create_document_resolver/
│   │       ├── workflow_tracker/
│   │       └── <lambda_name>/
│   └── integration/
│       └── pattern-2/
│           └── test_ocr_workflow.py
```

### Where to Put Tests

| Test Type | Location | Example |
|-----------|----------|---------|
| **Core library functions** | `lib/idp_common_pkg/tests/unit/` | Document model, utilities |
| **Service classes** | `lib/idp_common_pkg/tests/unit/<service>/` | OcrService, ClassificationService |
| **Lambda handlers** | `tests/unit/lambda/<lambda_name>/` | OCR Lambda, Classification Lambda |
| **Pattern workflows** | `tests/integration/pattern-<N>/` | End-to-end workflow tests |
| **Cross-service** | `tests/integration/` | AppSync + DynamoDB interactions |

## Test Types and When to Use Them

### 1. Unit Tests (Most Common)

**Location**: `lib/idp_common_pkg/tests/unit/` or `tests/unit/`

**Characteristics**:
- Test a single function/class in isolation
- Mock external dependencies (AWS services, databases, etc.)
- Run in < 100ms each
- Should comprise 80%+ of your test suite

**Example Use Cases**:
```python
# Testing utility functions
@pytest.mark.unit
def test_extract_user_id_from_valid_path():
    user_id = extract_user_id_from_object_key("users/123-456/file.pdf")
    assert user_id == "123-456"

# Testing business logic
@pytest.mark.unit
def test_document_classification_confidence_threshold():
    doc = Document.from_dict({"classification": "invoice", "confidence": 0.95})
    assert doc.meets_threshold(0.9) == True
```

### 2. Integration Tests

**Location**: `lib/idp_common_pkg/tests/integration/` or `tests/integration/`

**Characteristics**:
- Test interactions between components
- May use real AWS services (with moto mocking or test accounts)
- Run in seconds
- Should comprise 15-20% of your test suite

**Example Use Cases**:
```python
@pytest.mark.integration
def test_document_appsync_update_flow(dynamodb_table):
    """Test that document updates propagate to DynamoDB via AppSync"""
    # Create document
    doc = create_document(user_id="123")
    
    # Update via AppSync
    service.update_document(doc)
    
    # Verify in DynamoDB
    item = dynamodb_table.get_item(...)
    assert item["UserId"] == "123"
```

### 3. End-to-End Tests

**Location**: `tests/integration/pattern-<N>/`

**Characteristics**:
- Test complete workflows from S3 upload to final output
- Use real AWS services in test environments
- Run in minutes
- Should be minimal (5% of test suite)

**Example Use Cases**:
```python
@pytest.mark.integration
@pytest.mark.slow
def test_pattern2_complete_ocr_workflow(s3_bucket, test_pdf):
    """Test complete OCR workflow from upload to completion"""
    # Upload PDF
    s3.upload_file(test_pdf, bucket, "users/123/test.pdf")
    
    # Wait for workflow completion
    execution_arn = wait_for_workflow_start()
    result = wait_for_workflow_completion(execution_arn)
    
    # Verify outputs
    assert result["status"] == "COMPLETED"
    assert result["num_pages"] > 0
```

## Writing Tests for Bug Fixes

### Standard Workflow

When you discover a bug (like the `UserId` issue), follow this pattern:

1. **Write a Failing Test**
   ```python
   @pytest.mark.unit
   def test_document_has_user_id_for_appsync_update():
       """Regression test for: UserId required but not provided error"""
       doc = Document.from_dict({
           "input_key": "users/93c46832-90d1-7096-708c-e7d4f19e6695/invoice.pdf"
       })
       
       # This should pass after fix
       assert doc.user_id is not None
       assert doc.user_id == "93c46832-90d1-7096-708c-e7d4f19e6695"
   ```

2. **Fix the Bug**
   - Implement the fix in the code

3. **Verify Test Passes**
   ```bash
   pytest tests/unit/test_document_user_id_extraction.py -v
   ```

4. **Add Edge Cases**
   ```python
   @pytest.mark.unit
   def test_user_id_extraction_edge_cases():
       # Non-user path
       doc = Document.from_dict({"input_key": "documents/file.pdf"})
       assert doc.user_id is None
       
       # Explicit user_id takes precedence
       doc = Document.from_dict({
           "input_key": "users/123/file.pdf",
           "user_id": "explicit-456"
       })
       assert doc.user_id == "explicit-456"
   ```

## Test Naming Conventions

### File Names
- `test_<feature>.py` - Feature-specific tests
- `test_<class_name>.py` - Class-specific tests
- `test_<bug_id>_regression.py` - Regression tests for specific bugs

### Test Function Names

Use descriptive names that explain WHAT is being tested:

```python
# ✅ Good
def test_extracts_user_id_from_valid_user_scoped_path():
def test_returns_none_for_non_user_scoped_path():
def test_appsync_update_includes_user_id_for_user_scoped_documents():

# ❌ Bad
def test_user_id():
def test_path():
def test_function():
```

### Class Names

Group related tests in classes:

```python
class TestExtractUserIdFromObjectKey:
    """Tests for the extract_user_id_from_object_key utility"""
    
    def test_valid_path(self):
        ...
    
    def test_invalid_path(self):
        ...

class TestDocumentUserIdForAppSync:
    """Tests ensuring user_id is properly set for AppSync mutations"""
    
    def test_update_includes_user_id(self):
        ...
```

## Common Testing Patterns

### 1. Arrange-Act-Assert (AAA)

```python
def test_document_status_transition():
    # Arrange
    doc = Document(status=Status.QUEUED)
    
    # Act
    doc.status = Status.OCR
    
    # Assert
    assert doc.status == Status.OCR
```

### 2. Parametrized Tests

Test multiple inputs efficiently:

```python
@pytest.mark.parametrize("object_key,expected_user_id", [
    ("users/123-456/file.pdf", "123-456"),
    ("users/ABC-DEF/file.pdf", "ABC-DEF"),
    ("documents/file.pdf", None),
])
def test_various_paths(object_key, expected_user_id):
    user_id = extract_user_id_from_object_key(object_key)
    assert user_id == expected_user_id
```

### 3. Fixture Usage

Reuse common setup:

```python
# In conftest.py
@pytest.fixture
def sample_document():
    return Document(
        input_key="users/123/file.pdf",
        status=Status.QUEUED,
        num_pages=5
    )

# In test file
def test_document_processing(sample_document):
    result = process_document(sample_document)
    assert result.status == Status.COMPLETED
```

### 4. Mocking External Services

```python
from unittest.mock import Mock, patch

@patch('idp_common.appsync.client.AppSyncClient')
def test_document_update_without_aws(mock_client):
    service = DocumentAppSyncService(appsync_client=mock_client)
    doc = Document(input_key="users/123/file.pdf")
    
    service.update_document(doc)
    
    # Verify the client was called correctly
    mock_client.execute_mutation.assert_called_once()
```

## Lambda-Specific Testing

### Lambda Test Structure

For each Lambda function, create:

```
tests/unit/lambda/<lambda_name>/
├── conftest.py              # Lambda-specific fixtures
├── test_handler.py          # Main handler tests
├── test_<feature>.py        # Feature-specific logic
└── test_utilities.py        # Helper functions
```

### Example Lambda Test

```python
# tests/unit/lambda/ocr_function/test_handler.py

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, patch

# Add lambda to path
LAMBDA_DIR = Path(__file__).parent.parent.parent.parent / 'patterns' / 'pattern-2' / 'src' / 'ocr_function'
sys.path.insert(0, str(LAMBDA_DIR))

import index


@pytest.mark.unit
@pytest.mark.lambda
class TestOCRHandler:
    """Tests for OCR Lambda handler"""
    
    @patch('index.ocr.OcrService')
    @patch('index.create_document_service')
    def test_handler_extracts_user_id_from_event(
        self, mock_service, mock_ocr, mock_lambda_context
    ):
        """Should extract user_id from document in event"""
        event = {
            "document": {
                "input_key": "users/93c46832-90d1-7096-708c-e7d4f19e6695/invoice.pdf",
                "status": "QUEUED"
            }
        }
        
        result = index.handler(event, mock_lambda_context)
        
        # Verify user_id was extracted and available for AppSync update
        assert mock_service.return_value.update_document.called
        updated_doc = mock_service.return_value.update_document.call_args[0][0]
        assert updated_doc.user_id == "93c46832-90d1-7096-708c-e7d4f19e6695"
```

## Running Tests

### Quick Commands

```bash
# Run all unit tests
cd lib/idp_common_pkg && pytest tests/unit/ -v

# Run specific test file
pytest tests/unit/test_document_user_id_extraction.py -v

# Run specific test
pytest tests/unit/test_document_user_id_extraction.py::TestExtractUserIdFromObjectKey::test_extracts_user_id_from_valid_path -v

# Run tests matching pattern
pytest -k "user_id" -v

# Run with coverage
pytest tests/unit/ --cov=idp_common --cov-report=html

# Run fast (skip slow tests)
pytest -m "not slow" -v
```

### CI/CD Integration

Tests run automatically on:
- Pull request creation
- Commits to `dev` or `main` branches
- Pre-deployment validation

## Code Coverage Guidelines

### Targets
- **Overall**: 80% minimum, 90%+ target
- **Core libraries**: 90%+ required
- **Lambda handlers**: 80%+ required
- **Utilities**: 95%+ required

### Checking Coverage

```bash
# Generate coverage report
pytest tests/unit/ --cov=idp_common --cov-report=term-missing

# Generate HTML report
pytest tests/unit/ --cov=idp_common --cov-report=html
# View: open htmlcov/index.html
```

### What to Focus On

High-value coverage areas:
1. ✅ **Core business logic** (classification, extraction, user_id handling)
2. ✅ **Error handling paths** (invalid input, missing data, AWS errors)
3. ✅ **Data transformations** (Document.from_dict, to_dict, serialization)
4. ❌ Simple getters/setters (low value)
5. ❌ Configuration loading (tested via integration)

## Continuous Improvement

### When to Add Tests

Add tests when:
- ✅ Fixing a bug (regression test)
- ✅ Adding a new feature
- ✅ Refactoring existing code
- ✅ Code review identifies missing coverage
- ✅ Production issue occurs

### Test Maintenance

- Review test suite monthly
- Remove obsolete tests
- Update tests when requirements change
- Refactor slow tests to be faster
- Keep test data up-to-date

## Example: Complete Testing Workflow

### Scenario: User ID Extraction Bug

**1. Bug Discovered**
```
Error: UserId is required for document updates but was not provided
Object Key: users/93c46832-90d1-7096-708c-e7d4f19e6695/invoice7.pdf
```

**2. Create Test File**
```bash
touch lib/idp_common_pkg/tests/unit/test_document_user_id_extraction.py
```

**3. Write Failing Test**
```python
@pytest.mark.unit
def test_document_from_dict_extracts_user_id():
    doc = Document.from_dict({
        "input_key": "users/93c46832-90d1-7096-708c-e7d4f19e6695/invoice.pdf"
    })
    assert doc.user_id == "93c46832-90d1-7096-708c-e7d4f19e6695"
```

**4. Run Test (Should Fail)**
```bash
pytest tests/unit/test_document_user_id_extraction.py -v
# FAILED: AssertionError: assert None == '93c46832-90d1-7096-708c-e7d4f19e6695'
```

**5. Fix the Code**
```python
# In models.py
def extract_user_id_from_object_key(object_key: str) -> Optional[str]:
    if not object_key or not object_key.startswith("users/"):
        return None
    parts = object_key.split("/")
    return parts[1] if len(parts) >= 3 else None
```

**6. Run Test (Should Pass)**
```bash
pytest tests/unit/test_document_user_id_extraction.py -v
# PASSED
```

**7. Add Edge Cases**
```python
def test_user_id_extraction_edge_cases():
    # Non-user path
    assert extract_user_id_from_object_key("docs/file.pdf") is None
    # Empty
    assert extract_user_id_from_object_key("") is None
    # Invalid structure
    assert extract_user_id_from_object_key("users/only-one-part") is None
```

**8. Run All Tests**
```bash
pytest tests/unit/ -v
# All pass ✓
```

**9. Commit with Test**
```bash
git add lib/idp_common_pkg/idp_common/models.py
git add lib/idp_common_pkg/tests/unit/test_document_user_id_extraction.py
git commit -m "fix: Extract user_id from object key automatically

- Added extract_user_id_from_object_key() utility function
- Updated Document.from_dict() to auto-extract user_id
- Fixes: UserId required for document updates error
- Added comprehensive unit tests for regression prevention"
```

## Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Testing Best Practices](https://docs.python-guide.org/writing/tests/)
- [MLOps Testing Guide](https://ml-ops.org/content/testing)
- [AWS Lambda Testing](https://docs.aws.amazon.com/lambda/latest/dg/testing-functions.html)

## Questions?

See:
- `/tests/README.md` - Project test structure
- `/lib/idp_common_pkg/tests/README.md` - Library test structure
- Existing tests for examples
- Ask in team chat for guidance
