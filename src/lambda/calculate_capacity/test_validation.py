# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for validation module."""

import json
import os
import pytest
from unittest.mock import patch
from validation import (
    ValidationError,
    validate_required_env_vars,
    sanitize_json_input,
    validate_capacity_input,
    get_validated_env_vars,
)


class TestEnvironmentValidation:
    """Tests for environment variable validation."""

    @pytest.fixture
    def valid_env_vars(self):
        """Fixture providing valid environment variables."""
        return {
            'TRACKING_TABLE': 'test-tracking-table',
            'METERING_TABLE_NAME': 'test-metering-table',
            'LAMBDA_MEMORY_GB': '1.0',
            'RECOMMENDATION_HIGH_COMPLEXITY_THRESHOLD': '2.5',
            'RECOMMENDATION_MEDIUM_COMPLEXITY_THRESHOLD': '1.5',
            'RECOMMENDATION_HIGH_LOAD_THRESHOLD': '3.0',
            'RECOMMENDATION_MEDIUM_LOAD_THRESHOLD': '2.0',
            'RECOMMENDATION_HIGH_LATENCY_THRESHOLD': '300',
            'RECOMMENDATION_LARGE_DOC_THRESHOLD': '50000',
            'RECOMMENDATION_HIGH_PAGE_THRESHOLD': '20',
            'MEDIUM_COMPLEXITY_THRESHOLD': '5000',
            'HIGH_COMPLEXITY_THRESHOLD': '15000',
            'PAGE_COMPLEXITY_FACTOR': '0.1',
            'HIGH_COMPLEXITY_MULTIPLIER': '2.0',
            'MEDIUM_COMPLEXITY_MULTIPLIER': '1.5',
            'MIN_TOKENS_PER_REQUEST': '500',
            'BEDROCK_MODEL_QUOTA_CODES': '{"model1": "L-12345"}',
            'BEDROCK_MODEL_RPM_QUOTA_CODES': '{"model1": "L-67890"}',
        }

    def test_validate_all_required_vars_present(self, valid_env_vars):
        """Test validation passes when all required vars are present."""
        with patch.dict(os.environ, valid_env_vars, clear=True):
            result = validate_required_env_vars()
            assert result['tracking_table'] == 'test-tracking-table'
            assert result['lambda_memory_gb'] == 1.0
            assert result['min_tokens_per_request'] == 500
            assert isinstance(result['bedrock_model_quota_codes'], dict)

    def test_validate_missing_tracking_table(self, valid_env_vars):
        """Test validation fails when TRACKING_TABLE is missing."""
        env_vars = valid_env_vars.copy()
        del env_vars['TRACKING_TABLE']

        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                validate_required_env_vars()
            assert 'TRACKING_TABLE' in str(exc_info.value)

    def test_validate_invalid_lambda_memory(self, valid_env_vars):
        """Test validation fails with invalid LAMBDA_MEMORY_GB."""
        env_vars = valid_env_vars.copy()
        env_vars['LAMBDA_MEMORY_GB'] = 'invalid'

        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                validate_required_env_vars()
            assert 'LAMBDA_MEMORY_GB' in str(exc_info.value)

    def test_validate_negative_lambda_memory(self, valid_env_vars):
        """Test validation fails with negative LAMBDA_MEMORY_GB."""
        env_vars = valid_env_vars.copy()
        env_vars['LAMBDA_MEMORY_GB'] = '-1.0'

        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                validate_required_env_vars()
            assert 'positive' in str(exc_info.value).lower()

    def test_validate_invalid_json_quota_codes(self, valid_env_vars):
        """Test validation fails with invalid JSON in quota codes."""
        env_vars = valid_env_vars.copy()
        env_vars['BEDROCK_MODEL_QUOTA_CODES'] = 'invalid json'

        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                validate_required_env_vars()
            assert 'BEDROCK_MODEL_QUOTA_CODES' in str(exc_info.value)
            assert 'JSON' in str(exc_info.value)

    def test_validate_empty_quota_codes(self, valid_env_vars):
        """Test validation fails with empty quota codes."""
        env_vars = valid_env_vars.copy()
        env_vars['BEDROCK_MODEL_QUOTA_CODES'] = '{}'

        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValidationError) as exc_info:
                validate_required_env_vars()
            assert 'cannot be empty' in str(exc_info.value)


