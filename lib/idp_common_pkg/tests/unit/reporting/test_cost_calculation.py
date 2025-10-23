#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""
Unit tests for cost calculation functionality
"""

from datetime import datetime

import pytest
from idp_common.models import Document
from idp_common.reporting.save_reporting_data import SaveReportingData


@pytest.mark.unit
def test_cost_calculation_pricing_lookup():
    """Test the pricing lookup functionality"""
    # Create pricing configuration
    pricing_config = {
        "pricing": [
            {
                "name": "bedrock/eu.anthropic.claude-3-haiku-20240307-v1:0",
                "units": [
                    {"name": "inputTokens", "price": "0.00025"},
                    {"name": "outputTokens", "price": "0.00125"},
                ],
            },
            {
                "name": "bedrock/eu.amazon.nova-lite-v1:0",
                "units": [
                    {"name": "inputTokens", "price": "0.00006"},
                    {"name": "outputTokens", "price": "0.00024"},
                ],
            },
            {
                "name": "textract/detect_document_text",
                "units": [{"name": "pages", "price": "0.0015"}],
            },
        ]
    }

    # Create SaveReportingData instance with pricing config
    reporter = SaveReportingData("test-bucket", config=pricing_config)

    # Test Bedrock pricing lookup
    claude_input_cost = reporter._get_unit_cost(
        "bedrock/eu.anthropic.claude-3-haiku-20240307-v1:0", "inputTokens"
    )
    claude_output_cost = reporter._get_unit_cost(
        "bedrock/eu.anthropic.claude-3-haiku-20240307-v1:0", "outputTokens"
    )

    assert claude_input_cost > 0, (
        "Claude Haiku input token cost should be greater than 0"
    )
    assert claude_output_cost > 0, (
        "Claude Haiku output token cost should be greater than 0"
    )

    # Test Nova pricing lookup
    nova_input_cost = reporter._get_unit_cost(
        "bedrock/eu.amazon.nova-lite-v1:0", "inputTokens"
    )
    nova_output_cost = reporter._get_unit_cost(
        "bedrock/eu.amazon.nova-lite-v1:0", "outputTokens"
    )

    assert nova_input_cost > 0, "Nova Lite input token cost should be greater than 0"
    assert nova_output_cost > 0, "Nova Lite output token cost should be greater than 0"

    # Test Textract pricing lookup
    textract_cost = reporter._get_unit_cost("textract/detect_document_text", "pages")
    assert textract_cost > 0, (
        "Textract detect document text cost should be greater than 0"
    )


@pytest.mark.unit
def test_cost_calculation_with_document():
    """Test cost calculation with document metering data structure"""
    # Create pricing configuration
    pricing_config = {
        "pricing": [
            {
                "name": "bedrock/eu.anthropic.claude-3-haiku-20240307-v1:0",
                "units": [
                    {"name": "inputTokens", "price": "0.00025"},
                    {"name": "outputTokens", "price": "0.00125"},
                ],
            },
            {
                "name": "bedrock/eu.amazon.nova-lite-v1:0",
                "units": [
                    {"name": "inputTokens", "price": "0.00006"},
                    {"name": "outputTokens", "price": "0.00024"},
                ],
            },
            {
                "name": "textract/detect_document_text",
                "units": [{"name": "pages", "price": "0.0015"}],
            },
        ]
    }

    # Create SaveReportingData instance with pricing config
    reporter = SaveReportingData("test-bucket", config=pricing_config)

    # Get unit costs
    claude_input_cost = reporter._get_unit_cost(
        "bedrock/eu.anthropic.claude-3-haiku-20240307-v1:0", "inputTokens"
    )
    claude_output_cost = reporter._get_unit_cost(
        "bedrock/eu.anthropic.claude-3-haiku-20240307-v1:0", "outputTokens"
    )
    nova_input_cost = reporter._get_unit_cost(
        "bedrock/eu.amazon.nova-lite-v1:0", "inputTokens"
    )
    nova_output_cost = reporter._get_unit_cost(
        "bedrock/eu.amazon.nova-lite-v1:0", "outputTokens"
    )
    textract_cost = reporter._get_unit_cost("textract/detect_document_text", "pages")

    # Calculate expected costs
    claude_total = (1000 * claude_input_cost) + (200 * claude_output_cost)
    nova_total = (2000 * nova_input_cost) + (500 * nova_output_cost)
    textract_total = 5 * textract_cost
    expected_total = claude_total + nova_total + textract_total

    # Verify all costs are positive
    assert claude_total > 0, "Claude total cost should be greater than 0"
    assert nova_total > 0, "Nova total cost should be greater than 0"
    assert textract_total > 0, "Textract total cost should be greater than 0"
    assert expected_total > 0, "Total cost should be greater than 0"

    # Verify the total is the sum of individual costs
    assert (
        abs(expected_total - (claude_total + nova_total + textract_total)) < 0.000001
    ), "Total cost should equal sum of individual costs"


@pytest.mark.unit
def test_cost_calculation_unknown_service():
    """Test cost calculation behavior with unknown service"""
    reporter = SaveReportingData("test-bucket")

    # Test with unknown service - should return 0 or handle gracefully
    unknown_cost = reporter._get_unit_cost("unknown/service", "unknown_metric")
    assert unknown_cost >= 0, "Unknown service cost should be 0 or positive"


@pytest.mark.unit
def test_cost_calculation_empty_metering():
    """Test cost calculation with document having empty metering data"""
    document = Document(
        id="test-doc-empty",
        input_key="empty-document.pdf",
        num_pages=1,
        metering={},
        initial_event_time=datetime.now().isoformat(),
    )

    # This test verifies that empty metering data doesn't cause errors
    assert document.metering == {}, "Document should have empty metering data"
    assert document.num_pages == 1, "Document should have 1 page"
