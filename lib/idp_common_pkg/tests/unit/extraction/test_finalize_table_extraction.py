# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Tests for the finalize_table_extraction tool used in agentic extraction."""

from __future__ import annotations

import sys
from typing import Optional
from unittest.mock import MagicMock

import strands  # noqa: E402 — mocked by conftest

# Make @tool a passthrough decorator for testing
strands.tool = lambda fn: fn

# Mock additional strands submodules required by agentic_idp imports
for mod_name in [
    "strands.agent",
    "strands.agent.conversation_manager",
    "strands.types",
    "strands.types.agent",
    "strands.types.content",
    "strands.types.media",
]:
    sys.modules.setdefault(mod_name, MagicMock())

from pydantic import BaseModel  # noqa: E402

from idp_common.extraction.agentic_idp import (  # noqa: E402
    create_dynamic_extraction_tool_and_patch_tool,
)

# ---------------------------------------------------------------------------
# Lightweight mock for Strands Agent (only needs .state with get/set)
# ---------------------------------------------------------------------------


class _SimpleState:
    def __init__(self):
        self._data: dict = {}

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value):
        self._data[key] = value


class MockAgent:
    def __init__(self):
        self.state = _SimpleState()


# ---------------------------------------------------------------------------
# Test Pydantic models
# ---------------------------------------------------------------------------


class TransactionItem(BaseModel):
    date: str
    description: str
    amount: Optional[str] = None


class BankStatement(BaseModel):
    account_number: str
    statement_period: Optional[str] = None
    transactions: list[TransactionItem]


class SimpleDoc(BaseModel):
    title: str
    items: list[dict]


# ---------------------------------------------------------------------------
# Helper to get the finalize tool from the factory
# ---------------------------------------------------------------------------


def _get_finalize_tool(model_class):
    """Extract finalize_table_extraction from the factory tuple."""
    *_, finalize_tool = create_dynamic_extraction_tool_and_patch_tool(model_class)
    return finalize_tool


# =============================================================================
# Success cases
# =============================================================================


class TestFinalizeTableExtractionSuccess:
    """Tests for successful finalize_table_extraction calls."""

    def test_basic_finalize(self):
        finalize = _get_finalize_tool(BankStatement)
        agent = MockAgent()
        agent.state.set(
            "mapped_table_rows",
            {
                "mapped_rows": [
                    {"date": "01/15", "description": "Deposit", "amount": "100"},
                    {"date": "01/16", "description": "ATM", "amount": "200"},
                ],
                "row_count": 2,
            },
        )

        result = finalize(
            table_array_field="transactions",
            scalar_fields={
                "account_number": "12345",
                "statement_period": "Jan 2025",
            },
            agent=agent,
        )
        assert result["status"] == "success"
        assert result["row_count"] == 2
        assert "account_number" in result["scalar_fields"]

    def test_empty_scalar_fields(self):
        finalize = _get_finalize_tool(SimpleDoc)
        agent = MockAgent()
        agent.state.set(
            "mapped_table_rows",
            {
                "mapped_rows": [{"key": "val"}],
                "row_count": 1,
            },
        )
        result = finalize(
            table_array_field="items",
            scalar_fields={"title": "Test"},
            agent=agent,
        )
        assert result["status"] == "success"

    def test_large_row_count(self):
        finalize = _get_finalize_tool(SimpleDoc)
        agent = MockAgent()
        rows = [{"k": f"v{i}"} for i in range(150)]
        agent.state.set(
            "mapped_table_rows",
            {"mapped_rows": rows, "row_count": 150},
        )
        result = finalize(
            table_array_field="items",
            scalar_fields={"title": "Big Doc"},
            agent=agent,
        )
        assert result["status"] == "success"
        assert result["row_count"] == 150

    def test_state_persists_after_finalize(self):
        finalize = _get_finalize_tool(BankStatement)
        agent = MockAgent()
        agent.state.set(
            "mapped_table_rows",
            {
                "mapped_rows": [
                    {"date": "01/15", "description": "Deposit", "amount": "100"}
                ],
                "row_count": 1,
            },
        )
        finalize(
            table_array_field="transactions",
            scalar_fields={"account_number": "12345"},
            agent=agent,
        )
        extraction = agent.state.get("current_extraction")
        assert extraction is not None
        assert extraction["account_number"] == "12345"
        assert len(extraction["transactions"]) == 1
        assert extraction["transactions"][0]["date"] == "01/15"


