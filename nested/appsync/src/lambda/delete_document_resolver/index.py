# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Delete document resolver Lambda function.

This function handles document deletion via GraphQL API, using the shared
delete_documents implementation from idp_common for consistent behavior
across CLI, SDK, and Web UI.
"""

import json
import logging
import os
from typing import List

import boto3

from idp_common.delete_documents import delete_single_document
from idp_common.utils.auth import get_caller_groups

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Initialize AWS clients
dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")


def handler(event, context):
    """Handle document deletion requests from AppSync."""
    logger.info(f"Delete document resolver invoked with event: {json.dumps(event)}")

    try:
        # Enforce role-based authorization: only Admin and Supervisor users
        # may delete documents, consistent with complete_section_review pattern.
        caller_groups = get_caller_groups(event)
        is_admin = "Admin" in caller_groups
        is_supervisor = "Supervisor" in caller_groups
        if not is_admin and not is_supervisor:
            logger.warning(
                "Access denied for delete_document: caller groups %s lack Admin or Supervisor role",
                caller_groups,
            )
            raise PermissionError(
                "Access denied: only Admin and Supervisor users can delete documents"
            )

        object_keys: List[str] = event["arguments"]["objectKeys"]

        # Validate input
        if not object_keys or not isinstance(object_keys, list):
            raise ValueError("objectKeys must be a non-empty list")

        tracking_table = dynamodb.Table(os.environ["TRACKING_TABLE_NAME"])
        input_bucket = os.environ["INPUT_BUCKET"]
        output_bucket = os.environ["OUTPUT_BUCKET"]

        logger.info(f"Preparing to delete {len(object_keys)} documents: {object_keys}")

        deleted_count = 0
        failed_count = 0

        # Delete each document using the shared idp_common implementation
        for object_key in object_keys:
            logger.info(f"Processing deletion for document: {object_key}")

            result = delete_single_document(
                object_key=object_key,
                tracking_table=tracking_table,
                s3_client=s3,
                input_bucket=input_bucket,
                output_bucket=output_bucket,
            )

            if result["success"]:
                deleted_count += 1
                logger.info(f"Successfully deleted document: {object_key}")
            else:
                failed_count += 1
                logger.error(
                    f"Failed to delete document {object_key}: {result.get('errors', [])}"
                )

        logger.info(
            f"Completed deletion: {deleted_count} successful, {failed_count} failed"
        )
        return deleted_count > 0 or failed_count == 0

    except Exception as e:
        logger.error(f"Error in delete_document resolver: {str(e)}", exc_info=True)
        raise e