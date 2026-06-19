# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Post bootstrap/synthesis job status to AppSync via a SigV4-signed mutation."""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_MUTATION = """
mutation UpdateConfigBootstrapJobStatus($jobId: ID!, $status: String!, $statusMessage: String, $errorMessage: String, $configVersion: String, $testSetId: String) {
  updateConfigBootstrapJobStatus(jobId: $jobId, status: $status, statusMessage: $statusMessage, errorMessage: $errorMessage, configVersion: $configVersion, testSetId: $testSetId) {
    jobId
    status
    statusMessage
    errorMessage
    configVersion
    testSetId
  }
}
"""


def post_synthesis_status(
    api_url: str,
    job_id: str,
    status: str,
    status_message: Optional[str] = None,
    error_message: Optional[str] = None,
    config_version: Optional[str] = None,
    test_set_id: Optional[str] = None,
) -> bool:
    if not api_url:
        logger.warning("APPSYNC_API_URL not configured; skipping status post")
        return False
    try:
        import boto3
        import requests
        from aws_requests_auth.aws_auth import AWSRequestsAuth
    except ImportError as e:
        logger.warning("AppSync status deps unavailable: %s", e)
        return False

    session = boto3.Session()
    credentials = session.get_credentials()
    region = session.region_name or os.environ.get("AWS_REGION", "us-east-1")
    auth = AWSRequestsAuth(
        aws_access_key=credentials.access_key,
        aws_secret_access_key=credentials.secret_key,
        aws_token=credentials.token,
        aws_host=api_url.replace("https://", "").replace("/graphql", ""),
        aws_region=region,
        aws_service="appsync",
    )

    variables = {"jobId": job_id, "status": status}
    if status_message:
        variables["statusMessage"] = status_message
    if error_message:
        variables["errorMessage"] = error_message
    if config_version:
        variables["configVersion"] = config_version
    if test_set_id:
        variables["testSetId"] = test_set_id

    try:
        response = requests.post(
            api_url,
            json={"query": _MUTATION, "variables": variables},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            auth=auth,
            timeout=30,
        )
        if response.status_code == 200 and "errors" not in response.json():
            return True
        logger.error("AppSync status post failed: %s", response.text[:500])
        return False
    except Exception:
        logger.warning("AppSync status post raised", exc_info=True)
        return False
