# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import logging
import os
import urllib.parse
from datetime import datetime, timedelta, timezone

import boto3
from idp_common.docs_service import create_document_service

# Import IDP Common modules
from idp_common.models import Document, Status
from idp_common.utils.auth import get_caller_groups

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Initialize AWS clients
sqs_client = boto3.client("sqs")
s3_client = boto3.client("s3")

# Initialize document service (same as queue_sender - defaults to AppSync)
document_service = create_document_service()

# Environment variables
queue_url = os.environ.get("QUEUE_URL")
input_bucket = os.environ.get("INPUT_BUCKET")
output_bucket = os.environ.get("OUTPUT_BUCKET")
retentionDays = int(os.environ.get("DATA_RETENTION_IN_DAYS", "365"))


def handler(event, context):
    logger.info(f"Reprocess resolver invoked with event: {json.dumps(event)}")

    try:
        # Enforce role-based authorization: only Admin and Supervisor users
        # may reprocess documents, consistent with complete_section_review pattern.
        caller_groups = get_caller_groups(event)
        is_admin = "Admin" in caller_groups
        is_supervisor = "Supervisor" in caller_groups
        if not is_admin and not is_supervisor:
            logger.warning(
                "Access denied for reprocess_document: caller groups %s lack Admin or Supervisor role",
                caller_groups,
            )
            raise PermissionError(
                "Access denied: only Admin and Supervisor users can reprocess documents"
            )

        # Validate environment variables
        if not input_bucket:
            raise Exception("INPUT_BUCKET environment variable is not set")
        if not output_bucket:
            raise Exception("OUTPUT_BUCKET environment variable is not set")
        if not queue_url:
            raise Exception("QUEUE_URL environment variable is not set")

        # Extract arguments from GraphQL event
        args = event.get("arguments", {})
        object_keys = args.get("objectKeys", [])
        version = args.get("version")  # Optional version parameter

        if not object_keys or not isinstance(object_keys, list):
            logger.error(
                "objectKeys must be a non-empty list, got %s: %r",
                type(object_keys).__name__,
                object_keys,
            )
            return False

        invalid = [k for k in object_keys if not isinstance(k, str) or not k.strip()]
        if invalid:
            logger.error("objectKeys contains invalid entries: %r", invalid)
            return False

        logger.info(
            f"Reprocessing {len(object_keys)} documents"
            + (f" with version: {version}" if version else "")
        )

        # Process each document
        success_count = 0
        for object_key in object_keys:
            try:
                reprocess_document(object_key, version)
                success_count += 1
            except Exception as e:
                logger.error(
                    f"Error reprocessing document {object_key}: {str(e)}", exc_info=True
                )
                # Continue with other documents even if one fails

        logger.info(
            f"Successfully queued {success_count}/{len(object_keys)} documents for reprocessing"
        )
        return True

    except Exception as e:
        logger.error(f"Error in reprocess handler: {str(e)}", exc_info=True)
        raise e


def reprocess_document(object_key, version=None):
    """
    Reprocess a document by creating a fresh Document object and queueing it.
    This exactly mirrors the queue_sender pattern for consistency and avoids
    S3 copy operations that can trigger duplicate events for large files.

    Args:
        object_key: S3 object key of the document to reprocess
        version: Optional configuration version to use for reprocessing
    """
    logger.info(
        f"Reprocessing document: {object_key}"
        + (f" with version: {version}" if version else "")
    )

    # Verify file exists in S3
    try:
        s3_client.head_object(Bucket=input_bucket, Key=object_key)
    except Exception as e:
        raise ValueError(
            f"Document {object_key} not found in S3 bucket {input_bucket}: {str(e)}"
        )

    # Create a fresh Document object (same as queue_sender does)
    current_time = datetime.now(timezone.utc).isoformat()

    # Extract use-case routing from S3 key (mirrors Document.from_s3_event logic)
    business_unit_id = None
    use_case_id = None
    parts = object_key.split("/", 2)
    if len(parts) >= 3:
        candidate_bu = urllib.parse.unquote_plus(parts[0])
        candidate_uc = urllib.parse.unquote_plus(parts[1])
        normalized_bu = candidate_bu.upper().lstrip("_")
        normalized_uc = candidate_uc.upper().lstrip("_")
        is_reserved = (
            normalized_bu == "DEFAULT"
            or normalized_bu.startswith("DEFAULT_")
            or normalized_uc == "DEFAULT"
            or normalized_uc.startswith("DEFAULT_")
        )
        if (
            candidate_bu
            and candidate_uc
            and "#" not in candidate_bu
            and "#" not in candidate_uc
            and "/" not in candidate_bu
            and "/" not in candidate_uc
            and not is_reserved
        ):
            business_unit_id = candidate_bu
            use_case_id = candidate_uc

    document = Document(
        id=object_key,
        input_bucket=input_bucket,
        input_key=object_key,
        output_bucket=output_bucket,
        status=Status.QUEUED,
        queued_time=current_time,
        initial_event_time=current_time,
        pages={},
        sections=[],
        config_version=version,
        business_unit_id=business_unit_id,
        use_case_id=use_case_id,
    )

    logger.info(f"Created fresh document object for reprocessing: {object_key}")

    # Calculate expiry date (same as queue_sender)
    expires_after = int(
        (datetime.now(timezone.utc) + timedelta(days=retentionDays)).timestamp()
    )

    # Create document in DynamoDB via document service (same as queue_sender - uses AppSync by default)
    logger.info(f"Creating document via document service: {document.input_key}")
    created_key = document_service.create_document(
        document, expires_after=expires_after
    )
    logger.info(f"Document created with key: {created_key}")

    # Send serialized document to SQS queue (same as queue_sender)
    doc_json = document.to_json()
    message = {
        "QueueUrl": queue_url,
        "MessageBody": doc_json,
        "MessageAttributes": {
            "EventType": {"StringValue": "DocumentReprocessed", "DataType": "String"},
            "ObjectKey": {"StringValue": object_key, "DataType": "String"},
        },
    }
    logger.info(f"Sending document to SQS queue: {object_key}")
    response = sqs_client.send_message(**message)
    logger.info(f"SQS response: {response}")

    logger.info(f"Successfully reprocessed document: {object_key}")
    return response.get("MessageId")
