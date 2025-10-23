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
from idp_common.s3 import write_content

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
    """
    result = defaultdict(lambda: defaultdict(dict))
    array_pattern = re.compile(r"^(.*?)\[(\d+)\]$")

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
            if isinstance(meta, dict) and "value" in meta:
                if key in inference_data:
                    updated[key] = {
                        **meta,
                        "value": convert_type(inference_data[key], meta.get("type")),
                    }
                else:
                    updated[key] = meta
            elif isinstance(meta, (dict, list)) and key in inference_data:
                updated[key] = sync_explainability(inference_data[key], meta)
            else:
                updated[key] = meta
        return updated
    return explainability_info


def clean_empty_values(data):
    """
    Recursively convert empty string values to None for DynamoDB compatibility
    while preserving the field structure.
    """
    if isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            if key and key.strip():  # Ensure key is not empty
                cleaned_value = clean_empty_values(value)
                # Convert empty strings to None, but keep the field
                if cleaned_value == "":
                    cleaned[key] = None
                else:
                    cleaned[key] = cleaned_value
        return cleaned
    elif isinstance(data, list):
        return [clean_empty_values(item) for item in data]
    else:
        # Convert empty strings to None for DynamoDB compatibility
        return None if data == "" else data


def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError


def extract_ids_from_human_loop_name(human_loop_name):
    """
    Extract execution_id, record_number, and page_id from human loop name.
    Expected format: review-bda-{human_review_id}-{execution_id}-{record_number}-{page_id_num}
    Where human_review_id is a 2-digit random value and execution_id is a UUID (contains hyphens)
    """
    try:
        if human_loop_name.startswith("review-bda-"):
            remaining = human_loop_name[11:]  # Remove 'review-bda-' (11 chars)

            # Split from right to get the last 2 parts (record_number and page_id)
            parts = remaining.rsplit("-", 2)  # Split from right, max 2 splits
            if len(parts) == 3:
                # parts[0] contains human_review_id + execution_id
                # parts[1] is record_number
                # parts[2] is page_id
                record_number = int(parts[1])
                page_id = int(parts[2]) - 1

                # Now split the first part to separate human_review_id from execution_id
                # The human_review_id is the first part before the first hyphen
                prefix_parts = parts[0].split("-", 1)  # Split only on first hyphen
                if len(prefix_parts) == 2:
                    prefix_parts[0]  # e.g., 'SI'
                    execution_id = prefix_parts[
                        1
                    ]  # e.g., 'ca13b3ed-d4eb-4e7f-a9aa-01913d24a1e7'
                    return execution_id, record_number, page_id
    except Exception as e:
        logger.error(f"Error parsing human loop name {human_loop_name}: {str(e)}")

    return None, None, None


def update_token_status(token_id, status, failure_reason, tracking_table):
    """Update the status of a token in the tracking table"""
    try:
        update_expression = "SET #status = :status, UpdatedAt = :updated_at"
        expression_values = {
            ":status": status,
            ":updated_at": datetime.datetime.now().isoformat(),
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
        logger.info(f"check_all_sections_complete_sections: {sections}")

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
        logger.info(f"check_all_pages_complete_items: {items}")

        if not items:
            return False, []

        Failed_pages = []
        for item in items:
            status = item.get("Status")
            if status in ["Failed", "Stopped"]:
                Failed_pages.append(
                    {
                        "page_id": item.get("PageId"),
                        "status": status,
                        "failure_reason": item.get("FailureReason", "Unknown failure"),
                    }
                )
            elif status != "Completed":
                return False, []  # Still has pending pages

        return True, Failed_pages
    except Exception as e:
        logger.error(f"Error checking page completion status: {str(e)}")
        return False, []


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
        logger.info(f"Task token items: {items}")

        if items:
            return items[0].get("TaskToken")
        return None
    except Exception as e:
        logger.error(f"Error finding section task token: {str(e)}")
        return None


def process_Completed_hitl(detail, execution_id, record_id, page_id, table, s3_client):
    """Process Completed HITL task"""
    try:
        # Parse A2I output from S3
        output_s3_uri = detail["humanLoopOutput"]["outputS3Uri"]
        bucket, key = output_s3_uri.replace("s3://", "").split("/", 1)
        response = s3_client.get_object(Bucket=bucket, Key=key)
        output_data = json.loads(response["Body"].read())

        logger.info(f"output_data: {output_data}")

        # Extract required fields
        input_content = output_data["inputContent"]
        human_answers = output_data["humanAnswers"][0]["answerContent"]

        # Get blueprint info
        answer_bp = human_answers.get("blueprintSelection")
        input_bp = input_content.get("blueprintName")

        # Fetch existing record from DynamoDB
        db_response = table.get_item(
            Key={"execution_id": execution_id, "record_number": record_id}
        )

        if "Item" not in db_response:
            logger.error(
                f"No record found for execution_id: {execution_id}, record_number: {record_id}"
            )
            return False

        db_item = db_response["Item"]

        # If blueprint matches, update inference result in DynamoDB
        if (
            answer_bp is not None and input_bp is not None and answer_bp == input_bp
        ) or (answer_bp is None):
            existing_result = db_item.get("hitl_corrected_result", {})
            output_bucket = db_item.get("output_bucket", {})
            object_key = db_item.get("object_key", {})
            s3_record_id = record_id - 1
            output_object_key = f"{object_key}/sections/{s3_record_id}/"

            # Process and merge human answers
            nested_update = unflatten(human_answers)
            merged_inference = deep_merge(
                existing_result.get("inference_result", {}), nested_update
            )

            # Update explainability info
            explainability = existing_result.get("explainability_info", [])
            updated_explainability = sync_explainability(
                merged_inference, explainability
            )

            # Prepare and write update to DynamoDB
            final_update = {
                **existing_result,
                "inference_result": merged_inference,
                "explainability_info": updated_explainability,
            }

            # Clean empty values to prevent DynamoDB validation errors
            cleaned_update = clean_empty_values(final_update)

            table.update_item(
                Key={"execution_id": execution_id, "record_number": record_id},
                UpdateExpression="SET hitl_corrected_result = :val",
                ExpressionAttributeValues={":val": cleaned_update},
                ReturnValues="UPDATED_NEW",
            )

            # Update S3 result file
            result_json_key = output_object_key + "result.json"
            try:
                s3_response = s3_client.get_object(
                    Bucket=output_bucket, Key=result_json_key
                )
                existing_json = json.loads(
                    s3_response["Body"].read(), parse_float=Decimal
                )
            except s3_client.exceptions.NoSuchKey:
                existing_json = {}
            except Exception as e:
                logger.error(f"Error reading existing result.json: {e}")
                existing_json = {}

            merged_json = deep_merge(existing_json, final_update)
            json_string = json.dumps(merged_json, default=decimal_default)

            write_content(
                json_string,
                output_bucket,
                result_json_key,
                content_type="application/json",
            )

            logger.info(f"Successfully updated record {execution_id}/{record_id}")

        # If blueprint selection is changed, update DynamoDB
        elif answer_bp is not None:
            table.update_item(
                Key={"execution_id": execution_id, "record_number": record_id},
                UpdateExpression="SET hitl_bp_change = :bp, hitl_corrected_result = :result",
                ExpressionAttributeValues={":bp": answer_bp, ":result": None},
                ReturnValues="UPDATED_NEW",
            )
            logger.info(
                f"Successfully updated record {execution_id}/{record_id} for Blueprint change"
            )
        else:
            raise ValueError("Blueprint Value is null and need to review error manual")

        return True
    except Exception as e:
        logger.error(f"Error processing Completed HITL: {str(e)}")
        return False


def lambda_handler(event, context):
    """
    AWS Lambda entry point for processing HITL status changes.
    """
    logger.info(f"Processing event: {json.dumps(event)}")

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(os.environ["DYNAMODB_TABLE"])
    tracking_table = dynamodb.Table(os.environ["TRACKING_TABLE"])

    try:
        detail = event.get("detail", {})
        human_loop_status = detail.get("humanLoopStatus")
        human_loop_name = detail.get("humanLoopName")

        # Extract execution_id, record_number, and page_id from human loop name
        execution_id, record_id, page_id = extract_ids_from_human_loop_name(
            human_loop_name
        )

        if not all([execution_id, record_id is not None, page_id is not None]):
            logger.error(
                f"Could not extract IDs from human loop name: {human_loop_name}"
            )
            return {"statusCode": 400, "body": "Invalid human loop name format"}

        # Get document_id from BDA metadata table
        db_response = table.get_item(
            Key={"execution_id": execution_id, "record_number": record_id}
        )

        if "Item" not in db_response:
            logger.error(
                f"No record found for execution_id: {execution_id}, record_number: {record_id}"
            )
            return {"statusCode": 404, "body": "Record not found"}

        document_id = db_response["Item"].get("object_key")
        page_token_id = f"HITL#{document_id}#section#{record_id}#page#{page_id}"
        section_token_id = f"HITL#{document_id}#section#{record_id}"

        # Get failure reason for Failed/Stopped tasks
        failure_reason = (
            detail.get("failureReason", "Unknown failure reason")
            if human_loop_status in ["Failed", "Stopped"]
            else None
        )

        # Process Completed HITL tasks
        if human_loop_status == "Completed":
            success = process_Completed_hitl(
                detail, execution_id, record_id, page_id, table, s3_client
            )
            if not success:
                return {"statusCode": 500, "body": "Failed to process Completed HITL"}

        # Update page task token status
        update_token_status(
            page_token_id, human_loop_status, failure_reason, tracking_table
        )

        # Check if all pages in this section are complete
        all_pages_complete, Failed_pages_in_section = check_all_pages_complete(
            document_id, record_id, tracking_table
        )
        logger.info(
            f"all_pages_complete status: {all_pages_complete}, Failed_pages: {Failed_pages_in_section}"
        )

        if all_pages_complete:
            # Update section token status
            section_status = "Failed" if Failed_pages_in_section else "Completed"
            section_failure_reason = (
                f"Section has {len(Failed_pages_in_section)} Failed pages"
                if Failed_pages_in_section
                else None
            )
            update_token_status(
                section_token_id, section_status, section_failure_reason, tracking_table
            )

            # Check if all sections for this document are complete
            all_sections_complete, has_failed_sections = check_all_sections_complete(
                document_id, tracking_table
            )
            logger.info(
                f"all_sections_complete: {all_sections_complete}, has_failed_sections: {has_failed_sections}"
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
                                ":failed_status": "FAILED",
                                ":stopped_status": "STOPPED",
                            },
                        )

                        for item in response.get("Items", []):
                            all_failed_pages.append(
                                {
                                    "execution_id": execution_id,
                                    "record_id": item.get("SectionId"),
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
                        # Check for blueprint changes
                        response = table.query(
                            KeyConditionExpression="execution_id = :eid",
                            ExpressionAttributeValues={":eid": execution_id},
                        )

                        blueprint_changes = []
                        for item in response.get("Items", []):
                            if item.get("hitl_bp_change") is not None:
                                blueprint_changes.append(
                                    {
                                        "record_id": item.get("record_number"),
                                        "original_blueprint": item.get(
                                            "blueprint_name", ""
                                        ),
                                        "new_blueprint": item.get("hitl_bp_change"),
                                    }
                                )

                        # Send task success
                        stepfunctions.send_task_success(
                            taskToken=section_task_token,
                            output=json.dumps(
                                {
                                    "status": "Completed",
                                    "executionId": execution_id,
                                    "message": "All human reviews Completed",
                                    "blueprintChanged": len(blueprint_changes) > 0,
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

        return {"statusCode": 200, "body": "Processing Completed successfully"}

    except ClientError as e:
        logger.error(f"DynamoDB error: {e.response['Error']['Message']}")
        return {"statusCode": 500, "body": "Database error"}
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return {"statusCode": 500, "body": "Processing Failed"}
