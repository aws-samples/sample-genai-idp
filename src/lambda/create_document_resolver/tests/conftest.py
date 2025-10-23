"""
Pytest configuration and fixtures for create_document_resolver tests.
"""
import pytest
import sys
import os
from unittest.mock import Mock

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


@pytest.fixture
def valid_uuid():
    """Standard UUID format from Cognito sub."""
    return '123e4567-e89b-12d3-a456-426614174000'


@pytest.fixture
def valid_event(valid_uuid):
    """A valid AppSync event with Cognito identity."""
    return {
        'identity': {
            'username': valid_uuid
        },
        'arguments': {
            'input': {
                'ObjectKey': f'users/{valid_uuid}/test-document.pdf',
                'QueuedTime': '2025-01-15T10:30:00Z'
            }
        }
    }


@pytest.fixture
def event_with_sub(valid_uuid):
    """Event using 'sub' instead of 'username'."""
    return {
        'identity': {
            'sub': valid_uuid
        },
        'arguments': {
            'input': {
                'ObjectKey': f'users/{valid_uuid}/test-document.pdf',
                'QueuedTime': '2025-01-15T10:30:00Z'
            }
        }
    }


@pytest.fixture
def event_with_both_identifiers(valid_uuid):
    """Event with both username and sub (username should take precedence)."""
    return {
        'identity': {
            'username': 'preferred-username',
            'sub': valid_uuid
        },
        'arguments': {
            'input': {
                'ObjectKey': 'test-document.pdf',
                'QueuedTime': '2025-01-15T10:30:00Z'
            }
        }
    }


@pytest.fixture
def mock_dynamodb_table():
    """Mock DynamoDB table with standard responses."""
    mock_table = Mock()
    mock_table.get_item.return_value = {}
    mock_table.put_item.return_value = {}
    return mock_table


@pytest.fixture
def mock_context():
    """Mock Lambda context object."""
    context = Mock()
    context.function_name = 'create_document_resolver'
    context.memory_limit_in_mb = 128
    context.invoked_function_arn = 'arn:aws:lambda:us-east-1:123456789012:function:test'
    context.aws_request_id = 'test-request-id'
    return context
