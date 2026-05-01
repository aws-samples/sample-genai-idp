# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Utility functions for working with Amazon S3.
"""

import json
import boto3
from typing import Dict, Any, Tuple, Optional, Union
from urllib.parse import urlparse


class S3Util:
    """
    Utility class for common S3 operations.
    """

    @staticmethod
    def get_bytes(bucket: str, key: str, region: Optional[str] = None) -> bytes:
        """
        Get binary data from an S3 object.

        Args:
            bucket: S3 bucket name
            key: S3 object key
            region: AWS region (optional)

        Returns:
            The object content as bytes
        """
        s3_client = boto3.client("s3", region_name=region)
        response = s3_client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    @staticmethod
    def put_bytes(
        bucket: str, key: str, data: bytes, region: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Upload binary data to an S3 object.

        Args:
            bucket: S3 bucket name
            key: S3 object key
            data: Binary data to upload
            region: AWS region (optional)

        Returns:
            S3 put_object response
        """
        s3_client = boto3.client("s3", region_name=region)
        return s3_client.put_object(Bucket=bucket, Key=key, Body=data)

    @staticmethod
    def get_unicode(
        bucket: str, key: str, encoding: str = "utf-8", region: Optional[str] = None
    ) -> str:
        """
        Get text data from an S3 object.

        Args:
            bucket: S3 bucket name
            key: S3 object key
            encoding: Text encoding (default: utf-8)
            region: AWS region (optional)

        Returns:
            The object content as a string
        """
        data = S3Util.get_bytes(bucket, key, region)
        return data.decode(encoding)

    @staticmethod
    def put_unicode(
        bucket: str,
        key: str,
        data: str,
        encoding: str = "utf-8",
        region: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Upload text data to an S3 object.

        Args:
            bucket: S3 bucket name
            key: S3 object key
            data: Text data to upload
            encoding: Text encoding (default: utf-8)
            region: AWS region (optional)

        Returns:
            S3 put_object response
        """
        return S3Util.put_bytes(bucket, key, data.encode(encoding), region)

    @staticmethod
    def get_dict(bucket: str, key: str, region: Optional[str] = None) -> Dict[str, Any]:
        """
        Get JSON data from an S3 object and parse it into a dictionary.

        Args:
            bucket: S3 bucket name
            key: S3 object key
            region: AWS region (optional)

        Returns:
            The parsed JSON content as a dictionary
        """
        json_str = S3Util.get_unicode(bucket, key, region=region)
        return json.loads(json_str)

    @staticmethod
    def put_dict(
        bucket: str,
        key: str,
        data: Dict[str, Any],
        indent: Optional[int] = None,
        region: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Convert a dictionary to JSON and upload it to an S3 object.

        Args:
            bucket: S3 bucket name
            key: S3 object key
            data: Dictionary to upload as JSON
            indent: JSON indentation level (optional)
            region: AWS region (optional)

        Returns:
            S3 put_object response
        """
        json_str = json.dumps(data, indent=indent)
        return S3Util.put_unicode(bucket, key, json_str, region=region)

    @staticmethod
    def bucket_key_to_s3_uri(bucket: str, key: str) -> str:
        """
        Convert a bucket and key to an S3 URL.

        Args:
            bucket: S3 bucket name
            key: S3 object key

        Returns:
            S3 URL in the format s3://bucket/key
        """
        return f"s3://{bucket}/{key}"

    @staticmethod
    def s3_url_to_bucket_key(s3_url: str) -> Tuple[str, str]:
        """
        Parse an S3 URL into bucket and key components.

        Args:
            s3_url: S3 URL in the format s3://bucket/key

        Returns:
            Tuple of (bucket, key)

        Raises:
            ValueError: If the URL is not a valid S3 URL
        """
        if not s3_url.startswith("s3://"):
            raise ValueError(f"Invalid S3 URL format: {s3_url}")

        parts = s3_url[5:].split("/", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid S3 URI format: {s3_url}")

        parsed = urlparse(s3_url)
        bucket = parsed.netloc
        # Remove leading slash from key
        key = parsed.path.lstrip("/")

        return bucket, key
