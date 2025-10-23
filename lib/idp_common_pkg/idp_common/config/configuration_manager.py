# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import boto3
import json
import os
from typing import Dict, Any, Optional
from botocore.exceptions import ClientError
import logging

logger = logging.getLogger(__name__)

class ConfigurationManager:
    def __init__(self, table_name=None):
        """
        Initialize the configuration reader using the table name from environment variable or parameter
        
        Args:
            table_name: Optional override for configuration table name
        """
        table_name = table_name or os.environ.get('CONFIGURATION_TABLE_NAME')
        if not table_name:
            raise ValueError("Configuration table name not provided. Either set CONFIGURATION_TABLE_NAME environment variable or provide table_name parameter.")
            
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(table_name)
        logger.info(f"Initialized ConfigurationReader with table: {table_name}")


    def get_configuration(self, config_type: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a configuration item from DynamoDB
        
        Args:
            config_type: The configuration type to retrieve ('Default' or 'Custom')
            
        Returns:
            Configuration dictionary if found, None otherwise
        """
        try:
            response = self.table.get_item(
                Key={
                    'Configuration': config_type
                }
            )
            return response.get('Item')
        except ClientError as e:
            logger.error(f"Error retrieving configuration {config_type}: {str(e)}")
            raise

    """
    Recursively convert all values to strings
    """
    def _stringify_values(self, obj):
        if isinstance(obj, dict):
            return {k: self._stringify_values(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._stringify_values(item) for item in obj]
        else:
            # Convert everything to string, except None values
            return str(obj) if obj is not None else None

    def _convert_floats_to_decimal(self, obj):
        """
        Recursively convert float values to Decimal for DynamoDB compatibility
        """
        from decimal import Decimal
        if isinstance(obj, float):
            return Decimal(str(obj))
        elif isinstance(obj, dict):
            return {k: self._convert_floats_to_decimal(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._convert_floats_to_decimal(item) for item in obj]
        return obj

    def update_configuration(self, configuration_type: str, data: Dict[str, Any]) -> None:
        """
        Updates or creates a configuration item in DynamoDB
        """
        try:
            # Convert any float values to Decimal for DynamoDB compatibility
            converted_data = self._convert_floats_to_decimal(data)
            
            self.table.put_item(
                Item={
                    'Configuration': configuration_type,
                    **converted_data
                }
            )
        except ClientError as e:
            logger.error(f"Error updating configuration {configuration_type}: {str(e)}")
            raise

    def delete_configuration(self, configuration_type: str) -> None:
        """
        Deletes a configuration item from DynamoDB
        """
        try:
            self.table.delete_item(
                Key={
                    'Configuration': configuration_type
                }
            )
        except ClientError as e:
            logger.error(f"Error deleting configuration {configuration_type}: {str(e)}")
            raise


    def handle_update_custom_configuration(self, custom_config):
        """
        Handle the updateConfiguration GraphQL mutation
        Updates the Custom or Default configuration item in DynamoDB
        """
        try:
            # Handle empty configuration case
            if not custom_config:
                # For empty config, just store the Configuration key with no other attributes
                response = self.table.put_item(
                    Item={
                        'Configuration': 'Custom'
                    }
                )
                logger.info("Stored empty Custom configuration")
                return True
            
            # Parse the customConfig JSON string if it's a string
            if isinstance(custom_config, str):
                custom_config_obj = json.loads(custom_config)
            else:
                custom_config_obj = custom_config
            
            # Normal custom config update
            stringified_config = self._stringify_values(custom_config_obj)
            
            self.table.put_item(
                Item={
                    'Configuration': 'Custom',
                    **stringified_config
                }
            )
            
            logger.info("Updated Custom configuration")
            
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

    def remove_configuration_key(self, item):
        """
        Remove the 'Configuration' key from a DynamoDB item
        """
        if not item:
            return {}
        
        result = item.copy()
        result.pop('Configuration', None)
        return result

