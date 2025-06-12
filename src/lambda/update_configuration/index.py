# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import os
import logging
import boto3
from botocore.exceptions import ClientError
from typing import Dict, Any, Union
import cfnresponse
import yaml

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logging.getLogger('idp_common.bedrock.client').setLevel(os.environ.get("BEDROCK_LOG_LEVEL", "INFO"))
# Get LOG_LEVEL from environment variable with INFO as default

dynamodb = boto3.resource('dynamodb')
s3_client = boto3.client('s3')
table = dynamodb.Table(os.environ['CONFIGURATION_TABLE_NAME'])

def fetch_content_from_s3(s3_uri: str) -> Union[Dict[str, Any], str]:
    """
    Fetches content from S3 URI and parses as JSON or YAML if possible
    """
    try:
        # Parse S3 URI
        if not s3_uri.startswith('s3://'):
            raise ValueError(f"Invalid S3 URI: {s3_uri}")
        
        # Remove s3:// prefix and split bucket and key
        s3_path = s3_uri[5:]
        bucket, key = s3_path.split('/', 1)
        
        logger.info(f"Fetching content from S3: bucket={bucket}, key={key}")
        
        # Fetch object from S3
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read().decode('utf-8')
        
        # Try to parse as JSON first, then YAML, return as string if both fail
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            try:
                return yaml.safe_load(content)
            except yaml.YAMLError:
                logger.warning(f"Content from {s3_uri} is not valid JSON or YAML, returning as string")
                return content
            
    except ClientError as e:
        logger.error(f"Error fetching content from S3 {s3_uri}: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error processing S3 URI {s3_uri}: {str(e)}")
        raise

def resolve_content(content: Union[str, Dict[str, Any]]) -> Union[Dict[str, Any], str]:
    """
    Resolves content - if it's a string starting with s3://, fetch from S3
    Otherwise return as-is
    """
    if isinstance(content, str) and content.startswith('s3://'):
        return fetch_content_from_s3(content)
    return content

def update_configuration(configuration_type: str, data: Dict[str, Any]) -> None:
    """
    Updates or creates a configuration item in DynamoDB
    """
    try:
        table.put_item(
            Item={
                'Configuration': configuration_type,
                **data
            }
        )
    except ClientError as e:
        logger.error(f"Error updating configuration {configuration_type}: {str(e)}")
        raise

def delete_configuration(configuration_type: str) -> None:
    """
    Deletes a configuration item from DynamoDB
    """
    try:
        table.delete_item(
            Key={
                'Configuration': configuration_type
            }
        )
    except ClientError as e:
        logger.error(f"Error deleting configuration {configuration_type}: {str(e)}")
        raise

def generate_physical_id(stack_id: str, logical_id: str) -> str:
    """
    Generates a consistent physical ID for the custom resource
    """
    return f"{stack_id}/{logical_id}/configuration"

def handler(event: Dict[str, Any], context: Any) -> None:
    """
    Handles CloudFormation Custom Resource events for configuration management
    """
    logger.info(f"Received event: {json.dumps(event)}")
    
    try:
        request_type = event['RequestType']
        properties = event['ResourceProperties']
        stack_id = event['StackId']
        logical_id = event['LogicalResourceId']
        
        # Generate physical ID
        physical_id = generate_physical_id(stack_id, logical_id)
        
        # Remove ServiceToken from properties as it's not needed in DynamoDB
        properties.pop('ServiceToken', None)
        
        if request_type in ['Create', 'Update']:
            # Update Schema configuration
            if 'Schema' in properties:
                resolved_schema = resolve_content(properties['Schema'])
                update_configuration('Schema', {'Schema': resolved_schema})
            
            # Update Default configuration
            if 'Default' in properties:
                resolved_default = resolve_content(properties['Default'])
                
                # Apply custom model ARNs if provided
                if isinstance(resolved_default, dict):
                    # Replace classification model if CustomClassificationModelARN is provided and not empty
                    if 'CustomClassificationModelARN' in properties and properties['CustomClassificationModelARN'].strip():
                        if 'classification' in resolved_default:
                            resolved_default['classification']['model'] = properties['CustomClassificationModelARN']
                            logger.info(f"Updated classification model to: {properties['CustomClassificationModelARN']}")
                    
                    # Replace extraction model if CustomExtractionModelARN is provided and not empty
                    if 'CustomExtractionModelARN' in properties and properties['CustomExtractionModelARN'].strip():
                        if 'extraction' in resolved_default:
                            resolved_default['extraction']['model'] = properties['CustomExtractionModelARN']
                            logger.info(f"Updated extraction model to: {properties['CustomExtractionModelARN']}")
                
                update_configuration('Default', resolved_default)
            
            # Update Custom configuration if provided and not empty
            if 'Custom' in properties and properties['Custom'].get('Info') != 'Custom inference settings':
                resolved_custom = resolve_content(properties['Custom'])
                update_configuration('Custom', resolved_custom)
            
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {
                'Message': f'Successfully {request_type.lower()}d configurations'
            }, physical_id)
            
        elif request_type == 'Delete':
            # Do nothing on delete - preserve any existing configuration otherwise 
            # data is lost during custom resource replacement (cleanup step), e.g. 
            # if nested stack name or resource name is changed
            logger.info("Delete - no op...")            
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {
                'Message': 'Sucess (delete = no-op)'
            }, physical_id)
            
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        # Still need to send physical ID even on failure
        physical_id = generate_physical_id(event['StackId'], event['LogicalResourceId'])
        cfnresponse.send(event, context, cfnresponse.FAILED, {
            'Error': str(e)
        }, physical_id, reason=str(e))
