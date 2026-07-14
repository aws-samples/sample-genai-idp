# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Bootstrap/synthesis job status reporting.

The host removed AWS AppSync (and its subscriptions) in favor of an API Gateway
REST API + polling. The original live-status path posted an
``updateConfigBootstrapJobStatus`` AppSync mutation that a UI subscription
consumed. That transport no longer exists, so status reporting is temporarily a
no-op and must be re-implemented against the DynamoDB + polling model (write to
BootstrapTrackingTable, UI polls) as a follow-up. Signature is preserved so
callers are unaffected.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def post_synthesis_status(
    api_url: str,
    job_id: str,
    status: str,
    status_message: Optional[str] = None,
    error_message: Optional[str] = None,
    config_version: Optional[str] = None,
    test_set_id: Optional[str] = None,
) -> bool:
    logger.info(
        "Bootstrap status (job=%s status=%s config_version=%s test_set=%s): "
        "live status reporting is disabled pending the post-AppSync polling port",
        job_id,
        status,
        config_version,
        test_set_id,
    )
    return False
