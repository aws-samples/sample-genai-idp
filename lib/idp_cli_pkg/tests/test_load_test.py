# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Tests for load_test module
"""

import os
import tempfile
from unittest.mock import Mock, patch

import pytest


class TestLoadTester:
    """Tests for LoadTester class"""

    @pytest.fixture
    def mock_stack_info(self):
        """Mock StackInfo to return test resources"""
        with patch("idp_sdk.core.load_test.StackInfo") as mock:
            mock_instance = Mock()
            mock_instance.get_resources.return_value = {
                "InputBucket": "test-input-bucket",
            }
            mock.return_value = mock_instance
            yield mock

    @pytest.fixture
    def mock_boto_clients(self):
        """Mock boto3 clients"""
        with patch("idp_sdk.core.load_test.boto3.Session") as mock_session:
            mock_s3 = Mock()

            mock_session_instance = Mock()
            mock_session_instance.client.return_value = mock_s3

            mock_session.return_value = mock_session_instance
            yield {"s3": mock_s3, "session": mock_session}

    def test_init_loads_resources(self, mock_stack_info, mock_boto_clients):
        """Test that initialization loads stack resources"""
        from idp_sdk.core.load_test import LoadTester

        tester = LoadTester("test-stack", region="us-east-1")

        mock_stack_info.assert_called_once_with("test-stack", "us-east-1")
        assert tester.input_bucket == "test-input-bucket"

    def test_init_no_bucket_sets_none(self, mock_boto_clients):
        """Test initialization sets input_bucket to None when not found"""
        with patch("idp_sdk.core.load_test.StackInfo") as mock_si:
            mock_si.return_value.get_resources.return_value = {}

            from idp_sdk.core.load_test import LoadTester

            tester = LoadTester("test-stack")

            # LoadTester sets to None rather than raising
            assert tester.input_bucket is None

    def test_run_constant_load_no_bucket(self, mock_boto_clients):
        """Test run_constant_load returns error when no bucket"""
        with patch("idp_sdk.core.load_test.StackInfo") as mock_si:
            mock_si.return_value.get_resources.return_value = {}

            from idp_sdk.core.load_test import LoadTester

            tester = LoadTester("test-stack")

            result = tester.run_constant_load(
                source_file="test.pdf", rate=100, duration=1, dest_prefix="test"
            )

            assert result["success"] is False
            assert "bucket" in result["error"].lower()

    def test_run_constant_load_file_not_found(self, mock_stack_info, mock_boto_clients):
        """Test run_constant_load returns error when file not found"""
        from idp_sdk.core.load_test import LoadTester

        tester = LoadTester("test-stack")

        result = tester.run_constant_load(
            source_file="/nonexistent/file.pdf",
            rate=100,
            duration=1,
            dest_prefix="test",
        )

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_run_constant_load_success(self, mock_stack_info, mock_boto_clients):
        """Test successful constant rate load test"""
        from idp_sdk.core.load_test import LoadTester

        tester = LoadTester("test-stack")

        # Create temp source file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"test content")
            source_file = f.name

        try:
            # Run very short test
            result = tester.run_constant_load(
                source_file=source_file,
                rate=60,  # 1 file per second
                duration=0.02,  # ~1 second
                dest_prefix="test-load",
            )

            assert result["success"] is True
            assert "total_files" in result
            assert result["total_files"] >= 0
        finally:
            os.unlink(source_file)

    def test_run_constant_load_s3_source(self, mock_stack_info, mock_boto_clients):
        """Test constant load with S3 source file"""
        from idp_sdk.core.load_test import LoadTester

        tester = LoadTester("test-stack")

        result = tester.run_constant_load(
            source_file="s3://source-bucket/docs/invoice.pdf",
            rate=60,
            duration=0.02,
            dest_prefix="test-load",
        )

        assert result["success"] is True
        assert "total_files" in result

    def test_run_scheduled_load_no_bucket(self, mock_boto_clients):
        """Test run_scheduled_load returns error when no bucket"""
        with patch("idp_sdk.core.load_test.StackInfo") as mock_si:
            mock_si.return_value.get_resources.return_value = {}

            from idp_sdk.core.load_test import LoadTester

            tester = LoadTester("test-stack")

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".csv", delete=False
            ) as f:
                f.write("1,10\n")
                schedule_file = f.name

            try:
                result = tester.run_scheduled_load(
                    source_file="test.pdf",
                    schedule_file=schedule_file,
                    dest_prefix="test",
                )

                assert result["success"] is False
                assert "bucket" in result["error"].lower()
            finally:
                os.unlink(schedule_file)

    def test_run_scheduled_load_invalid_schedule(
        self, mock_stack_info, mock_boto_clients
    ):
        """Test run_scheduled_load with invalid schedule"""
        from idp_sdk.core.load_test import LoadTester

        tester = LoadTester("test-stack")

        # Create schedule with no valid entries
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("invalid,data\n")
            f.write("not,numeric\n")
            schedule_file = f.name

        try:
            result = tester.run_scheduled_load(
                source_file="test.pdf", schedule_file=schedule_file, dest_prefix="test"
            )

            assert result["success"] is False
            assert "schedule" in result["error"].lower()
        finally:
            os.unlink(schedule_file)


class TestCopyStats:
    """Tests for CopyStats class"""

    def test_increment(self):
        """Test increment counter"""
        from idp_sdk.core.load_test import CopyStats

        stats = CopyStats()
        assert stats.get_total() == 0

        stats.increment()
        assert stats.get_total() == 1

        stats.increment()
        stats.increment()
        assert stats.get_total() == 3

    def test_increment_by_minute(self):
        """Test increment with minute tracking"""
        from idp_sdk.core.load_test import CopyStats

        stats = CopyStats()

        stats.increment(minute=1)
        stats.increment(minute=1)
        stats.increment(minute=2)

        assert stats.get_minute_copies(1) == 2
        assert stats.get_minute_copies(2) == 1
        assert stats.get_total() == 3

    def test_get_current_rate(self):
        """Test rate calculation"""
        import time

        from idp_sdk.core.load_test import CopyStats

        stats = CopyStats()

        # Add some files
        for _ in range(10):
            stats.increment()

        # Wait a bit (rate will be high)
        time.sleep(0.1)

        rate = stats.get_current_rate()
        # Rate should be positive and reasonable
        assert rate > 0

    def test_get_elapsed_time(self):
        """Test elapsed time calculation"""
        import time

        from idp_sdk.core.load_test import CopyStats

        stats = CopyStats()
        time.sleep(0.1)

        minutes, seconds = stats.get_elapsed_time()
        assert minutes >= 0
        assert 0 <= seconds < 60


class TestLoadTestInternal:
    """Tests for internal LoadTester methods"""

    @pytest.fixture
    def mock_stack_info(self):
        """Mock StackInfo"""
        with patch("idp_sdk.core.load_test.StackInfo") as mock:
            mock.return_value.get_resources.return_value = {
                "InputBucket": "test-bucket",
            }
            yield mock

    @pytest.fixture
    def mock_boto(self):
        """Mock boto3"""
        with patch("idp_sdk.core.load_test.boto3.Session") as mock:
            mock.return_value.client.return_value = Mock()
            yield mock

    def test_copy_file_success(self, mock_stack_info, mock_boto):
        """Test _copy_file method"""
        from idp_sdk.core.load_test import CopyStats, LoadTester

        tester = LoadTester("test-stack")
        stats = CopyStats()

        result = tester._copy_file(
            source_bucket="source-bucket",
            source_key="docs/test.pdf",
            dest_prefix="load-test",
            stats=stats,
        )

        assert result is True
        assert stats.get_total() == 1
        tester.s3.copy_object.assert_called_once()

    def test_copy_file_error(self, mock_stack_info, mock_boto):
        """Test _copy_file handles errors"""
        from botocore.exceptions import ClientError
        from idp_sdk.core.load_test import CopyStats, LoadTester

        tester = LoadTester("test-stack")
        tester.s3.copy_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied"}}, "CopyObject"
        )

        stats = CopyStats()
        result = tester._copy_file(
            source_bucket="source-bucket",
            source_key="docs/test.pdf",
            dest_prefix="load-test",
            stats=stats,
        )

        assert result is False

    def test_upload_local_file_success(self, mock_stack_info, mock_boto):
        """Test _upload_local_file method"""
        from idp_sdk.core.load_test import CopyStats, LoadTester

        tester = LoadTester("test-stack")
        stats = CopyStats()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"test")
            source_file = f.name

        try:
            result = tester._upload_local_file(source_file, "load-test", stats)

            assert result is True
            assert stats.get_total() == 1
            tester.s3.upload_file.assert_called_once()
        finally:
            os.unlink(source_file)

    def test_upload_local_file_error(self, mock_stack_info, mock_boto):
        """Test _upload_local_file handles errors"""
        from botocore.exceptions import ClientError
        from idp_sdk.core.load_test import CopyStats, LoadTester

        tester = LoadTester("test-stack")
        tester.s3.upload_file.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied"}}, "PutObject"
        )

        stats = CopyStats()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"test")
            source_file = f.name

        try:
            result = tester._upload_local_file(source_file, "load-test", stats)

            assert result is False
        finally:
            os.unlink(source_file)
