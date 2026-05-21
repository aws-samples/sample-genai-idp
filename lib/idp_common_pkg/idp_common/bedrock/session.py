# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Session factory for Bedrock clients.

Returns a ``boto3.Session`` configured for either same-account or
cross-account (hub-account) Bedrock access. When the
``BEDROCK_ASSUME_ROLE_ARN`` environment variable is set, the returned
session uses ``DeferredRefreshableCredentials`` so that the underlying
``sts:AssumeRole`` is refreshed automatically before expiry — required
for warm Lambda containers that outlive a single STS session.

When the environment variable is not set, a default session is
returned with no behavior change from prior versions.
"""

import logging
import os
import threading
from typing import Optional

import boto3
from botocore.credentials import (
    DeferredRefreshableCredentials,
    create_assume_role_refresher,
)
from botocore.session import Session as BotocoreSession

logger = logging.getLogger(__name__)

# Lambda function names are <= 64 chars, but RoleSessionName allows up
# to 64 with a restricted character set. Truncate defensively.
_MAX_SESSION_NAME_LENGTH = 64

_session_lock = threading.Lock()
_cached_session: Optional[boto3.Session] = None
_cached_region: Optional[str] = None


def get_bedrock_session(region: Optional[str] = None) -> boto3.Session:
    """
    Return a boto3 Session for Bedrock data-plane and control-plane clients.

    Behavior:
        - If ``BEDROCK_ASSUME_ROLE_ARN`` is unset (or empty), returns a
          plain ``boto3.Session`` using the Lambda's execution-role
          credentials (same-account, unchanged behavior).
        - If set, returns a session whose credentials are produced by
          ``sts:AssumeRole`` against the given role ARN, with automatic
          credential refresh via
          ``botocore.credentials.DeferredRefreshableCredentials``.

    Optional environment variables:
        ``BEDROCK_ASSUME_ROLE_EXTERNAL_ID``: passed to ``AssumeRole`` as
        ``ExternalId``. Common requirement for cross-account trust
        policies.
        ``BEDROCK_ASSUME_ROLE_SESSION_NAME``: overrides the session name
        used in CloudTrail. Defaults to ``AWS_LAMBDA_FUNCTION_NAME`` for
        easy attribution.

    The returned session is cached per-process keyed on ``region``.

    Args:
        region: AWS region for the session and STS call. Defaults to
            None (boto3 picks up ``AWS_REGION`` / ``AWS_DEFAULT_REGION``).

    Returns:
        A ``boto3.Session`` ready to construct Bedrock clients from.
    """
    global _cached_session, _cached_region

    with _session_lock:
        if _cached_session is not None and _cached_region == region:
            return _cached_session

        role_arn = os.environ.get("BEDROCK_ASSUME_ROLE_ARN", "").strip()
        if not role_arn:
            session = boto3.Session(region_name=region)
            _cached_session = session
            _cached_region = region
            return session

        session_name = (
            os.environ.get("BEDROCK_ASSUME_ROLE_SESSION_NAME")
            or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
            or "idp-bedrock"
        )[:_MAX_SESSION_NAME_LENGTH]
        external_id = (
            os.environ.get("BEDROCK_ASSUME_ROLE_EXTERNAL_ID", "").strip() or None
        )

        sts_client = boto3.client("sts", region_name=region)
        assume_role_params = {
            "RoleArn": role_arn,
            "RoleSessionName": session_name,
        }
        if external_id:
            assume_role_params["ExternalId"] = external_id

        botocore_sess = BotocoreSession()
        botocore_sess._credentials = DeferredRefreshableCredentials(
            method="sts-assume-role",
            refresh_using=create_assume_role_refresher(sts_client, assume_role_params),
        )

        logger.info(
            "Bedrock session configured for cross-account access "
            "(role=%s session_name=%s external_id=%s region=%s)",
            role_arn,
            session_name,
            "set" if external_id else "unset",
            region or "default",
        )

        session = boto3.Session(botocore_session=botocore_sess, region_name=region)
        _cached_session = session
        _cached_region = region
        return session


def reset_cached_session() -> None:
    """Reset the cached session. Intended for unit tests only."""
    global _cached_session, _cached_region
    with _session_lock:
        _cached_session = None
        _cached_region = None
