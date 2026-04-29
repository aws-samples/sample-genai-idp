# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Job service factory module."""

import os
from typing import Optional

from idp_common.dynamodb.job_service import JobDynamoDBService


def create_job_service(
    table_name: Optional[str] = None,
) -> Optional[JobDynamoDBService]:
    """
    Create a job service instance.

    Args:
        table_name: Optional table name override. If not provided, uses
                    TRACKING_TABLE environment variable.

    Returns:
        JobDynamoDBService instance, or None if table name not configured
    """
    if table_name is None:
        table_name = os.environ.get("TRACKING_TABLE", "")

    if not table_name:
        return None

    return JobDynamoDBService(table_name=table_name)