class TestJSONSanitization:
    """Tests for JSON input sanitization."""

    def test_sanitize_valid_json(self):
        """Test sanitization of valid JSON object."""
        input_str = '{"key": "value", "number": 123}'
        result = sanitize_json_input(input_str)
        assert result == {"key": "value", "number": 123}

    def test_sanitize_invalid_json(self):
        """Test sanitization fails with invalid JSON."""
        with pytest.raises(ValidationError) as exc_info:
            sanitize_json_input('{"invalid": }')
        assert 'Invalid JSON format' in str(exc_info.value)

    def test_sanitize_non_object_json(self):
        """Test sanitization fails when JSON is not an object."""
        with pytest.raises(ValidationError) as exc_info:
            sanitize_json_input('["array"]')
        assert 'must be a JSON object' in str(exc_info.value)

    def test_sanitize_non_string_input(self):
        """Test sanitization fails with non-string input."""
        with pytest.raises(ValidationError) as exc_info:
            sanitize_json_input(123)
        assert 'must be a string' in str(exc_info.value)

    def test_sanitize_exceeds_size_limit(self):
        """Test sanitization fails when input exceeds size limit."""
        large_input = '{"key": "' + ('x' * 1_000_000) + '"}'
        with pytest.raises(ValidationError) as exc_info:
            sanitize_json_input(large_input, max_size_bytes=1000)
        assert 'exceeds maximum size' in str(exc_info.value)

    def test_sanitize_respects_custom_size_limit(self):
        """Test sanitization respects custom size limits."""
        input_str = '{"key": "value"}'
        # Should pass with large limit
        result = sanitize_json_input(input_str, max_size_bytes=1_000_000)
        assert result == {"key": "value"}


