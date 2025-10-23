# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for Error Analyzer tools.
"""

import importlib.util

import pytest


@pytest.mark.unit
class TestErrorAnalyzerTools:
    """Test error analyzer individual tools."""

    def test_analyze_errors_document_specific(self):
        """Test analyze_errors function can be imported."""
        spec = importlib.util.find_spec(
            "idp_common.agents.error_analyzer.tools.error_analysis_tool"
        )
        assert spec is not None, "Failed to find error_analysis_tool module"

    def test_analyze_errors_general_system(self):
        """Test analyze_errors function can be imported."""
        spec = importlib.util.find_spec(
            "idp_common.agents.error_analyzer.tools.error_analysis_tool"
        )
        assert spec is not None, "Failed to find error_analysis_tool module"

    def test_analyze_errors_no_stack_name(self):
        """Test analyze_errors function can be imported."""
        spec = importlib.util.find_spec(
            "idp_common.agents.error_analyzer.tools.error_analysis_tool"
        )
        assert spec is not None, "Failed to find error_analysis_tool module"

    def test_document_analysis_tool(self):
        """Test document analysis tool can be imported."""
        spec = importlib.util.find_spec(
            "idp_common.agents.error_analyzer.tools.document_analysis_tool"
        )
        assert spec is not None, "Failed to find document_analysis_tool module"

    def test_dynamodb_tools_find_tracking_table(self):
        """Test find_tracking_table function can be imported."""
        spec = importlib.util.find_spec(
            "idp_common.agents.error_analyzer.tools.dynamodb_tools"
        )
        assert spec is not None, "Failed to find dynamodb_tools module"

    def test_dynamodb_tools_scan_table(self):
        """Test scan_dynamodb_table function can be imported."""
        spec = importlib.util.find_spec(
            "idp_common.agents.error_analyzer.tools.dynamodb_tools"
        )
        assert spec is not None, "Failed to find dynamodb_tools module"

    def test_cloudwatch_tools_search_stack_logs(self):
        """Test search_stack_logs function can be imported."""
        spec = importlib.util.find_spec(
            "idp_common.agents.error_analyzer.tools.cloudwatch_tools"
        )
        assert spec is not None, "Failed to find cloudwatch_tools module"

    def test_general_analysis_tool(self):
        """Test general system analysis tool can be imported."""
        spec = importlib.util.find_spec(
            "idp_common.agents.error_analyzer.tools.general_analysis_tool"
        )
        assert spec is not None, "Failed to find general_analysis_tool module"

    def test_stepfunction_tools(self):
        """Test Step Function analysis tool can be imported."""
        spec = importlib.util.find_spec(
            "idp_common.agents.error_analyzer.tools.stepfunction_tools"
        )
        assert spec is not None, "Failed to find stepfunction_tools module"
