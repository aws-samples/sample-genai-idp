# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import logging
import os
import time

import boto3
import cfnresponse

log_level = os.environ.get('LOG_LEVEL', 'INFO')
logger = logging.getLogger()
logger.setLevel(getattr(logging, log_level))

CLIENT = boto3.client('bedrock-agent')

# Bedrock ingestion job statuses that are non-terminal (job is running or
# transitioning). DeleteDataSource fails with ConflictException while any
# job is in one of these states, so on stack delete we proactively stop
# them and wait for terminal status before returning.
NON_TERMINAL_STATUSES = ("STARTING", "IN_PROGRESS", "STOPPING")
TERMINAL_STATUSES = ("COMPLETE", "FAILED", "STOPPED")

# Polling configuration for the Delete path. The Lambda's overall timeout
# is set in the template (15 min); leave headroom for cfnresponse + cold
# start by capping at 12 min here.
POLL_INTERVAL_SECONDS = 10
MAX_WAIT_SECONDS = 12 * 60


def start_ingestion_job(knowledgeBaseId, dataSourceId):
    try:
        response = CLIENT.start_ingestion_job(knowledgeBaseId=knowledgeBaseId,
                                              dataSourceId=dataSourceId, description="Autostart by CloudFormation")
        logger.info(f"start_ingestion_job response: {response}")
    except Exception as e:
        logger.warning(
            f"WARN: start_ingestion_job failed.. Retry manually from bedrock console: {e}")
        pass


def _list_running_jobs(knowledgeBaseId, dataSourceId):
    jobs = []
    for status in NON_TERMINAL_STATUSES:
        paginator = CLIENT.get_paginator('list_ingestion_jobs')
        for page in paginator.paginate(
            knowledgeBaseId=knowledgeBaseId,
            dataSourceId=dataSourceId,
            filters=[{"attribute": "STATUS", "operator": "EQ", "values": [status]}],
        ):
            jobs.extend(page.get('ingestionJobSummaries', []))
    return jobs


def stop_running_ingestion_jobs(knowledgeBaseId, dataSourceId):
    """Stop all non-terminal ingestion jobs and wait for terminal status.

    Never raises — Delete must always succeed so the stack can finish
    tearing down. Failures are logged as warnings.
    """
    try:
        running = _list_running_jobs(knowledgeBaseId, dataSourceId)
    except Exception as e:
        logger.warning(f"list_ingestion_jobs failed for kb={knowledgeBaseId} ds={dataSourceId}: {e}")
        return

    if not running:
        logger.info(f"No running ingestion jobs for kb={knowledgeBaseId} ds={dataSourceId}")
        return

    job_ids = [j['ingestionJobId'] for j in running]
    logger.info(f"Stopping {len(job_ids)} running ingestion job(s): {job_ids}")
    for job_id in job_ids:
        try:
            CLIENT.stop_ingestion_job(
                knowledgeBaseId=knowledgeBaseId,
                dataSourceId=dataSourceId,
                ingestionJobId=job_id,
            )
        except CLIENT.exceptions.ResourceNotFoundException:
            logger.info(f"Job {job_id} already gone")
        except CLIENT.exceptions.ConflictException as e:
            logger.info(f"Job {job_id} already stopping/stopped: {e}")
        except Exception as e:
            logger.warning(f"stop_ingestion_job failed for {job_id}: {e}")

    deadline = time.monotonic() + MAX_WAIT_SECONDS
    pending = set(job_ids)
    while pending and time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL_SECONDS)
        for job_id in list(pending):
            try:
                resp = CLIENT.get_ingestion_job(
                    knowledgeBaseId=knowledgeBaseId,
                    dataSourceId=dataSourceId,
                    ingestionJobId=job_id,
                )
                status = resp['ingestionJob']['status']
                if status in TERMINAL_STATUSES:
                    logger.info(f"Job {job_id} reached terminal status: {status}")
                    pending.discard(job_id)
            except CLIENT.exceptions.ResourceNotFoundException:
                pending.discard(job_id)
            except Exception as e:
                logger.warning(f"get_ingestion_job failed for {job_id}: {e}")
                pending.discard(job_id)

    if pending:
        logger.warning(
            f"Timed out waiting for ingestion jobs to stop: {sorted(pending)} — "
            f"DeleteDataSource may fail with ConflictException; the stack delete "
            f"will need to be retried."
        )


def lambda_handler(event, context):
    logger.info(f"Event: {json.dumps(event)}")
    status = cfnresponse.SUCCESS
    physicalResourceId = event.get('PhysicalResourceId', None)
    responseData = {}
    reason = "Success"
    create_update_args = event['ResourceProperties']
    create_update_args.pop('ServiceToken', None)
    if event['RequestType'] == 'Create' or event['RequestType'] == 'Update':
        try:
            logger.info(f"Start datasource args: {json.dumps(create_update_args)}")
            knowledgeBaseId = event['ResourceProperties']['knowledgeBaseId']
            dataSourceId = event['ResourceProperties']['dataSourceId']
            physicalResourceId = f"{knowledgeBaseId}/{dataSourceId}"
            start_ingestion_job(knowledgeBaseId, dataSourceId)
        except Exception as e:
            status = cfnresponse.FAILED
            reason = f"Exception - {e}"
    else:  # Delete
        try:
            knowledgeBaseId = event.get('ResourceProperties', {}).get('knowledgeBaseId')
            dataSourceId = event.get('ResourceProperties', {}).get('dataSourceId')
            if not (knowledgeBaseId and dataSourceId) and physicalResourceId and '/' in physicalResourceId:
                knowledgeBaseId, dataSourceId = physicalResourceId.split('/', 1)
            if knowledgeBaseId and dataSourceId:
                stop_running_ingestion_jobs(knowledgeBaseId, dataSourceId)
            else:
                logger.info("Delete: no kb/ds ids available, nothing to stop")
        except Exception as e:
            logger.warning(f"Delete cleanup failed (continuing): {e}")
    logger.info(f"Status: {status}, Reason: {reason}")
    cfnresponse.send(event, context, status, responseData,
                     physicalResourceId, reason=reason)
