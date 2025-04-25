import boto3
import json
import cfnresponse
import os
import logging

# Get logging level from environment variable with INFO as default
log_level = os.environ.get('LOG_LEVEL', 'INFO')
logger = logging.getLogger()
logger.setLevel(getattr(logging, log_level))

CLIENT = boto3.client('bedrock-agent')

"""
Attempt to start the ingestion job - catch and ignore failures
Currently only 1 job can run at a time, so when more that one datasource is created
the second one fails to start.
"""


def start_ingestion_job(knowledgeBaseId, dataSourceId):
    try:
        response = CLIENT.start_ingestion_job(knowledgeBaseId=knowledgeBaseId,
                                              dataSourceId=dataSourceId, description="Autostart by CloudFormation")
        logger.info(f"start_ingestion_job response: {response}")
    except Exception as e:
        logger.warning(
            f"WARN: start_ingestion_job failed.. Retry manually from bedrock console: {e}")
        pass


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
        logger.info("Delete no op")
    logger.info(f"Status: {status}, Reason: {reason}")
    cfnresponse.send(event, context, status, responseData,
                     physicalResourceId, reason=reason)
