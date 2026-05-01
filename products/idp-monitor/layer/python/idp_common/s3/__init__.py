# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import boto3
import json
import logging
import os
from typing import Dict, Any, Optional, Union, List
from ..utils import parse_s3_uri

logger = logging.getLogger(__name__)

# Initialize clients
_s3_client = None


def get_s3_client():
    """
    Get or initialize the S3 client

    Returns:
        boto3 S3 client
    """
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3")
    return _s3_client


def get_text_content(s3_uri: str) -> str:
    """
    Read text content from an S3 URI

    Args:
        s3_uri: The S3 URI in format s3://bucket/key

    Returns:
        Text content from the S3 object
    """
    try:
        bucket, key = parse_s3_uri(s3_uri)
        s3 = get_s3_client()
        response = s3.get_object(Bucket=bucket, Key=key)
        content_str = response["Body"].read().decode("utf-8")

        # Check if the content is JSON or plain text
        if s3_uri.endswith(".json"):
            try:
                content = json.loads(content_str)
                return content.get("text", content_str)
            except json.JSONDecodeError:
                logger.warning(
                    f"File has .json extension but content is not valid JSON: {s3_uri}"
                )
                return content_str
        else:
            # For non-JSON files (like .md), return the content directly
            return content_str
    except Exception as e:
        logger.error(f"Error reading text from {s3_uri}: {e}")
        raise


def get_json_content(s3_uri: str) -> Dict[str, Any]:
    """
    Read JSON content from an S3 URI

    Args:
        s3_uri: The S3 URI in format s3://bucket/key

    Returns:
        Parsed JSON content
    """
    try:
        bucket, key = parse_s3_uri(s3_uri)
        s3 = get_s3_client()
        response = s3.get_object(Bucket=bucket, Key=key)
        return json.loads(response["Body"].read().decode("utf-8"))
    except Exception as e:
        logger.error(f"Error reading JSON from {s3_uri}: {e}")
        raise


def get_binary_content(s3_uri: str) -> bytes:
    """
    Read binary content from an S3 URI

    Args:
        s3_uri: The S3 URI in format s3://bucket/key

    Returns:
        Binary content from the S3 object
    """
    try:
        bucket, key = parse_s3_uri(s3_uri)
        s3 = get_s3_client()
        response = s3.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()
    except Exception as e:
        logger.error(f"Error reading binary content from {s3_uri}: {e}")
        raise


def write_content(
    content: Union[str, bytes, Dict[str, Any], List[Any]],
    bucket: str,
    key: str,
    content_type: Optional[str] = None,
) -> None:
    """
    Write content to S3

    Args:
        content: The content to write (string, bytes, or dict that will be converted to JSON)
        bucket: The S3 bucket
        key: The S3 key
        content_type: Optional content type for the S3 object
    """
    try:
        s3 = get_s3_client()

        # Handle different content types
        if isinstance(content, (dict, list)):
            body = json.dumps(content).encode("utf-8")
            if content_type is None:
                content_type = "application/json"
        elif isinstance(content, str):
            body = content
            if content_type is None:
                content_type = "text/plain"
        else:
            body = content
            if content_type is None:
                content_type = "application/octet-stream"

        # Upload to S3
        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type

        s3.put_object(Bucket=bucket, Key=key, Body=body, **extra_args)
        logger.info(f"Successfully wrote to s3://{bucket}/{key}")
    except Exception as e:
        logger.error(f"Error writing to s3://{bucket}/{key}: {e}")
        raise


def list_images_from_path(image_path: str) -> List[str]:
    """
    List all image files from an S3 prefix or local directory.
    Returns image URIs/paths sorted by filename.

    Args:
        image_path: S3 URI (s3://bucket/prefix/) or local directory path

    Returns:
        List of image file paths/URIs sorted by filename
    """
    image_extensions = {
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".bmp",
        ".tiff",
        ".tif",
        ".webp",
    }

    if image_path.startswith("s3://"):
        return _list_s3_images(image_path, image_extensions)
    else:
        return _list_local_images(image_path, image_extensions)


