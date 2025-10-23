"""
Unit tests for queue_sender Lambda handler.

Tests the main handler function including S3 event processing,
user extraction, and SQS message sending.
"""
import pytest
import os
import json
from unittest.mock import Mock, patch
import sys

# Add Lambda source directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../../src/lambda/queue_sender'))

import index


@patch.dict(os.environ, {
    'QUEUE_URL': 'https://sqs.us-east-1.amazonaws.com/123456789012/test-queue',
    'APPSYNC_API_URL': 'https://test-api.appsync-api.us-east-1.amazonaws.com/graphql',
    'DATA_RETENTION_IN_DAYS': '30',
    'OUTPUT_BUCKET': 'test-output-bucket'
})
class TestHandlerMessageSending:
    """Tests for SQS message sending logic."""
    
    @patch('index.sqs')
    def test_sends_message_with_user_context(
        self, mock_sqs, valid_s3_event, mock_lambda_context, 
        valid_cognito_uuid, mock_sqs_response
    ):
        """Should send SQS message with user ID extracted from path."""
        # Setup
        mock_sqs.send_message.return_value = mock_sqs_response
        
        # Execute
        result = index.handler(valid_s3_event, mock_lambda_context)
        
        # Verify SQS call
        mock_sqs.send_message.assert_called_once()
        call_args = mock_sqs.send_message.call_args[1]
        
        # Verify queue URL
        assert call_args['QueueUrl'] == os.environ['QUEUE_URL']
        
        # Verify message body
        message_body = json.loads(call_args['MessageBody'])
        assert message_body['Bucket'] == 'test-input-bucket'
        assert message_body['ObjectKey'] == f'users/{valid_cognito_uuid}/test-document.pdf'
        assert message_body['UserId'] == valid_cognito_uuid
        assert 'EventTime' in message_body
        
        # Verify message attributes
        attrs = call_args['MessageAttributes']
        assert attrs['UserId']['StringValue'] == valid_cognito_uuid
        assert attrs['UserId']['DataType'] == 'String'
        assert attrs['ObjectKey']['StringValue'] == f'users/{valid_cognito_uuid}/test-document.pdf'
        
        # Verify response
        assert result['statusCode'] == 200
        response_body = json.loads(result['body'])
        assert response_body['userId'] == valid_cognito_uuid
        assert response_body['messageId'] == 'test-message-id-12345'
    
    @patch('index.sqs')
    def test_includes_last_modified_time(
        self, mock_sqs, valid_s3_event, mock_lambda_context, mock_sqs_response
    ):
        """Should use S3 last-modified time when available."""
        # Setup
        mock_sqs.send_message.return_value = mock_sqs_response
        
        # Execute
        result = index.handler(valid_s3_event, mock_lambda_context)
        
        # Verify EventTime in message
        call_args = mock_sqs.send_message.call_args[1]
        message_body = json.loads(call_args['MessageBody'])
        assert message_body['EventTime'] == '2025-01-15T10:30:00Z'
    
    @patch('index.datetime')
    @patch('index.sqs')
    def test_uses_current_time_when_last_modified_missing(
        self, mock_sqs, mock_datetime, mock_lambda_context, mock_sqs_response
    ):
        """Should use current time when last-modified is not provided."""
        # Setup
        event = {
            'detail': {
                'bucket': {'name': 'test-bucket'},
                'object': {'key': 'users/test-user-id/doc.pdf'}
            }
        }
        mock_sqs.send_message.return_value = mock_sqs_response
        mock_now = Mock()
        mock_now.isoformat.return_value = '2025-01-15T12:00:00Z'
        mock_datetime.now.return_value = mock_now
        
        # Execute
        result = index.handler(event, mock_lambda_context)
        
        # Verify current time was used
        call_args = mock_sqs.send_message.call_args[1]
        message_body = json.loads(call_args['MessageBody'])
        assert message_body['EventTime'] == '2025-01-15T12:00:00Z'
    
    @patch('index.sqs')
    def test_handles_nested_user_paths(
        self, mock_sqs, s3_event_with_nested_path, 
        mock_lambda_context, valid_cognito_uuid, mock_sqs_response
    ):
        """Should correctly extract user ID from nested path structure."""
        # Setup
        mock_sqs.send_message.return_value = mock_sqs_response
        
        # Execute
        result = index.handler(s3_event_with_nested_path, mock_lambda_context)
        
        # Verify user ID extraction
        call_args = mock_sqs.send_message.call_args[1]
        message_body = json.loads(call_args['MessageBody'])
        assert message_body['UserId'] == valid_cognito_uuid
        assert message_body['ObjectKey'] == f'users/{valid_cognito_uuid}/subfolder/nested/document.pdf'


