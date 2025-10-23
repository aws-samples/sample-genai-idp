# Tests for create_document_resolver Lambda

This directory contains comprehensive unit and integration tests for the `create_document_resolver` Lambda function.

## Test Structure

```
tests/
├── __init__.py           # Package marker
├── conftest.py           # Pytest fixtures and configuration
├── test_index.py         # Main test suite
├── requirements-test.txt # Test dependencies
└── README.md            # This file
```

## Running Tests

### Install Test Dependencies

```bash
# From the lambda directory
cd /home/josian/git/fiscalshield-idp-core/src/lambda/create_document_resolver

# Install test dependencies
pip install -r tests/requirements-test.txt
```

### Run All Tests

```bash
# Run all tests with verbose output
pytest tests/ -v

# Run with coverage report
pytest tests/ -v --cov=. --cov-report=term-missing

# Run with coverage and generate HTML report
pytest tests/ -v --cov=. --cov-report=html
```

### Run Specific Test Classes or Methods

```bash
# Run only user ID extraction tests
pytest tests/test_index.py::TestUserIdExtraction -v

# Run only handler tests
pytest tests/test_index.py::TestHandler -v

# Run a specific test
pytest tests/test_index.py::TestHandler::test_handler_creates_user_scoped_key -v
```

### Run with Different Verbosity Levels

```bash
# Quiet mode (only show test summary)
pytest tests/ -q

# Very verbose (show full diff on failures)
pytest tests/ -vv

# Show local variables on failure
pytest tests/ -l
```

## Test Coverage

The test suite covers:

### ✅ User ID Extraction
- Extracting from `username` field
- Extracting from `sub` field (fallback)
- Preferring `username` over `sub`
- Handling missing user IDs
- Handling missing identity context

### ✅ User ID Validation
- Valid UUID format
- Uppercase UUIDs
- Non-UUID formats (with warnings)

### ✅ Handler Integration
- Creating user-scoped partition keys
- Using both `username` and `sub`
- Deleting existing document entries
- Handling deletion failures gracefully
- Handling get_item failures gracefully
- Input validation (ObjectKey, QueuedTime, input data)
- Authentication validation
- Including optional fields (ExpiresAfter)
- Shard calculation integration

### ✅ Utilities
- DecimalEncoder JSON serialization

## Continuous Integration

Add this to your CI/CD pipeline:

```yaml
# Example GitHub Actions workflow
- name: Run Lambda Tests
  run: |
    cd src/lambda/create_document_resolver
    pip install -r tests/requirements-test.txt
    pytest tests/ -v --cov=. --cov-report=xml --cov-fail-under=80
```

## Writing New Tests

1. **Use fixtures** from `conftest.py` to reduce boilerplate
2. **Mock external dependencies** (DynamoDB, other AWS services)
3. **Test error paths** not just happy paths
4. **Use descriptive test names** that explain what is being tested
5. **Group related tests** in classes

### Example Test Template

```python
@patch('index.dynamodb')
def test_handler_new_feature(self, mock_dynamodb, valid_event, mock_context):
    """Should handle new feature correctly."""
    # Setup
    mock_table = Mock()
    mock_dynamodb.Table.return_value = mock_table
    mock_table.some_method.return_value = expected_value
    
    # Execute
    result = index.handler(valid_event, mock_context)
    
    # Assert
    assert result['field'] == expected_value
    mock_table.some_method.assert_called_once()
```

## Troubleshooting

### Import Errors
If you get import errors, ensure you're running pytest from the lambda directory:
```bash
cd /home/josian/git/fiscalshield-idp-core/src/lambda/create_document_resolver
pytest tests/ -v
```

### Mock Issues
If mocks aren't working, check that you're patching the right location:
- Patch where it's used: `@patch('index.dynamodb')`
- Not where it's defined: `@patch('boto3.resource')`

### Environment Variables
Some tests require environment variables. These are set in the test decorators:
```python
@patch.dict(os.environ, {'TRACKING_TABLE_NAME': 'test-table'})
```
