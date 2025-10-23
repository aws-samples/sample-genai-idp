# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
import boto3
import cfnresponse
import json
import logging
import os
import time

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

def handler(event, context):
    """
    Lambda function handler to retrieve the SageMaker Ground Truth workforce portal URL.
    """
    logger.info(f"Received event: {json.dumps(event)}")
    
    # Initialize physical resource ID for CloudFormation
    physical_resource_id = f"WorkforceURL-{event.get('LogicalResourceId', 'unknown')}"
    response_data = {}
    
    try:
        # For Delete requests, just return success
        if event['RequestType'] == 'Delete':
            logger.info("Delete request - no action needed")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, response_data, physical_resource_id)
            return
        
        # Get the workteam name from the event
        workteam_name = event['ResourceProperties']['WorkteamName']
        # Ignore the SourceCodeHash property as it's only used to force updates
        _ = event['ResourceProperties'].get('SourceCodeHash')
        logger.info(f"Getting portal URL for workteam: {workteam_name}")
        
        # Initialize SageMaker client
        sagemaker_client = boto3.client('sagemaker')
        
        # The workteam might not be fully created yet, so we'll retry a few times
        max_retries = 5
        retry_delay = 5  # seconds
        
        for attempt in range(max_retries):
            try:
                # Get the workteam details
                response = sagemaker_client.describe_workteam(
                    WorkteamName=workteam_name
                )
                
                # Extract the portal URL
                if 'Workteam' in response and 'SubDomain' in response['Workteam']:
                    portal_url = response['Workteam']['SubDomain']
                    response_data['PortalURL'] = f"https://{portal_url}"
                    logger.info(f"Retrieved portal URL: {response_data['PortalURL']}")
                    
                    # Also include the console URL for convenience
                    response_data['ConsoleURL'] = f"https://{os.environ.get('REGION', 'us-east-1')}.console.aws.amazon.com/sagemaker/groundtruth?region={os.environ.get('REGION', 'us-east-1')}#/labeling-workforces/private"
                    
                    # Send success response
                    cfnresponse.send(event, context, cfnresponse.SUCCESS, response_data, physical_resource_id)
                    return
                else:
                    logger.warning("No SubDomain found in workteam response")
                    if attempt < max_retries - 1:
                        logger.info(f"Retrying in {retry_delay} seconds... (Attempt {attempt + 1}/{max_retries})")
                        time.sleep(retry_delay)
                    else:
                        response_data['PortalURL'] = "Not available"
                        response_data['ConsoleURL'] = f"https://{os.environ.get('REGION', 'us-east-1')}.console.aws.amazon.com/sagemaker/groundtruth?region={os.environ.get('REGION', 'us-east-1')}#/labeling-workforces/private"
                        logger.warning("Maximum retries reached, returning not available")
            except sagemaker_client.exceptions.ResourceNotFound:
                if attempt < max_retries - 1:
                    logger.info(f"Workteam not found yet. Retrying in {retry_delay} seconds... (Attempt {attempt + 1}/{max_retries})")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Workteam {workteam_name} not found after {max_retries} attempts")
                    response_data['PortalURL'] = "Workteam not found"
                    response_data['ConsoleURL'] = f"https://{os.environ.get('REGION', 'us-east-1')}.console.aws.amazon.com/sagemaker/groundtruth?region={os.environ.get('REGION', 'us-east-1')}#/labeling-workforces/private"
            except Exception as e:
                logger.error(f"Error on attempt {attempt + 1}: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    raise
        
        # If we get here, we've exhausted retries
        cfnresponse.send(event, context, cfnresponse.SUCCESS, response_data, physical_resource_id)
        
    except KeyError as e:
        error_msg = f"Missing required property: {str(e)}"
        logger.error(error_msg)
        cfnresponse.send(event, context, cfnresponse.FAILED, {'Error': error_msg}, physical_resource_id, reason=error_msg)
        
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(error_msg, exc_info=True)
        cfnresponse.send(event, context, cfnresponse.FAILED, {'Error': error_msg}, physical_resource_id, reason=error_msg)