@patch.dict(os.environ, {
    'QUEUE_URL': 'https://sqs.us-east-1.amazonaws.com/123456789012/test-queue'
})
class TestHandlerValidation:
    """Tests for input validation and error handling."""
    
    @patch('index.sqs')
    def test_raises_error_on_missing_bucket_name(self, mock_sqs, mock_lambda_context):
        """Should raise ValueError when bucket name is missing."""
        event = {
            'detail': {
                'object': {'key': 'users/test-user/doc.pdf'}
            }
        }
        
        with pytest.raises(ValueError, match="Missing bucket name or object key"):
            index.handler(event, mock_lambda_context)
    
    @patch('index.sqs')
    def test_raises_error_on_missing_object_key(self, mock_sqs, mock_lambda_context):
        """Should raise ValueError when object key is missing."""
        event = {
            'detail': {
                'bucket': {'name': 'test-bucket'}
            }
        }
        
        with pytest.raises(ValueError, match="Missing bucket name or object key"):
            index.handler(event, mock_lambda_context)
    
    @patch('index.sqs')
    def test_raises_error_on_invalid_path_format(
        self, mock_sqs, s3_event_invalid_path, mock_lambda_context
    ):
        """Should raise ValueError for invalid path format."""
        with pytest.raises(ValueError, match="Invalid path format"):
            index.handler(s3_event_invalid_path, mock_lambda_context)
    
    @patch('index.sqs')
    def test_raises_error_on_empty_user_id(
        self, mock_sqs, s3_event_empty_user_id, mock_lambda_context
    ):
        """Should raise ValueError when user ID is empty."""
        with pytest.raises(ValueError, match="User ID is empty"):
            index.handler(s3_event_empty_user_id, mock_lambda_context)
    
    @patch('index.sqs')
    def test_raises_error_on_short_path(
        self, mock_sqs, s3_event_short_path, mock_lambda_context
    ):
        """Should raise ValueError when path is too short."""
        with pytest.raises(ValueError, match="Invalid path structure"):
            index.handler(s3_event_short_path, mock_lambda_context)
    
    @patch('index.sqs')
    def test_logs_path_validation_error(
        self, mock_sqs, s3_event_invalid_path, mock_lambda_context, caplog
    ):
        """Should log path validation errors before raising."""
        with pytest.raises(ValueError):
            index.handler(s3_event_invalid_path, mock_lambda_context)
        
        assert "Path validation error" in caplog.text


@patch.dict(os.environ, {
    'QUEUE_URL': 'https://sqs.us-east-1.amazonaws.com/123456789012/test-queue'
})
class TestHandlerNonUuidUsers:
    """Tests for handling non-UUID user IDs (warning but not blocking)."""
    
    @patch('index.sqs')
    def test_processes_non_uuid_user_id_with_warning(
        self, mock_sqs, s3_event_non_uuid_user, 
        mock_lambda_context, mock_sqs_response, caplog
    ):
        """Should process non-UUID user ID but log warning."""
        # Setup
        mock_sqs.send_message.return_value = mock_sqs_response
        
        # Execute
        result = index.handler(s3_event_non_uuid_user, mock_lambda_context)
        
        # Verify warning was logged
        assert "doesn't match UUID pattern" in caplog.text
        
        # Verify message was still sent
        assert result['statusCode'] == 200
        call_args = mock_sqs.send_message.call_args[1]
        message_body = json.loads(call_args['MessageBody'])
        assert message_body['UserId'] == 'admin-user'


@patch.dict(os.environ, {
    'QUEUE_URL': 'https://sqs.us-east-1.amazonaws.com/123456789012/test-queue'
})
class TestHandlerSqsErrors:
    """Tests for SQS error handling."""
    
    @patch('index.sqs')
    def test_raises_error_on_sqs_failure(
        self, mock_sqs, valid_s3_event, mock_lambda_context
    ):
        """Should raise exception when SQS send_message fails."""
        # Setup
        mock_sqs.send_message.side_effect = Exception("SQS connection failed")
        
        # Execute and verify
        with pytest.raises(Exception, match="SQS connection failed"):
            index.handler(valid_s3_event, mock_lambda_context)
    
    @patch('index.sqs')
    def test_logs_sqs_error(
        self, mock_sqs, valid_s3_event, mock_lambda_context, caplog
    ):
        """Should log SQS errors with full context."""
        # Setup
        mock_sqs.send_message.side_effect = Exception("SQS error")
        
        # Execute
        with pytest.raises(Exception):
            index.handler(valid_s3_event, mock_lambda_context)
        
        # Verify logging
        assert "Error in QueueSender" in caplog.text


@patch.dict(os.environ, {
    'QUEUE_URL': 'https://sqs.us-east-1.amazonaws.com/123456789012/test-queue'
})
class TestHandlerLogging:
    """Tests for logging behavior."""
    
    @patch('index.sqs')
    def test_logs_event_details(
        self, mock_sqs, valid_s3_event, mock_lambda_context, 
        mock_sqs_response, caplog
    ):
        """Should log comprehensive event details."""
        # Setup
        mock_sqs.send_message.return_value = mock_sqs_response
        
        # Execute
        result = index.handler(valid_s3_event, mock_lambda_context)
        
        # Verify logging
        assert "QueueSender invoked with event" in caplog.text
        assert "Processing S3 event" in caplog.text
        assert "test-input-bucket" in caplog.text
    
    @patch('index.sqs')
    def test_logs_extracted_user_id(
        self, mock_sqs, valid_s3_event, mock_lambda_context, 
        valid_cognito_uuid, mock_sqs_response, caplog
    ):
        """Should log extracted user ID."""
        # Setup
        mock_sqs.send_message.return_value = mock_sqs_response
        
        # Execute
        result = index.handler(valid_s3_event, mock_lambda_context)
        
        # Verify user ID logging
        assert f"Extracted user_id: {valid_cognito_uuid}" in caplog.text
        assert f"Sending message to SQS with UserId: {valid_cognito_uuid}" in caplog.text
    
    @patch('index.sqs')
    def test_logs_successful_message_id(
        self, mock_sqs, valid_s3_event, mock_lambda_context, 
        mock_sqs_response, caplog
    ):
        """Should log SQS message ID on success."""
        # Setup
        mock_sqs.send_message.return_value = mock_sqs_response
        
        # Execute
        result = index.handler(valid_s3_event, mock_lambda_context)
        
        # Verify message ID logging
        assert "Successfully sent message to SQS" in caplog.text
        assert "test-message-id-12345" in caplog.text