class TestCapacityInputValidation:
    """Tests for capacity input validation."""

    def test_validate_valid_input(self):
        """Test validation passes with valid input."""
        input_data = {
            'pattern': 'pattern-2',
            'maxAllowedLatency': 60,
            'documentConfigs': [
                {
                    'type': 'invoice',
                    'avgPages': 5,
                    'ocrTokens': 1000,
                    'classificationTokens': 500,
                    'extractionTokens': 2000,
                }
            ],
        }
        # Should not raise
        validate_capacity_input(input_data)

    def test_validate_missing_pattern(self):
        """Test validation fails when pattern is missing."""
        input_data = {
            'maxAllowedLatency': 60,
            'documentConfigs': [{'type': 'invoice'}],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_capacity_input(input_data)
        assert 'pattern is required' in str(exc_info.value)

    def test_validate_unsupported_pattern(self):
        """Test validation fails with unsupported pattern."""
        input_data = {
            'pattern': 'pattern-1',
            'maxAllowedLatency': 60,
            'documentConfigs': [{'type': 'invoice'}],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_capacity_input(input_data)
        assert 'pattern-2 is supported' in str(exc_info.value)

    def test_validate_missing_max_latency(self):
        """Test validation fails when maxAllowedLatency is missing."""
        input_data = {
            'pattern': 'pattern-2',
            'documentConfigs': [{'type': 'invoice'}],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_capacity_input(input_data)
        assert 'maxAllowedLatency' in str(exc_info.value)

    def test_validate_negative_max_latency(self):
        """Test validation fails with negative maxAllowedLatency."""
        input_data = {
            'pattern': 'pattern-2',
            'maxAllowedLatency': -10,
            'documentConfigs': [{'type': 'invoice'}],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_capacity_input(input_data)
        assert 'must be positive' in str(exc_info.value)

    def test_validate_excessive_max_latency(self):
        """Test validation fails with excessive maxAllowedLatency."""
        input_data = {
            'pattern': 'pattern-2',
            'maxAllowedLatency': 5000,
            'documentConfigs': [{'type': 'invoice'}],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_capacity_input(input_data)
        assert 'cannot exceed 3600' in str(exc_info.value)

    def test_validate_empty_document_configs(self):
        """Test validation fails with empty documentConfigs."""
        input_data = {
            'pattern': 'pattern-2',
            'maxAllowedLatency': 60,
            'documentConfigs': [],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_capacity_input(input_data)
        assert 'cannot be empty' in str(exc_info.value)

    def test_validate_document_config_missing_type(self):
        """Test validation fails when document config missing type."""
        input_data = {
            'pattern': 'pattern-2',
            'maxAllowedLatency': 60,
            'documentConfigs': [{'avgPages': 5}],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_capacity_input(input_data)
        assert 'type is required' in str(exc_info.value)

    def test_validate_document_config_negative_values(self):
        """Test validation fails with negative token values."""
        input_data = {
            'pattern': 'pattern-2',
            'maxAllowedLatency': 60,
            'documentConfigs': [
                {
                    'type': 'invoice',
                    'avgPages': 5,
                    'ocrTokens': -100,
                }
            ],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_capacity_input(input_data)
        assert 'cannot be negative' in str(exc_info.value)

    def test_validate_time_slots_invalid_hour(self):
        """Test validation fails with invalid hour in time slots."""
        input_data = {
            'pattern': 'pattern-2',
            'maxAllowedLatency': 60,
            'documentConfigs': [{'type': 'invoice'}],
            'timeSlots': [{'hour': 25, 'docsPerHour': 100}],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_capacity_input(input_data)
        assert 'between 0 and 23' in str(exc_info.value)

    def test_validate_time_slots_negative_docs(self):
        """Test validation fails with negative docsPerHour."""
        input_data = {
            'pattern': 'pattern-2',
            'maxAllowedLatency': 60,
            'documentConfigs': [{'type': 'invoice'}],
            'timeSlots': [{'hour': 9, 'docsPerHour': -10}],
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_capacity_input(input_data)
        assert 'cannot be negative' in str(exc_info.value)

    def test_validate_invalid_user_config_json(self):
        """Test validation fails with invalid userConfig JSON."""
        input_data = {
            'pattern': 'pattern-2',
            'maxAllowedLatency': 60,
            'documentConfigs': [{'type': 'invoice'}],
            'userConfig': 'invalid json',
        }
        with pytest.raises(ValidationError) as exc_info:
            validate_capacity_input(input_data)
        assert 'userConfig must be valid JSON' in str(exc_info.value)


class TestGetValidatedEnvVars:
    """Tests for caching of validated environment variables."""

    @pytest.fixture(autouse=True)
    def reset_cache(self):
        """Reset the global cache before each test."""
        import validation
        validation._validated_env_vars = None

    def test_get_validated_env_vars_caches_result(self, valid_env_vars):
        """Test that validated env vars are cached."""
        with patch.dict(os.environ, valid_env_vars, clear=True):
            # First call should validate and cache
            result1 = get_validated_env_vars()
            # Second call should return cached result
            result2 = get_validated_env_vars()

            assert result1 is result2  # Same object reference
            assert result1['tracking_table'] == 'test-tracking-table'

    @pytest.fixture
    def valid_env_vars(self):
        """Fixture providing valid environment variables."""
        return {
            'TRACKING_TABLE': 'test-tracking-table',
            'METERING_TABLE_NAME': 'test-metering-table',
            'LAMBDA_MEMORY_GB': '1.0',
            'RECOMMENDATION_HIGH_COMPLEXITY_THRESHOLD': '2.5',
            'RECOMMENDATION_MEDIUM_COMPLEXITY_THRESHOLD': '1.5',
            'RECOMMENDATION_HIGH_LOAD_THRESHOLD': '3.0',
            'RECOMMENDATION_MEDIUM_LOAD_THRESHOLD': '2.0',
            'RECOMMENDATION_HIGH_LATENCY_THRESHOLD': '300',
            'RECOMMENDATION_LARGE_DOC_THRESHOLD': '50000',
            'RECOMMENDATION_HIGH_PAGE_THRESHOLD': '20',
            'MEDIUM_COMPLEXITY_THRESHOLD': '5000',
            'HIGH_COMPLEXITY_THRESHOLD': '15000',
            'PAGE_COMPLEXITY_FACTOR': '0.1',
            'HIGH_COMPLEXITY_MULTIPLIER': '2.0',
            'MEDIUM_COMPLEXITY_MULTIPLIER': '1.5',
            'MIN_TOKENS_PER_REQUEST': '500',
            'BEDROCK_MODEL_QUOTA_CODES': '{"model1": "L-12345"}',
            'BEDROCK_MODEL_RPM_QUOTA_CODES': '{"model1": "L-67890"}',
        }


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
