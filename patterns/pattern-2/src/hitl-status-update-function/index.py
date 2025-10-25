# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Lambda function to update document HITL metadata after HITL completion.

This function is called as part of the Step Functions workflow after HITLWait
to update the document with the final HITL completion status.
"""
import json
import boto3
import logging
from typing import Any, Dict
from urllib.parse import urlparse

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.resource("s3")

# Configure logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Lambda handler to update document HITL metadata after HITL completion.

    Args:
        event: Step Functions event containing document and HITL result data
        context: Lambda context

    Returns:
        Updated document data for Step Functions
    """
    try:
        logger.info(
            f"HITL Status Update function started with event: {json.dumps(event, default=str)}"
        )

        # Extract document from event - handle different event structures
        document = None
        if "Result" in event and "document" in event["Result"]:
            document = event["Result"]["document"]
        elif "document" in event:
            document = event["document"]
        elif "HITLWaitResult" in event and "document" in event["HITLWaitResult"]:
            document = event["HITLWaitResult"]["document"]

        if not document:
            logger.error("No document found in event")
            return {"statusCode": 400, "body": "No document found in event"}

        # Extract S3 URI from document
        s3_uri = document.get("s3_uri")
        if not s3_uri:
            logger.error("No s3_uri found in document")
            return {"statusCode": 400, "body": "No s3_uri found in document"}

        parsed = urlparse(s3_uri)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")

        try:
            # Read the JSON file from S3
            obj = s3.Object(bucket, key)
            file_content = obj.get()["Body"].read().decode("utf-8")
            data = json.loads(file_content)

            # Update hitl_completed for every object in hitl_metadata
            hitl_metadata = data.get("hitl_metadata", [])
            for item in hitl_metadata:
                item["hitl_completed"] = True

            # Write the updated JSON back to S3
            obj.put(Body=json.dumps(data, separators=(",", ":")).encode("utf-8"))

            logger.info(f"Updated hitl_completed for all items in {bucket}/{key}")

            # Update the document object for the next step
            updated_document = {**document}
            if "hitl_metadata" in updated_document:
                for item in updated_document["hitl_metadata"]:
                    item["hitl_completed"] = True

            return {
                "statusCode": 200,
                "hitl_status_updated": True,
                "hitl_a2i_review": "Completed",
                "document": updated_document,
            }

        except Exception as e:
            logger.error(f"Error processing file {bucket}/{key}: {e}")
            return {"statusCode": 500, "body": f"Error: {str(e)}"}

    except Exception as e:
        logger.error(f"Error in HITL status update function: {str(e)}", exc_info=True)
        raise e
