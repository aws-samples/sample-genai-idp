# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for Error Analyzer tools.
"""

import pytest


@pytest.mark.unit
class TestErrorAnalyzerTools:
    """Test error analyzer individual tools."""

    def test_cloudwatch_tools_import(self):
        """Test CloudWatch tools can be imported."""
        from idp_common.agents.error_analyzer.tools import (
            search_cloudwatch_logs,
            search_performance_issues,
        )

        assert search_cloudwatch_logs is not None
        assert callable(search_cloudwatch_logs)
        assert search_performance_issues is not None
        assert callable(search_performance_issues)

    def test_dynamodb_tools_import(self):
        """Test DynamoDB tools can be imported."""
        from idp_common.agents.error_analyzer.tools import (
            fetch_document_record,
            fetch_recent_records,
        )

        assert fetch_document_record is not None
        assert callable(fetch_document_record)
        assert fetch_recent_records is not None
        assert callable(fetch_recent_records)

    def test_execution_context_tools_import(self):
        """Test execution context tools can be imported."""
        from idp_common.agents.error_analyzer.tools import (
            analyze_workflow_execution,
            retrieve_document_context,
        )

        assert retrieve_document_context is not None
        assert callable(retrieve_document_context)
        assert analyze_workflow_execution is not None
        assert callable(analyze_workflow_execution)

    def test_xray_tools_import(self):
        """Test X-Ray tools can be imported."""
        from idp_common.agents.error_analyzer.tools import (
            analyze_document_trace,
            analyze_system_performance,
        )

        assert analyze_document_trace is not None
        assert callable(analyze_document_trace)
        assert analyze_system_performance is not None
        assert callable(analyze_system_performance)

    def test_config_tool_import(self):
        """Test the pipeline configuration tool can be imported."""
        from idp_common.agents.error_analyzer.tools import (
            fetch_pipeline_configuration,
        )

        assert fetch_pipeline_configuration is not None
        assert callable(fetch_pipeline_configuration)

    def test_all_tools_available(self):
        """Test that all 9 tools are available in the tools module."""
        from idp_common.agents.error_analyzer.tools import __all__

        expected_tools = {
            "search_cloudwatch_logs",
            "search_performance_issues",
            "fetch_pipeline_configuration",
            "fetch_document_record",
            "fetch_recent_records",
            "retrieve_document_context",
            "analyze_workflow_execution",
            "analyze_document_trace",
            "analyze_system_performance",
        }

        assert len(__all__) == 9
        assert set(__all__) == expected_tools


@pytest.mark.unit
class TestCollectStageModels:
    """Test the config-walking helper that extracts per-stage model IDs."""

    def test_collects_models_and_model_ids_with_paths(self):
        from idp_common.agents.error_analyzer.tools.config_tool import (
            _collect_stage_models,
        )

        config = {
            "ocr": {"backend": "textract", "model_id": "us.amazon.nova-lite-v1:0"},
            "extraction": {
                "model": "us.anthropic.claude-sonnet-5",
                "confidence": {"model": "us.amazon.nova-lite-v1:0"},
            },
            "summarization": {
                "enabled": True,
                "model": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            },
            "evaluation": {"llm_method": {"model": "us.amazon.nova-pro-v1:0"}},
        }
        out = []
        _collect_stage_models(config, "", out)

        by_stage = {d["stage"]: d["model"] for d in out}
        assert by_stage["ocr"] == "us.amazon.nova-lite-v1:0"
        assert by_stage["extraction"] == "us.anthropic.claude-sonnet-5"
        assert by_stage["extraction.confidence"] == "us.amazon.nova-lite-v1:0"
        assert (
            by_stage["summarization"] == "us.anthropic.claude-3-7-sonnet-20250219-v1:0"
        )
        assert by_stage["evaluation.llm_method"] == "us.amazon.nova-pro-v1:0"

    def test_ignores_empty_and_non_string_models(self):
        from idp_common.agents.error_analyzer.tools.config_tool import (
            _collect_stage_models,
        )

        config = {"ocr": {"model": ""}, "classification": {"model": None}}
        out = []
        _collect_stage_models(config, "", out)
        assert out == []

    def test_walks_lists(self):
        from idp_common.agents.error_analyzer.tools.config_tool import (
            _collect_stage_models,
        )

        config = {"agents": [{"model_id": "m1"}, {"model_id": "m2"}]}
        out = []
        _collect_stage_models(config, "", out)
        assert {d["model"] for d in out} == {"m1", "m2"}
