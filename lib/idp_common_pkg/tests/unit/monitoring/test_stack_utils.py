# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for idp_common.monitoring.stack_utils
"""

from unittest.mock import MagicMock, patch

import pytest

import idp_common.monitoring.stack_utils as stack_module
from idp_common.monitoring.stack_utils import (
    extract_stack_name_from_arn,
    get_lambda_function_names,
    get_stack_name,
    get_stack_resources,
    get_state_machine_arn,
)


# ---------------------------------------------------------------------------
# Reset module-level boto3 client cache between tests
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_cf_client():
    """Reset the module-level _cf_client singleton before every test."""
    stack_module._cf_client = None
    yield
    stack_module._cf_client = None


# ---------------------------------------------------------------------------
# extract_stack_name_from_arn
# ---------------------------------------------------------------------------


class TestExtractStackNameFromArn:
    def test_document_processing_workflow_suffix(self):
        arn = "arn:aws:states:us-east-1:123456789012:execution:MY-STACK-DocumentProcessingWorkflow:exec-1"
        assert extract_stack_name_from_arn(arn) == "MY-STACK"

    def test_processing_state_machine_suffix(self):
        arn = "arn:aws:states:us-east-1:123456789012:execution:DEV-ProcessingStateMachine:exec-1"
        assert extract_stack_name_from_arn(arn) == "DEV"

    def test_workflow_state_machine_suffix(self):
        arn = "arn:aws:states:us-east-1:123456789012:execution:PROD-STACK-WorkflowStateMachine:exec-1"
        assert extract_stack_name_from_arn(arn) == "PROD-STACK"

    def test_workflow_suffix(self):
        arn = "arn:aws:states:us-east-1:123456789012:execution:MY-STACK-Workflow:exec-1"
        assert extract_stack_name_from_arn(arn) == "MY-STACK"

    def test_hyphenated_stack_name(self):
        arn = "arn:aws:states:us-east-1:123456789012:execution:DEV-P2-EA8-DocumentProcessingWorkflow:exec-id"
        assert extract_stack_name_from_arn(arn) == "DEV-P2-EA8"

    def test_fallback_strips_last_segment(self):
        # No known suffix — strips last hyphen-delimited word
        arn = "arn:aws:states:us-east-1:123:execution:MYSTACK-SomeUnknownSuffix:exec-id"
        result = extract_stack_name_from_arn(arn)
        assert result == "MYSTACK"

    def test_empty_arn_returns_empty(self):
        assert extract_stack_name_from_arn("") == ""

    def test_none_like_short_arn_returns_empty(self):
        assert extract_stack_name_from_arn("arn:aws:states:us-east-1") == ""

    def test_arn_without_execution_returns_empty(self):
        # Too few colon-separated fields
        assert extract_stack_name_from_arn("not:a:real:arn") == ""


# ---------------------------------------------------------------------------
# get_stack_name
# ---------------------------------------------------------------------------


class TestGetStackName:
    def test_from_document_record_workflow_arn(self, monkeypatch):
        monkeypatch.delenv("AWS_STACK_NAME", raising=False)
        monkeypatch.delenv("STACK_NAME", raising=False)
        doc = {
            "WorkflowExecutionArn": (
                "arn:aws:states:us-east-1:123:execution:"
                "MY-STACK-DocumentProcessingWorkflow:exec-1"
            )
        }
        assert get_stack_name(document_record=doc) == "MY-STACK"

    def test_from_document_record_execution_arn_fallback(self, monkeypatch):
        monkeypatch.delenv("AWS_STACK_NAME", raising=False)
        monkeypatch.delenv("STACK_NAME", raising=False)
        doc = {
            "ExecutionArn": (
                "arn:aws:states:us-east-1:123:execution:"
                "PROD-DocumentProcessingWorkflow:exec-1"
            )
        }
        assert get_stack_name(document_record=doc) == "PROD"

    def test_from_aws_stack_name_env_var(self, monkeypatch):
        monkeypatch.setenv("AWS_STACK_NAME", "FROM-ENV")
        monkeypatch.delenv("STACK_NAME", raising=False)
        assert get_stack_name() == "FROM-ENV"

    def test_from_stack_name_env_var(self, monkeypatch):
        monkeypatch.delenv("AWS_STACK_NAME", raising=False)
        monkeypatch.setenv("STACK_NAME", "FALLBACK-STACK")
        assert get_stack_name() == "FALLBACK-STACK"

    def test_aws_stack_name_takes_priority_over_stack_name(self, monkeypatch):
        monkeypatch.setenv("AWS_STACK_NAME", "PRIMARY")
        monkeypatch.setenv("STACK_NAME", "SECONDARY")
        assert get_stack_name() == "PRIMARY"

    def test_document_record_takes_priority_over_env_var(self, monkeypatch):
        monkeypatch.setenv("AWS_STACK_NAME", "ENV-STACK")
        doc = {
            "WorkflowExecutionArn": (
                "arn:aws:states:us-east-1:123:execution:"
                "DOC-STACK-DocumentProcessingWorkflow:exec-1"
            )
        }
        assert get_stack_name(document_record=doc) == "DOC-STACK"

    def test_raises_when_no_source_available(self, monkeypatch):
        monkeypatch.delenv("AWS_STACK_NAME", raising=False)
        monkeypatch.delenv("STACK_NAME", raising=False)
        with pytest.raises(ValueError, match="Stack name could not be resolved"):
            get_stack_name()

    def test_empty_document_record_falls_back_to_env(self, monkeypatch):
        monkeypatch.setenv("AWS_STACK_NAME", "ENV")
        monkeypatch.delenv("STACK_NAME", raising=False)
        assert get_stack_name(document_record={}) == "ENV"


# ---------------------------------------------------------------------------
# get_stack_resources
# ---------------------------------------------------------------------------


class TestGetStackResources:
    def test_returns_resources_list(self):
        mock_cf = MagicMock()
        mock_paginator = MagicMock()
        mock_cf.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {
                "StackResourceSummaries": [
                    {
                        "ResourceType": "AWS::Lambda::Function",
                        "PhysicalResourceId": "fn-1",
                    },
                    {
                        "ResourceType": "AWS::DynamoDB::Table",
                        "PhysicalResourceId": "tbl-1",
                    },
                ]
            }
        ]

        with patch("idp_common.monitoring.stack_utils.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_cf
            resources = get_stack_resources("MY-STACK")

        assert len(resources) == 2
        assert resources[0]["PhysicalResourceId"] == "fn-1"

    def test_returns_empty_list_on_stack_not_found(self):
        mock_cf = MagicMock()
        mock_cf.get_paginator.side_effect = Exception("Stack not found")

        with patch("idp_common.monitoring.stack_utils.boto3") as mock_boto3:
            mock_boto3.client.return_value = mock_cf
            resources = get_stack_resources("MISSING-STACK")

        assert resources == []


# ---------------------------------------------------------------------------
# get_lambda_function_names
# ---------------------------------------------------------------------------


class TestGetLambdaFunctionNames:
    def test_returns_correct_function_names(self):
        with patch(
            "idp_common.monitoring.stack_utils.get_stack_resources"
        ) as mock_resources:
            mock_resources.return_value = [
                {"ResourceType": "AWS::Lambda::Function", "PhysicalResourceId": "fn-a"},
                {"ResourceType": "AWS::Lambda::Function", "PhysicalResourceId": "fn-b"},
                {"ResourceType": "AWS::DynamoDB::Table", "PhysicalResourceId": "tbl-x"},
            ]
            names = get_lambda_function_names("MY-STACK")

        assert names == ["fn-a", "fn-b"]

    def test_returns_empty_list_when_no_lambdas(self):
        with patch(
            "idp_common.monitoring.stack_utils.get_stack_resources"
        ) as mock_resources:
            mock_resources.return_value = [
                {"ResourceType": "AWS::DynamoDB::Table", "PhysicalResourceId": "tbl-x"},
            ]
            names = get_lambda_function_names("MY-STACK")

        assert names == []


# ---------------------------------------------------------------------------
# get_state_machine_arn
# ---------------------------------------------------------------------------


class TestGetStateMachineArn:
    def test_returns_document_processing_workflow_arn(self):
        with patch(
            "idp_common.monitoring.stack_utils.get_stack_resources"
        ) as mock_resources:
            mock_resources.return_value = [
                {
                    "ResourceType": "AWS::StepFunctions::StateMachine",
                    "LogicalResourceId": "DocumentProcessingWorkflow",
                    "PhysicalResourceId": "arn:aws:states:us-east-1:123:stateMachine:MY-STACK-DocumentProcessingWorkflow",
                }
            ]
            arn = get_state_machine_arn("MY-STACK")

        assert "DocumentProcessingWorkflow" in arn

    def test_returns_empty_string_when_not_found(self):
        with patch(
            "idp_common.monitoring.stack_utils.get_stack_resources"
        ) as mock_resources:
            mock_resources.return_value = []
            arn = get_state_machine_arn("MY-STACK")

        assert arn == ""

    def test_returns_empty_when_only_other_resources(self):
        with patch(
            "idp_common.monitoring.stack_utils.get_stack_resources"
        ) as mock_resources:
            mock_resources.return_value = [
                {"ResourceType": "AWS::Lambda::Function", "PhysicalResourceId": "fn-1"}
            ]
            arn = get_state_machine_arn("MY-STACK")

        assert arn == ""
