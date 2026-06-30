# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Post bootstrap/synthesis job status to AppSync via a SigV4-signed mutation."""

from __future__ import annotations

import logging
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
        from idp_common.appsync.client import AppSyncClient
    except ImportError as e:
        logger.warning("AppSync status deps unavailable: %s", e)
        return False

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
        with AppSyncClient(api_url=api_url) as client:
            client.execute_mutation(_MUTATION, variables)
        return True
    except Exception:
        logger.warning("AppSync status post raised", exc_info=True)
        return False
