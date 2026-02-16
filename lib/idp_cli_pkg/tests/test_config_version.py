"""
Test config-version parameter flow in batch processor
"""

from unittest.mock import Mock, patch

import pytest
from idp_sdk.core.batch_processor import BatchProcessor


@pytest.mark.unit
def test_copy_s3_file_with_config_version():
    """Test that _copy_s3_file applies config-version metadata"""

    with patch("idp_sdk.core.batch_processor.StackInfo") as mock_stack_info:
        # Mock stack validation
        mock_stack_info.return_value.validate_stack.return_value = True
        mock_stack_info.return_value.get_resources.return_value = {
            "InputBucket": "test-input-bucket",
            "TestSetBucket": "test-set-bucket",
        }

        with patch("boto3.client") as mock_boto3:
            mock_s3 = Mock()
            mock_boto3.return_value = mock_s3

            processor = BatchProcessor("test-stack", "us-east-1")

            # Test document from S3
            test_doc = {
                "type": "s3",
                "filename": "test.png",
                "path": "s3://test-set-bucket/test.png",
            }

            # Test with config_version
            processor._copy_s3_file(test_doc, "test-batch", config_version="v2")

            # Verify copy_object was called with metadata
            mock_s3.copy_object.assert_called_once()
            call_args = mock_s3.copy_object.call_args[1]

            assert "Metadata" in call_args
            assert call_args["Metadata"]["config-version"] == "v2"
            assert call_args["MetadataDirective"] == "REPLACE"


@pytest.mark.unit
def test_copy_s3_file_without_config_version():
    """Test that _copy_s3_file works without config-version"""

    with patch("idp_sdk.core.batch_processor.StackInfo") as mock_stack_info:
        mock_stack_info.return_value.validate_stack.return_value = True
        mock_stack_info.return_value.get_resources.return_value = {
            "InputBucket": "test-input-bucket",
            "TestSetBucket": "test-set-bucket",
        }

        with patch("boto3.client") as mock_boto3:
            mock_s3 = Mock()
            mock_boto3.return_value = mock_s3

            processor = BatchProcessor("test-stack", "us-east-1")

            test_doc = {
                "type": "s3",
                "filename": "test.png",
                "path": "s3://test-set-bucket/test.png",
            }

            # Test without config_version
            processor._copy_s3_file(test_doc, "test-batch", config_version=None)

            # Verify copy_object was called without metadata
            mock_s3.copy_object.assert_called_once()
            call_args = mock_s3.copy_object.call_args[1]

            assert "Metadata" not in call_args
            assert "MetadataDirective" not in call_args
