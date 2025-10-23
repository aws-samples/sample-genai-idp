# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import boto3
import json
import os
import logging
import datetime
import re
from collections import defaultdict
from decimal import Decimal
from botocore.exceptions import ClientError

# Configure logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize clients
stepfunctions = boto3.client("stepfunctions")
s3_client = boto3.client("s3")


def unflatten(data: dict) -> dict:
    """
    Convert flattened dictionary keys with array notation (e.g., 'a.b[0].c')
    into nested dictionaries/lists.
    If keys don't contain dots, return the data as-is.
    """
    if not data:
        return data

    # Check if any keys contain dots (indicating nested structure)
    has_nested_keys = any("." in key for key in data.keys())

    # If no nested keys, return data as-is
    if not has_nested_keys:
        logger.info("No nested keys found in human answers, returning flat structure")
        return data

    result = defaultdict(lambda: defaultdict(dict))
    array_pattern = re.compile(r"^(.*?)\[(\d+)\]$")

    try:
        for key, value in data.items():
            current = result
            parts = key.split(".")
            for i, part in enumerate(parts):
                arr_match = array_pattern.match(part)
                if arr_match:
                    base_name = arr_match.group(1)
                    idx = int(arr_match.group(2))
                    if base_name not in current:
                        current[base_name] = []
                    while len(current[base_name]) <= idx:
                        current[base_name].append(defaultdict(dict))
                    if i == len(parts) - 1:
                        current[base_name][idx] = value
                    else:
                        current = current[base_name][idx]
                else:
                    if i == len(parts) - 1:
                        current[part] = value
                    else:
                        if part not in current:
                            current[part] = defaultdict(dict)
                        current = current[part]
    except Exception as e:
        logger.error(f"Error in unflatten function: {str(e)}, returning original data")
        return data

    def convert(obj):
        if isinstance(obj, defaultdict):
            return {k: convert(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert(item) for item in obj]
        return obj

    return convert(result)


def deep_merge(target, source):
    """
    Recursively merge two nested dictionaries/lists.
    """
    if isinstance(target, dict) and isinstance(source, dict):
        for key, value in source.items():
            if key in target:
                target[key] = deep_merge(target[key], value)
            else:
                target[key] = value
        return target
    elif isinstance(target, list) and isinstance(source, list):
        merged = []
        max_len = max(len(target), len(source))
        for i in range(max_len):
            t = target[i] if i < len(target) else {}
            s = source[i] if i < len(source) else {}
            merged.append(deep_merge(t, s))
        return merged
    else:
        return source


def convert_type(value, data_type):
    """
    Convert value to the specified data_type for explainability_info.
    """
    if value == "None":
        return None if data_type != "string" else ""
    if data_type == "boolean":
        return str(value).lower() in ("true", "1", "yes")
    if data_type == "number":
        try:
            return Decimal(str(value)) if "." in str(value) else int(value)
        except Exception:
            return value
    return value


def sync_explainability(inference_data, explainability_info):
    """
    Update explainability_info with values from inference_data, preserving types.
    """
    try:
        if explainability_info is None:
            return None

        # Handle case where explainability_info is a string
        if isinstance(explainability_info, str):
            logger.warning(
                "explainability_info is unexpectedly a string, returning as-is"
            )
            return explainability_info

        # Handle case where inference_data is not a dict
        if not isinstance(inference_data, dict):
            return explainability_info

        if isinstance(explainability_info, list):
            if isinstance(inference_data, list):
                return [
                    (
                        sync_explainability(inference_data[i], explainability_info[i])
                        if i < len(inference_data)
                        else explainability_info[i]
                    )
                    for i in range(len(explainability_info))
                ]
            else:
                return [
                    sync_explainability(inference_data, item)
                    for item in explainability_info
                ]

        if isinstance(explainability_info, dict):
            updated = {}
            for key, meta in explainability_info.items():
                try:
                    if isinstance(meta, dict) and "value" in meta:
                        if inference_data and key in inference_data:
                            updated[key] = {
                                **meta,
                                "value": convert_type(
                                    inference_data[key], meta.get("type")
                                ),
                            }
                        else:
                            updated[key] = meta
                    elif (
                        isinstance(meta, (dict, list))
                        and inference_data
                        and key in inference_data
                    ):
                        updated[key] = sync_explainability(inference_data[key], meta)
                    else:
                        updated[key] = meta
                except Exception as e:
                    logger.warning(f"Error processing key '{key}': {str(e)}")
                    updated[key] = meta
            return updated

        return explainability_info

    except Exception as e:
        logger.error(f"Unexpected error in sync_explainability: {str(e)}")
        return explainability_info


def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError


def update_token_status(token_id, status, failure_reason, tracking_table):
    """Update the status of a token in the tracking table"""
    try:
        update_expression = "SET #status = :status, UpdatedAt = :updated_at"
        expression_values = {
            ":status": status,
            ":updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        if failure_reason:
            update_expression += ", FailureReason = :reason"
            expression_values[":reason"] = failure_reason

        tracking_table.update_item(
            Key={"PK": token_id, "SK": "none"},
            UpdateExpression=update_expression,
            ExpressionAttributeNames={"#status": "Status"},
            ExpressionAttributeValues=expression_values,
        )
        logger.info(f"Updated token {token_id} status to {status}")
    except Exception as e:
        logger.error(f"Error updating token status: {str(e)}")


def check_all_pages_complete(document_id, section_id, tracking_table):
    """Check if all pages in a section are complete (Completed, Failed, or Stopped) and return failure info"""
    try:
        response = tracking_table.scan(
            FilterExpression="begins_with(PK, :prefix) AND TokenType = :type",
            ExpressionAttributeValues={
                ":prefix": f"HITL#{document_id}#section#{section_id}#page#",
                ":type": "HITL_PAGE",
            },
        )

        items = response.get("Items", [])

        if not items:
            return False, []

        failed_pages = []
        for item in items:
            status = item.get("Status")
            if status in ["Failed", "Stopped"]:
                failed_pages.append(
                    {
                        "page_id": item.get("PageId"),
                        "status": status,
                        "failure_reason": item.get("FailureReason", "Unknown failure"),
                    }
                )
            elif status != "Completed":
                return False, []  # Still has pending pages

        return True, failed_pages
    except Exception as e:
        logger.error(f"Error checking page completion status: {str(e)}")
        return False, []


def check_all_sections_complete(document_id, tracking_table):
    """Check if all sections for this document are complete (Completed or Failed)"""
    try:
        response = tracking_table.scan(
            FilterExpression="begins_with(PK, :prefix) AND TokenType = :type",
            ExpressionAttributeValues={
                ":prefix": f"HITL#{document_id}#section#",
                ":type": "HITL_SECTION",
            },
        )

        sections = response.get("Items", [])

        if not sections:
            return False, False

        has_failed_sections = False
        for section in sections:
            status = section.get("Status")
            if status == "Failed":
                has_failed_sections = True
            elif status != "Completed":
                return False, False  # Still has pending sections

        return True, has_failed_sections
    except Exception as e:
        logger.error(f"Error checking section completion status: {str(e)}")
        return False, False


def find_doc_task_token(document_id, tracking_table):
    """Find any record with a task token for this document"""
    try:
        response = tracking_table.scan(
            FilterExpression="begins_with(PK, :prefix) AND TokenType = :type AND attribute_exists(TaskToken)",
            ExpressionAttributeValues={
                ":prefix": f"HITL#TaskToken#{document_id}",
                ":type": "HITL_DOC",
            },
        )

        items = response.get("Items", [])

        if items:
            return items[0].get("TaskToken")
        return None
    except Exception as e:
        logger.error(f"Error finding section task token: {str(e)}")
        return None


def extract_ids_from_human_loop_name(human_loop_name):
    """
    Extract execution_id, section_id, and page_number from human loop name.
    Expected format: review-section-{unique_value}-{execution_id}-{section_id}-{page_number}
    """
    try:
        if human_loop_name.startswith("review-section-"):
            remaining = human_loop_name[15:]  # Remove 'review-section-' (15 chars)

            # Split from right to get the last 3 parts (execution_id, section_id, page_number)
            parts = remaining.rsplit("-", 3)  # Split from right, max 3 splits
            if len(parts) == 4:
                # parts[0] is unique_value
                # parts[1] is execution_id
                # parts[2] is section_id
                # parts[3] is page_number
                execution_id = parts[1]
                section_id = parts[2]
                page_number = int(parts[3])
                return execution_id, section_id, page_number
    except Exception as e:
        logger.error(f"Error parsing human loop name {human_loop_name}: {str(e)}")

    return None, None, None


def write_content_to_s3(content, bucket, key, content_type="application/json"):
    """Write content to S3 bucket"""
    try:
        s3_client.put_object(
            Bucket=bucket, Key=key, Body=content, ContentType=content_type
        )
        logger.info(f"Successfully wrote content to s3://{bucket}/{key}")
    except Exception as e:
        logger.error(f"Error writing to S3: {str(e)}")
        raise


def process_completed_hitl(
    detail, execution_id, section_id, page_number, s3_bucket, document_id
):
    """Process completed HITL task and update S3 results"""
    try:
        # Parse A2I output from S3
        output_s3_uri = detail["humanLoopOutput"]["outputS3Uri"]
        bucket, key = output_s3_uri.replace("s3://", "").split("/", 1)
        response = s3_client.get_object(Bucket=bucket, Key=key)
        output_data = json.loads(response["Body"].read())

        logger.info(f"Processing A2I output for section {section_id}")

        # Extract required fields
        input_content = output_data["inputContent"]
        human_answers = output_data["humanAnswers"][0]["answerContent"]

        # Get S3 context from input content
        s3_bucket = input_content.get("s3Bucket", s3_bucket)
        document_id = input_content.get("documentId", document_id)
        section_id = input_content.get("sectionId", section_id)

        # Construct S3 path for section results
        section_result_key = f"{document_id}/sections/{section_id}/result.json"

        # Read existing section result from S3
        try:
            s3_response = s3_client.get_object(Bucket=s3_bucket, Key=section_result_key)
            existing_result = json.loads(
                s3_response["Body"].read(), parse_float=Decimal
            )
        except s3_client.exceptions.NoSuchKey:
            logger.warning(
                f"Section result file not found: s3://{s3_bucket}/{section_result_key}"
            )
            existing_result = {}
        except Exception as e:
            logger.error(f"Error reading existing section result: {e}")
            existing_result = {}

        # Process and merge human answers
        try:
            nested_update = unflatten(human_answers)
        except Exception as e:
            logger.error(f"Error in unflatten function: {str(e)}")
            nested_update = human_answers

        # Get existing inference result and explainability info
        existing_inference = existing_result.get("inference_result", {})
        existing_explainability = existing_result.get("explainability_info", [])

        # Ensure existing_explainability is the correct type (list or dict, not string)
        if isinstance(existing_explainability, str):
            logger.warning(
                "explainability_info is a string, attempting to parse as JSON"
            )
            try:
                existing_explainability = json.loads(existing_explainability)
            except json.JSONDecodeError:
                logger.error(
                    "Failed to parse explainability_info as JSON, using empty list"
                )
                existing_explainability = []

        # Merge human corrections with existing inference result
        try:
            merged_inference = deep_merge(existing_inference, nested_update)
        except Exception as e:
            logger.error(f"Error in deep_merge function: {str(e)}")
            merged_inference = nested_update

        # Update explainability info with corrected values
        try:
            updated_explainability = sync_explainability(
                merged_inference, existing_explainability
            )
        except Exception as e:
            logger.error(f"Error in sync_explainability function: {str(e)}")
            updated_explainability = existing_explainability

        # Update the result with corrected data
        updated_result = {
            **existing_result,
            "inference_result": merged_inference,
            "explainability_info": updated_explainability,
            "hitl_corrected": True,
            "hitl_correction_timestamp": datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat(),
        }

        # Write updated result back to S3
        json_string = json.dumps(updated_result, default=decimal_default)
        write_content_to_s3(json_string, s3_bucket, section_result_key)

        logger.info(
            f"Successfully updated section result for {document_id}/section/{section_id}"
        )
        return True

    except Exception as e:
        logger.error(f"Error processing completed HITL: {str(e)}")
        return False


def lambda_handler(event, context):
    """
    AWS Lambda entry point for processing HITL status changes.
    """
    logger.info(f"Processing event: {json.dumps(event)}")

    # Initialize DynamoDB tracking table
    dynamodb = boto3.resource("dynamodb")
    tracking_table = dynamodb.Table(os.environ.get("TRACKING_TABLE", ""))

    try:
        detail = event.get("detail", {})
        human_loop_status = detail.get("humanLoopStatus")
        human_loop_name = detail.get("humanLoopName")

        # Extract execution_id, section_id, and page_number from human loop name
        execution_id, section_id, page_number = extract_ids_from_human_loop_name(
            human_loop_name
        )

        if not all([execution_id, section_id, page_number is not None]):
            logger.error(
                f"Could not extract IDs from human loop name: {human_loop_name}"
            )
            return {"statusCode": 400, "body": "Invalid human loop name format"}

        logger.info(
            f"Processing HITL status change: {human_loop_status} for execution_id: {execution_id}, section_id: {section_id}, page: {page_number}"
        )

        # Get S3 context from A2I input if available
        s3_bucket = None
        document_id = None

        if human_loop_status == "Completed":
            # Parse A2I output to get S3 context
            output_s3_uri = detail["humanLoopOutput"]["outputS3Uri"]
            bucket, key = output_s3_uri.replace("s3://", "").split("/", 1)
            response = s3_client.get_object(Bucket=bucket, Key=key)
            output_data = json.loads(response["Body"].read())
            input_content = output_data["inputContent"]

            s3_bucket = input_content.get("s3Bucket")
            document_id = input_content.get("documentId")

            if not s3_bucket or not document_id:
                logger.error(
                    f"Missing S3 context in A2I input: bucket={s3_bucket}, document_id={document_id}"
                )
                return {"statusCode": 400, "body": "Missing S3 context in A2I input"}

            # Process completed HITL task
            success = process_completed_hitl(
                detail, execution_id, section_id, page_number, s3_bucket, document_id
            )
            if not success:
                return {"statusCode": 500, "body": "Failed to process completed HITL"}

        # For Failed/Stopped tasks, get document_id from A2I input if available
        if human_loop_status in ["Failed", "Stopped"] and not document_id:
            try:
                output_s3_uri = detail.get("humanLoopOutput", {}).get("outputS3Uri")
                if output_s3_uri:
                    bucket, key = output_s3_uri.replace("s3://", "").split("/", 1)
                    response = s3_client.get_object(Bucket=bucket, Key=key)
                    output_data = json.loads(response["Body"].read())
                    input_content = output_data["inputContent"]
                    document_id = input_content.get("documentId")
            except Exception as e:
                logger.warning(
                    f"Could not extract document_id from failed/stopped task: {str(e)}"
                )
                # Fallback: try to extract from human loop name pattern
                document_id = execution_id  # Use execution_id as fallback

        if not document_id:
            logger.error("Could not determine document_id")
            return {"statusCode": 400, "body": "Could not determine document_id"}

        # Create token IDs
        page_token_id = f"HITL#{document_id}#section#{section_id}#page#{page_number}"
        section_token_id = f"HITL#{document_id}#section#{section_id}"

        # Get failure reason for Failed/Stopped tasks
        failure_reason = (
            detail.get("failureReason", "Unknown failure reason")
            if human_loop_status in ["Failed", "Stopped"]
            else None
        )

        # Update page task token status
        update_token_status(
            page_token_id, human_loop_status, failure_reason, tracking_table
        )

        # Check if all pages in this section are complete
        all_pages_complete, failed_pages_in_section = check_all_pages_complete(
            document_id, section_id, tracking_table
        )

        if all_pages_complete:
            # Update section token status
            section_status = "Failed" if failed_pages_in_section else "Completed"
            section_failure_reason = (
                f"Section has {len(failed_pages_in_section)} failed pages"
                if failed_pages_in_section
                else None
            )
            update_token_status(
                section_token_id, section_status, section_failure_reason, tracking_table
            )

            # Check if all sections for this document are complete
            all_sections_complete, has_failed_sections = check_all_sections_complete(
                document_id, tracking_table
            )

            if all_sections_complete:
                section_task_token = find_doc_task_token(document_id, tracking_table)

                if section_task_token:
                    if has_failed_sections:
                        # Collect all failed pages for failure message
                        all_failed_pages = []
                        response = tracking_table.scan(
                            FilterExpression="begins_with(PK, :prefix) AND TokenType = :type AND (#status = :failed_status OR #status = :stopped_status)",
                            ExpressionAttributeNames={"#status": "Status"},
                            ExpressionAttributeValues={
                                ":prefix": f"HITL#{document_id}#section#",
                                ":type": "HITL_PAGE",
                                ":failed_status": "Failed",
                                ":stopped_status": "Stopped",
                            },
                        )

                        for item in response.get("Items", []):
                            all_failed_pages.append(
                                {
                                    "execution_id": execution_id,
                                    "section_id": item.get("SectionId"),
                                    "page_id": item.get("PageId"),
                                    "failure_reason": item.get(
                                        "FailureReason", "Unknown failure"
                                    ),
                                }
                            )

                        # Send task failure
                        stepfunctions.send_task_failure(
                            taskToken=section_task_token,
                            error="HITLFailedException",
                            cause=f"HITL review failed for {len(all_failed_pages)} page(s): {json.dumps(all_failed_pages)}",
                        )
                        logger.info(f"Sent task failure for execution {execution_id}")

                        # Update document tracking to FAILED
                        tracking_table.update_item(
                            Key={"PK": f"document#{document_id}", "SK": "metadata"},
                            UpdateExpression="SET HITLStatus = :status, HITLCompletionTime = :time",
                            ExpressionAttributeValues={
                                ":status": "FAILED",
                                ":time": datetime.datetime.now(
                                    datetime.timezone.utc
                                ).isoformat(),
                            },
                        )

                        tracking_table.update_item(
                            Key={"PK": f"doc#{document_id}", "SK": "none"},
                            UpdateExpression="SET ObjectStatus = :status, HITLStatus = :hitlStatus",
                            ExpressionAttributeValues={
                                ":status": "HITL_FAILED",
                                ":hitlStatus": "FAILED",
                            },
                        )
                    else:
                        # Send task success
                        stepfunctions.send_task_success(
                            taskToken=section_task_token,
                            output=json.dumps(
                                {
                                    "status": "Completed",
                                    "executionId": execution_id,
                                    "message": "All human reviews completed",
                                }
                            ),
                        )
                        logger.info(f"Sent task success for execution {execution_id}")

                        # Update document tracking to Completed
                        tracking_table.update_item(
                            Key={"PK": f"document#{document_id}", "SK": "metadata"},
                            UpdateExpression="SET HITLStatus = :status, HITLCompletionTime = :time, HITLReviewURL = :url",
                            ExpressionAttributeValues={
                                ":status": "Completed",
                                ":time": datetime.datetime.now(
                                    datetime.timezone.utc
                                ).isoformat(),
                                ":url": None,
                            },
                        )

                        tracking_table.update_item(
                            Key={"PK": f"doc#{document_id}", "SK": "none"},
                            UpdateExpression="SET ObjectStatus = :status, HITLStatus = :hitlStatus, HITLReviewURL = :url",
                            ExpressionAttributeValues={
                                ":status": "Completed",
                                ":hitlStatus": "Completed",
                                ":url": None,
                            },
                        )

        return {
            "statusCode": 200,
            "body": f"Processing completed successfully for {human_loop_status}",
        }

    except ClientError as e:
        logger.error(f"AWS service error: {e.response['Error']['Message']}")
        return {"statusCode": 500, "body": "AWS service error"}
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return {"statusCode": 500, "body": "Processing failed"}
