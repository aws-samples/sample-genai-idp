# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
import boto3
import json
import os
import logging
from datetime import datetime, timezone, timedelta
from idp_common.models import Document

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Initialize clients
dynamodb = boto3.resource("dynamodb")

# Get environment variables
TRACKING_TABLE = os.environ.get("TRACKING_TABLE")
BDA_METADATA_TABLE = os.environ.get("DYNAMODB_TABLE")
SAGEMAKER_A2I_REVIEW_PORTAL_URL = os.environ.get("SAGEMAKER_A2I_REVIEW_PORTAL_URL", "")


def lambda_handler(event, context):
    """
    Enhanced HITL wait function that:
    1. Creates task tokens for sections and pages that need human review
    2. Returns information about sections needing review
    """
    logger.info(f"Processing event: {json.dumps(event)}")

    # Extract document information using load_document to handle compression
    document_data = event.get("Payload", {}).get("Result", {}).get("document", {})
    if not document_data:
        document_data = (
            event.get("Payload", {}).get("ProcessingResult", {}).get("document", {})
        )
    if not document_data:
        document_data = event.get("Payload", {}).get("document", {})

    # Get working bucket for decompression
    working_bucket = os.environ.get("WORKING_BUCKET")
    if not working_bucket:
        logger.warning("WORKING_BUCKET environment variable not set")

    # Load document using utility method to handle compression/decompression
    try:
        document_obj = Document.load_document(document_data, working_bucket, logger)
        # Convert back to dict for the rest of the function
        document = document_obj.to_dict()
    except Exception as e:
        logger.error(f"Error loading document: {str(e)}")
        raise

    document_id = document.get("id")
    workflow_execution_arn = document.get("workflow_execution_arn")
    execution_id = None
    doc_task_token = event.get("taskToken", {})
    logger.info(f"token: {doc_task_token}")

    if workflow_execution_arn:
        execution_id = workflow_execution_arn.split(":")[-1]

    # Get hitl_metadata from the document
    hitl_metadata = document.get("hitl_metadata", [])

    if not hitl_metadata:
        logger.warning(f"No HITL metadata found for document {document_id}")
        return {
            "status": "completed",
            "message": "No human review required",
            "blueprintChanged": False,
            "blueprintChanges": [],
        }

    tracking_table = dynamodb.Table(TRACKING_TABLE)

    # Create a mapping of section IDs to task tokens
    section_task_tokens = {}
    page_task_tokens = {}

    # Process each section that needs HITL
    for section in hitl_metadata:
        if section.get("hitl_triggered"):
            section_id = str(section.get("record_number"))
            page_array = section.get("page_array", [])
            section_execution_id = section.get("execution_id")

            if not section_execution_id:
                section_execution_id = execution_id

            # Create a main section token with distinct prefix
            section_token_id = f"HITL#{document_id}#section#{section_id}"

            # Store section-level token in tracking table
            store_token_in_tracking_table(
                tracking_table,
                token_id=section_token_id,
                task_token=None,
                document_id=document_id,
                execution_id=section_execution_id,
                section_id=section_id,
                token_type="HITL_SECTION",
            )

            section_task_tokens[section_id] = section_token_id
            page_task_tokens[section_id] = {}

            # Create individual page task tokens
            for page_id in page_array:
                page_id_str = str(page_id)
                page_token_id = (
                    f"HITL#{document_id}#section#{section_id}#page#{page_id_str}"
                )

                # Store page-level token in tracking table
                store_token_in_tracking_table(
                    tracking_table,
                    token_id=page_token_id,
                    task_token=None,
                    document_id=document_id,
                    execution_id=section_execution_id,
                    section_id=section_id,
                    page_id=page_id_str,
                    token_type="HITL_PAGE",
                )

                page_task_tokens[section_id][page_id_str] = page_token_id

    # Update the document tracking record with HITL status
    try:
        # Update the HITL metadata record
        tracking_table.update_item(
            Key={"PK": f"document#{document_id}", "SK": "metadata"},
            UpdateExpression="SET HITLStatus = :status, HITLStartTime = :time, HITLReviewURL = :url",
            ExpressionAttributeValues={
                ":status": "IN_PROGRESS",
                ":time": datetime.now(timezone.utc).isoformat(),
                ":url": SAGEMAKER_A2I_REVIEW_PORTAL_URL,
            },
        )

        # Also update the main document record to show it's in HITL review
        # and include the HITL metadata fields in the main record
        tracking_table.update_item(
            Key={"PK": f"doc#{document_id}", "SK": "none"},
            UpdateExpression="SET ObjectStatus = :status, HITLStatus = :hitlStatus, HITLReviewURL = :url",
            ExpressionAttributeValues={
                ":status": "HITL_IN_PROGRESS",
                ":hitlStatus": "IN_PROGRESS",
                ":url": SAGEMAKER_A2I_REVIEW_PORTAL_URL,
            },
        )
    except Exception as e:
        logger.warning(f"Could not update document tracking record: {str(e)}")

    DocumentTokenkey = f"HITL#TaskToken#{document_id}"

    # Store OverallDocument token in tracking table
    store_token_in_tracking_table(
        tracking_table,
        token_id=DocumentTokenkey,
        task_token=doc_task_token,
        document_id=document_id,
        execution_id=section_execution_id,
        section_id=section_id,
        token_type="HITL_DOC",
    )

    # Return waiting status with section and page tokens
    return {
        "status": "waiting",
        "message": f"Waiting for {len(section_task_tokens)} human reviews to complete",
        "document": document,
        "section_task_tokens": section_task_tokens,
        "page_task_tokens": page_task_tokens,
    }


def store_token_in_tracking_table(
    table,
    token_id,
    task_token,
    document_id,
    execution_id,
    section_id,
    token_type="HITL_SECTION",
    page_id=None,
):
    """Store the token information in the tracking table"""
    item = {
        "PK": token_id,
        "SK": "none",
        "ExecutionId": execution_id,
        "DocumentId": document_id,
        "SectionId": section_id,
        "TokenType": token_type,
        "Status": "WAITING",
        "CreatedAt": datetime.now(timezone.utc).isoformat(),
        "ExpiresAfter": int(
            (datetime.now(timezone.utc) + timedelta(days=30)).timestamp()
        ),
    }

    if task_token:
        item["TaskToken"] = task_token

    if page_id is not None:
        item["PageId"] = page_id

    try:
        table.put_item(Item=item)
        logger.info(f"Stored token information: {token_id}")
    except Exception as e:
        logger.error(f"Error storing token {token_id}: {str(e)}")
