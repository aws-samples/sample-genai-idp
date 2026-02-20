# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for capacity calculation utility functions."""

import pytest
from decimal import Decimal


class TestDecimalConversion:
    """Tests for DynamoDB Decimal conversion."""

    def test_convert_decimal_to_float_integer(self):
        """Test conversion of integer Decimal to int."""
        from index import convert_decimal_to_float

        assert convert_decimal_to_float(Decimal('10')) == 10
        assert isinstance(convert_decimal_to_float(Decimal('10')), int)

    def test_convert_decimal_to_float_float(self):
        """Test conversion of float Decimal to float."""
        from index import convert_decimal_to_float

        assert convert_decimal_to_float(Decimal('10.5')) == 10.5
        assert isinstance(convert_decimal_to_float(Decimal('10.5')), float)

    def test_convert_decimal_nested_dict(self):
        """Test conversion in nested dictionary."""
        from index import convert_decimal_to_float

        result = convert_decimal_to_float({
            'a': Decimal('10'),
            'b': {'c': Decimal('20.5')},
        })
        assert result == {'a': 10, 'b': {'c': 20.5}}

    def test_convert_decimal_list(self):
        """Test conversion in list."""
        from index import convert_decimal_to_float

        result = convert_decimal_to_float([Decimal('1'), Decimal('2.5')])
        assert result == [1, 2.5]

    def test_convert_decimal_non_decimal_values(self):
        """Test that non-Decimal values pass through unchanged."""
        from index import convert_decimal_to_float

        assert convert_decimal_to_float('string') == 'string'
        assert convert_decimal_to_float(123) == 123
        assert convert_decimal_to_float(None) is None
        assert convert_decimal_to_float(True) is True


class TestRecommendations:
    """Tests for recommendation generation."""

    def test_generate_recommendations_returns_list(self):
        """Test that recommendations return a list of strings."""
        from index import generate_adaptive_recommendations
        import os
        from unittest.mock import patch

        latency_dist = {
            'complexityFactor': '1.0x',
            'loadFactor': '1.0x',
            'varianceFactor': '1.0x',
            'p99': '30s',
            'exceedsLimit': False,
            'dataSource': 'document_timestamps',
        }

        quota_reqs = []
        document_configs = []

        # Mock environment variables
        with patch.dict(os.environ, {
            'RECOMMENDATION_HIGH_COMPLEXITY_THRESHOLD': '2.5',
            'RECOMMENDATION_MEDIUM_COMPLEXITY_THRESHOLD': '1.5',
            'RECOMMENDATION_HIGH_LOAD_THRESHOLD': '3.0',
            'RECOMMENDATION_MEDIUM_LOAD_THRESHOLD': '2.0',
            'RECOMMENDATION_HIGH_LATENCY_THRESHOLD': '300',
            'RECOMMENDATION_LARGE_DOC_THRESHOLD': '50000',
            'RECOMMENDATION_HIGH_PAGE_THRESHOLD': '20',
        }):
            recommendations = generate_adaptive_recommendations(
                latency_dist, quota_reqs, 100, 'pattern-2', document_configs
            )

            # Should return a list
            assert isinstance(recommendations, list)
            # Should have at least one recommendation
            assert len(recommendations) > 0
            # All recommendations should be strings
            assert all(isinstance(rec, str) for rec in recommendations)


class TestCacheConstants:
    """Tests for cache configuration constants."""

    def test_cache_duration_constant(self):
        """Test that cache duration constant is set correctly."""
        import index

        # Verify cache duration constant exists and has expected value
        assert hasattr(index, 'CACHE_DURATION_SECONDS')
        assert index.CACHE_DURATION_SECONDS == 300  # 5 minutes

    def test_cache_globals_exist(self):
        """Test that cache global variables exist."""
        import index

        # Verify cache globals exist
        assert hasattr(index, '_processing_times_cache')
        assert hasattr(index, '_cache_expiry')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
