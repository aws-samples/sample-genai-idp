# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Additional unit tests for the BdaService class.
"""

from unittest.mock import MagicMock, call, patch

import pytest

from idp_common.bda.bda_service import BdaService


@pytest.mark.unit
@patch("idp_common.bda.bda_service.time")
@patch("idp_common.bda.bda_service.boto3")
def test_wait_data_automation_invocation_success(mock_boto3, mock_time):
    """Test wait_data_automation_invocation with successful completion."""
    # Setup mocks
    mock_bda_client = MagicMock()
    mock_boto3.client.return_value = mock_bda_client

    # First call returns 'InProgress', second call returns 'Success'
    mock_bda_client.get_data_automation_status.side_effect = [
        {"status": "InProgress"},
        {"status": "Success"},
    ]

    # Create service
    service = BdaService(output_s3_uri="s3://output-bucket/output-path")

    # Call the method
    service.wait_data_automation_invocation(
        invocationArn="test-invocation-arn", sleep_seconds=5
    )

    # Verify
    assert mock_bda_client.get_data_automation_status.call_count == 2
    mock_bda_client.get_data_automation_status.assert_has_calls(
        [
            call(invocationArn="test-invocation-arn"),
            call(invocationArn="test-invocation-arn"),
        ]
    )
    mock_time.sleep.assert_called_once_with(5)


@pytest.mark.unit
@patch("idp_common.bda.bda_service.time")
@patch("idp_common.bda.bda_service.boto3")
def test_wait_data_automation_invocation_error(mock_boto3, mock_time):
    """Test wait_data_automation_invocation with error completion."""
    # Setup mocks
    mock_bda_client = MagicMock()
    mock_boto3.client.return_value = mock_bda_client

    # First call returns 'InProgress', second call returns 'ServiceError'
    mock_bda_client.get_data_automation_status.side_effect = [
        {"status": "InProgress"},
        {"status": "ServiceError"},
    ]

    # Create service
    service = BdaService(output_s3_uri="s3://output-bucket/output-path")

    # Call the method
    service.wait_data_automation_invocation(
        invocationArn="test-invocation-arn", sleep_seconds=5
    )

    # Verify
    assert mock_bda_client.get_data_automation_status.call_count == 2
    mock_bda_client.get_data_automation_status.assert_has_calls(
        [
            call(invocationArn="test-invocation-arn"),
            call(invocationArn="test-invocation-arn"),
        ]
    )
    mock_time.sleep.assert_called_once_with(5)


@pytest.mark.unit
@patch("idp_common.bda.bda_service.boto3")
def test_get_data_automation_invocation_success(mock_boto3):
    """Test get_data_automation_invocation with successful status."""
    # Setup mocks
    mock_bda_client = MagicMock()
    mock_boto3.client.return_value = mock_bda_client

    mock_bda_client.get_data_automation_status.return_value = {
        "status": "Success",
        "outputConfiguration": {"s3Uri": "s3://output-bucket/output-path/job-123"},
    }

    # Create service
    service = BdaService(output_s3_uri="s3://output-bucket/output-path")

    # Call the method
    result = service.get_data_automation_invocation(invocationArn="test-invocation-arn")

    # Verify
    mock_bda_client.get_data_automation_status.assert_called_once_with(
        invocationArn="test-invocation-arn"
    )

    assert result == {
        "status": "success",
        "output_location": "s3://output-bucket/output-path/job-123",
    }


@pytest.mark.unit
@patch("idp_common.bda.bda_service.boto3")
def test_get_data_automation_invocation_failed(mock_boto3):
    """Test get_data_automation_invocation with failed status."""
    # Setup mocks
    mock_bda_client = MagicMock()
    mock_boto3.client.return_value = mock_bda_client

    mock_bda_client.get_data_automation_status.return_value = {
        "status": "ServiceError",
        "errorType": "ValidationError",
        "errorMessage": "Invalid input format",
    }

    # Create service
    service = BdaService(output_s3_uri="s3://output-bucket/output-path")

    # Call the method
    result = service.get_data_automation_invocation(invocationArn="test-invocation-arn")

    # Verify
    mock_bda_client.get_data_automation_status.assert_called_once_with(
        invocationArn="test-invocation-arn"
    )

    assert result == {
        "status": "failed",
        "error_type": "ValidationError",
        "error_message": "Invalid input format",
    }


@pytest.mark.unit
@patch("idp_common.bda.bda_service.BdaService.get_data_automation_invocation")
@patch("idp_common.bda.bda_service.BdaService.wait_data_automation_invocation")
@patch("idp_common.bda.bda_service.BdaService.invoke_data_automation_async")
@patch("idp_common.bda.bda_service.boto3")
def test_invoke_data_automation(
    mock_boto3, mock_invoke_async, mock_wait, mock_get_invocation
):
    """Test invoke_data_automation which combines async, wait, and get methods."""
    # Setup mocks
    mock_invoke_async.return_value = {"invocationArn": "test-invocation-arn"}
    mock_get_invocation.return_value = {
        "status": "success",
        "output_location": "s3://output-bucket/output-path/job-123",
    }

    # Create service
    service = BdaService(output_s3_uri="s3://output-bucket/output-path")

    # Call the method
    result = service.invoke_data_automation(
        input_s3_uri="s3://input-bucket/input-path/document.pdf",
        blueprintArn="arn:aws:bedrock:us-west-2:123456789012:blueprint/blueprint-id",
        sleep_seconds=15,
    )

    # Verify
    mock_invoke_async.assert_called_once_with(
        input_s3_uri="s3://input-bucket/input-path/document.pdf",
        blueprintArn="arn:aws:bedrock:us-west-2:123456789012:blueprint/blueprint-id",
    )

    mock_wait.assert_called_once_with(
        invocationArn="test-invocation-arn", sleep_seconds=15
    )

    mock_get_invocation.assert_called_once_with(invocationArn="test-invocation-arn")

    assert result == {
        "status": "success",
        "output_location": "s3://output-bucket/output-path/job-123",
    }
