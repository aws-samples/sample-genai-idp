# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for S3Util — specifically s3_url_to_bucket_key.
"""

import pytest

from idp_common.utils.s3util import S3Util


class TestS3UtilParsing:
    """Test S3Util.s3_url_to_bucket_key URI parsing."""

    def test_s3_url_to_bucket_key_plain(self):
        """Plain S3 URI parses correctly."""
        bucket, key = S3Util.s3_url_to_bucket_key("s3://my-bucket/path/to/document.pdf")
        assert bucket == "my-bucket"
        assert key == "path/to/document.pdf"

    def test_s3_url_to_bucket_key_with_hash(self):
        """S3 URI whose key contains '#' must not be truncated.

        urlparse treats '#' as a URL fragment delimiter and silently drops
        everything from '#' onward. parse_s3_uri uses str.split and is safe.
        """
        bucket, key = S3Util.s3_url_to_bucket_key("s3://my-bucket/path/file #99.pdf")
        assert bucket == "my-bucket"
        assert key == "path/file #99.pdf"

    def test_s3_url_to_bucket_key_invalid_scheme(self):
        """Non-S3 URI raises ValueError."""
        with pytest.raises(ValueError):
            S3Util.s3_url_to_bucket_key("https://my-bucket/path/file.pdf")

    def test_s3_url_to_bucket_key_no_key(self):
        """Bucket-only URI (no key) raises ValueError, as before this change."""
        with pytest.raises(ValueError):
            S3Util.s3_url_to_bucket_key("s3://my-bucket")
