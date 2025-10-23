"""
Unit tests for upload_resolver Lambda handler.

Tests the main handler function including presigned URL generation,
user scoping, and authentication.
"""
import pytest
import os
import json
from unittest.mock import Mock, patch
import sys

# Add Lambda source directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../../src/lambda/upload_resolver'))

import index


@patch.dict(os.environ, {'INPUT_BUCKET': 'fallback-bucket'})
class TestHandlerUserScoping:
    """Tests for user-scoped upload paths."""
    
    @patch('index.s3_client')
    def test_creates_user_scoped_path(
        self, mock_s3, valid_upload_event, mock_lambda_context, 
        valid_cognito_uuid, mock_presigned_post
    ):
        """Should create S3 path with user ID prefix."""
        # Setup
        mock_s3.generate_presigned_post.return_value = mock_presigned_post
        
        # Execute
        result = index.handler(valid_upload_event, mock_lambda_context)
        
        # Verify presigned POST was called with user-scoped key
        call_args = mock_s3.generate_presigned_post.call_args[1]
        assert call_args['Key'] == f'users/{valid_cognito_uuid}/invoice-2025.pdf'
        assert call_args['Bucket'] == 'test-input-bucket'
        
        # Verify response
        assert result['objectKey'] == f'users/{valid_cognito_uuid}/invoice-2025.pdf'
        assert result['userId'] == valid_cognito_uuid
        assert result['usePostMethod'] is True
    
    @patch('index.s3_client')
    def test_includes_user_subdirectory_in_path(
        self, mock_s3, upload_event_with_prefix, mock_lambda_context, 
        valid_cognito_uuid, mock_presigned_post
    ):
        """Should append user subdirectory after user ID."""
        # Setup
        mock_s3.generate_presigned_post.return_value = mock_presigned_post
        
        # Execute
        result = index.handler(upload_event_with_prefix, mock_lambda_context)
        
        # Verify path structure: users/<user_id>/<user_prefix>/filename
        expected_key = f'users/{valid_cognito_uuid}/invoices/2025/document.pdf'
        call_args = mock_s3.generate_presigned_post.call_args[1]
        assert call_args['Key'] == expected_key
        assert result['objectKey'] == expected_key
    
    @patch('index.s3_client')
    def test_sanitizes_filename_spaces(
        self, mock_s3, upload_event_with_spaces, mock_lambda_context, 
        valid_cognito_uuid, mock_presigned_post
    ):
        """Should replace spaces with underscores in filename."""
        # Setup
        mock_s3.generate_presigned_post.return_value = mock_presigned_post
        
        # Execute
        result = index.handler(upload_event_with_spaces, mock_lambda_context)
        
        # Verify sanitized filename
        expected_key = f'users/{valid_cognito_uuid}/My_Invoice_2025.pdf'
        call_args = mock_s3.generate_presigned_post.call_args[1]
        assert call_args['Key'] == expected_key
    
    @patch('index.s3_client')
    def test_uses_sub_when_username_missing(
        self, mock_s3, upload_event_with_sub, mock_lambda_context, 
        valid_cognito_uuid, mock_presigned_post
    ):
        """Should use 'sub' field when 'username' is not present."""
        # Setup
        mock_s3.generate_presigned_post.return_value = mock_presigned_post
        
        # Execute
        result = index.handler(upload_event_with_sub, mock_lambda_context)
        
        # Verify user ID from sub was used
        expected_key = f'users/{valid_cognito_uuid}/receipt.pdf'
        call_args = mock_s3.generate_presigned_post.call_args[1]
        assert call_args['Key'] == expected_key
        assert result['userId'] == valid_cognito_uuid


@patch.dict(os.environ, {})
class TestHandlerPresignedPost:
    """Tests for presigned POST generation."""
    
    @patch('index.s3_client')
    def test_generates_presigned_post_with_content_type(
        self, mock_s3, valid_upload_event, mock_lambda_context, mock_presigned_post
    ):
        """Should generate presigned POST with correct content type."""
        # Setup
        mock_s3.generate_presigned_post.return_value = mock_presigned_post
        
        # Execute
        result = index.handler(valid_upload_event, mock_lambda_context)
        
        # Verify presigned POST configuration
        call_args = mock_s3.generate_presigned_post.call_args[1]
        assert call_args['Fields']['Content-Type'] == 'application/pdf'
        assert call_args['ExpiresIn'] == 900  # 15 minutes
        
        # Verify conditions
        conditions = call_args['Conditions']
        assert ['content-length-range', 1, 104857600] in conditions  # 1B to 100MB
        assert {'Content-Type': 'application/pdf'} in conditions
    
    @patch('index.s3_client')
    def test_returns_presigned_post_as_json_string(
        self, mock_s3, valid_upload_event, mock_lambda_context, mock_presigned_post
    ):
        """Should return presigned POST data as JSON string."""
        # Setup
        mock_s3.generate_presigned_post.return_value = mock_presigned_post
        
        # Execute
        result = index.handler(valid_upload_event, mock_lambda_context)
        
        # Verify presignedUrl is JSON string
        assert isinstance(result['presignedUrl'], str)
        parsed_post = json.loads(result['presignedUrl'])
        assert parsed_post['url'] == mock_presigned_post['url']
        assert parsed_post['fields'] == mock_presigned_post['fields']


