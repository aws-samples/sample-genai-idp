# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import os
import json
import boto3
from botocore.exceptions import ClientError
import logging

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logging.getLogger("idp_common.bedrock.client").setLevel(
    os.environ.get("BEDROCK_LOG_LEVEL", "INFO")
)
# Get LOG_LEVEL from environment variable with INFO as default

# Get the DynamoDB table name from the environment variable
CONFIGURATION_TABLE_NAME = os.environ["CONFIGURATION_TABLE_NAME"]

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(CONFIGURATION_TABLE_NAME)


def get_configuration_item(config_type):
    """
    Retrieve a configuration item from DynamoDB
    """
    try:
        response = table.get_item(Key={"Configuration": config_type})
        return response.get("Item")
    except ClientError as e:
        logger.error(f"Error retrieving {config_type} configuration: {str(e)}")
        raise Exception(f"Failed to retrieve {config_type} configuration")


def handler(event, context):
    """
    AWS Lambda handler for GraphQL operations related to configuration
    """
    logger.info(f"Event received: {json.dumps(event)}")

    # Extract the GraphQL operation type
    operation = event["info"]["fieldName"]

    if operation == "getConfiguration":
        return handle_get_configuration()
    elif operation == "updateConfiguration":
        args = event["arguments"]
        custom_config = args.get("customConfig")
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
        schema_item = get_configuration_item("Schema")
        schema_config = schema_item.get("Schema", {}) if schema_item else {}

        # Get the Default configuration
        default_item = get_configuration_item("Default")
        default_config = remove_configuration_key(default_item) if default_item else {}

        # Get the Custom configuration (if it exists)
        custom_item = get_configuration_item("Custom")
        custom_config = remove_configuration_key(custom_item) if custom_item else {}

        # Return all configurations
        result = {
            "Schema": schema_config,
            "Default": default_config,
            "Custom": custom_config,
        }

        logger.info("Returning configuration")
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


def deep_merge(target, source):
    """
    Deep merge two dictionaries
    """
    result = target.copy()

    if not source:
        return result

    for key, value in source.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value

    return result


def send_configuration_update_message(configuration_key: str, configuration_data: dict):
    """
    Send a message to the ConfigurationQueue to notify pattern-specific processors
    about configuration updates.

    Args:
        configuration_key (str): The configuration key that was updated ('Custom' or 'Default')
        configuration_data (dict): The updated configuration data
    """
    try:
        configuration_queue_url = os.environ.get("CONFIGURATION_QUEUE_URL")
        if not configuration_queue_url:
            logger.warning("CONFIGURATION_QUEUE_URL environment variable not set")
            return

        sqs = boto3.client("sqs")

        # Create message payload
        import datetime

        message_body = {
            "eventType": "CONFIGURATION_UPDATED",
            "configurationKey": configuration_key,
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "data": {
                "configurationKey": configuration_key,
            },
        }

        # Send message to SQS
        response = sqs.send_message(
            QueueUrl=configuration_queue_url,
            MessageBody=json.dumps(message_body),
            MessageAttributes={
                "eventType": {
                    "StringValue": "CONFIGURATION_UPDATED",
                    "DataType": "String",
                },
                "configurationKey": {
                    "StringValue": configuration_key,
                    "DataType": "String",
                },
            },
        )

        logger.info(
            f"Configuration update message sent to queue. MessageId: {response.get('MessageId')}"
        )

    except Exception as e:
        logger.error(f"Error sending configuration update message: {str(e)}")
        raise


def handle_update_configuration(custom_config):
    """
    Handle the updateConfiguration GraphQL mutation
    Updates the Custom or Default configuration item in DynamoDB
    """
    try:
        # Handle empty configuration case
        if not custom_config:
            # For empty config, just store the Configuration key with no other attributes
            table.put_item(Item={"Configuration": "Custom"})
            logger.info("Stored empty Custom configuration")
            return True

        # Parse the customConfig JSON string if it's a string
        if isinstance(custom_config, str):
            custom_config_obj = json.loads(custom_config)
        else:
            custom_config_obj = custom_config

        # Check if this should be saved as default
        save_as_default = custom_config_obj.pop("saveAsDefault", False)

        if save_as_default:
            # Get current default configuration
            default_item = get_configuration_item("Default")
            current_default = (
                remove_configuration_key(default_item) if default_item else {}
            )

            # Merge custom changes with current default to create new complete default
            new_default_config = deep_merge(current_default, custom_config_obj)

            # Convert to strings for DynamoDB
            stringified_default = stringify_values(new_default_config)

            # Save new default configuration
            table.put_item(Item={"Configuration": "Default", **stringified_default})

            # Clear custom configuration
            table.put_item(Item={"Configuration": "Custom"})

            logger.info("Updated Default configuration and cleared Custom")

        else:
            # Normal custom config update
            stringified_config = stringify_values(custom_config_obj)

            table.put_item(Item={"Configuration": "Custom", **stringified_config})

            logger.info("Updated Custom configuration")

            # Send configuration update message for Custom configuration
            try:
                send_configuration_update_message("Custom", custom_config_obj)
            except Exception as sqs_error:
                logger.warning(
                    f"Failed to send configuration update message to queue: {sqs_error}"
                )
                # Don't fail the entire operation if queue message fails

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
    result.pop("Configuration", None)
    return result
