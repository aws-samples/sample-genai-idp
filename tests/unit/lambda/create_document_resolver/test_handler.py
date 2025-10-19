"""
Unit tests for create_document_resolver Lambda handler.

Tests the main handler function including document creation,
user scoping, and error handling.
"""
import pytest
import os
from unittest.mock import Mock, patch
import index


@patch.dict(os.environ, {'TRACKING_TABLE_NAME': 'test-tracking-table'})
class TestHandlerDocumentCreation:
    """Tests for document creation logic."""
    
    @patch('index.dynamodb')
    def test_creates_user_scoped_partition_key(
        self, mock_dynamodb, valid_create_document_event, 
        mock_lambda_context, valid_cognito_uuid
    ):
        """Should create document with user-scoped partition key."""
        # Setup
        mock_table = Mock()
        mock_dynamodb.Table.return_value = mock_table
        mock_table.get_item.return_value = {}
        mock_table.put_item.return_value = {}
        
        # Execute
        result = index.handler(valid_create_document_event, mock_lambda_context)
        
        # Verify DynamoDB calls
        calls = mock_table.put_item.call_args_list
        assert len(calls) == 2  # Document record + list item
        
        # Verify document record structure
        doc_item = calls[0][1]['Item']
        # PK should use FULL object_key to match GetDocumentResolver
        expected_pk = f'user#{valid_cognito_uuid}#doc#{doc_item["ObjectKey"]}'
        assert doc_item['PK'] == expected_pk
        assert doc_item['SK'] == 'none'
        assert doc_item['UserId'] == valid_cognito_uuid
        
        # Verify return value
        assert result['UserId'] == valid_cognito_uuid
    
    @patch('index.dynamodb')
    def test_creates_list_item_with_shard(
        self, mock_dynamodb, valid_create_document_event, mock_lambda_context, valid_cognito_uuid
    ):
        """Should create list item with proper sharding and UserId."""
        # Setup
        mock_table = Mock()
        mock_dynamodb.Table.return_value = mock_table
        mock_table.get_item.return_value = {}
        mock_table.put_item.return_value = {}
        
        # Execute
        result = index.handler(valid_create_document_event, mock_lambda_context)
        
        # Verify list item
        list_item = mock_table.put_item.call_args_list[1][1]['Item']
        assert list_item['PK'].startswith('list#')
        assert 's#' in list_item['PK']  # Shard number
        assert list_item['SK'].startswith('ts#')
        assert 'ObjectKey' in list_item
        assert list_item['UserId'] == valid_cognito_uuid  # CRITICAL: UserId must be in list item
    
    @patch('index.dynamodb')
    def test_uses_sub_when_username_missing(
        self, mock_dynamodb, create_document_event_with_sub, 
        mock_lambda_context, valid_cognito_uuid
    ):
        """Should use 'sub' field when 'username' is not present."""
        # Setup
        mock_table = Mock()
        mock_dynamodb.Table.return_value = mock_table
        mock_table.get_item.return_value = {}
        mock_table.put_item.return_value = {}
        
        # Execute
        result = index.handler(create_document_event_with_sub, mock_lambda_context)
        
        # Verify user ID from sub was used
        doc_item = mock_table.put_item.call_args_list[0][1]['Item']
        assert doc_item['UserId'] == valid_cognito_uuid
        assert result['UserId'] == valid_cognito_uuid
    
    @patch('index.dynamodb')
    def test_includes_optional_expires_after(
        self, mock_dynamodb, create_document_event_with_expires, mock_lambda_context
    ):
        """Should include ExpiresAfter in list item when provided."""
        # Setup
        mock_table = Mock()
        mock_dynamodb.Table.return_value = mock_table
        mock_table.get_item.return_value = {}
        mock_table.put_item.return_value = {}
        
        # Execute
        result = index.handler(create_document_event_with_expires, mock_lambda_context)
        
        # Verify list item includes ExpiresAfter
        list_item = mock_table.put_item.call_args_list[1][1]['Item']
        assert list_item['ExpiresAfter'] == 1234567890
    
    @patch('index.calculate_shard')
    @patch('index.dynamodb')
    def test_uses_shard_calculation(
        self, mock_dynamodb, mock_calculate_shard, 
        valid_create_document_event, mock_lambda_context
    ):
        """Should use calculate_shard utility for list partition key."""
        # Setup
        mock_table = Mock()
        mock_dynamodb.Table.return_value = mock_table
        mock_table.get_item.return_value = {}
        mock_table.put_item.return_value = {}
        mock_calculate_shard.return_value = ('2025-01-15', '03')
        
        # Execute
        result = index.handler(valid_create_document_event, mock_lambda_context)
        
        # Verify calculate_shard was called
        mock_calculate_shard.assert_called_once()
        
        # Verify list PK uses shard values
        list_item = mock_table.put_item.call_args_list[1][1]['Item']
        assert list_item['PK'] == 'list#2025-01-15#s#03'


