#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Unit tests for configuration-based pricing functionality in SaveReportingData.
Tests that pricing is loaded exclusively from configuration dictionary.
"""

import pytest
from idp_common.reporting.save_reporting_data import SaveReportingData


@pytest.mark.unit
def test_pricing_from_config_with_valid_configuration():
    """Test that pricing is loaded correctly from configuration dictionary"""

    # Mock configuration data that matches the expected format
    mock_config = {
        "pricing": [
            {
                "name": "textract/detect_document_text",
                "units": [
                    {
                        "name": "pages",
                        "price": "0.002",
                    }  # Different from hardcoded value
                ],
            },
            {
                "name": "bedrock/eu.amazon.nova-lite-v1:0",
                "units": [
                    {
                        "name": "inputTokens",
                        "price": "7.0E-8",
                    },  # Different from hardcoded value
                    {"name": "outputTokens", "price": "3.0E-7"},
                ],
            },
        ]
    }

    # Create SaveReportingData instance with config dictionary
    reporter = SaveReportingData("test-bucket", config=mock_config)

    # Test that pricing is loaded from configuration
    textract_cost = reporter._get_unit_cost("textract/detect_document_text", "pages")
    nova_input_cost = reporter._get_unit_cost(
        "bedrock/eu.amazon.nova-lite-v1:0", "inputTokens"
    )
    nova_output_cost = reporter._get_unit_cost(
        "bedrock/eu.amazon.nova-lite-v1:0", "outputTokens"
    )

    # Verify the costs match the configuration values
    assert textract_cost == 0.002, f"Expected 0.002, got {textract_cost}"
    assert nova_input_cost == 7.0e-8, f"Expected 7.0e-8, got {nova_input_cost}"
    assert nova_output_cost == 3.0e-7, f"Expected 3.0e-7, got {nova_output_cost}"


@pytest.mark.unit
def test_pricing_returns_zero_when_config_fails():
    """Test that pricing returns 0.0 when configuration processing fails"""

    # Create SaveReportingData instance with invalid config
    invalid_config = {"invalid": "config"}
    reporter = SaveReportingData("test-bucket", config=invalid_config)

    # Test that pricing returns 0.0 when configuration is invalid
    textract_cost = reporter._get_unit_cost("textract/detect_document_text", "pages")
    nova_input_cost = reporter._get_unit_cost(
        "bedrock/eu.amazon.nova-lite-v1:0", "inputTokens"
    )

    # Verify the costs return 0.0 when configuration is not valid
    assert textract_cost == 0.0, f"Expected 0.0 (no valid config), got {textract_cost}"
    assert nova_input_cost == 0.0, (
        f"Expected 0.0 (no valid config), got {nova_input_cost}"
    )


@pytest.mark.unit
def test_pricing_without_config_returns_zero():
    """Test that pricing returns 0.0 when no config is provided"""

    # Create SaveReportingData instance without config
    reporter = SaveReportingData("test-bucket")

    # Test that pricing returns 0.0 when no config is available
    textract_cost = reporter._get_unit_cost("textract/detect_document_text", "pages")
    nova_input_cost = reporter._get_unit_cost(
        "bedrock/eu.amazon.nova-lite-v1:0", "inputTokens"
    )

    # Verify the costs return 0.0 when no configuration is available
    assert textract_cost == 0.0, f"Expected 0.0 (no config), got {textract_cost}"
    assert nova_input_cost == 0.0, f"Expected 0.0 (no config), got {nova_input_cost}"


@pytest.mark.unit
def test_pricing_cache_functionality():
    """Test that pricing data is cached to avoid repeated configuration processing"""

    mock_config = {
        "pricing": [
            {
                "name": "textract/detect_document_text",
                "units": [{"name": "pages", "price": "0.002"}],
            }
        ]
    }

    reporter = SaveReportingData("test-bucket", config=mock_config)

    # Call _get_unit_cost multiple times
    cost1 = reporter._get_unit_cost("textract/detect_document_text", "pages")
    cost2 = reporter._get_unit_cost("textract/detect_document_text", "pages")
    cost3 = reporter._get_unit_cost("textract/detect_document_text", "pages")

    # Verify all calls return the same value
    assert cost1 == cost2 == cost3 == 0.002


@pytest.mark.unit
def test_clear_pricing_cache():
    """Test that clearing the cache forces reload of configuration"""

    mock_config = {
        "pricing": [
            {
                "name": "textract/detect_document_text",
                "units": [{"name": "pages", "price": "0.002"}],
            }
        ]
    }

    reporter = SaveReportingData("test-bucket", config=mock_config)

    # First call loads from config
    cost1 = reporter._get_unit_cost("textract/detect_document_text", "pages")
    assert cost1 == 0.002

    # Clear cache
    reporter.clear_pricing_cache()

    # Second call should still return the same value from config
    cost2 = reporter._get_unit_cost("textract/detect_document_text", "pages")
    assert cost2 == 0.002


@pytest.mark.unit
def test_pricing_with_invalid_price_values():
    """Test handling of invalid price values in configuration"""

    mock_config = {
        "pricing": [
            {
                "name": "textract/detect_document_text",
                "units": [
                    {"name": "pages", "price": "invalid_price"},  # Invalid price
                    {"name": "documents", "price": "0.002"},  # Valid price
                ],
            }
        ]
    }

    reporter = SaveReportingData("test-bucket", config=mock_config)

    # Test that invalid price is skipped and returns 0.0
    invalid_cost = reporter._get_unit_cost("textract/detect_document_text", "pages")
    valid_cost = reporter._get_unit_cost("textract/detect_document_text", "documents")

    # Invalid price should return 0.0 (not found in pricing map)
    assert invalid_cost == 0.0  # No valid price found
    # Valid price should use config value
    assert valid_cost == 0.002
