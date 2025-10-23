"""
Shared test fixtures for queue_sender Lambda tests.
"""
import pytest
from unittest.mock import Mock


@pytest.fixture
def valid_cognito_uuid():
    """Valid Cognito user UUID."""
    return 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'


@pytest.fixture
def mock_lambda_context():
    """Mock Lambda context object."""
    context = Mock()
    context.function_name = 'queue-sender'
    context.memory_limit_in_mb = 128
    context.invoked_function_arn = 'arn:aws:lambda:us-east-1:123456789012:function:queue-sender'
    context.aws_request_id = 'test-request-id'
    return context


@pytest.fixture
def valid_s3_event(valid_cognito_uuid):
    """Valid S3 Object Created event from EventBridge."""
    return {
        'version': '0',
        'id': 'test-event-id',
        'detail-type': 'Object Created',
        'source': 'aws.s3',
        'account': '123456789012',
        'time': '2025-01-15T10:30:00Z',
        'region': 'us-east-1',
        'detail': {
            'version': '0',
            'bucket': {
                'name': 'test-input-bucket'
            },
            'object': {
                'key': f'users/{valid_cognito_uuid}/test-document.pdf',
                'size': 12345,
                'etag': 'test-etag',
                'last-modified': '2025-01-15T10:30:00Z'
            },
            'request-id': 'test-request-id',
            'requester': 'test-requester'
        }
    }


@pytest.fixture
def s3_event_with_nested_path(valid_cognito_uuid):
    """S3 event with nested user path."""
    return {
        'version': '0',
        'id': 'test-event-id',
        'detail-type': 'Object Created',
        'source': 'aws.s3',
        'detail': {
            'bucket': {
                'name': 'test-input-bucket'
            },
            'object': {
                'key': f'users/{valid_cognito_uuid}/subfolder/nested/document.pdf',
                'last-modified': '2025-01-15T10:30:00Z'
            }
        }
    }


@pytest.fixture
def s3_event_invalid_path():
    """S3 event with invalid path (missing users prefix)."""
    return {
        'version': '0',
        'id': 'test-event-id',
        'detail-type': 'Object Created',
        'source': 'aws.s3',
        'detail': {
            'bucket': {
                'name': 'test-input-bucket'
            },
            'object': {
                'key': 'documents/test-document.pdf'
            }
        }
    }


@pytest.fixture
def s3_event_empty_user_id():
    """S3 event with empty user ID in path."""
    return {
        'version': '0',
        'id': 'test-event-id',
        'detail-type': 'Object Created',
        'source': 'aws.s3',
        'detail': {
            'bucket': {
                'name': 'test-input-bucket'
            },
            'object': {
                'key': 'users//test-document.pdf'
            }
        }
    }


@pytest.fixture
def s3_event_short_path():
    """S3 event with path that's too short."""
    return {
        'version': '0',
        'id': 'test-event-id',
        'detail-type': 'Object Created',
        'source': 'aws.s3',
        'detail': {
            'bucket': {
                'name': 'test-input-bucket'
            },
            'object': {
                'key': 'users/test-user'
            }
        }
    }


@pytest.fixture
def s3_event_non_uuid_user():
    """S3 event with non-UUID user ID."""
    return {
        'version': '0',
        'id': 'test-event-id',
        'detail-type': 'Object Created',
        'source': 'aws.s3',
        'detail': {
            'bucket': {
                'name': 'test-input-bucket'
            },
            'object': {
                'key': 'users/admin-user/test-document.pdf',
                'last-modified': '2025-01-15T10:30:00Z'
            }
        }
    }


@pytest.fixture
def mock_sqs_response():
    """Mock SQS send_message response."""
    return {
        'MessageId': 'test-message-id-12345',
        'MD5OfMessageBody': 'test-md5-hash',
        'ResponseMetadata': {
            'RequestId': 'test-request-id',
            'HTTPStatusCode': 200
        }
    }