@patch.dict(os.environ, {'TRACKING_TABLE_NAME': 'test-tracking-table'})
class TestHandlerExistingDocuments:
    """Tests for handling existing documents."""
    
    @patch('index.delete_list_entries_robust')
    @patch('index.dynamodb')
    def test_deletes_existing_document_entries(
        self, mock_dynamodb, mock_delete_robust, 
        valid_create_document_event, existing_document_item, mock_lambda_context
    ):
        """Should delete existing document list entries before creating new ones."""
        # Setup
        mock_table = Mock()
        mock_dynamodb.Table.return_value = mock_table
        mock_table.get_item.return_value = {'Item': existing_document_item}
        mock_table.put_item.return_value = {}
        mock_delete_robust.return_value = True
        
        # Execute
        result = index.handler(valid_create_document_event, mock_lambda_context)
        
        # Verify deletion was attempted
        assert mock_delete_robust.called
    
    @patch('index.delete_list_entries_robust')
    @patch('index.dynamodb')
    def test_continues_on_deletion_failure(
        self, mock_dynamodb, mock_delete_robust, 
        valid_create_document_event, mock_lambda_context, caplog
    ):
        """Should continue creating new document even if deletion fails."""
        # Setup
        mock_table = Mock()
        mock_dynamodb.Table.return_value = mock_table
        mock_table.get_item.return_value = {'Item': {'PK': 'old-doc'}}
        mock_table.put_item.return_value = {}
        mock_delete_robust.side_effect = Exception("Deletion failed")
        
        # Execute
        result = index.handler(valid_create_document_event, mock_lambda_context)
        
        # Verify still succeeded
        assert 'ObjectKey' in result
        assert 'Error in robust list entry deletion' in caplog.text
    
    @patch('index.dynamodb')
    def test_continues_on_get_item_failure(
        self, mock_dynamodb, valid_create_document_event, 
        mock_lambda_context, caplog
    ):
        """Should continue if checking for existing document fails."""
        # Setup
        mock_table = Mock()
        mock_dynamodb.Table.return_value = mock_table
        mock_table.get_item.side_effect = Exception("DynamoDB error")
        mock_table.put_item.return_value = {}
        
        # Execute
        result = index.handler(valid_create_document_event, mock_lambda_context)
        
        # Verify still succeeded
        assert 'ObjectKey' in result
        assert 'Error checking for existing document' in caplog.text


@patch.dict(os.environ, {'TRACKING_TABLE_NAME': 'test-tracking-table'})
class TestHandlerValidation:
    """Tests for input validation."""
    
    @patch('index.dynamodb')
    def test_raises_error_on_missing_object_key(self, mock_dynamodb, valid_cognito_uuid):
        """Should raise ValueError when ObjectKey is missing."""
        event = {
            'identity': {'username': valid_cognito_uuid},
            'arguments': {
                'input': {
                    'QueuedTime': '2025-01-15T10:30:00Z'
                }
            }
        }
        
        with pytest.raises(ValueError, match="ObjectKey must be a non-empty string"):
            index.handler(event, {})
    
    @patch('index.dynamodb')
    def test_raises_error_on_missing_queued_time(self, mock_dynamodb, valid_cognito_uuid):
        """Should raise ValueError when QueuedTime is missing."""
        event = {
            'identity': {'username': valid_cognito_uuid},
            'arguments': {
                'input': {
                    'ObjectKey': 'test.pdf'
                }
            }
        }
        
        with pytest.raises(ValueError, match="QueuedTime must be a non-empty string"):
            index.handler(event, {})
    
    @patch('index.dynamodb')
    def test_raises_error_on_empty_input(self, mock_dynamodb, valid_cognito_uuid):
        """Should raise ValueError when input data is empty."""
        event = {
            'identity': {'username': valid_cognito_uuid},
            'arguments': {
                'input': {}
            }
        }
        
        with pytest.raises(ValueError, match="Input data is required"):
            index.handler(event, {})
    
    def test_raises_error_on_missing_user_id(self):
        """Should raise ValueError when user identity is missing."""
        event = {
            'identity': {},
            'arguments': {
                'input': {
                    'ObjectKey': 'test.pdf',
                    'QueuedTime': '2025-01-15T10:30:00Z'
                }
            }
        }
        
        with pytest.raises(ValueError, match="User not authenticated"):
            index.handler(event, {})
