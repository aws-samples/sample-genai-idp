# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import importlib.util
import os
from unittest.mock import patch

import pytest

# Mock environment variables and dependencies before importing
with patch.dict(
    os.environ,
    {
        "TRACKING_TABLE": "test-table",
        "CONFIG_TABLE": "test-config-table",
        "FILE_COPY_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123456789012/test-queue",
        "AWS_REGION": "us-east-1",
    },
):
    with patch("boto3.client"), patch("boto3.resource"):
        # Import the specific lambda module
        spec = importlib.util.spec_from_file_location(
            "test_runner_index",
            os.path.join(
                os.path.dirname(__file__),
                "../../../../nested/appsync/src/lambda/test_runner/index.py",
            ),
        )
        if spec is None or spec.loader is None:
            raise ImportError("Could not load test_runner module")
        test_runner_index = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(test_runner_index)


# Test Studio test runner operations are Admin+Author; supply an authorized
# Cognito identity on handler events so the defense-in-depth group gate passes.
_ADMIN_IDENTITY = {
    "claims": {"cognito:groups": ["Admin"], "email": "admin@example.com"}
}


@pytest.mark.unit
class TestTestRunnerRBAC:
    """RBAC tests for test runner Lambda function"""

    def test_handler_rejects_viewer(self):
        """Defense-in-depth: a Viewer must not reach startTestRun operation."""
        event = {
            "arguments": {
                "input": {
                    "testSetId": "test-set-123",
                    "context": "test",
                }
            },
            "identity": {"claims": {"cognito:groups": ["Viewer"]}},
        }
        with pytest.raises(Exception, match="requires Admin or Author group"):
            test_runner_index.handler(event, {})

    @patch.dict(
        os.environ,
        {
            "TRACKING_TABLE": "test-table",
            "CONFIG_TABLE": "test-config-table",
            "FILE_COPY_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123456789012/test-queue",
        },
    )
    def test_handler_allows_direct_lambda_invoke_no_identity(self):
        """RBAC bypass: direct Lambda invocation (no identity) proceeds for CI/automation."""
        with (
            patch.object(test_runner_index, "_get_test_set") as mock_get_test_set,
            patch.object(test_runner_index, "_capture_config") as mock_capture_config,
            patch.object(
                test_runner_index, "_store_test_run_metadata"
            ) as _mock_store_metadata,
            patch.object(test_runner_index.sqs, "send_message") as mock_sqs,
            patch("datetime.datetime") as mock_datetime,
        ):
            # Mock return values
            mock_get_test_set.return_value = {
                "name": "Test-Set",
                "fileCount": 3,
            }
            mock_capture_config.return_value = {"Config": {"key": "value"}}
            mock_datetime.utcnow.return_value.strftime.return_value = "20260611-120000"

            # Direct Lambda invoke: no 'identity' field (CI/automation path)
            event = {
                "arguments": {
                    "input": {
                        "testSetId": "test-set-123",
                        "context": "CI test",
                    }
                }
            }

            # Should NOT raise - bypass works as designed
            result = test_runner_index.handler(event, {})
            # RBAC bypass worked - we got a result instead of "Unauthorized" exception
            assert "testRunId" in result
            assert result["status"] == "QUEUED"
            mock_sqs.assert_called_once()

    @patch.dict(
        os.environ,
        {
            "TRACKING_TABLE": "test-table",
            "CONFIG_TABLE": "test-config-table",
            "FILE_COPY_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123456789012/test-queue",
        },
    )
    def test_handler_allows_direct_lambda_invoke_identity_none(self):
        """RBAC bypass: direct Lambda invocation (identity=None) proceeds for CI/automation."""
        with (
            patch.object(test_runner_index, "_get_test_set") as mock_get_test_set,
            patch.object(test_runner_index, "_capture_config") as mock_capture_config,
            patch.object(
                test_runner_index, "_store_test_run_metadata"
            ) as _mock_store_metadata,
            patch.object(test_runner_index.sqs, "send_message") as mock_sqs,
            patch("datetime.datetime") as mock_datetime,
        ):
            # Mock return values
            mock_get_test_set.return_value = {
                "name": "Test-Set",
                "fileCount": 3,
            }
            mock_capture_config.return_value = {"Config": {"key": "value"}}
            mock_datetime.utcnow.return_value.strftime.return_value = "20260611-120000"

            # Direct Lambda invoke: identity explicitly None
            event = {
                "arguments": {
                    "input": {
                        "testSetId": "test-set-123",
                        "context": "CI test",
                    }
                },
                "identity": None,
            }

            # Should NOT raise - bypass works as designed
            result = test_runner_index.handler(event, {})
            # RBAC bypass worked - we got a result instead of "Unauthorized" exception
            assert "testRunId" in result
            assert result["status"] == "QUEUED"
            mock_sqs.assert_called_once()

    def test_handler_still_enforces_rbac_for_appsync_viewer(self):
        """Regression guard: AppSync invocation with non-Admin/Author still raises."""
        event = {
            "arguments": {
                "input": {
                    "testSetId": "test-set-123",
                    "context": "test",
                }
            },
            "identity": {"claims": {"cognito:groups": ["Viewer"]}},
        }
        with pytest.raises(Exception, match="requires Admin or Author group"):
            test_runner_index.handler(event, {})

    @patch.dict(
        os.environ,
        {
            "TRACKING_TABLE": "test-table",
            "CONFIG_TABLE": "test-config-table",
            "FILE_COPY_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123456789012/test-queue",
        },
    )
    def test_handler_allows_admin(self):
        """Admin user can invoke startTestRun via AppSync."""
        with (
            patch.object(test_runner_index, "_get_test_set") as mock_get_test_set,
            patch.object(test_runner_index, "_capture_config") as mock_capture_config,
            patch.object(
                test_runner_index, "_store_test_run_metadata"
            ) as _mock_store_metadata,
            patch.object(test_runner_index.sqs, "send_message") as mock_sqs,
            patch("datetime.datetime") as mock_datetime,
        ):
            # Mock return values
            mock_get_test_set.return_value = {
                "name": "Test-Set",
                "fileCount": 3,
            }
            mock_capture_config.return_value = {"Config": {"key": "value"}}
            mock_datetime.utcnow.return_value.strftime.return_value = "20260611-120000"

            event = {
                "arguments": {
                    "input": {
                        "testSetId": "test-set-123",
                        "context": "UI test",
                    }
                },
                "identity": _ADMIN_IDENTITY,
            }

            # Should succeed - Admin has permission
            result = test_runner_index.handler(event, {})
            # Admin RBAC check passed - we got a result
            assert "testRunId" in result
            assert result["status"] == "QUEUED"
            mock_sqs.assert_called_once()

    @patch.dict(
        os.environ,
        {
            "TRACKING_TABLE": "test-table",
            "CONFIG_TABLE": "test-config-table",
            "FILE_COPY_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123456789012/test-queue",
        },
    )
    def test_handler_allows_author(self):
        """Author user can invoke startTestRun via AppSync."""
        with (
            patch.object(test_runner_index, "_get_test_set") as mock_get_test_set,
            patch.object(test_runner_index, "_capture_config") as mock_capture_config,
            patch.object(
                test_runner_index, "_store_test_run_metadata"
            ) as _mock_store_metadata,
            patch.object(test_runner_index.sqs, "send_message") as mock_sqs,
            patch("datetime.datetime") as mock_datetime,
        ):
            # Mock return values
            mock_get_test_set.return_value = {
                "name": "Test-Set",
                "fileCount": 3,
            }
            mock_capture_config.return_value = {"Config": {"key": "value"}}
            mock_datetime.utcnow.return_value.strftime.return_value = "20260611-120000"

            event = {
                "arguments": {
                    "input": {
                        "testSetId": "test-set-123",
                        "context": "UI test",
                    }
                },
                "identity": {
                    "claims": {
                        "cognito:groups": ["Author"],
                        "email": "author@example.com",
                    }
                },
            }

            # Should succeed - Author has permission
            result = test_runner_index.handler(event, {})
            # Author RBAC check passed - we got a result
            assert "testRunId" in result
            assert result["status"] == "QUEUED"
            mock_sqs.assert_called_once()
