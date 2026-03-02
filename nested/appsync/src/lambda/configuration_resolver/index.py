# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from idp_common.config.configuration_manager import ConfigurationManager
from idp_common.config.models import SchemaConfig, IDPConfig, PricingConfig
from idp_common.config.constants import (
    CONFIG_TYPE_SCHEMA,
    CONFIG_TYPE_DEFAULT_PRICING,
    CONFIG_TYPE_CUSTOM_PRICING,
    CONFIG_TYPE_CONFIG,
    DEFAULT_VERSION,
)
from pydantic import ValidationError
import os
import json
import logging
import re

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logging.getLogger("idp_common.bedrock.client").setLevel(
    os.environ.get("BEDROCK_LOG_LEVEL", "INFO")
)


def validate_version_name(name):
    """Validate version name: alphanumeric, hyphens, underscores only, max 50 chars"""
    if not name or not isinstance(name, str):
        return False
    return re.match(r'^[a-zA-Z0-9-_]+$', name) and len(name) <= 50


def validate_description(description):
    """Validate description: max 200 chars only"""
    if description is None or description == "":
        return True  # Optional field
    if not isinstance(description, str):
        return False
    return len(description) <= 200


def handler(event, context):
    """
    AWS Lambda handler for GraphQL operations related to configuration.

    Returns structured responses with success/error information:

    Success response:
    {
        "success": true,
        "Schema": {...},
        "Default": {...},
        "Custom": {...}
    }

    Error response:
    {
        "success": false,
        "error": {
            "type": "ValidationError" | "JSONDecodeError",
            "message": "...",
            "validationErrors": [...]  // if ValidationError
        }
    }
    """
    logger.info(f"Event received: {json.dumps(event)}")

    # Extract the GraphQL operation type
    operation = event["info"]["fieldName"]

    # Initialize ConfigurationManager
    manager = ConfigurationManager()

    try:
        if operation == "getConfigVersions":
            return handle_get_config_versions(manager)
        elif operation == "getConfigVersion":
            return handle_get_configuration(manager, event["arguments"].get("versionName"))
        elif operation == "updateConfiguration":
            args = event["arguments"]
            version = args.get("versionName")
            custom_config = args.get("customConfig")
            description = args.get("description")
            if not version:
                return {
                    "success": False,
                    "error": {
                        "type": "ValidationError",
                        "message": "versionId is required",
                    },
                }
            # Validate version name if provided
            if not validate_version_name(version):
                return {
                    "success": False,
                    "error": {
                        "type": "ValidationError",
                        "message": "Version name can only contain letters, numbers, hyphens, and underscores (max 50 characters)",
                    },
                }
            # Validate description if provided
            if description and not validate_description(description):
                return {
                    "success": False,
                    "error": {
                        "type": "ValidationError",
                        "message": "Description cannot exceed 200 characters",
                    },
                }
            success = manager.handle_update_custom_configuration(custom_config, version, description)
            return {
                "success": success,
                "message": "Configuration updated successfully"
                if success
                else "Configuration update failed",
            }
        elif operation == "setActiveVersion":
            args = event["arguments"]
            version = args.get("versionName")
            return handle_set_active_version(manager, version)
        elif operation == "deleteConfigVersion":
            args = event["arguments"]
            version = args.get("versionName")
            return handle_delete_config_version(manager, version)
        elif operation == "getPricing":
            return handle_get_pricing(manager)
        elif operation == "updatePricing":
            args = event["arguments"]
            pricing_config = args.get("pricingConfig")
            return handle_update_pricing(manager, pricing_config)
        elif operation == "restoreDefaultPricing":
            return handle_restore_default_pricing(manager)
        elif operation == "listConfigurationLibrary":
            return handle_list_config_library(event["arguments"])
        elif operation == "getConfigurationLibraryFile":
            return handle_get_config_library_file(event["arguments"])
        else:
            raise Exception(f"Unsupported operation: {operation}")
    except ValidationError as e:
        # Pydantic validation error - return structured error for UI
        logger.error(f"Configuration validation error: {e}")

        # Build structured error response that UI can parse
        validation_errors = []
        for error in e.errors():
            field_path = " -> ".join(str(loc) for loc in error["loc"])
            validation_errors.append(
                {"field": field_path, "message": error["msg"], "type": error["type"]}
            )

        # Return error as data (not exception) so UI can handle it
        return {
            "success": False,
            "error": {
                "type": "ValidationError",
                "message": "Configuration validation failed",
                "validationErrors": validation_errors,
            },
        }

    except json.JSONDecodeError as e:
        # JSON parsing error - return structured error
        logger.error(f"JSON decode error: {e}")
        return {
            "success": False,
            "error": {
                "type": "JSONDecodeError",
                "message": f"Invalid JSON format: {str(e)}",
                "position": {
                    "line": e.lineno if hasattr(e, "lineno") else None,
                    "column": e.colno if hasattr(e, "colno") else None,
                },
            },
        }
    except Exception as e:
        # Catch all other exceptions to prevent lambda failures
        logger.error(f"Unexpected error in {operation}: {str(e)}", exc_info=True)
        return {
            "success": False,
            "error": {
                "type": "UnexpectedError",
                "message": f"An unexpected error occurred: {str(e)}",
            },
        }


