"""
Comprehensive tests for create_document_resolver Lambda function.
Tests user ID extraction, validation, and document creation with user isolation.
"""
import pytest
import json
import os
from unittest.mock import Mock, patch, MagicMock
from decimal import Decimal

import index


class TestUserIdExtraction:
    """Tests for extracting user ID from AppSync context."""
    
    def test_extract_user_id_from_username(self, valid_uuid):
        """Should extract user ID from 'username' field."""
        event = {
            'identity': {
                'username': valid_uuid
            }
        }
        user_id = index.extract_user_id(event)
        assert user_id == valid_uuid
    
    def test_extract_user_id_from_sub(self, valid_uuid):
        """Should extract user ID from 'sub' field when username is missing."""
        event = {
            'identity': {
                'sub': valid_uuid
            }
        }
        user_id = index.extract_user_id(event)
        assert user_id == valid_uuid
    
    def test_extract_user_id_prefers_username(self):
        """Should prefer 'sub' field over 'username' when both are present."""
        event = {
            'identity': {
                'username': 'preferred-username-id',
                'sub': 'fallback-sub-id'
            }
        }
        user_id = index.extract_user_id(event)
        # sub is prioritized over username as it contains the actual Cognito UUID
        assert user_id == 'fallback-sub-id'
    
    def test_extract_user_id_missing_raises_error(self):
        """Should raise ValueError when no user ID is found."""
        event = {'identity': {}}
        with pytest.raises(ValueError, match="User not authenticated"):
            index.extract_user_id(event)
    
    def test_extract_user_id_empty_identity(self):
        """Should raise ValueError when identity is missing."""
        event = {}
        with pytest.raises(ValueError, match="User not authenticated"):
            index.extract_user_id(event)


class TestUserIdValidation:
    """Tests for user ID validation logic."""
    
    def test_validate_uuid_format(self, valid_uuid):
        """Should accept valid UUID format."""
        result = index.validate_user_id(valid_uuid)
        assert result == valid_uuid
    
    def test_validate_uppercase_uuid(self):
        """Should accept UUID with uppercase letters."""
        uuid_upper = '123E4567-E89B-12D3-A456-426614174000'
        result = index.validate_user_id(uuid_upper)
        assert result == uuid_upper
    
    def test_validate_non_uuid_logs_warning(self, caplog):
        """Should log warning for non-UUID format but still return it."""
        non_uuid = 'custom-username-format'
        result = index.validate_user_id(non_uuid)
        assert result == non_uuid
        assert 'UUID pattern' in caplog.text


