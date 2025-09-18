import boto3
import json
import logging
import os

# Get logging level from environment variable with INFO as default
logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

bd_client = boto3.client('bedrock-agent')

def start_ingestion_job(knowledgeBaseId, dataSourceId):
    try:
        response = bd_client.start_ingestion_job(knowledgeBaseId=knowledgeBaseId,
                                              dataSourceId=dataSourceId, description="Scheduled ingestion job")
        logger.info(f"start_ingestion_job response: {response}")
    except Exception as e:
        logger.warning(
            f"WARN: start_ingestion_job failed.. Retry manually from bedrock console: {e}")
        pass


def handler(event, context):
    logger.info(f"Event: {json.dumps(event)}")
    
    # Get environment variables
    knowledge_base_id = os.environ.get("KNOWLEDGE_BASE_ID")
    data_source_id = os.environ.get("DATA_SOURCE_ID")
    
    if not knowledge_base_id or not data_source_id:
        logger.error("Missing required environment variables: KNOWLEDGE_BASE_ID or DATA_SOURCE_ID")
        return
    
    # Start ingestion job
    start_ingestion_job(knowledge_base_id, data_source_id)

# Simple scheduled ingestion - just trigger the job, Bedrock handles the rest