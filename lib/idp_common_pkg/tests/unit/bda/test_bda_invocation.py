# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for the BdaInvocation class.
"""

from unittest.mock import patch

import pytest

from idp_common.bda.bda_invocation import BdaInvocation


@pytest.mark.unit
def test_bda_invocation_init():
    """Test BdaInvocation initialization with default values."""
    invocation = BdaInvocation()
    assert invocation.bucket_name is None
    assert invocation.job_id is None
    assert invocation.custom_output_segments is None
    assert invocation.job_metadata is None


@pytest.mark.unit
def test_bda_invocation_init_with_values():
    """Test BdaInvocation initialization with provided values."""
    bucket_name = "test-bucket"
    job_id = "test-job-id"
    custom_output_segments = [{"key": "value"}]
    job_metadata = {"job_id": job_id, "status": "completed"}

    invocation = BdaInvocation(
        bucket_name=bucket_name,
        job_id=job_id,
        custom_output_segments=custom_output_segments,
        job_metadata=job_metadata,
    )

    assert invocation.bucket_name == bucket_name
    assert invocation.job_id == job_id
    assert invocation.custom_output_segments == custom_output_segments
    assert invocation.job_metadata == job_metadata


@pytest.mark.unit
@patch("idp_common.bda.bda_invocation.S3Util")
def test_from_s3(mock_s3_util):
    """Test creating a BdaInvocation from S3 URL."""
    # Setup mock
    s3_url = "s3://test-bucket/output-docs/job-123/job_metadata.json"
    mock_bucket = "test-bucket"
    mock_key = "output-docs/job-123/job_metadata.json"
    mock_job_metadata = {
        "job_id": "job-123",
        "status": "completed",
        "output_metadata": [],
    }

    mock_s3_util.s3_url_to_bucket_key.return_value = (mock_bucket, mock_key)
    mock_s3_util.get_dict.return_value = mock_job_metadata

    # Call the method
    result = BdaInvocation.from_s3(s3_url)

    # Verify
    mock_s3_util.s3_url_to_bucket_key.assert_called_once_with(s3_url=s3_url)
    mock_s3_util.get_dict.assert_called_once_with(mock_bucket, mock_key)

    assert result.bucket_name == mock_bucket
    assert result.job_id == "job-123"
    assert result.job_metadata == mock_job_metadata
    assert result.custom_output_segments is None


@pytest.mark.unit
def test_get_custom_output_no_metadata():
    """Test get_custom_output with no job metadata."""
    invocation = BdaInvocation()

    with pytest.raises(
        ValueError, match="Job metadata not populated. Use from_s3\\(\\) first."
    ):
        invocation.get_custom_output()


@pytest.mark.unit
def test_get_custom_output_no_output_metadata():
    """Test get_custom_output with no output metadata."""
    invocation = BdaInvocation(
        job_metadata={"job_id": "job-123", "output_metadata": []}
    )

    with pytest.raises(ValueError, match="No output metadata found for asset ID 0"):
        invocation.get_custom_output()


@pytest.mark.unit
def test_get_custom_output_no_segment_metadata():
    """Test get_custom_output with no segment metadata."""
    invocation = BdaInvocation(
        job_metadata={
            "job_id": "job-123",
            "output_metadata": [{"segment_metadata": []}],
        }
    )

    with pytest.raises(
        ValueError, match="No segment metadata found for segment index 0"
    ):
        invocation.get_custom_output()


@pytest.mark.unit
def test_get_custom_output_no_custom_output_path():
    """Test get_custom_output with no custom output path."""
    invocation = BdaInvocation(
        job_metadata={
            "job_id": "job-123",
            "output_metadata": [{"segment_metadata": [{}]}],
        }
    )

    with pytest.raises(
        ValueError, match="No custom output path found for asset ID 0, segment index 0"
    ):
        invocation.get_custom_output()


@pytest.mark.unit
def test_get_custom_output_invalid_s3_uri():
    """Test get_custom_output with invalid S3 URI."""
    invocation = BdaInvocation(
        job_metadata={
            "job_id": "job-123",
            "output_metadata": [
                {"segment_metadata": [{"custom_output_path": "invalid-path"}]}
            ],
        }
    )

    with pytest.raises(ValueError, match="Invalid S3 URI format: invalid-path"):
        invocation.get_custom_output()


@pytest.mark.unit
@patch("idp_common.bda.bda_invocation.S3Util")
def test_get_custom_output_success(mock_s3_util):
    """Test successful get_custom_output."""
    # Setup mock
    custom_output_path = "s3://test-bucket/output-docs/job-123/custom_output.json"
    mock_bucket = "test-bucket"
    mock_key = "output-docs/job-123/custom_output.json"
    mock_custom_output = {"field1": "value1", "field2": "value2"}

    mock_s3_util.s3_url_to_bucket_key.return_value = (mock_bucket, mock_key)
    mock_s3_util.get_dict.return_value = mock_custom_output

    invocation = BdaInvocation(
        job_metadata={
            "job_id": "job-123",
            "output_metadata": [
                {"segment_metadata": [{"custom_output_path": custom_output_path}]}
            ],
        }
    )

    # Call the method
    result = invocation.get_custom_output()

    # Verify
    mock_s3_util.s3_url_to_bucket_key.assert_called_once_with(s3_url=custom_output_path)
    mock_s3_util.get_dict.assert_called_once_with(mock_bucket, mock_key)

    assert result == mock_custom_output
    assert invocation.custom_output_segments == [mock_custom_output]


@pytest.mark.unit
@patch("idp_common.bda.bda_invocation.S3Util")
def test_get_custom_output_with_asset_id_and_segment_index(mock_s3_util):
    """Test get_custom_output with specific asset_id and segment_index."""
    # Setup mock
    custom_output_path = "s3://test-bucket/output-docs/job-123/custom_output.json"
    mock_bucket = "test-bucket"
    mock_key = "output-docs/job-123/custom_output.json"
    mock_custom_output = {"field1": "value1", "field2": "value2"}

    mock_s3_util.s3_url_to_bucket_key.return_value = (mock_bucket, mock_key)
    mock_s3_util.get_dict.return_value = mock_custom_output

    invocation = BdaInvocation(
        job_metadata={
            "job_id": "job-123",
            "output_metadata": [
                {"segment_metadata": [{"custom_output_path": "s3://other-path"}]},
                {
                    "segment_metadata": [
                        {"custom_output_path": "s3://other-path2"},
                        {"custom_output_path": custom_output_path},
                    ]
                },
            ],
        }
    )

    # Call the method
    result = invocation.get_custom_output(asset_id=1, segment_index=1)

    # Verify
    mock_s3_util.s3_url_to_bucket_key.assert_called_once_with(s3_url=custom_output_path)
    mock_s3_util.get_dict.assert_called_once_with(mock_bucket, mock_key)

    assert result == mock_custom_output
    assert len(invocation.custom_output_segments) == 2
    assert invocation.custom_output_segments[0] == {}
    assert invocation.custom_output_segments[1] == mock_custom_output
