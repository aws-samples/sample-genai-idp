"""
Unit tests for DocumentDynamoDBService user scoping functionality.

Tests verify that user-scoped partition keys work correctly for
create, update, and get operations.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from idp_common.dynamodb.service import DocumentDynamoDBService
from idp_common.models import Document, Status


@pytest.fixture
def mock_dynamodb_client():
    """Mock DynamoDB client."""
    return Mock()


@pytest.fixture
def service(mock_dynamodb_client):
    """DocumentDynamoDBService instance with mocked client."""
    with patch('idp_common.dynamodb.service.DynamoDBClient', return_value=mock_dynamodb_client):
        return DocumentDynamoDBService()


@pytest.fixture
def sample_document_with_user():
    """Sample document with user_id."""
    return Document(
        id='test-doc.pdf',
        input_key='users/user-123/test-doc.pdf',
        user_id='user-123',
        status=Status.QUEUED,
        queued_time='2025-10-17T10:30:00Z',
        initial_event_time='2025-10-17T10:30:00Z'
    )


@pytest.fixture
def sample_document_without_user():
    """Sample document without user_id (legacy format)."""
    return Document(
        id='test-doc.pdf',
        input_key='test-doc.pdf',
        user_id=None,
        status=Status.QUEUED,
        queued_time='2025-10-17T10:30:00Z',
        initial_event_time='2025-10-17T10:30:00Z'
    )


class TestDocumentCreationWithUserScoping:
    """Tests for document creation with user scoping."""
    
    def test_creates_user_scoped_pk_when_user_id_present(
        self, service, sample_document_with_user, mock_dynamodb_client
    ):
        """Should create document with user-scoped PK when user_id is present."""
        # Setup
        mock_dynamodb_client.transact_write_items.return_value = {}
        
        # Execute
        result = service.create_document(sample_document_with_user)
        
        # Verify
        assert result == sample_document_with_user.input_key
        
        # Check transact_write_items was called
        call_args = mock_dynamodb_client.transact_write_items.call_args[0][0]
        doc_item = call_args[0]['Put']['Item']
        
        # Verify user-scoped PK format (uses FULL input_key to match GetDocumentResolver)
        expected_pk = f"user#{sample_document_with_user.user_id}#doc#{sample_document_with_user.input_key}"
        assert doc_item['PK'] == expected_pk
        assert doc_item['SK'] == 'none'
        assert doc_item['UserId'] == sample_document_with_user.user_id
    
    def test_creates_legacy_pk_when_user_id_missing(
        self, service, sample_document_without_user, mock_dynamodb_client
    ):
        """Should create document with legacy PK format when user_id is missing."""
        # Setup
        mock_dynamodb_client.transact_write_items.return_value = {}
        
        # Execute
        result = service.create_document(sample_document_without_user)
        
        # Verify
        call_args = mock_dynamodb_client.transact_write_items.call_args[0][0]
        doc_item = call_args[0]['Put']['Item']
        
        # Verify legacy PK format
        expected_pk = f"doc#{sample_document_without_user.input_key}"
        assert doc_item['PK'] == expected_pk
        assert doc_item['SK'] == 'none'
        assert 'UserId' not in doc_item
    
    def test_includes_user_id_in_list_item(
        self, service, sample_document_with_user, mock_dynamodb_client
    ):
        """Should include UserId in list item for filtering."""
        # Setup
        mock_dynamodb_client.transact_write_items.return_value = {}
        
        # Execute
        service.create_document(sample_document_with_user)
        
        # Verify list item
        call_args = mock_dynamodb_client.transact_write_items.call_args[0][0]
        list_item = call_args[1]['Put']['Item']
        
        assert list_item['UserId'] == sample_document_with_user.user_id
        assert list_item['ObjectKey'] == sample_document_with_user.input_key
        assert list_item['PK'].startswith('list#')
    
    def test_includes_expires_after_when_provided(
        self, service, sample_document_with_user, mock_dynamodb_client
    ):
        """Should include ExpiresAfter in both items when provided."""
        # Setup
        mock_dynamodb_client.transact_write_items.return_value = {}
        expires_after = 1729252800  # Sample timestamp
        
        # Execute
        service.create_document(sample_document_with_user, expires_after=expires_after)
        
        # Verify
        call_args = mock_dynamodb_client.transact_write_items.call_args[0][0]
        doc_item = call_args[0]['Put']['Item']
        list_item = call_args[1]['Put']['Item']
        
        assert doc_item['ExpiresAfter'] == expires_after
        assert list_item['ExpiresAfter'] == expires_after


class TestDocumentUpdateWithUserScoping:
    """Tests for document update with user scoping."""
    
    def test_updates_with_user_scoped_pk_when_user_id_present(
        self, service, sample_document_with_user, mock_dynamodb_client
    ):
        """Should update document using user-scoped PK when user_id is present."""
        # Setup
        sample_document_with_user.status = Status.COMPLETED
        sample_document_with_user.completion_time = '2025-10-17T10:35:00Z'
        
        mock_dynamodb_client.update_item.return_value = {
            'Attributes': {
                'PK': f"user#{sample_document_with_user.user_id}#doc#{sample_document_with_user.input_key}",
                'SK': 'none',
                'ObjectKey': sample_document_with_user.input_key,
                'ObjectStatus': 'COMPLETED',
                'UserId': sample_document_with_user.user_id
            }
        }
        
        # Execute
        result = service.update_document(sample_document_with_user)
        
        # Verify correct PK was used (uses FULL input_key to match GetDocumentResolver)
        call_args = mock_dynamodb_client.update_item.call_args[1]
        expected_pk = f"user#{sample_document_with_user.user_id}#doc#{sample_document_with_user.input_key}"
        assert call_args['key']['PK'] == expected_pk
        assert call_args['key']['SK'] == 'none'
    
    def test_updates_with_legacy_pk_when_user_id_missing(
        self, service, sample_document_without_user, mock_dynamodb_client
    ):
        """Should update document using legacy PK when user_id is missing."""
        # Setup
        sample_document_without_user.status = Status.COMPLETED
        
        mock_dynamodb_client.update_item.return_value = {
            'Attributes': {
                'PK': f"doc#{sample_document_without_user.input_key}",
                'SK': 'none',
                'ObjectKey': sample_document_without_user.input_key,
                'ObjectStatus': 'COMPLETED'
            }
        }
        
        # Execute
        result = service.update_document(sample_document_without_user)
        
        # Verify correct PK was used
        call_args = mock_dynamodb_client.update_item.call_args[1]
        expected_pk = f"doc#{sample_document_without_user.input_key}"
        assert call_args['key']['PK'] == expected_pk
    
    def test_update_includes_workflow_status(
        self, service, sample_document_with_user, mock_dynamodb_client
    ):
        """Should include WorkflowStatus in update expression."""
        # Setup
        sample_document_with_user.status = Status.COMPLETED
        
        mock_dynamodb_client.update_item.return_value = {
            'Attributes': {
                'PK': f"user#{sample_document_with_user.user_id}#doc#{sample_document_with_user.input_key}",
                'SK': 'none',
                'ObjectKey': sample_document_with_user.input_key,
                'ObjectStatus': 'COMPLETED',
                'WorkflowStatus': 'SUCCEEDED'
            }
        }
        
        # Execute
        result = service.update_document(sample_document_with_user)
        
        # Verify WorkflowStatus in expression values
        call_args = mock_dynamodb_client.update_item.call_args[1]
        assert ':WorkflowStatus' in call_args['expression_attribute_values']
        assert call_args['expression_attribute_values'][':WorkflowStatus'] == 'SUCCEEDED'


class TestDocumentGetWithUserScoping:
    """Tests for document retrieval with user scoping."""
    
    def test_gets_document_with_user_scoped_pk_when_user_id_provided(
        self, service, mock_dynamodb_client
    ):
        """Should retrieve document using user-scoped PK when user_id is provided."""
        # Setup
        object_key = 'users/user-123/test-doc.pdf'
        user_id = 'user-123'
        
        mock_dynamodb_client.get_item.return_value = {
            'PK': f"user#{user_id}#doc#{object_key}",
            'SK': 'none',
            'ObjectKey': object_key,
            'ObjectStatus': 'QUEUED',
            'UserId': user_id
        }
        
        # Execute
        result = service.get_document(object_key, user_id=user_id)
        
        # Verify correct PK was used (uses FULL object_key to match GetDocumentResolver)
        call_args = mock_dynamodb_client.get_item.call_args[0][0]
        expected_pk = f"user#{user_id}#doc#{object_key}"
        assert call_args['PK'] == expected_pk
        assert call_args['SK'] == 'none'
        
        # Verify document has user_id
        assert result is not None
        assert result.user_id == user_id
    
    def test_gets_document_with_legacy_pk_when_user_id_not_provided(
        self, service, mock_dynamodb_client
    ):
        """Should retrieve document using legacy PK when user_id is not provided."""
        # Setup
        object_key = 'test-doc.pdf'
        
        mock_dynamodb_client.get_item.return_value = {
            'PK': f"doc#{object_key}",
            'SK': 'none',
            'ObjectKey': object_key,
            'ObjectStatus': 'QUEUED'
        }
        
        # Execute
        result = service.get_document(object_key)
        
        # Verify correct PK was used
        call_args = mock_dynamodb_client.get_item.call_args[0][0]
        expected_pk = f"doc#{object_key}"
        assert call_args['PK'] == expected_pk
    
    def test_returns_none_when_document_not_found(
        self, service, mock_dynamodb_client
    ):
        """Should return None when document doesn't exist."""
        # Setup
        mock_dynamodb_client.get_item.return_value = None
        
        # Execute
        result = service.get_document('nonexistent.pdf', user_id='user-123')
        
        # Verify
        assert result is None
    
    def test_extracts_user_id_from_dynamodb_item(
        self, service, mock_dynamodb_client
    ):
        """Should extract UserId from DynamoDB item and populate document."""
        # Setup
        object_key = 'users/user-123/test-doc.pdf'
        user_id = 'user-123'
        
        mock_dynamodb_client.get_item.return_value = {
            'PK': f"user#{user_id}#doc#{object_key}",
            'SK': 'none',
            'ObjectKey': object_key,
            'ObjectStatus': 'COMPLETED',
            'UserId': user_id,
            'PageCount': 5
        }
        
        # Execute
        result = service.get_document(object_key, user_id=user_id)
        
        # Verify document has user_id populated
        assert result is not None
        assert result.user_id == user_id
        assert result.input_key == object_key
        assert result.num_pages == 5


