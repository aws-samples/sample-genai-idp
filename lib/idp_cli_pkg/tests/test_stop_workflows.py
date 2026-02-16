# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Tests for stop_workflows module
"""

from unittest.mock import Mock, patch

import pytest


class TestWorkflowStopper:
    """Tests for WorkflowStopper class"""

    @pytest.fixture
    def mock_stack_info(self):
        """Mock StackInfo to return test resources"""
        with patch("idp_sdk.core.stop_workflows.StackInfo") as mock:
            mock_instance = Mock()
            mock_instance.get_resources.return_value = {
                "DocumentQueueUrl": "https://sqs.us-east-1.amazonaws.com/123456789/test-queue",
                "StateMachineArn": "arn:aws:states:us-east-1:123456789:stateMachine:test-sm",
                "DocumentsTable": "test-tracking-table",
            }
            mock.return_value = mock_instance
            yield mock

    @pytest.fixture
    def mock_boto_clients(self):
        """Mock boto3 clients"""
        with patch("idp_sdk.core.stop_workflows.boto3.Session") as mock_session:
            mock_sqs = Mock()
            mock_sfn = Mock()

            mock_session_instance = Mock()
            mock_session_instance.client.side_effect = lambda service, **kwargs: {
                "sqs": mock_sqs,
                "stepfunctions": mock_sfn,
            }.get(service, Mock())

            mock_session.return_value = mock_session_instance
            yield {"sqs": mock_sqs, "sfn": mock_sfn, "session": mock_session}

    def test_init_loads_resources(self, mock_stack_info, mock_boto_clients):
        """Test that initialization loads stack resources"""
        from idp_sdk.core.stop_workflows import WorkflowStopper

        stopper = WorkflowStopper("test-stack", region="us-east-1")

        mock_stack_info.assert_called_once_with("test-stack", "us-east-1")
        assert (
            stopper.queue_url
            == "https://sqs.us-east-1.amazonaws.com/123456789/test-queue"
        )
        assert (
            stopper.state_machine_arn
            == "arn:aws:states:us-east-1:123456789:stateMachine:test-sm"
        )
        assert stopper.documents_table == "test-tracking-table"

    def test_purge_queue_success(self, mock_stack_info, mock_boto_clients):
        """Test successful queue purge"""
        from idp_sdk.core.stop_workflows import WorkflowStopper

        stopper = WorkflowStopper("test-stack")
        result = stopper.purge_queue()

        assert result["success"] is True
        assert (
            result["queue_url"]
            == "https://sqs.us-east-1.amazonaws.com/123456789/test-queue"
        )
        mock_boto_clients["sqs"].purge_queue.assert_called_once()

    def test_purge_queue_no_url(self, mock_boto_clients):
        """Test purge queue when URL not found"""
        with patch("idp_sdk.core.stop_workflows.StackInfo") as mock_si:
            mock_si.return_value.get_resources.return_value = {}

            from idp_sdk.core.stop_workflows import WorkflowStopper

            stopper = WorkflowStopper("test-stack")
            result = stopper.purge_queue()

            assert result["success"] is False
            assert "not found" in result["error"]

    def test_purge_queue_error(self, mock_stack_info, mock_boto_clients):
        """Test purge queue handles errors"""
        from botocore.exceptions import ClientError
        from idp_sdk.core.stop_workflows import WorkflowStopper

        mock_boto_clients["sqs"].purge_queue.side_effect = ClientError(
            {"Error": {"Code": "AWS.SimpleQueueService.PurgeQueueInProgress"}},
            "PurgeQueue",
        )

        stopper = WorkflowStopper("test-stack")
        result = stopper.purge_queue()

        assert result["success"] is False
        assert "error" in result

    def test_count_running_executions(self, mock_stack_info, mock_boto_clients):
        """Test counting running executions"""
        from idp_sdk.core.stop_workflows import WorkflowStopper

        # Mock paginator
        mock_paginator = Mock()
        mock_paginator.paginate.return_value = [
            {"executions": [{"executionArn": "arn:1"}, {"executionArn": "arn:2"}]},
            {"executions": [{"executionArn": "arn:3"}]},
        ]
        mock_boto_clients["sfn"].get_paginator.return_value = mock_paginator

        stopper = WorkflowStopper("test-stack")
        count = stopper.count_running_executions()

        assert count == 3

    def test_stop_executions_no_running(self, mock_stack_info, mock_boto_clients):
        """Test stop executions when none are running"""
        from idp_sdk.core.stop_workflows import WorkflowStopper

        # Mock paginator returning empty
        mock_paginator = Mock()
        mock_paginator.paginate.return_value = [{"executions": []}]
        mock_boto_clients["sfn"].get_paginator.return_value = mock_paginator

        stopper = WorkflowStopper("test-stack")
        result = stopper.stop_executions()

        assert result["success"] is True
        assert result["total_stopped"] == 0
        assert result["remaining"] == 0

    def test_stop_executions_stops_all(self, mock_stack_info, mock_boto_clients):
        """Test stopping all executions"""
        from idp_sdk.core.stop_workflows import WorkflowStopper

        # First call returns executions, second call returns empty
        call_count = [0]

        def mock_paginate(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:  # First two calls for counting and stopping
                return [
                    {
                        "executions": [
                            {"executionArn": "arn:1"},
                            {"executionArn": "arn:2"},
                        ]
                    }
                ]
            return [{"executions": []}]  # Final verification call

        mock_paginator = Mock()
        mock_paginator.paginate.side_effect = mock_paginate
        mock_boto_clients["sfn"].get_paginator.return_value = mock_paginator
        mock_boto_clients["sfn"].stop_execution = Mock()
        mock_boto_clients["sfn"].exceptions = Mock()
        mock_boto_clients["sfn"].exceptions.ExecutionNotFound = Exception

        stopper = WorkflowStopper("test-stack")
        result = stopper.stop_executions()

        assert result["total_stopped"] >= 2
        assert mock_boto_clients["sfn"].stop_execution.call_count >= 2

    def test_stop_all_calls_all_methods(self, mock_stack_info, mock_boto_clients):
        """Test stop_all calls all component methods"""
        from idp_sdk.core.stop_workflows import WorkflowStopper

        # Mock empty responses
        mock_paginator = Mock()
        mock_paginator.paginate.return_value = [{"executions": []}]
        mock_boto_clients["sfn"].get_paginator.return_value = mock_paginator

        with patch("idp_sdk.core.stop_workflows.DocumentDynamoDBService"):
            stopper = WorkflowStopper("test-stack")

            with patch.object(
                stopper, "purge_queue", return_value={"success": True}
            ) as mock_purge:
                with patch.object(
                    stopper, "stop_executions", return_value={"success": True}
                ) as mock_stop:
                    with patch.object(
                        stopper,
                        "abort_queued_documents",
                        return_value={"success": True},
                    ) as mock_abort:
                        stopper.stop_all()

                        mock_purge.assert_called_once()
                        mock_stop.assert_called_once()
                        mock_abort.assert_called_once()

    def test_stop_all_skip_purge(self, mock_stack_info, mock_boto_clients):
        """Test stop_all with skip_purge flag"""
        from idp_sdk.core.stop_workflows import WorkflowStopper

        mock_paginator = Mock()
        mock_paginator.paginate.return_value = [{"executions": []}]
        mock_boto_clients["sfn"].get_paginator.return_value = mock_paginator

        stopper = WorkflowStopper("test-stack")

        with patch.object(stopper, "purge_queue") as mock_purge:
            with patch.object(
                stopper, "stop_executions", return_value={"success": True}
            ):
                with patch.object(stopper, "abort_queued_documents"):
                    stopper.stop_all(skip_purge=True)

                    mock_purge.assert_not_called()

    def test_stop_all_skip_stop(self, mock_stack_info, mock_boto_clients):
        """Test stop_all with skip_stop flag"""
        from idp_sdk.core.stop_workflows import WorkflowStopper

        stopper = WorkflowStopper("test-stack")

        with patch.object(stopper, "purge_queue", return_value={"success": True}):
            with patch.object(stopper, "stop_executions") as mock_stop:
                with patch.object(
                    stopper, "abort_queued_documents", return_value={"success": True}
                ):
                    stopper.stop_all(skip_stop=True)

                    mock_stop.assert_not_called()


class TestAbortQueuedDocuments:
    """Tests for abort_queued_documents functionality"""

    @pytest.fixture
    def mock_stack_info(self):
        """Mock StackInfo"""
        with patch("idp_sdk.core.stop_workflows.StackInfo") as mock:
            mock.return_value.get_resources.return_value = {
                "DocumentQueueUrl": "https://sqs.example.com/queue",
                "StateMachineArn": "arn:aws:states:us-east-1:123:stateMachine:sm",
                "DocumentsTable": "test-table",
            }
            yield mock

    @pytest.fixture
    def mock_boto(self):
        """Mock boto3"""
        with patch("idp_sdk.core.stop_workflows.boto3.Session") as mock:
            mock.return_value.client.return_value = Mock()
            yield mock

    def test_abort_no_documents_table(self, mock_boto):
        """Test abort when no documents table configured"""
        with patch("idp_sdk.core.stop_workflows.StackInfo") as mock_si:
            mock_si.return_value.get_resources.return_value = {}

            from idp_sdk.core.stop_workflows import WorkflowStopper

            stopper = WorkflowStopper("test-stack")
            result = stopper.abort_queued_documents()

            assert result["success"] is False
            assert "not found" in result["error"]

    def test_abort_no_queued_documents(self, mock_stack_info, mock_boto):
        """Test abort when no queued documents exist"""
        from idp_sdk.core.stop_workflows import WorkflowStopper

        with patch(
            "idp_sdk.core.stop_workflows.DocumentDynamoDBService"
        ) as mock_service:
            mock_service.return_value.client.scan.return_value = {"Items": []}

            stopper = WorkflowStopper("test-stack")
            result = stopper.abort_queued_documents()

            assert result["success"] is True
            assert result["documents_aborted"] == 0

    def test_abort_updates_documents(self, mock_stack_info, mock_boto):
        """Test abort updates queued documents to ABORTED status"""
        from idp_common.models import Status
        from idp_sdk.core.stop_workflows import WorkflowStopper

        with patch(
            "idp_sdk.core.stop_workflows.DocumentDynamoDBService"
        ) as mock_service_class:
            mock_service = Mock()
            mock_service_class.return_value = mock_service

            # Mock scan returning queued documents
            mock_service.client.scan.return_value = {
                "Items": [
                    {"ObjectKey": "doc1.pdf"},
                    {"ObjectKey": "doc2.pdf"},
                ]
            }

            # Mock get_document returning documents - need to return new mock each time
            def create_mock_doc(*args, **kwargs):
                mock_doc = Mock()
                mock_doc.status = Status.QUEUED
                return mock_doc

            mock_service.get_document.side_effect = create_mock_doc

            stopper = WorkflowStopper("test-stack")
            result = stopper.abort_queued_documents()

            assert result["success"] is True
            assert result["documents_aborted"] == 2
            # Verify update was called
            assert mock_service.update_document.call_count == 2

    def test_abort_handles_errors(self, mock_stack_info, mock_boto):
        """Test abort handles individual document errors gracefully"""
        from idp_common.models import Status
        from idp_sdk.core.stop_workflows import WorkflowStopper

        with patch(
            "idp_sdk.core.stop_workflows.DocumentDynamoDBService"
        ) as mock_service_class:
            mock_service = Mock()
            mock_service_class.return_value = mock_service

            mock_service.client.scan.return_value = {
                "Items": [
                    {"ObjectKey": "doc1.pdf"},
                    {"ObjectKey": "doc2.pdf"},
                ]
            }

            # First doc succeeds, second fails
            mock_doc = Mock()
            mock_doc.status = Status.QUEUED
            mock_service.get_document.side_effect = [mock_doc, Exception("DB error")]

            stopper = WorkflowStopper("test-stack")
            result = stopper.abort_queued_documents()

            assert result["success"] is True
            assert result["documents_aborted"] == 1
            assert result["documents_failed"] == 1
