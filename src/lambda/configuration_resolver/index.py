import os
import json
import boto3
from botocore.exceptions import ClientError
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Get the DynamoDB table name from the environment variable
CONFIGURATION_TABLE_NAME = os.environ['CONFIGURATION_TABLE_NAME']
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(CONFIGURATION_TABLE_NAME)

def get_configuration_item(config_type):
    """
    Retrieve a configuration item from DynamoDB
    """
    try:
        response = table.get_item(
            Key={
                'Configuration': config_type
            }
        )
        return response.get('Item')
    except ClientError as e:
        logger.error(f"Error retrieving {config_type} configuration: {str(e)}")
        raise Exception(f"Failed to retrieve {config_type} configuration")

def handler(event, context):
    """
    AWS Lambda handler for GraphQL operations related to configuration
    """
    logger.info(f"Event received: {json.dumps(event)}")
    
    # Extract the GraphQL operation type
    operation = event['info']['fieldName']
    
    if operation == 'getConfiguration':
        return handle_get_configuration()
    elif operation == 'updateConfiguration':
        args = event['arguments']
        custom_config = args.get('customConfig')
        return handle_update_configuration(custom_config)
    else:
        raise Exception(f"Unsupported operation: {operation}")

def handle_get_configuration():
    """
    Handle the getConfiguration GraphQL query
    Returns Schema, Default, and Custom configuration items
    """
    try:
        # Get the Schema configuration
        schema_item = get_configuration_item('Schema')
        schema_config = schema_item.get('Schema', {}) if schema_item else {}
        
        # Get the Default configuration
        default_item = get_configuration_item('Default')
        default_config = remove_configuration_key(default_item) if default_item else {}
        
        # Get the Custom configuration (if it exists)
        custom_item = get_configuration_item('Custom')
        custom_config = remove_configuration_key(custom_item) if custom_item else {}
        
        # Return all configurations
        result = {
            'Schema': schema_config,
            'Default': default_config,
            'Custom': custom_config if custom_config else None
        }
        
        logger.info(f"Returning configuration: {json.dumps(result)}")
        return result
        
    except Exception as e:
        logger.error(f"Error in getConfiguration: {str(e)}")
        raise e

def stringify_values(obj):
    """
    Recursively convert all values to strings
    """
    if isinstance(obj, dict):
        return {k: stringify_values(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [stringify_values(item) for item in obj]
    else:
        # Convert everything to string, except None values
        return str(obj) if obj is not None else None

def handle_update_configuration(custom_config):
    """
    Handle the updateConfiguration GraphQL mutation
    Updates the Custom configuration item in DynamoDB
    """
    if not custom_config:
        raise Exception("No custom configuration provided")
    
    try:
        # Parse the customConfig JSON string if it's a string
        if isinstance(custom_config, str):
            custom_config_obj = json.loads(custom_config)
        else:
            custom_config_obj = custom_config
        
        # Add a descriptive Info field if not present
        if 'Info' not in custom_config_obj:
            custom_config_obj['Info'] = 'Custom configuration settings'
        
        # Convert all values to strings to ensure compatibility with DynamoDB
        stringified_config = stringify_values(custom_config_obj)
        
        # Update the Custom configuration in DynamoDB
        response = table.put_item(
            Item={
                'Configuration': 'Custom',
                **stringified_config
            }
        )
        
        logger.info(f"Updated Custom configuration: {json.dumps(stringified_config)}")
        return True
        
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in customConfig: {str(e)}")
        raise Exception(f"Invalid configuration format: {str(e)}")
    except ClientError as e:
        logger.error(f"DynamoDB error in updateConfiguration: {str(e)}")
        raise Exception(f"Failed to update configuration: {str(e)}")
    except Exception as e:
        logger.error(f"Error in updateConfiguration: {str(e)}")
        raise e

def remove_configuration_key(item):
    """
    Remove the 'Configuration' key from a DynamoDB item
    """
    if not item:
        return {}
    
    result = item.copy()
    result.pop('Configuration', None)
    return result