"""
Shared test fixtures for upload_resolver Lambda tests.
"""
import pytest
import sys
from pathlib import Path
from unittest.mock import Mock

# Add Lambda source directory to path
LAMBDA_DIR = Path(__file__).parent.parent.parent.parent.parent / 'src' / 'lambda' / 'upload_resolver'
sys.path.insert(0, str(LAMBDA_DIR))


@pytest.fixture
def valid_cognito_uuid():
    """Valid Cognito user UUID."""
    return 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'


@pytest.fixture
def mock_lambda_context():
    """Mock Lambda context object."""
    context = Mock()
    context.function_name = 'upload-resolver'
    context.memory_limit_in_mb = 128
    context.invoked_function_arn = 'arn:aws:lambda:us-east-1:123456789012:function:upload-resolver'
    context.aws_request_id = 'test-request-id'
    return context


@pytest.fixture
def valid_upload_event(valid_cognito_uuid):
    """Valid AppSync upload event with Cognito identity."""
    return {
        'identity': {
            'username': valid_cognito_uuid,
            'sourceIp': ['192.0.2.1'],
            'userArn': f'arn:aws:sts::123456789012:assumed-role/AppSyncRole/{valid_cognito_uuid}',
        },
        'arguments': {
            'fileName': 'invoice-2025.pdf',
            'contentType': 'application/pdf',
            'prefix': '',
            'bucket': 'test-input-bucket'
        }
    }


@pytest.fixture
def upload_event_with_prefix(valid_cognito_uuid):
    """Upload event with user-provided subdirectory prefix."""
    return {
        'identity': {
            'username': valid_cognito_uuid
        },
        'arguments': {
            'fileName': 'document.pdf',
            'contentType': 'application/pdf',
            'prefix': 'invoices/2025',
            'bucket': 'test-input-bucket'
        }
    }


@pytest.fixture
def upload_event_with_sub(valid_cognito_uuid):
    """Upload event using 'sub' instead of 'username'."""
    return {
        'identity': {
            'sub': valid_cognito_uuid
        },
        'arguments': {
            'fileName': 'receipt.pdf',
            'contentType': 'application/pdf',
            'bucket': 'test-input-bucket'
        }
    }


@pytest.fixture
def upload_event_no_auth():
    """Upload event with missing authentication."""
    return {
        'identity': {},
        'arguments': {
            'fileName': 'document.pdf',
            'contentType': 'application/pdf',
            'bucket': 'test-input-bucket'
        }
    }


@pytest.fixture
def upload_event_with_spaces(valid_cognito_uuid):
    """Upload event with filename containing spaces."""
    return {
        'identity': {
            'username': valid_cognito_uuid
        },
        'arguments': {
            'fileName': 'My Invoice 2025.pdf',
            'contentType': 'application/pdf',
            'bucket': 'test-input-bucket'
        }
    }


@pytest.fixture
def mock_presigned_post():
    """Mock S3 presigned POST response."""
    return {
        'url': 'https://test-bucket.s3.amazonaws.com/',
        'fields': {
            'key': 'users/test-user/document.pdf',
            'AWSAccessKeyId': 'AKIAIOSFODNN7EXAMPLE',
            'policy': 'eyJleHBpcmF0aW9uIjogIjIwMjUtMDEtMTVUMTE6MDA6MDBaIn0=',
            'signature': 'test-signature',
            'Content-Type': 'application/pdf'
        }
    }
