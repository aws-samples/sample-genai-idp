"""
Unit tests for user ID extraction logic in queue_sender.

Tests the extract_user_id_from_path and validate_user_id functions.
"""
import pytest
import sys
import os

# Add Lambda source directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../../src/lambda/queue_sender'))

import index


class TestExtractUserIdFromPath:
    """Tests for extract_user_id_from_path function."""
    
    def test_extracts_user_id_from_valid_path(self, valid_cognito_uuid):
        """Should extract user ID from valid path."""
        object_key = f'users/{valid_cognito_uuid}/document.pdf'
        
        result = index.extract_user_id_from_path(object_key)
        
        assert result == valid_cognito_uuid
    
    def test_extracts_user_id_from_nested_path(self, valid_cognito_uuid):
        """Should extract user ID from nested path structure."""
        object_key = f'users/{valid_cognito_uuid}/folder/subfolder/document.pdf'
        
        result = index.extract_user_id_from_path(object_key)
        
        assert result == valid_cognito_uuid
    
    def test_raises_error_on_missing_users_prefix(self):
        """Should raise ValueError when path doesn't start with 'users/'."""
        object_key = 'documents/test-document.pdf'
        
        with pytest.raises(ValueError, match=r"Invalid path format.*Expected 'users/"):
            index.extract_user_id_from_path(object_key)
    
    def test_raises_error_on_short_path(self):
        """Should raise ValueError when path has insufficient parts."""
        object_key = 'users/test-user'
        
        with pytest.raises(ValueError, match="Invalid path structure.*Expected at least 3 parts"):
            index.extract_user_id_from_path(object_key)
    
    def test_raises_error_on_empty_user_id(self):
        """Should raise ValueError when user ID is empty."""
        object_key = 'users//document.pdf'
        
        with pytest.raises(ValueError, match="User ID is empty in path"):
            index.extract_user_id_from_path(object_key)
    
    def test_handles_special_characters_in_filename(self, valid_cognito_uuid):
        """Should handle filenames with special characters."""
        object_key = f'users/{valid_cognito_uuid}/my document (2024).pdf'
        
        result = index.extract_user_id_from_path(object_key)
        
        assert result == valid_cognito_uuid
    
    def test_handles_unicode_in_filename(self, valid_cognito_uuid):
        """Should handle filenames with unicode characters."""
        object_key = f'users/{valid_cognito_uuid}/документ.pdf'
        
        result = index.extract_user_id_from_path(object_key)
        
        assert result == valid_cognito_uuid


class TestValidateUserId:
    """Tests for validate_user_id function."""
    
    def test_accepts_valid_uuid(self, valid_cognito_uuid):
        """Should accept valid Cognito UUID format."""
        result = index.validate_user_id(valid_cognito_uuid)
        
        assert result == valid_cognito_uuid
    
    def test_accepts_uppercase_uuid(self):
        """Should accept UUID with uppercase letters."""
        user_id = 'A1B2C3D4-E5F6-7890-ABCD-EF1234567890'
        
        result = index.validate_user_id(user_id)
        
        assert result == user_id
    
    def test_accepts_mixed_case_uuid(self):
        """Should accept UUID with mixed case."""
        user_id = 'A1b2C3d4-e5F6-7890-aBcD-eF1234567890'
        
        result = index.validate_user_id(user_id)
        
        assert result == user_id
    
    def test_logs_warning_for_non_uuid_format(self, caplog):
        """Should log warning for non-UUID format but still return it."""
        user_id = 'admin-user-123'
        
        result = index.validate_user_id(user_id)
        
        assert result == user_id
        assert "doesn't match UUID pattern" in caplog.text
    
    def test_logs_warning_for_short_string(self, caplog):
        """Should log warning for too-short user ID."""
        user_id = 'short'
        
        result = index.validate_user_id(user_id)
        
        assert result == user_id
        assert "doesn't match UUID pattern" in caplog.text
    
    def test_accepts_all_numeric_segments(self):
        """Should accept UUID with all numeric segments."""
        user_id = '12345678-1234-1234-1234-123456789012'
        
        result = index.validate_user_id(user_id)
        
        assert result == user_id