@patch.dict(os.environ, {})
class TestHandlerValidation:
    """Tests for input validation."""
    
    @patch('index.s3_client')
    def test_raises_error_on_missing_filename(self, mock_s3, valid_cognito_uuid):
        """Should raise ValueError when fileName is missing."""
        event = {
            'identity': {'username': valid_cognito_uuid},
            'arguments': {
                'bucket': 'test-bucket'
            }
        }
        
        with pytest.raises(ValueError, match="fileName is required"):
            index.handler(event, {})
    
    @patch('index.s3_client')
    def test_raises_error_on_missing_bucket(self, mock_s3, valid_cognito_uuid):
        """Should raise ValueError when bucket is missing and no INPUT_BUCKET."""
        event = {
            'identity': {'username': valid_cognito_uuid},
            'arguments': {
                'fileName': 'test.pdf'
            }
        }
        
        with pytest.raises(ValueError, match="bucket parameter is required"):
            index.handler(event, {})
    
    def test_raises_error_on_missing_authentication(self, upload_event_no_auth):
        """Should raise ValueError when user is not authenticated."""
        with pytest.raises(ValueError, match="User not authenticated"):
            index.handler(upload_event_no_auth, {})


@patch.dict(os.environ, {'INPUT_BUCKET': 'env-fallback-bucket'})
class TestHandlerBucketFallback:
    """Tests for INPUT_BUCKET environment variable fallback."""
    
    @patch('index.s3_client')
    def test_uses_input_bucket_fallback(
        self, mock_s3, valid_cognito_uuid, mock_lambda_context, mock_presigned_post
    ):
        """Should use INPUT_BUCKET when bucket argument not provided."""
        # Setup
        event = {
            'identity': {'username': valid_cognito_uuid},
            'arguments': {
                'fileName': 'test.pdf',
                'contentType': 'application/pdf'
                # No bucket argument
            }
        }
        mock_s3.generate_presigned_post.return_value = mock_presigned_post
        
        # Execute
        result = index.handler(event, mock_lambda_context)
        
        # Verify INPUT_BUCKET was used
        call_args = mock_s3.generate_presigned_post.call_args[1]
        assert call_args['Bucket'] == 'env-fallback-bucket'
    
    @patch('index.s3_client')
    def test_argument_bucket_overrides_fallback(
        self, mock_s3, valid_upload_event, mock_lambda_context, mock_presigned_post
    ):
        """Should use argument bucket even when INPUT_BUCKET is set."""
        # Setup
        mock_s3.generate_presigned_post.return_value = mock_presigned_post
        
        # Execute
        result = index.handler(valid_upload_event, mock_lambda_context)
        
        # Verify argument bucket was used, not env fallback
        call_args = mock_s3.generate_presigned_post.call_args[1]
        assert call_args['Bucket'] == 'test-input-bucket'


@patch.dict(os.environ, {})
class TestHandlerLogging:
    """Tests for logging behavior."""
    
    @patch('index.s3_client')
    def test_logs_user_extraction(
        self, mock_s3, valid_upload_event, mock_lambda_context, 
        valid_cognito_uuid, mock_presigned_post, caplog
    ):
        """Should log user ID extraction."""
        # Setup
        mock_s3.generate_presigned_post.return_value = mock_presigned_post
        
        # Execute
        result = index.handler(valid_upload_event, mock_lambda_context)
        
        # Verify logging
        assert f"Extracted user_id from username: {valid_cognito_uuid}" in caplog.text
        assert f"Processing upload request for user: {valid_cognito_uuid}" in caplog.text
    
    @patch('index.s3_client')
    def test_logs_user_scoped_path(
        self, mock_s3, valid_upload_event, mock_lambda_context, 
        valid_cognito_uuid, mock_presigned_post, caplog
    ):
        """Should log user-scoped upload path."""
        # Setup
        mock_s3.generate_presigned_post.return_value = mock_presigned_post
        
        # Execute
        result = index.handler(valid_upload_event, mock_lambda_context)
        
        # Verify path logging
        assert f"User-scoped upload path: users/{valid_cognito_uuid}/invoice-2025.pdf" in caplog.text
    
    @patch('index.s3_client')
    def test_logs_errors_with_traceback(
        self, mock_s3, valid_upload_event, mock_lambda_context, caplog
    ):
        """Should log errors with exception info."""
        # Setup
        mock_s3.generate_presigned_post.side_effect = Exception("S3 error")
        
        # Execute
        with pytest.raises(Exception):
            index.handler(valid_upload_event, mock_lambda_context)
        
        # Verify error logging
        assert "Error generating presigned URL" in caplog.text


@patch.dict(os.environ, {})
class TestHandlerS3Errors:
    """Tests for S3 error handling."""
    
    @patch('index.s3_client')
    def test_raises_error_on_s3_failure(
        self, mock_s3, valid_upload_event, mock_lambda_context
    ):
        """Should raise exception when S3 generate_presigned_post fails."""
        # Setup
        mock_s3.generate_presigned_post.side_effect = Exception("S3 connection failed")
        
        # Execute and verify
        with pytest.raises(Exception, match="S3 connection failed"):
            index.handler(valid_upload_event, mock_lambda_context)
