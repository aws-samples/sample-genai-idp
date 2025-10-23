"""
Fixtures specific to create_document_resolver lambda tests.
"""
import pytest
import sys
import os
from pathlib import Path

# Add the lambda function directory to path
LAMBDA_DIR = Path(__file__).parent.parent.parent.parent.parent / 'src' / 'lambda' / 'create_document_resolver'
sys.path.insert(0, str(LAMBDA_DIR))


@pytest.fixture
def valid_create_document_event(valid_cognito_uuid, iso_timestamp):
    """Valid AppSync event for creating a document."""
    return {
        'identity': {
            'username': valid_cognito_uuid
        },
        'arguments': {
            'input': {
                'ObjectKey': f'users/{valid_cognito_uuid}/test-document.pdf',
                'QueuedTime': iso_timestamp,
                'Status': 'QUEUED',
                'DocumentType': 'invoice'
            }
        }
    }


@pytest.fixture
def create_document_event_with_sub(valid_cognito_uuid, iso_timestamp):
    """Event using 'sub' instead of 'username'."""
    return {
        'identity': {
            'sub': valid_cognito_uuid
        },
        'arguments': {
            'input': {
                'ObjectKey': f'users/{valid_cognito_uuid}/test-document.pdf',
                'QueuedTime': iso_timestamp,
                'Status': 'QUEUED'
            }
        }
    }


@pytest.fixture
def create_document_event_with_expires(valid_cognito_uuid, iso_timestamp):
    """Event with ExpiresAfter field."""
    return {
        'identity': {
            'username': valid_cognito_uuid
        },
        'arguments': {
            'input': {
                'ObjectKey': f'users/{valid_cognito_uuid}/test-document.pdf',
                'QueuedTime': iso_timestamp,
                'Status': 'QUEUED',
                'ExpiresAfter': 1234567890
            }
        }
    }


@pytest.fixture
def existing_document_item(valid_cognito_uuid):
    """Existing document item in DynamoDB."""
    object_key = f'users/{valid_cognito_uuid}/existing-doc.pdf'
    return {
        'PK': f'user#{valid_cognito_uuid}#doc#{object_key}',
        'SK': 'none',
        'ObjectKey': object_key,
        'UserId': valid_cognito_uuid,
        'QueuedTime': '2025-01-14T10:00:00Z',
        'Status': 'COMPLETED'
    }
