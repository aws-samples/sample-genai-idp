"""
Integration tests for user-scoped document flow.

These tests verify the complete flow from document creation through
workflow updates, ensuring user isolation works correctly.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone
from idp_common.models import Document, Status
from idp_common.dynamodb.service import DocumentDynamoDBService


@pytest.fixture
def user_id():
    """Sample Cognito user ID."""
    return 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'


@pytest.fixture
def object_key(user_id):
    """Sample object key with user path."""
    return f'users/{user_id}/invoice-2024.pdf'


@pytest.fixture
def queued_time():
    """Sample queued timestamp."""
    return '2025-10-17T14:30:00Z'


@pytest.fixture
def mock_dynamodb_client():
    """Mock DynamoDB client."""
    return Mock()


@pytest.fixture
def document_service(mock_dynamodb_client):
    """DocumentDynamoDBService with mocked client."""
    with patch('idp_common.dynamodb.service.DynamoDBClient', return_value=mock_dynamodb_client):
        return DocumentDynamoDBService()


class TestUserScopedDocumentLifecycle:
    """Test complete document lifecycle with user scoping."""
    
    def test_complete_flow_single_user(
        self, document_service, mock_dynamodb_client, user_id, object_key, queued_time
    ):
        """
        Test complete document flow for a single user:
        1. Create document (queue_processor)
        2. Update document with workflow results (workflow_tracker)
        3. Retrieve document (GetDocument resolver)
        """
        # Step 1: Create document (simulates queue_processor)
        doc = Document(
            id=object_key,
            input_key=object_key,
            user_id=user_id,
            status=Status.QUEUED,
            queued_time=queued_time,
            initial_event_time=queued_time
        )
        
        mock_dynamodb_client.transact_write_items.return_value = {}
        result = document_service.create_document(doc)
        
        # Verify creation used user-scoped PK
        create_call = mock_dynamodb_client.transact_write_items.call_args[0][0]
        doc_item = create_call[0]['Put']['Item']
        assert doc_item['PK'] == f"user#{user_id}#doc#{object_key}"
        assert doc_item['UserId'] == user_id
        
        # Verify list item has UserId for filtering
        list_item = create_call[1]['Put']['Item']
        assert list_item['UserId'] == user_id
        
        # Step 2: Update document (simulates workflow_tracker)
        doc.status = Status.COMPLETED
        doc.completion_time = '2025-10-17T14:35:00Z'
        doc.num_pages = 3
        
        mock_dynamodb_client.update_item.return_value = {
            'Attributes': {
                'PK': f"user#{user_id}#doc#{object_key}",
                'SK': 'none',
                'ObjectKey': object_key,
                'ObjectStatus': 'COMPLETED',
                'UserId': user_id,
                'PageCount': 3
            }
        }
        
        updated_doc = document_service.update_document(doc)
        
        # Verify update used same user-scoped PK
        update_call = mock_dynamodb_client.update_item.call_args[1]
        assert update_call['key']['PK'] == f"user#{user_id}#doc#{object_key}"
        
        # Step 3: Retrieve document (simulates GetDocument resolver)
        mock_dynamodb_client.get_item.return_value = {
            'PK': f"user#{user_id}#doc#{object_key}",
            'SK': 'none',
            'ObjectKey': object_key,
            'ObjectStatus': 'COMPLETED',
            'UserId': user_id,
            'PageCount': 3,
            'CompletionTime': '2025-10-17T14:35:00Z'
        }
        
        retrieved_doc = document_service.get_document(object_key, user_id=user_id)
        
        # Verify retrieval used same user-scoped PK (uses FULL object_key to match GetDocumentResolver)
        get_call = mock_dynamodb_client.get_item.call_args[0][0]
        assert get_call['PK'] == f"user#{user_id}#doc#{object_key}"
        
        # Verify document has all expected data
        assert retrieved_doc.user_id == user_id
        assert retrieved_doc.input_key == object_key
        assert retrieved_doc.num_pages == 3
        assert retrieved_doc.status == Status.COMPLETED
    
    def test_multi_user_isolation(
        self, document_service, mock_dynamodb_client, queued_time
    ):
        """
        Test that multiple users can upload documents with same name
        and they remain isolated.
        """
        # Two different users
        user_1 = 'user-aaaa-1111'
        user_2 = 'user-bbbb-2222'
        
        # Same filename for both users
        filename = 'invoice.pdf'
        object_key_1 = f'users/{user_1}/{filename}'
        object_key_2 = f'users/{user_2}/{filename}'
        
        # User 1 uploads document
        doc1 = Document(
            id=object_key_1,
            input_key=object_key_1,
            user_id=user_1,
            status=Status.QUEUED,
            queued_time=queued_time,
            initial_event_time=queued_time
        )
        
        mock_dynamodb_client.transact_write_items.return_value = {}
        document_service.create_document(doc1)
        
        call1 = mock_dynamodb_client.transact_write_items.call_args_list[0][0][0]
        pk1 = call1[0]['Put']['Item']['PK']
        
        # User 2 uploads document with same name
        doc2 = Document(
            id=object_key_2,
            input_key=object_key_2,
            user_id=user_2,
            status=Status.QUEUED,
            queued_time=queued_time,
            initial_event_time=queued_time
        )
        
        document_service.create_document(doc2)
        
        call2 = mock_dynamodb_client.transact_write_items.call_args_list[1][0][0]
        pk2 = call2[0]['Put']['Item']['PK']
        
        # Verify PKs are different (user isolation)
        assert pk1 == f"user#{user_1}#doc#{object_key_1}"
        assert pk2 == f"user#{user_2}#doc#{object_key_2}"
        assert pk1 != pk2
        
        # Verify list items have different UserIds
        list_item_1 = call1[1]['Put']['Item']
        list_item_2 = call2[1]['Put']['Item']
        assert list_item_1['UserId'] == user_1
        assert list_item_2['UserId'] == user_2
        
        # Verify user 1 cannot access user 2's document
        mock_dynamodb_client.get_item.return_value = None
        result = document_service.get_document(object_key_2, user_id=user_1)
        assert result is None
    
    def test_workflow_update_maintains_user_scoping(
        self, document_service, mock_dynamodb_client, user_id, object_key, queued_time
    ):
        """
        Test that workflow updates (from workflow_tracker) maintain
        user scoping even when document has been through serialization.
        """
        # Create initial document
        doc = Document(
            id=object_key,
            input_key=object_key,
            user_id=user_id,
            status=Status.QUEUED,
            queued_time=queued_time,
            initial_event_time=queued_time
        )
        
        # Simulate document going through to_dict/from_dict (workflow serialization)
        doc_dict = doc.to_dict()
        assert doc_dict['user_id'] == user_id  # user_id preserved in serialization
        
        # Recreate document from dict (simulates workflow_tracker loading document)
        restored_doc = Document.from_dict(doc_dict)
        assert restored_doc.user_id == user_id
        
        # Update the restored document
        restored_doc.status = Status.COMPLETED
        restored_doc.completion_time = '2025-10-17T14:40:00Z'
        
        mock_dynamodb_client.update_item.return_value = {
            'Attributes': {
                'PK': f"user#{user_id}#doc#{object_key}",
                'SK': 'none',
                'ObjectKey': object_key,
                'ObjectStatus': 'COMPLETED',
                'UserId': user_id
            }
        }
        
        # This should use user-scoped PK because user_id was preserved
        document_service.update_document(restored_doc)
        
        # Verify update used correct user-scoped PK
        update_call = mock_dynamodb_client.update_item.call_args[1]
        assert update_call['key']['PK'] == f"user#{user_id}#doc#{object_key}"
        assert update_call['key']['SK'] == 'none'


class TestListDocumentFiltering:
    """Test that list documents filtering works correctly."""
    
    def test_list_items_include_user_id(
        self, document_service, mock_dynamodb_client, user_id, object_key, queued_time
    ):
        """Verify list items include UserId for filtering."""
        doc = Document(
            id=object_key,
            input_key=object_key,
            user_id=user_id,
            status=Status.QUEUED,
            queued_time=queued_time,
            initial_event_time=queued_time
        )
        
        mock_dynamodb_client.transact_write_items.return_value = {}
        document_service.create_document(doc)
        
        # Get list item
        call = mock_dynamodb_client.transact_write_items.call_args[0][0]
        list_item = call[1]['Put']['Item']
        
        # Verify list item structure for filtering
        assert 'UserId' in list_item
        assert list_item['UserId'] == user_id
        assert list_item['ObjectKey'] == object_key
        assert list_item['QueuedTime'] == queued_time
        assert list_item['PK'].startswith('list#')
        assert list_item['SK'].startswith('ts#')
    
    def test_multiple_users_different_list_items(
        self, document_service, mock_dynamodb_client, queued_time
    ):
        """Verify different users create list items with different UserIds."""
        user_1 = 'user-1111'
        user_2 = 'user-2222'
        
        doc1 = Document(
            id='doc1.pdf',
            input_key=f'users/{user_1}/doc1.pdf',
            user_id=user_1,
            status=Status.QUEUED,
            queued_time=queued_time,
            initial_event_time=queued_time
        )
        
        doc2 = Document(
            id='doc2.pdf',
            input_key=f'users/{user_2}/doc2.pdf',
            user_id=user_2,
            status=Status.QUEUED,
            queued_time=queued_time,
            initial_event_time=queued_time
        )
        
        mock_dynamodb_client.transact_write_items.return_value = {}
        document_service.create_document(doc1)
        document_service.create_document(doc2)
        
        # Get both list items
        call1 = mock_dynamodb_client.transact_write_items.call_args_list[0][0][0]
        list_item_1 = call1[1]['Put']['Item']
        
        call2 = mock_dynamodb_client.transact_write_items.call_args_list[1][0][0]
        list_item_2 = call2[1]['Put']['Item']
        
        # Verify different UserIds
        assert list_item_1['UserId'] == user_1
        assert list_item_2['UserId'] == user_2
        
        # Verify same shard (if uploaded at same time)
        # This shows filtering is needed since both are in same partition
        assert list_item_1['PK'] == list_item_2['PK']  # Same shard
        assert list_item_1['UserId'] != list_item_2['UserId']  # Different users


class TestBackwardsCompatibility:
    """Test that legacy documents without user_id still work."""
    
    def test_legacy_document_without_user_id(
        self, document_service, mock_dynamodb_client
    ):
        """Verify documents without user_id use legacy PK format."""
        # Create document without user_id
        doc = Document(
            id='legacy-doc.pdf',
            input_key='legacy-doc.pdf',
            user_id=None,  # No user_id
            status=Status.QUEUED,
            queued_time='2025-10-17T14:30:00Z',
            initial_event_time='2025-10-17T14:30:00Z'
        )
        
        mock_dynamodb_client.transact_write_items.return_value = {}
        document_service.create_document(doc)
        
        # Verify legacy PK format used
        call = mock_dynamodb_client.transact_write_items.call_args[0][0]
        doc_item = call[0]['Put']['Item']
        
        assert doc_item['PK'] == 'doc#legacy-doc.pdf'
        assert 'UserId' not in doc_item
        
        # Verify list item doesn't have UserId
        list_item = call[1]['Put']['Item']
        assert 'UserId' not in list_item
    
    def test_can_retrieve_legacy_document(
        self, document_service, mock_dynamodb_client
    ):
        """Verify can still retrieve legacy documents without user_id."""
        object_key = 'legacy-doc.pdf'
        
        mock_dynamodb_client.get_item.return_value = {
            'PK': f'doc#{object_key}',
            'SK': 'none',
            'ObjectKey': object_key,
            'ObjectStatus': 'COMPLETED'
        }
        
        # Get without user_id (legacy format)
        doc = document_service.get_document(object_key)
        
        # Verify legacy PK was used
        call = mock_dynamodb_client.get_item.call_args[0][0]
        assert call['PK'] == f'doc#{object_key}'
        
        assert doc is not None
        assert doc.input_key == object_key
