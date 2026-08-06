# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Tests for abort_test_runs functionality in CLI and SDK
"""

import io
import json
from unittest.mock import Mock, patch

import pytest


class TestAbortTestRuns:
    """Tests for abort test runs functionality"""

    @pytest.fixture
    def mock_stack_info(self):
        """Mock StackInfo to return test resources"""
        with patch("idp_sdk._core.test_studio_processor.StackInfo") as mock:
            mock_instance = Mock()
            mock_instance.get_nested_stack_output.return_value = (
                "arn:aws:lambda:us-east-1:123456789:function:test-abort-function"
            )
            mock.return_value = mock_instance
            yield mock

    @pytest.fixture
    def mock_lambda_client(self):
        """Mock boto3 Lambda client"""
        with patch("idp_sdk._core.test_studio_processor.boto3.client") as mock:
            mock_client = Mock()
            mock.return_value = mock_client
            yield mock_client

    def test_abort_single_test_run_success(self, mock_stack_info, mock_lambda_client):
        """Test successful abort of a single test run"""
        from idp_sdk._core.test_studio_processor import TestStudioProcessor

        # Mock Lambda response - use BytesIO for proper .read() behavior
        payload_data = json.dumps(
            {
                "success": True,
                "message": "Aborted 1 test run(s)",
                "abortedCount": 1,
                "failedCount": 0,
                "errors": None,
            }
        ).encode()
        mock_lambda_client.invoke.return_value = {"Payload": io.BytesIO(payload_data)}

        processor = TestStudioProcessor("test-stack", "us-east-1")
        result = processor.abort_test_runs(["test-run-123"])

        assert result["success"] is True
        assert result["abortedCount"] == 1
        assert result["failedCount"] == 0

        # Verify Lambda was invoked with correct payload
        mock_lambda_client.invoke.assert_called_once()
        call_args = mock_lambda_client.invoke.call_args
        payload = json.loads(call_args[1]["Payload"])
        assert payload["arguments"]["testRunIds"] == ["test-run-123"]

    def test_abort_multiple_test_runs(self, mock_stack_info, mock_lambda_client):
        """Test aborting multiple test runs"""
        from idp_sdk._core.test_studio_processor import TestStudioProcessor

        payload_data = json.dumps(
            {
                "success": True,
                "message": "Aborted 3 test run(s)",
                "abortedCount": 3,
                "failedCount": 0,
                "errors": None,
            }
        ).encode()
        mock_lambda_client.invoke.return_value = {"Payload": io.BytesIO(payload_data)}

        processor = TestStudioProcessor("test-stack", "us-east-1")
        result = processor.abort_test_runs(["run1", "run2", "run3"])

        assert result["success"] is True
        assert result["abortedCount"] == 3

    def test_abort_with_partial_failure(self, mock_stack_info, mock_lambda_client):
        """Test abort with some test runs failing"""
        from idp_sdk._core.test_studio_processor import TestStudioProcessor

        payload_data = json.dumps(
            {
                "success": True,
                "message": "Aborted 2 test run(s), 1 failed",
                "abortedCount": 2,
                "failedCount": 1,
                "errors": ["run3: Cannot abort test run with status COMPLETE"],
            }
        ).encode()
        mock_lambda_client.invoke.return_value = {"Payload": io.BytesIO(payload_data)}

        processor = TestStudioProcessor("test-stack", "us-east-1")
        result = processor.abort_test_runs(["run1", "run2", "run3"])

        assert result["success"] is True
        assert result["abortedCount"] == 2
        assert result["failedCount"] == 1
        assert len(result["errors"]) == 1
        assert "COMPLETE" in result["errors"][0]

    def test_abort_lambda_error(self, mock_stack_info, mock_lambda_client):
        """Test handling of Lambda invocation error"""
        from idp_sdk._core.test_studio_processor import TestStudioProcessor
        from idp_sdk.exceptions import IDPProcessingError

        payload_data = json.dumps({"errorMessage": "Internal server error"}).encode()
        mock_lambda_client.invoke.return_value = {"Payload": io.BytesIO(payload_data)}

        processor = TestStudioProcessor("test-stack", "us-east-1")

        with pytest.raises(IDPProcessingError, match="Abort failed"):
            processor.abort_test_runs(["test-run-123"])

    def test_abort_missing_function(self, mock_lambda_client):
        """Test error when abort function not found"""
        from idp_sdk._core.test_studio_processor import TestStudioProcessor
        from idp_sdk.exceptions import IDPResourceNotFoundError

        # get_nested_stack_output raises ValueError when the stack/output is
        # missing; abort_test_runs catches that and re-raises the friendlier
        # IDPResourceNotFoundError below.
        with patch("idp_sdk._core.test_studio_processor.StackInfo") as mock_si:
            mock_si.return_value.get_nested_stack_output.side_effect = ValueError(
                "Function not found"
            )

            processor = TestStudioProcessor("test-stack", "us-east-1")

            with pytest.raises(
                IDPResourceNotFoundError,
                match="AbortTestRunsResolverFunction not found",
            ):
                processor.abort_test_runs(["test-run-123"])

    def test_sdk_testing_operation_abort(self):
        """Test SDK TestingOperation.abort_test_run method"""
        from idp_sdk.operations.testing import TestingOperation

        mock_client = Mock()
        mock_client._require_stack.return_value = "test-stack"
        mock_client._region = "us-east-1"

        operation = TestingOperation(mock_client)

        with patch.object(operation, "_get_processor") as mock_processor:
            mock_processor.return_value.abort_test_runs.return_value = {
                "success": True,
                "abortedCount": 1,
                "failedCount": 0,
            }

            result = operation.abort_test_run(["test-run-123"])

            assert result["success"] is True
            mock_processor.return_value.abort_test_runs.assert_called_once_with(
                test_run_ids=["test-run-123"]
            )

    def test_sdk_abort_raises_on_exception(self):
        """Test SDK abort raises IDPProcessingError on exception"""
        from idp_sdk.exceptions import IDPProcessingError
        from idp_sdk.operations.testing import TestingOperation

        mock_client = Mock()
        mock_client._require_stack.return_value = "test-stack"
        mock_client._region = "us-east-1"

        operation = TestingOperation(mock_client)

        with patch.object(operation, "_get_processor") as mock_processor:
            mock_processor.return_value.abort_test_runs.side_effect = Exception(
                "Network error"
            )

            with pytest.raises(IDPProcessingError, match="Failed to abort test runs"):
                operation.abort_test_run(["test-run-123"])


class TestAbortTestRunsCLI:
    """Tests for CLI abort-test-run command"""

    def test_cli_abort_success(self):
        """Test CLI abort command with successful result"""
        from click.testing import CliRunner

        from idp_cli.cli import abort_test_run

        with patch("idp_sdk.IDPClient") as mock_client_class:
            mock_client = Mock()
            mock_client.testing.abort_test_run.return_value = {
                "success": True,
                "message": "Aborted 1 test run(s)",
                "abortedCount": 1,
                "failedCount": 0,
                "errors": None,
            }
            mock_client_class.return_value = mock_client

            runner = CliRunner()
            result = runner.invoke(
                abort_test_run,
                [
                    "--stack-name",
                    "test-stack",
                    "--test-run-ids",
                    "test-run-123",
                    "--force",
                ],
            )

            assert result.exit_code == 0
            mock_client.testing.abort_test_run.assert_called_once()

    def test_cli_abort_multiple_ids(self):
        """Test CLI abort with multiple test run IDs"""
        from click.testing import CliRunner

        from idp_cli.cli import abort_test_run

        with patch("idp_sdk.IDPClient") as mock_client_class:
            mock_client = Mock()
            mock_client.testing.abort_test_run.return_value = {
                "success": True,
                "message": "Aborted 3 test run(s)",
                "abortedCount": 3,
                "failedCount": 0,
                "errors": None,
            }
            mock_client_class.return_value = mock_client

            runner = CliRunner()
            result = runner.invoke(
                abort_test_run,
                [
                    "--stack-name",
                    "test-stack",
                    "--test-run-ids",
                    "run1,run2,run3",
                    "--force",
                ],
            )

            assert result.exit_code == 0
            call_args = mock_client.testing.abort_test_run.call_args
            assert call_args[1]["test_run_ids"] == ["run1", "run2", "run3"]

    def test_cli_abort_with_failures(self):
        """Test CLI abort with partial failures"""
        from click.testing import CliRunner

        from idp_cli.cli import abort_test_run

        with patch("idp_sdk.IDPClient") as mock_client_class:
            mock_client = Mock()
            mock_client.testing.abort_test_run.return_value = {
                "success": True,
                "message": "Aborted 1 test run(s), 1 failed",
                "abortedCount": 1,
                "failedCount": 1,
                "errors": ["run2: Test run not found"],
            }
            mock_client_class.return_value = mock_client

            runner = CliRunner()
            result = runner.invoke(
                abort_test_run,
                [
                    "--stack-name",
                    "test-stack",
                    "--test-run-ids",
                    "run1,run2",
                    "--force",
                ],
            )

            assert result.exit_code == 0

    def test_cli_abort_complete_failure(self):
        """Test CLI abort with complete failure"""
        from click.testing import CliRunner

        from idp_cli.cli import abort_test_run

        with patch("idp_sdk.IDPClient") as mock_client_class:
            mock_client = Mock()
            mock_client.testing.abort_test_run.return_value = {
                "success": False,
                "message": "Failed to abort test runs",
                "abortedCount": 0,
                "failedCount": 1,
                "errors": ["Internal error"],
            }
            mock_client_class.return_value = mock_client

            runner = CliRunner()
            result = runner.invoke(
                abort_test_run,
                [
                    "--stack-name",
                    "test-stack",
                    "--test-run-ids",
                    "test-run-123",
                    "--force",
                ],
            )

            assert result.exit_code == 1

    def test_cli_abort_confirmation_declined(self):
        """Test CLI abort when user declines confirmation"""
        from click.testing import CliRunner

        from idp_cli.cli import abort_test_run

        with patch("idp_sdk.IDPClient"):
            runner = CliRunner()
            result = runner.invoke(
                abort_test_run,
                [
                    "--stack-name",
                    "test-stack",
                    "--test-run-ids",
                    "test-run-123",
                ],
                input="n\n",  # Decline confirmation
            )

            assert result.exit_code == 0

    def test_cli_abort_empty_test_run_ids(self):
        """Test CLI abort with empty test run IDs"""
        from click.testing import CliRunner

        from idp_cli.cli import abort_test_run

        runner = CliRunner()
        result = runner.invoke(
            abort_test_run,
            [
                "--stack-name",
                "test-stack",
                "--test-run-ids",
                "",
                "--force",
            ],
        )

        assert result.exit_code == 1