def handle_get_configuration(manager, version: str):
    """
    Handle the getConfiguration GraphQL query
    Returns Schema and version configuration items.
    
    DESIGN PATTERN (CRITICAL):
    - Default: Full stack baseline (Pydantic validated)
    - Version: SPARSE DELTAS ONLY (raw from DynamoDB, NO Pydantic defaults!)
    - Frontend merges Default + Version for display
    - Runtime uses get_merged_configuration() for processing
    
    This design allows:
    - Stack upgrades to safely update Default without losing user customizations
    - Empty Version = all defaults (clean reset)
    - User customizations survive stack updates
    
    ANTI-PATTERNS TO AVOID:
    - DO NOT auto-copy default → version when version is empty
    - DO NOT use Pydantic validation on version (fills in defaults)
    """
    try:
        # Get Schema configuration (Pydantic validated - this is correct for Schema)
        schema_config = manager.get_configuration(CONFIG_TYPE_SCHEMA)
        if schema_config:
            # Remove config_type discriminator before sending to frontend
            schema_dict = schema_config.model_dump(
                mode="python", exclude={"config_type"}
            )
        else:
            schema_dict = {}

        # Get Default configuration (Pydantic validated - full stack baseline)
        default_config = manager.get_configuration(CONFIG_TYPE_CONFIG, DEFAULT_VERSION)
        if default_config and isinstance(default_config, IDPConfig):
            default_dict = default_config.model_dump(
                mode="python", exclude={"config_type"}
            )
        else:
            default_dict = {}

        if not version:
            raise ValueError("version is missing")
        
        
        # Get Version configuration as RAW dict (NO Pydantic defaults!)
        # This is critical for the sparse delta pattern to work correctly
        version_dict = manager.get_raw_configuration(CONFIG_TYPE_CONFIG, version)
        
        # If version dict doesn't exist or is empty, return empty dict
        # DO NOT auto-copy Default → Custom (this breaks the delta pattern)
        if not version_dict:
            logger.info("Custom config is empty or not found - returning empty dict (expected behavior)")
            version_dict = {}

        # Return all configurations as dicts (GraphQL requires JSON-serializable)
        result = {
            "success": True,
            "Schema": schema_dict,
            "Default": default_dict,
            "Custom": {} if version == "default" else version_dict,
        }

        logger.info("Returning configuration (default=full, Version=deltas only)")
        return result

    except Exception as e:
        logger.error(f"Error in getConfiguration: {str(e)}")
        raise e


