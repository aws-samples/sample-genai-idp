# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Lambda function to process agent queries using Strands agents.
"""

import json
import logging
import os
import time
from datetime import datetime

import boto3
import requests
from aws_requests_auth.aws_auth import AWSRequestsAuth
from botocore.exceptions import ClientError

# Import the analytics agent and configuration utilities from idp_common
from idp_common.agents.analytics import get_analytics_config, parse_agent_response
from idp_common.agents.factory import agent_factory
from idp_common.agents.common.config import configure_logging

# Configure logging for both application and Strands framework
# This will respect both LOG_LEVEL and STRANDS_LOG_LEVEL environment variables
configure_logging()

# Get logger for this module
logger = logging.getLogger(__name__)

# Initialize AWS clients
dynamodb = boto3.resource("dynamodb")
session = boto3.Session()
credentials = session.get_credentials()

# Get environment variables
AGENT_TABLE = os.environ.get("AGENT_TABLE")
APPSYNC_API_URL = os.environ.get("APPSYNC_API_URL")


def validate_job_ownership(table, user_id, job_id):
    """
    Validate that the job belongs to the specified user.

    Args:
        table: DynamoDB table resource
        user_id: The user ID to validate against
        job_id: The job ID to validate

    Returns:
        The job record if valid

    Raises:
        ValueError: If the job doesn't exist or doesn't belong to the user
    """
    try:
        response = table.get_item(Key={"PK": f"agent#{user_id}", "SK": job_id})

        job_record = response.get("Item")
        if not job_record:
            error_msg = f"Job not found: {job_id} for user: {user_id}"
            logger.error(error_msg)
            raise ValueError(error_msg)

        logger.info(f"Job ownership validated for job: {job_id}, user: {user_id}")
        return job_record

    except ClientError as e:
        error_msg = f"Error validating job ownership: {str(e)}"
        logger.error(error_msg)
        raise ValueError(error_msg)


def process_agent_query(
    query: str, agent_ids: list, job_id: str = None, user_id: str = None
) -> dict:
    """
    Process an agent query using either a single agent or orchestrator.

    Args:
        query: The natural language query to process
        agent_ids: List of agent IDs to use
        job_id: Agent job ID for monitoring (optional)
        user_id: User ID for monitoring (optional)

    Returns:
        Dict containing the agent result
    """

    try:
        # Validate agent_ids is not empty
        if not agent_ids:
            raise ValueError("At least one agent ID is required")

        logger.info(f"Processing query with agent IDs: {agent_ids}")

        # Get analytics configuration
        config = get_analytics_config()
        logger.info("Analytics configuration loaded successfully")

        # Determine whether to use single agent or orchestrator
        if len(agent_ids) == 1:
            # Single agent - use directly
            agent_id = agent_ids[0]
            logger.info(f"Using single agent: {agent_id}")

            agent = agent_factory.create_agent(
                agent_id=agent_id,
                config=config,
                session=session,
                job_id=job_id,
                user_id=user_id,
            )
            logger.info("Single agent created successfully")
        else:
            # Multiple agents - use orchestrator
            logger.info(f"Using orchestrator with {len(agent_ids)} agents: {agent_ids}")

            agent = agent_factory.create_orchestrator_agent(
                agent_ids=agent_ids,
                config=config,
                session=session,
                job_id=job_id,
                user_id=user_id,
            )
            logger.info("Orchestrator agent created successfully")

        # Process the query using context manager for MCP agents
        logger.info(f"Processing query: {query}")
        with agent:
            response = agent(query)
        logger.info("Query processed successfully")

        # Parse the response using the new parsing function
        try:
            result = parse_agent_response(response)
            logger.info(
                f"Parsed response with type: {result.get('responseType', 'unknown')}"
            )
            return result
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse agent response: {e}")
            logger.error(f"Raw response: {response}")
            # Return a text response with the raw output
            return {
                "responseType": "text",
                "content": f"Error parsing response: {response}",
            }

    except Exception as e:
        logger.exception(f"Error processing agent query: {str(e)}")
        # Re-raise the exception so the retry logic can handle it properly
        raise


def update_job_status_in_appsync(job_id, status, user_id, result=None):
    """
    Update the job status in AppSync via GraphQL mutation.

    NOTE: This function uses AppSync GraphQL mutations instead of direct DynamoDB updates
    for a specific reason: to enable real-time subscriptions in the frontend. The original
    plan was to have the frontend subscribe to job completion events so users wouldn't
    need to wait for polling intervals to see results.

    However, implementing proper AppSync subscriptions proved more complex than anticipated.
    The current implementation returns a Boolean from the mutation rather than the full
    AnalyticsJob object, which means subscriptions receive a simple true/false notification
    rather than the complete job data. This requires the frontend to make a separate query
    to fetch the actual job details when notified.

    TODO: Implement proper AppSync subscriptions that return the full AnalyticsJob object
    so the frontend can receive complete job data in real-time without additional queries.
    This would require:
    1. Changing the mutation return type from Boolean to AnalyticsJob
    2. Updating the AppSync resolver to return the updated DynamoDB item
    3. Ensuring the subscription properly receives and handles the job data

    For now, the frontend relies on polling every 30 seconds as a fallback mechanism,
    with the subscription serving as a potential optimization that isn't fully utilized.

    Args:
        job_id: The ID of the job to update
        status: The new status of the job
        user_id: The user ID who owns the job
        result: The result data (optional)
    """
    try:
        # Prepare the simplified mutation
        mutation = """
        mutation UpdateAgentJobStatus($jobId: ID!, $status: String!, $userId: String!, $result: String) {
            updateAgentJobStatus(jobId: $jobId, status: $status, userId: $userId, result: $result)
        }
        """

        logger.info(
            f"Updating AppSync for job {job_id}, user {user_id}, status {status}"
        )

        # Prepare the variables
        variables = {"jobId": job_id, "status": status, "userId": user_id}

        # Serialize result to JSON string if it's provided
        if result:
            if isinstance(result, str):
                variables["result"] = result
            else:
                variables["result"] = json.dumps(result)

        # Set up AWS authentication
        region = session.region_name or os.environ.get("AWS_REGION", "us-east-1")
        auth = AWSRequestsAuth(
            aws_access_key=credentials.access_key,
            aws_secret_access_key=credentials.secret_key,
            aws_token=credentials.token,
            aws_host=APPSYNC_API_URL.replace("https://", "").replace("/graphql", ""),
            aws_region=region,
            aws_service="appsync",
        )

        # Prepare the request
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        payload = {"query": mutation, "variables": variables}

        logger.info(f"Publishing analytics job update to AppSync for job: {job_id}")
        logger.debug(f"Mutation payload: {json.dumps(payload)}")

        # Make the request
        response = requests.post(
            APPSYNC_API_URL, json=payload, headers=headers, auth=auth, timeout=30
        )

        # Check for successful response
        if response.status_code == 200:
            response_json = response.json()
            if "errors" not in response_json:
                logger.info(
                    f"Successfully published analytics job update for: {job_id}, user: {user_id}"
                )
                logger.debug(f"Response: {response.text}")
                return True
            else:
                logger.error(
                    f"GraphQL errors in response: {json.dumps(response_json.get('errors'))}"
                )
                logger.error(f"Full mutation payload: {json.dumps(payload)}")
                return False
        else:
            logger.error(
                f"Failed to publish analytics job update. Status: {response.status_code}, Response: {response.text}"
            )
            return False

    except Exception as e:
        logger.error(f"Error updating job status in AppSync: {str(e)}")
        import traceback

        logger.error(f"Error traceback: {traceback.format_exc()}")
        return False


def handler(event, context):
    """
    Process agent queries.

    Args:
        event: The event dict with userId and jobId
        context: The Lambda context

    Returns:
        The updated job record
    """
    logger.info(f"Received event: {json.dumps(event)}")

    try:
        # Extract user ID and job ID from the event
        user_id = event.get("userId")
        job_id = event.get("jobId")

        if not user_id or not job_id:
            error_msg = "userId and jobId are required"
            logger.error(error_msg)
            return {"statusCode": 400, "body": error_msg}

        # Get the DynamoDB table
        table = dynamodb.Table(AGENT_TABLE)

        # Validate job ownership
        try:
            job_record = validate_job_ownership(table, user_id, job_id)
        except ValueError as e:
            return {"statusCode": 403, "body": str(e)}

        # Update the job status to PROCESSING
        update_job_status_in_appsync(job_id, "PROCESSING", user_id)
        logger.info(f"Updated job status to PROCESSING: {job_id}")

        # Process the agent query using the agent with retry logic
        # This retries the entire workflow -- if something dies, it restarts
        # from scratch with the initial query.
        max_retries = 3
        retry_delay = 10  # seconds
        result = None
        processing_error = None

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Processing agent query (attempt {attempt + 1}/{max_retries}): {job_id}"
                )

                # Parse agentIds from JSON string
                agent_ids_str = job_record.get("agentIds", "[]")
                try:
                    agent_ids = (
                        json.loads(agent_ids_str)
                        if isinstance(agent_ids_str, str)
                        else agent_ids_str
                    )
                except json.JSONDecodeError:
                    logger.warning(
                        f"Invalid JSON in agentIds for job {job_id}, using empty list"
                    )
                    agent_ids = []

                # Validate that agentIds are provided
                if not agent_ids:
                    raise ValueError(
                        "No agentIds provided - at least one agent ID is required"
                    )

                # Process the query using the agent
                result = process_agent_query(
                    job_record.get("query"), agent_ids, job_id, user_id
                )
                logger.info(
                    f"Successfully processed agent query on attempt {attempt + 1}: {job_id}"
                )
                break  # Success, exit retry loop

            except Exception as e:
                logger.warning(
                    f"Agent query processing failed on attempt {attempt + 1}/{max_retries} for job {job_id}: {str(e)}"
                )
                processing_error = e

                if attempt < max_retries - 1:  # Not the last attempt
                    logger.info(
                        f"Waiting {retry_delay} seconds before retry {attempt + 2}/{max_retries} for job {job_id}"
                    )
                    time.sleep(
                        retry_delay
                    )  # semgrep-ignore: arbitrary-sleep - Intentional delay. Duration is hardcoded and not user-controlled.
                else:
                    # Last attempt failed
                    logger.error(
                        f"All {max_retries} attempts failed for agent query processing, job {job_id}: {str(e)}"
                    )

        # Check if processing was successful
        if result is not None:
            # Success path - process the result
            try:
                # Prepare the result with metadata
                analytics_result = {
                    "responseType": result.get("responseType", "text"),
                    "metadata": {
                        "generatedAt": datetime.utcnow().strftime(
                            "%Y-%m-%dT%H:%M:%S.%fZ"
                        ),
                        "query": job_record.get("query"),
                    },
                }

                # Add the appropriate data field based on response type
                if result.get("responseType") == "plotData":
                    analytics_result["plotData"] = [
                        result
                    ]  # Wrap in array for consistency
                elif result.get("responseType") == "table":
                    analytics_result["tableData"] = result
                else:  # text or fallback
                    analytics_result["content"] = result.get(
                        "content", "No content available"
                    )

                # Serialize the analytics_result to a JSON string
                analytics_result_json = json.dumps(analytics_result)

                # Update the job status to COMPLETED with result via AppSync
                # This will handle DynamoDB update, completedAt timestamp, and subscription notification
                success = update_job_status_in_appsync(
                    job_id=job_id,
                    status="COMPLETED",
                    user_id=user_id,
                    result=analytics_result_json,
                )

                if success:
                    logger.info(
                        f"Successfully updated job status to COMPLETED with result: {job_id}"
                    )
                else:
                    logger.error(
                        f"Failed to update job status via AppSync for job: {job_id}"
                    )

                # Return the updated job record (without exposing userId)
                return {
                    "jobId": job_id,
                    "status": "COMPLETED",
                    "query": job_record.get("query"),
                    "createdAt": job_record.get("createdAt"),
                    "result": analytics_result,
                }

            except Exception as e:
                # Handle result processing error (this is different from query processing error)
                error_msg = f"Error processing analytics result: {str(e)}"
                logger.error(error_msg)
                processing_error = e

        # Failure path - all retries failed or result processing failed
        if processing_error:
            error_msg = f"Agent query processing failed: {str(processing_error)}"
            logger.error(error_msg)

            # Update the job status to FAILED via AppSync
            # This will handle DynamoDB update, completedAt timestamp, and subscription notification
            success = update_job_status_in_appsync(
                job_id=job_id, status="FAILED", user_id=user_id
            )

            if success:
                logger.info(f"Successfully updated job status to FAILED: {job_id}")
            else:
                logger.error(
                    f"Failed to update job status via AppSync for job: {job_id}"
                )

            return {"statusCode": 500, "body": error_msg}

    except ClientError as e:
        logger.error(f"DynamoDB error: {str(e)}")
        return {"statusCode": 500, "body": f"Database error: {str(e)}"}
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        return {"statusCode": 500, "body": f"Error processing request: {str(e)}"}
