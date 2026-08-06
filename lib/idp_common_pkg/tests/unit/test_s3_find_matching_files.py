# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from unittest.mock import Mock, patch

import pytest

from idp_common.s3 import find_matching_files


@pytest.mark.unit
class TestFindMatchingFiles:
    """Test find_matching_files function behavior"""

    @patch("idp_common.s3.get_s3_client")
    def test_case_sensitive_matching(self, mock_get_client):
        """Test that matching is case-sensitive"""
        mock_s3 = Mock()
        mock_get_client.return_value = mock_s3

        # Mock paginator
        mock_paginator = Mock()
        mock_s3.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "File.txt"},
                    {"Key": "file.txt"},
                    {"Key": "FILE.txt"},
                ]
            }
        ]

        result = find_matching_files("bucket", "file*")

        # Only exact case match
        assert result == ["file.txt"]

    @patch("idp_common.s3.get_s3_client")
    def test_wildcard_no_directory_crossing(self, mock_get_client):
        """Test that * doesn't match across / boundaries"""
        mock_s3 = Mock()
        mock_get_client.return_value = mock_s3

        mock_paginator = Mock()
        mock_s3.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "test.txt"},
                    {"Key": "test123.pdf"},
                    {"Key": "test/nested.txt"},
                    {"Key": "test/sub/deep.txt"},
                ]
            }
        ]

        result = find_matching_files("bucket", "test*")

        # Only root level matches, no directory crossing
        assert result == ["test.txt", "test123.pdf"]

    @patch("idp_common.s3.get_s3_client")
    def test_directory_pattern_matching(self, mock_get_client):
        """Test pattern matching within specific directory"""
        mock_s3 = Mock()
        mock_get_client.return_value = mock_s3

        mock_paginator = Mock()
        mock_s3.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "dir/file1.txt"},
                    {"Key": "dir/file2.pdf"},
                    {"Key": "dir/other.doc"},
                    {"Key": "dir/sub/nested.txt"},
                ]
            }
        ]

        result = find_matching_files("bucket", "dir/file*")

        # Only direct children matching pattern
        assert result == ["dir/file1.txt", "dir/file2.pdf"]

    @patch("idp_common.s3.get_s3_client")
    def test_question_mark_wildcard(self, mock_get_client):
        """Test that ? matches single character but not /"""
        mock_s3 = Mock()
        mock_get_client.return_value = mock_s3

        mock_paginator = Mock()
        mock_s3.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "file1.txt"},
                    {"Key": "file2.txt"},
                    {"Key": "file12.txt"},
                    {"Key": "file/.txt"},
                ]
            }
        ]

        result = find_matching_files("bucket", "file?.txt")

        # Only single character matches, not / or multiple chars
        assert result == ["file1.txt", "file2.txt"]

    @patch("idp_common.s3.get_s3_client")
    def test_skips_folder_pseudo_objects(self, mock_get_client):
        """Zero-byte '/'-terminated folder placeholders are never matched.

        The S3 console "Create folder" action writes a zero-byte object whose
        key ends in '/'. These are not documents and must be excluded even when
        the pattern would otherwise match them.
        """
        mock_s3 = Mock()
        mock_get_client.return_value = mock_s3

        mock_paginator = Mock()
        mock_s3.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "testfolder/"},
                    {"Key": "testfolder/doc1.pdf"},
                    {"Key": "testfolder/sub/"},
                ]
            }
        ]

        # Pattern that would otherwise match the "testfolder/" placeholder
        result = find_matching_files("bucket", "testfolder/*")
        assert result == ["testfolder/doc1.pdf"]

        # A pattern ending in '/' must not pull in the placeholder either
        assert find_matching_files("bucket", "testfolder/") == []