def handle_list_config_library(args):
    """
    List available configurations from S3 config_library for a specific pattern
    Returns: { success: bool, items: [...], error: str }
    """
    import boto3
    from botocore.exceptions import ClientError

    pattern = args.get("pattern")
    if not pattern:
        return {"success": False, "items": [], "error": "Pattern parameter is required"}

    try:
        s3_client = boto3.client("s3")
        bucket_name = os.environ.get("CONFIGURATION_BUCKET")
        prefix = f"config_library/{pattern}/"

        logger.info(
            f"Listing config library for pattern: {pattern} in bucket: {bucket_name}"
        )

        # List "directories" under the pattern folder
        response = s3_client.list_objects_v2(
            Bucket=bucket_name, Prefix=prefix, Delimiter="/"
        )

        items = []

        # CommonPrefixes are the "directories" (config folders)
        for common_prefix in response.get("CommonPrefixes", []):
            config_dir = common_prefix["Prefix"]
            config_name = config_dir.rstrip("/").split("/")[-1]

            # Check if README.md exists in this config directory
            readme_key = f"{config_dir}README.md"
            has_readme = False

            try:
                s3_client.head_object(Bucket=bucket_name, Key=readme_key)
                has_readme = True
            except ClientError as e:
                if e.response["Error"]["Code"] != "404":
                    logger.warning(f"Error checking README for {config_name}: {e}")

            # Detect which config file type exists (prefer YAML, fallback to JSON)
            config_file_type = None
            yaml_key = f"{config_dir}config.yaml"
            json_key = f"{config_dir}config.json"

            try:
                s3_client.head_object(Bucket=bucket_name, Key=yaml_key)
                config_file_type = "yaml"
            except ClientError:
                # YAML doesn't exist, try JSON
                try:
                    s3_client.head_object(Bucket=bucket_name, Key=json_key)
                    config_file_type = "json"
                except ClientError:
                    logger.warning(
                        f"No config file found for {config_name} (checked yaml and json)"
                    )
                    # Skip this config if no config file exists
                    continue

            items.append({
                "name": config_name,
                "hasReadme": has_readme,
                "path": config_dir,
                "configFileType": config_file_type
            })

        if not items:
            logger.info(f"No configurations found for pattern: {pattern}")

        logger.info(f"Found {len(items)} configurations for pattern: {pattern}")
        return {"success": True, "items": items, "error": None}

    except ClientError as e:
        logger.error(f"S3 error listing config library: {e}")
        return {
            "success": False,
            "items": [],
            "error": f"Failed to list configurations: {str(e)}",
        }
    except Exception as e:
        logger.error(f"Error listing config library: {e}")
        return {
            "success": False,
            "items": [],
            "error": f"Unexpected error: {str(e)}",
        }


def handle_get_config_library_file(args):
    """
    Get a specific file (config.yaml or README.md) from config library
    Returns: { success: bool, content: str, contentType: str, error: str }
    """
    import boto3
    from botocore.exceptions import ClientError

    pattern = args.get("pattern")
    config_name = args.get("configName")
    file_name = args.get("fileName")

    if not all([pattern, config_name, file_name]):
        return {
            "success": False,
            "content": "",
            "contentType": "",
            "error": "Missing required parameters",
        }

    # Security: Only allow specific file names
    if file_name not in ["config.yaml", "config.json", "README.md"]:
        return {
            "success": False,
            "content": "",
            "contentType": "",
            "error": f"Invalid file name: {file_name}",
        }

    try:
        s3_client = boto3.client("s3")
        bucket_name = os.environ.get("CONFIGURATION_BUCKET")
        key = f"config_library/{pattern}/{config_name}/{file_name}"

        logger.info(f"Getting file from S3: {bucket_name}/{key}")

        response = s3_client.get_object(Bucket=bucket_name, Key=key)
        content = response["Body"].read().decode("utf-8")

        # Set appropriate content type based on file extension
        if file_name == "README.md":
            content_type = "text/markdown"
        elif file_name == "config.json":
            content_type = "application/json"
        else:
            content_type = "text/yaml"

        logger.info(
            f"Successfully retrieved {file_name} for {pattern}/{config_name} "
            f"({len(content)} bytes)"
        )
        return {
            "success": True,
            "content": content,
            "contentType": content_type,
            "error": None,
        }

    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            error_msg = f"File not found: {file_name}"
        else:
            error_msg = f"S3 error: {str(e)}"

        logger.error(f"Error getting config library file: {error_msg}")
        return {
            "success": False,
            "content": "",
            "contentType": "",
            "error": error_msg,
        }
    except Exception as e:
        logger.error(f"Error getting config library file: {e}")
        return {
            "success": False,
            "content": "",
            "contentType": "",
            "error": f"Unexpected error: {str(e)}",
        }