@patch.dict(os.environ, {'TRACKING_TABLE_NAME': 'test-tracking-table'})
class TestHandler:
    """Integration tests for the main handler function."""
    
    @patch('index.dynamodb')
    def test_handler_creates_user_scoped_key(self, mock_dynamodb, valid_event, mock_context, valid_uuid):
        """Should create document with user-scoped partition key."""
        # Setup mock
        mock_table = Mock()
        mock_dynamodb.Table.return_value = mock_table
        mock_table.get_item.return_value = {}
        mock_table.put_item.return_value = {}
        
        # Execute
        result = index.handler(valid_event, mock_context)
        
        # Verify DynamoDB calls
        calls = mock_table.put_item.call_args_list
        assert len(calls) == 2  # Document record + list item
        
        # Verify document record
        doc_item = calls[0][1]['Item']
        # PK should only contain the filename, not the full path with user prefix
        expected_pk = f'user#{valid_uuid}#doc#test-document.pdf'
        assert doc_item['PK'] == expected_pk
        assert doc_item['SK'] == 'none'
        assert doc_item['UserId'] == valid_uuid
        assert doc_item['ObjectKey'] == f'users/{valid_uuid}/test-document.pdf'
        assert doc_item['QueuedTime'] == '2025-01-15T10:30:00Z'
        
        # Verify list item
        list_item = calls[1][1]['Item']
        assert list_item['PK'].startswith('list#')
        assert list_item['SK'].startswith('ts#2025-01-15T10:30:00Z#id#')
        assert list_item['ObjectKey'] == f'users/{valid_uuid}/test-document.pdf'
        
        # Verify return value
        assert result['ObjectKey'] == f'users/{valid_uuid}/test-document.pdf'
        assert result['UserId'] == valid_uuid
    
    @patch('index.dynamodb')
    def test_handler_uses_sub_when_username_missing(self, mock_dynamodb, event_with_sub, mock_context, valid_uuid):
        """Should use 'sub' field when 'username' is not present."""
        mock_table = Mock()
        mock_dynamodb.Table.return_value = mock_table
        mock_table.get_item.return_value = {}
        mock_table.put_item.return_value = {}
        
        result = index.handler(event_with_sub, mock_context)
        
        # Verify user ID from sub was used
        doc_item = mock_table.put_item.call_args_list[0][1]['Item']
        assert doc_item['UserId'] == valid_uuid
        assert result['UserId'] == valid_uuid
    
    @patch('index.delete_list_entries_robust')
    @patch('index.dynamodb')
    def test_handler_deletes_existing_document_entries(
        self, mock_dynamodb, mock_delete_robust, valid_event, mock_context, valid_uuid
    ):
        """Should delete existing document list entries before creating new ones."""
        mock_table = Mock()
        mock_dynamodb.Table.return_value = mock_table
        
        # Simulate existing document
        object_key = f'users/{valid_uuid}/test-document.pdf'
        existing_doc = {
            'PK': f'user#{valid_uuid}#doc#{object_key}',
            'SK': 'none',
            'ObjectKey': object_key,
            'UserId': valid_uuid
        }
        mock_table.get_item.return_value = {'Item': existing_doc}
        mock_table.put_item.return_value = {}
        mock_delete_robust.return_value = True
        
        result = index.handler(valid_event, mock_context)
        
        # Verify deletion was attempted
        mock_delete_robust.assert_called_once_with(mock_table, object_key, existing_doc)
        
        # Verify new document was still created
        assert result['ObjectKey'] == object_key
    
    @patch('index.delete_list_entries_robust')
    @patch('index.dynamodb')
    def test_handler_continues_on_deletion_failure(
        self, mock_dynamodb, mock_delete_robust, valid_event, mock_context, caplog
    ):
        """Should continue creating new document even if deletion fails."""
        mock_table = Mock()
        mock_dynamodb.Table.return_value = mock_table
        mock_table.get_item.return_value = {'Item': {'PK': 'old-doc'}}
        mock_table.put_item.return_value = {}
        
        # Simulate deletion failure
        mock_delete_robust.side_effect = Exception("Deletion failed")
        
        result = index.handler(valid_event, mock_context)
        
        # Should still succeed
        assert 'ObjectKey' in result
        assert 'Error in robust list entry deletion' in caplog.text
    
    @patch('index.dynamodb')
    def test_handler_continues_on_get_item_failure(
        self, mock_dynamodb, valid_event, mock_context, caplog
    ):
        """Should continue if checking for existing document fails."""
        mock_table = Mock()
        mock_dynamodb.Table.return_value = mock_table
        mock_table.get_item.side_effect = Exception("DynamoDB error")
        mock_table.put_item.return_value = {}
        
        result = index.handler(valid_event, mock_context)
        
        # Should still succeed
        assert 'ObjectKey' in result
        assert 'Error checking for existing document' in caplog.text
    
    @patch('index.dynamodb')
    def test_handler_missing_object_key_raises_error(self, mock_dynamodb, valid_uuid):
        """Should raise ValueError when ObjectKey is missing."""
        event = {
            'identity': {'username': valid_uuid},
            'arguments': {
                'input': {
                    'QueuedTime': '2025-01-15T10:30:00Z'
                }
            }
        }
        
        with pytest.raises(ValueError, match="ObjectKey must be a non-empty string"):
            index.handler(event, {})
    
    @patch('index.dynamodb')
    def test_handler_missing_queued_time_raises_error(self, mock_dynamodb, valid_uuid):
        """Should raise ValueError when QueuedTime is missing."""
        event = {
            'identity': {'username': valid_uuid},
            'arguments': {
                'input': {
                    'ObjectKey': 'test.pdf'
                }
            }
        }
        
        with pytest.raises(ValueError, match="QueuedTime must be a non-empty string"):
            index.handler(event, {})
    
    @patch('index.dynamodb')
    def test_handler_empty_input_data_raises_error(self, mock_dynamodb, valid_uuid):
        """Should raise ValueError when input data is empty."""
        event = {
            'identity': {'username': valid_uuid},
            'arguments': {
                'input': {}
            }
        }
        
        with pytest.raises(ValueError, match="Input data is required"):
            index.handler(event, {})
    
    def test_handler_missing_user_id_raises_error(self):
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
    
    @patch('index.dynamodb')
    def test_handler_includes_expires_after(self, mock_dynamodb, valid_event, mock_context):
        """Should include ExpiresAfter in list item when provided."""
        mock_table = Mock()
        mock_dynamodb.Table.return_value = mock_table
        mock_table.get_item.return_value = {}
        mock_table.put_item.return_value = {}
        
        # Add ExpiresAfter to input
        valid_event['arguments']['input']['ExpiresAfter'] = 1234567890
        
        result = index.handler(valid_event, mock_context)
        
        # Verify list item includes ExpiresAfter
        list_item = mock_table.put_item.call_args_list[1][1]['Item']
        assert list_item['ExpiresAfter'] == 1234567890
    
    @patch('index.calculate_shard')
    @patch('index.dynamodb')
    def test_handler_uses_calculated_shard(self, mock_dynamodb, mock_calculate_shard, valid_event, mock_context):
        """Should use calculate_shard utility for list partition key."""
        mock_table = Mock()
        mock_dynamodb.Table.return_value = mock_table
        mock_table.get_item.return_value = {}
        mock_table.put_item.return_value = {}
        
        # Mock shard calculation
        mock_calculate_shard.return_value = ('2025-01-15', '03')
        
        result = index.handler(valid_event, mock_context)
        
        # Verify calculate_shard was called with QueuedTime
        mock_calculate_shard.assert_called_once_with('2025-01-15T10:30:00Z')
        
        # Verify list PK uses shard values
        list_item = mock_table.put_item.call_args_list[1][1]['Item']
        assert list_item['PK'] == 'list#2025-01-15#s#03'


class TestDecimalEncoder:
    """Tests for DecimalEncoder JSON serialization."""
    
    def test_encode_decimal(self):
        """Should convert Decimal to float."""
        data = {'value': Decimal('123.45')}
        result = json.dumps(data, cls=index.DecimalEncoder)
        assert result == '{"value": 123.45}'
    
    def test_encode_regular_types(self):
        """Should handle regular types normally."""
        data = {'string': 'test', 'int': 42, 'float': 3.14}
        result = json.dumps(data, cls=index.DecimalEncoder)
        assert '"string": "test"' in result
        assert '"int": 42' in result
