# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Centralized config loader — reads config.yaml from S3 (primary) or local file (fallback).

S3 config allows the UI to update settings (model, redaction mode, bounding boxes)
without redeploying Lambdas. All handlers call load_config() instead of their own _load_config().

Env vars:
  CONFIG_BUCKET  — S3 bucket containing config.yaml (set by CFN/TF)
  CONFIG_KEY     — S3 key for config.yaml (default: config.yaml)
  CONFIG_PATH    — local fallback path (default: /var/task/config.yaml)
"""

import os
import logging
import yaml
import boto3

logger = logging.getLogger(__name__)

_cached_config = None
_s3_client = None

DEFAULT_CONFIG = {
    "processing": {"approach": "image"},
    "model": {
        "id": "global.anthropic.claude-sonnet-4-6",
        "provider": "anthropic",
    },
    "redaction": {"mode": "synthetic"},
}


def _get_s3_client():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3")
    return _s3_client


def load_config(use_cache=True):
    """Load config from S3 (if CONFIG_BUCKET set) or local file.

    Args:
        use_cache: If True, returns cached config after first load.
                   Set False to force re-read (e.g., after UI update).
    """
    global _cached_config
    if use_cache and _cached_config is not None:
        return _cached_config

    config = None
    bucket = os.environ.get("CONFIG_BUCKET", "")
    key = os.environ.get("CONFIG_KEY", "config.yaml")

    # Try S3 first
    if bucket:
        try:
            resp = _get_s3_client().get_object(Bucket=bucket, Key=key)
            config = yaml.safe_load(resp["Body"].read())
            logger.info(f"Config loaded from s3://{bucket}/{key}")
        except Exception as e:
            logger.warning(f"Failed to load config from S3: {e}, falling back to local")

    # Fallback to local file
    if config is None:
        config_path = os.environ.get("CONFIG_PATH", "/var/task/config.yaml")
        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)
            logger.info(f"Config loaded from {config_path}")
        except Exception as e:
            logger.warning(f"Failed to load local config: {e}, using defaults")
            config = DEFAULT_CONFIG

    _cached_config = config
    return config


def invalidate_cache():
    """Clear cached config so next load_config() re-reads from S3."""
    global _cached_config
    _cached_config = None