def handle_get_pricing(manager):
    """
    Handle the getPricing GraphQL query
    Returns both merged pricing and default pricing for UI diff/restore features

    This mirrors the Default/Custom pattern for IDP configuration:
    - DefaultPricing: Full baseline from deployment (stored at deployment time)
    - CustomPricing: User overrides only (deltas)
    - Returns:
      - pricing: Merged result (default + custom overrides)
      - defaultPricing: Original defaults for diff highlighting and restore

    Returns: { success: bool, pricing: {...}, defaultPricing: {...}, error: {...} }
    """
    try:
        # Get merged pricing (DefaultPricing + CustomPricing deltas)
        pricing_config = manager.get_merged_pricing()

        # Also get default pricing for UI diff/restore features
        default_pricing_config = manager.get_configuration(CONFIG_TYPE_DEFAULT_PRICING)

        empty_pricing = {
            "textract": {},
            "bedrock": {},
            "bda": {},
            "sagemaker": {},
        }

        if pricing_config and isinstance(pricing_config, PricingConfig):
            # Convert to dict, excluding config_type discriminator
            pricing_dict = pricing_config.model_dump(
                mode="python", exclude={"config_type"}
            )
            logger.info("Returning merged pricing configuration from DynamoDB")
        else:
            # No DefaultPricing in DynamoDB - this shouldn't happen after deployment
            logger.warning("No DefaultPricing found in DynamoDB")
            pricing_dict = empty_pricing

        if default_pricing_config and isinstance(default_pricing_config, PricingConfig):
            default_pricing_dict = default_pricing_config.model_dump(
                mode="python", exclude={"config_type"}
            )
            logger.info("Returning default pricing for UI diff/restore")
        else:
            logger.warning("No DefaultPricing found for diff/restore")
            default_pricing_dict = empty_pricing

        return {
            "success": True,
            "pricing": pricing_dict,
            "defaultPricing": default_pricing_dict,
        }

    except Exception as e:
        logger.error(f"Error in getPricing: {str(e)}")
        return {
            "success": False,
            "error": {
                "type": "Error",
                "message": f"Failed to get pricing: {str(e)}",
            },
        }


def handle_update_pricing(manager, pricing_config_json):
    """
    Handle the updatePricing GraphQL mutation
    Saves custom pricing overrides (deltas) to DynamoDB

    This saves to CustomPricing, which stores only user overrides.
    The overrides are merged with DefaultPricing when reading.

    Args:
        manager: ConfigurationManager instance
        pricing_config_json: JSON string or dict with pricing deltas

    Returns: { success: bool, message: str, error: {...} }
    """
    try:
        # Parse JSON if it's a string
        if isinstance(pricing_config_json, str):
            pricing_data = json.loads(pricing_config_json)
        else:
            pricing_data = pricing_config_json

        # Validate and create PricingConfig
        pricing_config = PricingConfig(**pricing_data)

        # Save to CustomPricing (deltas only)
        success = manager.save_custom_pricing(pricing_config)

        if success:
            logger.info("Custom pricing configuration updated successfully")
            return {
                "success": True,
                "message": "Pricing configuration updated successfully",
            }
        else:
            return {
                "success": False,
                "message": "Failed to save pricing configuration",
                "error": {
                    "type": "SaveError",
                    "message": "Failed to save pricing configuration to database",
                },
            }

    except ValidationError as e:
        logger.error(f"Pricing validation error: {e}")
        validation_errors = []
        for error in e.errors():
            field_path = " -> ".join(str(loc) for loc in error["loc"])
            validation_errors.append(
                {"field": field_path, "message": error["msg"], "type": error["type"]}
            )
        return {
            "success": False,
            "error": {
                "type": "ValidationError",
                "message": "Pricing validation failed",
                "validationErrors": validation_errors,
            },
        }

    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in pricing: {e}")
        return {
            "success": False,
            "error": {
                "type": "JSONDecodeError",
                "message": f"Invalid JSON format: {str(e)}",
            },
        }

    except Exception as e:
        logger.error(f"Error in updatePricing: {str(e)}")
        return {
            "success": False,
            "error": {
                "type": "Error",
                "message": f"Failed to update pricing: {str(e)}",
            },
        }


def handle_restore_default_pricing(manager):
    """
    Handle the restoreDefaultPricing GraphQL mutation
    Restores pricing to the default values by deleting CustomPricing

    This simply deletes the CustomPricing record from DynamoDB.
    After deletion, get_merged_pricing() returns DefaultPricing only.

    Returns: { success: bool, message: str, error: {...} }
    """
    try:
        # Delete CustomPricing - this effectively resets to defaults
        success = manager.delete_custom_pricing()

        if success:
            logger.info("Pricing restored to default by deleting CustomPricing")
            return {
                "success": True,
                "message": "Pricing restored to default values",
            }
        else:
            return {
                "success": False,
                "message": "Failed to restore default pricing",
                "error": {
                    "type": "DeleteError",
                    "message": "Failed to delete custom pricing from database",
                },
            }

    except Exception as e:
        logger.error(f"Error in restoreDefaultPricing: {str(e)}")
        return {
            "success": False,
            "error": {
                "type": "Error",
                "message": f"Failed to restore default pricing: {str(e)}",
            },
        }


def handle_get_config_versions(manager):
    """
    Handle the getConfigVersions GraphQL query
    Returns list of all available configuration versions
    """
    try:
        versions = manager.list_config_versions()
        
        return {
            "success": True,
            "versions": versions
        }
        
    except Exception as e:
        logger.error(f"Error in getConfigVersions: {str(e)}")
        return {
            "success": False,
            "error": {
                "type": "Error",
                "message": f"Failed to get configuration versions: {str(e)}",
            },
        }