# =============================================================================
# Error cases
# =============================================================================


class TestFinalizeTableExtractionErrors:
    """Tests for error handling in finalize_table_extraction."""

    def test_no_mapped_rows_returns_error(self):
        finalize = _get_finalize_tool(BankStatement)
        agent = MockAgent()
        agent.state.set("mapped_table_rows", {"mapped_rows": [], "row_count": 0})
        result = finalize(
            table_array_field="transactions",
            scalar_fields={"account_number": "12345"},
            agent=agent,
        )
        assert result["status"] == "error"

    def test_missing_state_key_returns_error(self):
        finalize = _get_finalize_tool(BankStatement)
        agent = MockAgent()
        # No mapped_table_rows in state at all
        result = finalize(
            table_array_field="transactions",
            scalar_fields={"account_number": "12345"},
            agent=agent,
        )
        assert result["status"] == "error"

    def test_validation_error_missing_required_field(self):
        """Missing required 'account_number' field should cause validation error."""
        finalize = _get_finalize_tool(BankStatement)
        agent = MockAgent()
        agent.state.set(
            "mapped_table_rows",
            {
                "mapped_rows": [{"date": "01/15", "description": "Deposit"}],
                "row_count": 1,
            },
        )
        result = finalize(
            table_array_field="transactions",
            scalar_fields={},  # Missing required account_number
            agent=agent,
        )
        assert result["status"] == "validation_error"


# =============================================================================
# Pydantic validation
# =============================================================================


class TestFinalizeTableExtractionValidation:
    """Tests for Pydantic model validation in finalize."""

    def test_optional_fields_default_to_none(self):
        finalize = _get_finalize_tool(BankStatement)
        agent = MockAgent()
        agent.state.set(
            "mapped_table_rows",
            {
                "mapped_rows": [
                    {"date": "01/15", "description": "Deposit"}
                    # amount is Optional, not provided
                ],
                "row_count": 1,
            },
        )
        result = finalize(
            table_array_field="transactions",
            scalar_fields={"account_number": "12345"},
            # statement_period is Optional, not provided
            agent=agent,
        )
        assert result["status"] == "success"
        extraction = agent.state.get("current_extraction")
        assert extraction["statement_period"] is None
        assert extraction["transactions"][0]["amount"] is None

    def test_array_items_validated_against_submodel(self):
        finalize = _get_finalize_tool(BankStatement)
        agent = MockAgent()
        agent.state.set(
            "mapped_table_rows",
            {
                "mapped_rows": [
                    # Missing required 'description' field in TransactionItem
                    {"date": "01/15"}
                ],
                "row_count": 1,
            },
        )
        result = finalize(
            table_array_field="transactions",
            scalar_fields={"account_number": "12345"},
            agent=agent,
        )
        assert result["status"] == "validation_error"

    def test_wrong_array_field_name_causes_validation_error(self):
        """Using wrong table_array_field name means the model is missing required field."""
        finalize = _get_finalize_tool(BankStatement)
        agent = MockAgent()
        agent.state.set(
            "mapped_table_rows",
            {
                "mapped_rows": [{"date": "01/15", "description": "Test"}],
                "row_count": 1,
            },
        )
        result = finalize(
            table_array_field="wrong_field_name",  # not in BankStatement
            scalar_fields={"account_number": "12345"},
            agent=agent,
        )
        assert result["status"] == "validation_error"
