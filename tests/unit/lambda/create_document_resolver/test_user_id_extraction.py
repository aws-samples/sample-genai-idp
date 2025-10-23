"""
Unit tests for user ID extraction from Cognito identity.

Tests the extraction and validation of user IDs from AppSync/Cognito context.
"""
import pytest
import index


class TestExtractUserId:
    """Tests for extract_user_id function."""
    
    def test_extract_from_username_field(self, valid_cognito_uuid):
        """Should extract user ID from 'username' field."""
        event = {
            'identity': {
                'username': valid_cognito_uuid
            }
        }
        user_id = index.extract_user_id(event)
        assert user_id == valid_cognito_uuid
    
    def test_extract_from_sub_field(self, valid_cognito_uuid):
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
    
    def test_missing_user_id_raises_error(self):
        """Should raise ValueError when no user ID is found."""
        event = {'identity': {}}
        with pytest.raises(ValueError, match="User not authenticated"):
            index.extract_user_id(event)
    
    def test_empty_identity_raises_error(self):
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
        uuid_upper = '123E4567-E89B-12D3-A456-426614174000'
        result = index.validate_user_id(uuid_upper)
        assert result == uuid_upper
    
    def test_accepts_lowercase_uuid(self):
        """Should accept UUID with lowercase letters."""
        uuid_lower = '123e4567-e89b-12d3-a456-426614174000'
        result = index.validate_user_id(uuid_lower)
        assert result == uuid_lower
    
    def test_accepts_mixed_case_uuid(self):
        """Should accept UUID with mixed case letters."""
        uuid_mixed = '123E4567-e89b-12D3-a456-426614174000'
        result = index.validate_user_id(uuid_mixed)
        assert result == uuid_mixed
    
    def test_non_uuid_logs_warning(self, caplog):
        """Should log warning for non-UUID format but still return it."""
        non_uuid = 'custom-username-format'
        result = index.validate_user_id(non_uuid)
        assert result == non_uuid
        assert 'UUID pattern' in caplog.text
    
    def test_email_format_logs_warning(self, caplog):
        """Should log warning for email format usernames."""
        email = 'user@example.com'
        result = index.validate_user_id(email)
        assert result == email
        assert 'UUID pattern' in caplog.text