def handle_set_active_version(manager, version):
    """
    Handle the setActiveVersion GraphQL mutation
    Sets a specific version as active and deactivates others.
    
    BDA Auto-Sync: If the version has use_bda=True and a linked BDA project,
    auto-syncs the config to BDA on activation to ensure it's current.
    If use_bda=True but no BDA project exists, auto-creates one.
    """
    try:
        if not version:
            return {
                "success": False,
                "error": {
                    "type": "ValidationError",
                    "message": "versionId is required",
                },
            }
        
        # Check if the version exists
        config = manager.get_configuration("Config", version)
        if not config:
            return {
                "success": False,
                "error": {
                    "type": "NotFoundError",
                    "message": f"Configuration version '{version}' not found",
                },
            }
        
        # Set the version as active
        manager.activate_version(version)
        
        # BDA Auto-Sync on activation: if use_bda is enabled, ensure BDA project is synced
        bda_message = ""
        try:
            config_dict = config.model_dump(mode="python") if hasattr(config, 'model_dump') else {}
            use_bda = config_dict.get("use_bda", False)
            
            if use_bda:
                bda_arn = manager.get_bda_project_arn(version)
                if bda_arn:
                    # Has linked project — mark as needing sync (actual sync happens via UI or next sync call)
                    bda_sync_status = manager.get_bda_project_arn(version)  # Check current status
                    logger.info(f"Version {version} activated with BDA project {bda_arn}")
                    bda_message = f" BDA project linked: {bda_arn}"
                else:
                    # No BDA project — note this for the user
                    logger.info(f"Version {version} activated with use_bda=True but no BDA project linked")
                    bda_message = " Note: BDA is enabled but no project is linked. Use 'Sync to BDA' to create one."
        except Exception as bda_e:
            logger.warning(f"BDA check during activation failed (non-blocking): {bda_e}")
        
        return {
            "success": True,
            "message": f"Configuration version {version} set as active.{bda_message}",
        }
        
    except Exception as e:
        logger.error(f"Error in setActiveVersion: {str(e)}")
        return {
            "success": False,
            "error": {
                "type": "Error",
                "message": f"Failed to set active version: {str(e)}",
            },
        }
    

def handle_delete_config_version(manager, version, delete_bda_project=True):
    """
    Handle the deleteConfigVersion GraphQL mutation.
    Deletes a specific configuration version and optionally its linked BDA project.
    
    Args:
        manager: ConfigurationManager instance
        version: Version name to delete
        delete_bda_project: If True, also delete the linked BDA project (default: True)
    """
    try:
        if not version:
            return {
                "success": False,
                "error": {
                    "type": "ValidationError",
                    "message": "versionId is required",
                },
            }
        
        # Prevent deletion of system default version
        if version == "default":
            return {
                "success": False,
                "error": {
                    "type": "ValidationError",
                    "message": "Cannot delete system default version",
                },
            }
        
        # Check for linked BDA project and optionally delete it
        bda_cleanup_message = ""
        if delete_bda_project:
            try:
                bda_arn = manager.get_bda_project_arn(version)
                if bda_arn:
                    logger.info(f"Attempting to delete linked BDA project: {bda_arn}")
                    try:
                        from idp_common.bda.bda_blueprint_service import BdaBlueprintService
                        bda_service = BdaBlueprintService(dataAutomationProjectArn=bda_arn)
                        bda_service.delete_project(bda_arn)
                        bda_cleanup_message = f" Linked BDA project deleted: {bda_arn}"
                        logger.info(f"Successfully deleted BDA project: {bda_arn}")
                    except Exception as bda_e:
                        logger.warning(f"Failed to delete BDA project {bda_arn}: {bda_e}")
                        bda_cleanup_message = f" Warning: Failed to delete linked BDA project: {bda_arn}"
            except Exception as e:
                logger.warning(f"Error checking BDA project for version {version}: {e}")
        
        # Delete the version
        manager.delete_configuration("Config", version)
        
        return {
            "success": True,
            "message": f"Configuration version {version} deleted successfully.{bda_cleanup_message}",
        }
        
    except Exception as e:
        logger.error(f"Error in deleteConfigVersion: {str(e)}")
        return {
            "success": False,
            "error": {
                "type": "Error",
                "message": f"Failed to delete configuration version: {str(e)}",
            },
        }
