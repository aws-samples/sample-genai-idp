# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import os
import logging

from idp_common.bda.bda_blueprint_service import BdaBlueprintService


logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logging.getLogger('idp_common.bedrock.client').setLevel(os.environ.get("BEDROCK_LOG_LEVEL", "INFO"))
# Get LOG_LEVEL from environment variable with INFO as default



def handler(event, context):
    """
    Processes discovery jobs from SQS queue.

    Args:
        event (dict): SQS event containing discovery job messages
        context (object): Lambda context

    Returns:
        dict: Processing results
    """
    logger.info(f"Received event: {json.dumps(event)}")

    batch_item_failures = []
    sqs_batch_response = {}
    try:
        bda_project_arn = os.environ.get("BDA_PROJECT_ARN")
        bdaBlueprintService = BdaBlueprintService( dataAutomationProjectArn=bda_project_arn )
        bdaBlueprintService.create_blueprints_from_custom_configuration()
        
    except Exception as e:
            logger.error(f"Error processing record: {str(e)}")
            batch_item_failures.append({"itemIdentifier": record['messageId']})
    
    sqs_batch_response["batchItemFailures"] = batch_item_failures
    return sqs_batch_response