class TestUserIsolation:
    """Tests to ensure users cannot access each other's documents."""
    
    def test_different_users_get_different_pks(
        self, service, mock_dynamodb_client
    ):
        """Should generate different PKs for different users."""
        # Setup
        object_key = 'test-doc.pdf'
        user_1 = 'user-111'
        user_2 = 'user-222'
        
        doc1 = Document(
            id=object_key,
            input_key=f'users/{user_1}/{object_key}',
            user_id=user_1,
            status=Status.QUEUED,
            queued_time='2025-10-17T10:30:00Z',
            initial_event_time='2025-10-17T10:30:00Z'
        )
        
        doc2 = Document(
            id=object_key,
            input_key=f'users/{user_2}/{object_key}',
            user_id=user_2,
            status=Status.QUEUED,
            queued_time='2025-10-17T10:30:00Z',
            initial_event_time='2025-10-17T10:30:00Z'
        )
        
        mock_dynamodb_client.transact_write_items.return_value = {}
        
        # Execute
        service.create_document(doc1)
        call1 = mock_dynamodb_client.transact_write_items.call_args_list[0][0][0]
        pk1 = call1[0]['Put']['Item']['PK']
        
        service.create_document(doc2)
        call2 = mock_dynamodb_client.transact_write_items.call_args_list[1][0][0]
        pk2 = call2[0]['Put']['Item']['PK']
        
        # Verify PKs are different (uses FULL input_key to match GetDocumentResolver)
        assert pk1 == f"user#{user_1}#doc#{doc1.input_key}"
        assert pk2 == f"user#{user_2}#doc#{doc2.input_key}"
        assert pk1 != pk2  # Different user IDs make PKs different
    
    def test_user_cannot_get_another_users_document(
        self, service, mock_dynamodb_client
    ):
        """Should not find document when queried with wrong user_id."""
        # Setup - Document belongs to user-111 but we query with user-222
        object_key = 'users/user-111/test-doc.pdf'
        actual_user = 'user-111'
        wrong_user = 'user-222'
        
        # Mock returns nothing because PK doesn't match
        mock_dynamodb_client.get_item.return_value = None
        
        # Execute
        result = service.get_document(object_key, user_id=wrong_user)
        
        # Verify
        assert result is None
        
        # Verify the query used wrong user's PK
        call_args = mock_dynamodb_client.get_item.call_args[0][0]
        wrong_pk = f"user#{wrong_user}#doc#{object_key}"
        assert call_args['PK'] == wrong_pk
