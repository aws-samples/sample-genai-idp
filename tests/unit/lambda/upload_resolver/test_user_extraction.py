"""
Unit tests for user ID extraction in upload_resolver.

Tests the extract_user_id and validate_user_id functions.
"""
import pytest
import sys
import os

# Add Lambda source directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../../src/lambda/upload_resolver'))

import index


class TestExtractUserId:
    """Tests for extract_user_id function."""
    
    def test_extracts_from_username_field(self, valid_cognito_uuid):
        """Should extract user ID from 'username' field."""
        event = {
            'identity': {
                'username': valid_cognito_uuid
            }
        }
        
        user_id = index.extract_user_id(event)
        
        assert user_id == valid_cognito_uuid
    
    def test_extracts_from_sub_field(self, valid_cognito_uuid):
        """Should extract user ID from 'sub' field when username is missing."""
        event = {
            'identity': {
                'sub': valid_cognito_uuid
            }
        }
        
        user_id = index.extract_user_id(event)
        
        assert user_id == valid_cognito_uuid
    
    def test_prefers_sub_over_username(self, valid_cognito_uuid):
        """Should prefer 'sub' (UUID) over 'username' (friendly name) when both are present.
        
        In Cognito AppSync context:
        - 'sub' contains the actual Cognito UUID (e.g., f364c882-40b1-70c3-7277-bfbe122eebc5)
        - 'username' contains the friendly username (e.g., 'josian')
        
        We must use 'sub' for proper user isolation.
        """
        event = {
            'identity': {
                'username': 'josian',  # Friendly name - should NOT be used
                'sub': valid_cognito_uuid  # Actual Cognito UUID - should be used
            }
        }
        
        user_id = index.extract_user_id(event)
        
        # Should extract the UUID from 'sub', not the friendly name from 'username'
        assert user_id == valid_cognito_uuid
        assert user_id != 'josian'
    
    def test_raises_error_on_missing_user_id(self):
        """Should raise ValueError when no user ID is found."""
        event = {'identity': {}}
        
        with pytest.raises(ValueError, match="User not authenticated"):
            index.extract_user_id(event)
    
    def test_raises_error_on_missing_identity(self):
        """Should raise ValueError when identity context is missing."""
        event = {}
        
        with pytest.raises(ValueError, match="User not authenticated"):
            index.extract_user_id(event)
    
    def test_logs_username_extraction(self, valid_cognito_uuid, caplog):
        """Should log when extracting from username field."""
        event = {'identity': {'username': valid_cognito_uuid}}
        
        index.extract_user_id(event)
        
        assert 'Extracted user_id from username' in caplog.text
    
    def test_logs_sub_extraction(self, valid_cognito_uuid, caplog):
        """Should log when extracting from sub field."""
        event = {'identity': {'sub': valid_cognito_uuid}}
        
        index.extract_user_id(event)
        
        assert 'Extracted user_id from sub' in caplog.text


class TestValidateUserId:
    """Tests for validate_user_id function."""
    
    def test_accepts_valid_uuid(self, valid_cognito_uuid):
        """Should accept and return valid UUID format."""
        result = index.validate_user_id(valid_cognito_uuid)
        
        assert result == valid_cognito_uuid
    
    def test_accepts_uppercase_uuid(self):
        """Should accept UUID with uppercase letters."""
        uuid_upper = 'A1B2C3D4-E5F6-7890-ABCD-EF1234567890'
        
        result = index.validate_user_id(uuid_upper)
        
        assert result == uuid_upper
    
    def test_accepts_mixed_case_uuid(self):
        """Should accept UUID with mixed case."""
        uuid_mixed = 'A1b2C3d4-e5F6-7890-aBcD-eF1234567890'
        
        result = index.validate_user_id(uuid_mixed)
        
        assert result == uuid_mixed
    
    def test_logs_warning_for_non_uuid(self, caplog):
        """Should log warning for non-UUID format but still return it."""
        non_uuid = 'custom-username-format'
        
        result = index.validate_user_id(non_uuid)
        
        assert result == non_uuid
        assert 'UUID pattern' in caplog.text
    
    def test_logs_warning_for_email_format(self, caplog):
        """Should log warning for email format usernames."""
        email = 'user@example.com'
        
        result = index.validate_user_id(email)
        
        assert result == email
        assert 'UUID pattern' in caplog.text
