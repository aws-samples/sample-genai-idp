# Running User-Scoping Tests

## Quick Start

The `run_tests.sh` script has been updated to include dedicated commands for testing user-scoped document tracking.

### Run All User-Scoping Tests

```bash
./run_tests.sh user-scoping
```

or the shorter alias:

```bash
./run_tests.sh scoping
```

This will run three test suites in isolation:
1. User-scoped document flow tests
2. DocumentDynamoDBService user-scoping tests
3. create_document_resolver tests (with user-scoping verification)

## Individual Test Commands

### Run Specific Test Suite

```bash
# Just the document flow integration tests
./run_tests.sh unit tests/unit/test_user_scoped_document_flow.py

# Just the DocumentDynamoDBService tests
./run_tests.sh unit lib/idp_common_pkg/tests/unit/dynamodb/test_service_user_scoping.py

# Just the create_document_resolver tests
./run_tests.sh lambda create_document_resolver
```

### Run with Verbose Output

```bash
./run_tests.sh user-scoping -v
./run_tests.sh user-scoping -vv  # Extra verbose
```

### Run with Coverage

```bash
# Run all tests with coverage
./run_tests.sh coverage

# Run specific test with coverage
pytest tests/unit/test_user_scoped_document_flow.py -v \
  --cov=lib/idp_common_pkg/idp_common/dynamodb/service \
  --cov-report=html
```

### Run in Parallel

```bash
./run_tests.sh parallel
```

## Test Isolation

The test runner automatically handles module isolation for lambda tests to prevent Python module caching issues. Each lambda test directory is run separately:

```bash
# This runs automatically when you use:
./run_tests.sh all
```

The new user-scoping tests are also included in the full test run.

## Available Commands

```bash
./run_tests.sh unit                     # All unit tests
./run_tests.sh integration              # Integration tests
./run_tests.sh lambda <name>            # Specific lambda
./run_tests.sh user-scoping             # User-scoping tests only
./run_tests.sh coverage                 # With coverage report
./run_tests.sh parallel                 # Parallel execution
./run_tests.sh help                     # Show all options
```

## Test Files Location

- **Integration Flow Tests**: `tests/unit/test_user_scoped_document_flow.py`
- **Service Layer Tests**: `lib/idp_common_pkg/tests/unit/dynamodb/test_service_user_scoping.py`
- **Lambda Resolver Tests**: `tests/unit/lambda/create_document_resolver/test_handler.py`

## Expected Output

When running user-scoping tests, you should see:

```
Running user-scoping tests...
Testing user-scoped document flow...
tests/unit/test_user_scoped_document_flow.py::TestUserScopedDocumentLifecycle::test_complete_flow_single_user PASSED
tests/unit/test_user_scoped_document_flow.py::TestUserScopedDocumentLifecycle::test_multi_user_isolation PASSED
...

Testing DocumentDynamoDBService user scoping...
lib/idp_common_pkg/tests/unit/dynamodb/test_service_user_scoping.py::TestDocumentCreationWithUserScoping::test_creates_user_scoped_pk_when_user_id_present PASSED
...

Testing create_document_resolver with user scoping...
tests/unit/lambda/create_document_resolver/test_handler.py::TestHandlerDocumentCreation::test_creates_user_scoped_partition_key PASSED
...

✓ Tests completed successfully
```

## Troubleshooting

### Virtual Environment Not Found

If you see:
```
Error: Virtual environment not found at .../idp-linux
```

Activate your virtual environment:
```bash
source idp-linux/bin/activate
```

### Import Errors

If you see import errors, ensure idp_common is installed:
```bash
cd lib/idp_common_pkg
pip install -e .
```

### Module Conflicts

If tests fail due to module caching, use the isolation mode:
```bash
./run_tests.sh all  # Runs each test suite separately
```

## CI/CD Integration

To integrate with CI/CD, add to your pipeline:

```yaml
# Example GitHub Actions
- name: Run User-Scoping Tests
  run: |
    source idp-linux/bin/activate
    ./run_tests.sh user-scoping
```

```yaml
# Example GitLab CI
test:user-scoping:
  script:
    - source idp-linux/bin/activate
    - ./run_tests.sh user-scoping
```

## Pre-Deployment Checklist

Before deploying, run:

```bash
# 1. Run all user-scoping tests
./run_tests.sh user-scoping

# 2. Run all unit tests
./run_tests.sh all

# 3. Generate coverage report
./run_tests.sh coverage

# 4. Verify no test failures
echo $?  # Should output 0
```

All tests should pass before deployment!
