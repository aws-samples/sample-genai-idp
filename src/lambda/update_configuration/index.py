import json
import os
import logging
import boto3
from botocore.exceptions import ClientError
from typing import Dict, Any
import cfnresponse

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
# Get LOG_LEVEL from environment variable with INFO as default

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['CONFIGURATION_TABLE_NAME'])

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
                update_configuration('Schema', {'Schema': properties['Schema']})
            
            # Update Default configuration
            if 'Default' in properties:
                update_configuration('Default', properties['Default'])
            
            # Update Custom configuration if provided and not empty
            if 'Custom' in properties and properties['Custom'].get('Info') != 'Custom inference settings':
                update_configuration('Custom', properties['Custom'])
            
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
        }, physical_id)