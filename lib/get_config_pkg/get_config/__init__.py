import boto3
import os
from typing import Dict, Any, Optional
from botocore.exceptions import ClientError
import logging
from copy import deepcopy

logger = logging.getLogger()
logger.setLevel(logging.INFO)

class ConfigurationReader:
    def __init__(self):
        """
        Initialize the configuration reader using the table name from environment variable
        """
        table_name = os.environ['CONFIGURATION_TABLE_NAME']
        self.dynamodb = boto3.resource('dynamodb')
        self.table = self.dynamodb.Table(table_name)

    def get_configuration(self, config_type: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a configuration item from DynamoDB
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

    def deep_merge(self, default: Dict[str, Any], custom: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively merge two dictionaries, with custom values taking precedence
        """
        result = deepcopy(default)  # Create a deep copy to avoid modifying the original

        for key, value in custom.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                # Recursively merge nested dictionaries
                result[key] = self.deep_merge(result[key], value)
            else:
                # Override or add the custom value
                result[key] = deepcopy(value)

        return result

    def get_merged_configuration(self) -> Dict[str, Any]:
        """
        Get and merge Default and Custom configurations
        """
        try:
            # Get Default configuration
            default_config = self.get_configuration('Default')
            if not default_config:
                raise ValueError("Default configuration not found")

            # Get Custom configuration
            custom_config = self.get_configuration('Custom')
            
            # If no custom config exists, return default
            if not custom_config:
                logger.info("No Custom configuration found, using Default only")
                return default_config

            # Remove the 'Configuration' key as it's not part of the actual config
            default_config.pop('Configuration', None)
            custom_config.pop('Configuration', None)

            # Merge configurations
            merged_config = self.deep_merge(default_config, custom_config)
            
            logger.info("Successfully merged configurations")
            return merged_config

        except Exception as e:
            logger.error(f"Error getting merged configuration: {str(e)}")
            raise

# Helper function to get the merged configuration
def get_config() -> Dict[str, Any]:
    """
    Get the merged configuration using the environment variable for table name
    """
    reader = ConfigurationReader()
    return reader.get_merged_configuration()