def _list_s3_images(s3_prefix: str, image_extensions: set) -> List[str]:
    """
    List image files from an S3 prefix.

    Args:
        s3_prefix: S3 URI prefix (s3://bucket/prefix/)
        image_extensions: Set of valid image file extensions

    Returns:
        List of S3 URIs for image files sorted by filename
    """
    try:
        bucket, prefix = parse_s3_uri(s3_prefix)

        # Ensure prefix ends with / if it's meant to be a directory
        if not prefix.endswith("/") and prefix:
            prefix += "/"

        s3 = get_s3_client()
        paginator = s3.get_paginator("list_objects_v2")

        image_files = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            if "Contents" in page:
                for obj in page["Contents"]:
                    key = obj["Key"]
                    # Skip the prefix itself if it's a "directory" key
                    if key == prefix:
                        continue

                    # Check if file has image extension
                    file_ext = os.path.splitext(key)[1].lower()
                    if file_ext in image_extensions:
                        image_files.append(f"s3://{bucket}/{key}")

        # Sort by filename (not full path)
        image_files.sort(key=lambda x: os.path.basename(x))
        logger.info(f"Found {len(image_files)} image files in S3 prefix: {s3_prefix}")
        return image_files

    except Exception as e:
        logger.error(f"Error listing images from S3 prefix {s3_prefix}: {e}")
        raise


def _list_local_images(directory_path: str, image_extensions: set) -> List[str]:
    """
    List image files from a local directory.

    Args:
        directory_path: Local directory path
        image_extensions: Set of valid image file extensions

    Returns:
        List of local file paths for image files sorted by filename
    """
    try:
        if not os.path.exists(directory_path):
            logger.warning(f"Local directory does not exist: {directory_path}")
            return []

        if not os.path.isdir(directory_path):
            logger.warning(f"Path is not a directory: {directory_path}")
            return []

        image_files = []
        for filename in os.listdir(directory_path):
            file_path = os.path.join(directory_path, filename)

            # Skip directories
            if os.path.isdir(file_path):
                continue

            # Check if file has image extension
            file_ext = os.path.splitext(filename)[1].lower()
            if file_ext in image_extensions:
                image_files.append(file_path)

        # Sort by filename
        image_files.sort(key=os.path.basename)
        logger.info(
            f"Found {len(image_files)} image files in local directory: {directory_path}"
        )
        return image_files

    except Exception as e:
        logger.error(f"Error listing images from local directory {directory_path}: {e}")
        raise


def find_matching_files(
    bucket: str, pattern: str, modified_after: str | None = None
) -> List[str]:
    """
    Find files in S3 bucket that match a given pattern.

    Args:
        bucket: S3 bucket name
        pattern: File pattern with wildcards (* and ?) - case sensitive, * doesn't match /
        modified_after: Optional ISO 8601 timestamp to filter files modified after this time

    Returns:
        List of matching file keys
    """
    import re
    from datetime import datetime, timezone

    try:
        s3 = get_s3_client()
        paginator = s3.get_paginator("list_objects_v2")

        # Convert pattern: * matches anything except /, ? matches single char except /
        regex_pattern = pattern.replace("*", "[^/]*").replace("?", "[^/]")
        regex = re.compile(f"^{regex_pattern}$")

        # Parse modified_after filter if provided
        cutoff_time = None
        if modified_after:
            cutoff_time = datetime.fromisoformat(
                modified_after.replace("Z", "+00:00")
            )
            if cutoff_time.tzinfo is None:
                cutoff_time = cutoff_time.replace(tzinfo=timezone.utc)
            logger.info(f"Filtering files modified after {cutoff_time.isoformat()}")

        matching_files = []

        for page in paginator.paginate(Bucket=bucket):
            if "Contents" in page:
                for obj in page["Contents"]:
                    key = obj["Key"]
                    if regex.match(key):
                        if cutoff_time and obj.get("LastModified"):
                            last_modified = obj["LastModified"]
                            if last_modified.tzinfo is None:
                                last_modified = last_modified.replace(
                                    tzinfo=timezone.utc
                                )
                            if last_modified < cutoff_time:
                                continue
                        matching_files.append(key)

        logger.info(
            f"Found {len(matching_files)} files matching pattern '{pattern}' in bucket '{bucket}'"
            + (f" (modified after {modified_after})" if modified_after else "")
        )
        return sorted(matching_files)

    except Exception as e:
        logger.error(
            f"Error finding matching files in bucket {bucket} with pattern {pattern}: {e}"
        )
        raise
