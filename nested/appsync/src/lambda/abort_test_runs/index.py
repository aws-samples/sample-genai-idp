# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Lambda function to abort test runs and their associated document processing.

This function handles aborting test runs by:
1. Retrieving test run metadata from DynamoDB
2. Invoking the abort workflow Lambda for all documents in the test run
3. Updating the test run status to ABORTED
"""

import json
import logging
import os
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')
sqs_client = boto3.client('sqs')

# Test run statuses that can be aborted (before processing completes)
ABORTABLE_STATUSES = {'QUEUED', 'RUNNING'}


def lambda_handler(event, context):
    """
    Abort test runs by stopping document processing and updating status.

    Args:
        event: GraphQL event with testRunIds argument
        context: Lambda context

    Returns:
        Dict with abort results including counts and errors
    """
    try:
        test_run_ids = event['arguments']['testRunIds']
        logger.info(f"Aborting test runs: {test_run_ids}")

        tracking_table_name = os.environ.get('TRACKING_TABLE_NAME')
        abort_workflow_function_name = os.environ.get('ABORT_WORKFLOW_FUNCTION_NAME')

        if not tracking_table_name or not abort_workflow_function_name:
            raise ValueError("Required environment variables not set")

        tracking_table = dynamodb.Table(tracking_table_name)  # type: ignore[attr-defined]

        aborted_count = 0
        failed_count = 0
        errors = []

        # Process each test run
        for test_run_id in test_run_ids:
            try:
                result = abort_single_test_run(
                    test_run_id,
                    tracking_table,
                    abort_workflow_function_name
                )

                if result['success']:
                    aborted_count += 1
                    logger.info(f"Successfully aborted test run {test_run_id}")
                else:
                    failed_count += 1
                    error_msg = result.get('error', 'Unknown error')
                    errors.append(f"{test_run_id}: {error_msg}")
                    logger.error(f"Failed to abort test run {test_run_id}: {error_msg}")

            except Exception as e:
                failed_count += 1
                error_msg = str(e)
                errors.append(f"{test_run_id}: {error_msg}")
                logger.error(
                    f"Exception aborting test run {test_run_id}: {error_msg}",
                    exc_info=True
                )

        # Prepare response
        success = aborted_count > 0 or failed_count == 0
        message = f"Aborted {aborted_count} test run(s)"
        if failed_count > 0:
            message += f", {failed_count} failed"

        logger.info(f"Abort test runs complete: {message}")

        return {
            "success": success,
            "message": message,
            "abortedCount": aborted_count,
            "failedCount": failed_count,
            "errors": errors if errors else None
        }

    except Exception as e:
        logger.error(f"Error in abort test runs handler: {str(e)}", exc_info=True)
        return {
            "success": False,
            "message": f"Error: {str(e)}",
            "abortedCount": 0,
            "failedCount": len(test_run_ids) if 'test_run_ids' in locals() else 0,
            "errors": [str(e)]
        }


def abort_single_test_run(test_run_id, tracking_table, abort_workflow_function_name):
    """
    Abort a single test run and its documents.

    Args:
        test_run_id: Test run identifier
        tracking_table: DynamoDB table resource
        abort_workflow_function_name: Name of the abort workflow Lambda function

    Returns:
        Dict with 'success' boolean and optional 'error' message
    """
    try:
        # Get test run metadata
        response = tracking_table.get_item(
            Key={'PK': f"testrun#{test_run_id}", 'SK': "metadata"}
        )

        if 'Item' not in response:
            return {"success": False, "error": "Test run not found"}

        item = response['Item']
        current_status = item.get('Status', '').upper()

        # Check if test run can be aborted
        if current_status not in ABORTABLE_STATUSES:
            return {
                "success": False,
                "error": f"Cannot abort test run with status {current_status}"
            }

        # Extract document object keys from Files list
        object_keys = []
        if 'Files' in item and item['Files']:
            for file_name in item['Files']:
                object_key = f"{test_run_id}/{file_name}"
                object_keys.append(object_key)

        # Abort all documents in the test run (async invocation)
        # Note: abort_workflow_resolver handles completed/failed gracefully
        if object_keys:
            logger.info(
                f"Aborting {len(object_keys)} documents for test run {test_run_id}"
            )
            try:
                lambda_client.invoke(
                    FunctionName=abort_workflow_function_name,
                    InvocationType='Event',  # Async
                    Payload=json.dumps({
                        'arguments': {'objectKeys': object_keys}
                    })
                )
                logger.info(f"Invoked abort workflow for {len(object_keys)} documents")
            except Exception as e:
                logger.error(f"Failed to invoke abort workflow: {str(e)}")
                # Continue anyway to wait for documents

        # Wait for documents to reach terminal state (max 25 seconds to stay within AppSync timeout)
        logger.info(f"Waiting for documents to reach terminal state for test run {test_run_id}")
        _wait_for_documents_terminal_state(tracking_table, test_run_id, object_keys, max_wait_time=25)

        # Queue metrics calculation for any completed documents
        try:
            queue_url = os.environ.get("TEST_RESULT_CACHE_UPDATE_QUEUE_URL")
            if queue_url:
                sqs_client.send_message(
                    QueueUrl=queue_url,
                    MessageBody=json.dumps({"testRunId": test_run_id}),
                )
                logger.info(
                    f"Queued cache update for aborted test run: {test_run_id}"
                )
        except Exception as e:
            logger.warning(
                f"Failed to queue cache update for {test_run_id}: {e}"
            )

        # Update test run status to ABORTED after documents have settled and metrics queued
        try:
            # Format timestamp for AppSync AWSDateTime scalar (ISO 8601 with Z suffix)
            completed_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            tracking_table.update_item(
                Key={'PK': f"testrun#{test_run_id}", 'SK': "metadata"},
                UpdateExpression="SET #status = :status, CompletedAt = :completed_at",
                ExpressionAttributeNames={'#status': 'Status'},
                ExpressionAttributeValues={
                    ':status': 'ABORTED',
                    ':completed_at': completed_at
                }
            )
            logger.info(f"Updated test run {test_run_id} status to ABORTED")
        except Exception as e:
            logger.error(f"Failed to update test run status: {str(e)}")
            return {"success": False, "error": f"Failed to update status: {str(e)}"}

        return {"success": True}

    except ClientError as e:
        logger.error(f"DynamoDB error for test run {test_run_id}: {str(e)}")
        return {"success": False, "error": f"Database error: {str(e)}"}
    except Exception as e:
        logger.error(
            f"Unexpected error for test run {test_run_id}: {str(e)}",
            exc_info=True
        )
        return {"success": False, "error": str(e)}


def _wait_for_documents_terminal_state(tracking_table, test_run_id, object_keys, max_wait_time=25):
    """
    Wait for all documents in the test run to reach a terminal state.

    Terminal states for documents:
    - ABORTED (stopped by abort workflow)
    - FAILED (processing failed)
    - COMPLETED with EvaluationStatus='COMPLETED' (finished evaluation)

    Args:
        tracking_table: DynamoDB table resource
        test_run_id: Test run identifier
        object_keys: List of document object keys (S3 paths)
        max_wait_time: Maximum time to wait in seconds (default 25 for AppSync timeout)
    """
    poll_interval = 2  # Check every 2 seconds
    start_time = time.time()

    terminal_statuses = {'ABORTED', 'FAILED'}

    while time.time() - start_time < max_wait_time:
        pending_count = 0
        completed_eval_count = 0
        aborted_count = 0

        for object_key in object_keys:
            try:
                # Query document status
                response = tracking_table.get_item(
                    Key={'PK': f"doc#{object_key}", 'SK': 'status'}
                )

                if 'Item' not in response:
                    logger.warning(f"Document {object_key} not found in tracking table")
                    continue

                item = response['Item']
                doc_status = item.get('Status', '').upper()
                eval_status = item.get('EvaluationStatus', '').upper()

                # Check if document reached terminal state
                if doc_status in terminal_statuses:
                    aborted_count += 1
                elif eval_status == 'COMPLETED':
                    completed_eval_count += 1
                else:
                    pending_count += 1

            except Exception as e:
                logger.warning(f"Failed to check status for {object_key}: {str(e)}")
                pending_count += 1

        logger.info(
            f"Document status check: {completed_eval_count} evaluated, "
            f"{aborted_count} aborted, {pending_count} pending"
        )

        # All documents reached terminal state
        if pending_count == 0:
            logger.info(
                f"All documents reached terminal state for test run {test_run_id} "
                f"({completed_eval_count} completed evaluation, {aborted_count} aborted)"
            )
            return

        # Wait before next poll
        time.sleep(poll_interval)

    # Timeout reached
    logger.warning(
        f"Timeout waiting for documents to reach terminal state for test run {test_run_id}. "
        f"Proceeding with metrics calculation anyway. "
        f"Final status: {completed_eval_count} evaluated, {aborted_count} aborted, {pending_count} pending"
    )
