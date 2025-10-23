"""
Global pytest configuration and shared fixtures.
This file is automatically discovered by pytest and makes fixtures available to all tests.
"""
import pytest
import sys
import os
from pathlib import Path
from unittest.mock import Mock

# Add src directory to Python path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src' / 'lambda'))

# Add idp_common_pkg to path for tests that need it
IDP_COMMON_PKG_PATH = PROJECT_ROOT / 'lib' / 'idp_common_pkg'
if IDP_COMMON_PKG_PATH.exists():
    sys.path.insert(0, str(IDP_COMMON_PKG_PATH))


# ============================================================================
# Lambda Context Fixtures
# ============================================================================

@pytest.fixture
def mock_lambda_context():
    """Mock AWS Lambda context object."""
    context = Mock()
    context.function_name = 'test-function'
    context.function_version = '$LATEST'
    context.invoked_function_arn = 'arn:aws:lambda:us-east-1:123456789012:function:test-function'
    context.memory_limit_in_mb = 128
    context.aws_request_id = 'test-request-id-12345'
    context.log_group_name = '/aws/lambda/test-function'
    context.log_stream_name = '2025/01/15/[$LATEST]test-stream'
    
    # Add get_remaining_time_in_millis method
    context.get_remaining_time_in_millis = Mock(return_value=300000)
    
    return context


# ============================================================================
# Cognito Identity Fixtures
# ============================================================================

@pytest.fixture
def valid_cognito_uuid():
    """Standard UUID format from Cognito sub."""
    return '123e4567-e89b-12d3-a456-426614174000'


@pytest.fixture
def cognito_identity_username(valid_cognito_uuid):
    """Cognito identity with username field."""
    return {
        'username': valid_cognito_uuid,
        'sourceIp': ['192.0.2.1'],
        'userArn': f'arn:aws:sts::123456789012:assumed-role/AppSyncRole/{valid_cognito_uuid}',
        'accountId': '123456789012',
        'caller': 'AIDAI...'
    }


@pytest.fixture
def cognito_identity_sub(valid_cognito_uuid):
    """Cognito identity with sub field (fallback)."""
    return {
        'sub': valid_cognito_uuid,
        'sourceIp': ['192.0.2.1'],
        'userArn': f'arn:aws:sts::123456789012:assumed-role/AppSyncRole/{valid_cognito_uuid}',
        'accountId': '123456789012',
        'caller': 'AIDAI...'
    }


# ============================================================================
# DynamoDB Fixtures
# ============================================================================

@pytest.fixture
def mock_dynamodb_table():
    """Mock DynamoDB table with standard responses."""
    mock_table = Mock()
    mock_table.table_name = 'test-tracking-table'
    mock_table.get_item.return_value = {}
    mock_table.put_item.return_value = {}
    mock_table.update_item.return_value = {}
    mock_table.delete_item.return_value = {}
    mock_table.query.return_value = {'Items': []}
    mock_table.scan.return_value = {'Items': []}
    return mock_table


# ============================================================================
# Timestamp Fixtures
# ============================================================================

@pytest.fixture
def iso_timestamp():
    """Standard ISO 8601 timestamp."""
    return '2025-01-15T10:30:00Z'


@pytest.fixture
def unix_timestamp():
    """Unix epoch timestamp."""
    return 1737800000


# ============================================================================
# Helper Functions
# ============================================================================

def load_event_from_file(event_name):
    """
    Load a test event from the events directory.
    
    Args:
        event_name: Name of the event file (without .json extension)
    
    Returns:
        dict: Parsed JSON event
    """
    import json
    event_path = PROJECT_ROOT / 'tests' / 'events' / f'{event_name}.json'
    with open(event_path, 'r') as f:
        return json.load(f)


@pytest.fixture
def event_loader():
    """Fixture that returns the event loader function."""
    return load_event_from_file
