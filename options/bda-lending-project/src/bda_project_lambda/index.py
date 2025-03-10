import json
import boto3
import cfnresponse
import logging
import os
from enum import Enum
import uuid

logger = logging.getLogger()
logger.setLevel(logging.INFO)

bedrock_client = boto3.client('bedrock-data-automation')

class State(str, Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"

def handler(event, context):
    logger.info(f"Received event: {json.dumps(event)}")
    
    request_type = event['RequestType']
    physical_id = event.get('PhysicalResourceId', None)
    
    try:
        if request_type == 'Create':
            response_data = create_project(event)
            physical_id = response_data.get('projectArn')
            cfnresponse.send(event, context, cfnresponse.SUCCESS, response_data, physical_id)
        
        elif request_type == 'Update':
            response_data = update_project(event, physical_id)
            cfnresponse.send(event, context, cfnresponse.SUCCESS, response_data, physical_id)
        
        elif request_type == 'Delete':
            delete_project(physical_id)
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physical_id)
        
        else:
            logger.error(f"Unknown request type: {request_type}")
            cfnresponse.send(event, context, cfnresponse.FAILED, {}, physical_id)
    
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        cfnresponse.send(event, context, cfnresponse.FAILED, {"Error": str(e)}, physical_id)

def get_filtered_public_blueprints(blueprint_names=None):
    """Retrieve all public blueprints (resourceOwner=SERVICE)
    
    Args:
        blueprint_names (list, optional): List of blueprint names to include. If None, all blueprints are included.
    
    Returns:
        list: List of blueprint configurations for project creation/update
    """
    all_blueprints = []
    
    try:
        # List all available public blueprints
        response = bedrock_client.list_blueprints(
            resourceOwner='SERVICE',
            maxResults=100
        )
        
        # Add each blueprint to the list
        for blueprint in response.get('blueprints', []):
            blueprint_arn = blueprint.get('blueprintArn')
            blueprint_name = blueprint.get('blueprintName')
            all_blueprints.append({
                "arn": blueprint_arn,
                "name": blueprint_name
            })
            logger.info(f"Found public blueprint: {blueprint_name} ({blueprint_arn})")
        
        logger.info(f"Retrieved {len(all_blueprints)} total public blueprints")
        
        # Log the blueprint names we're looking for
        if blueprint_names:
            logger.info(f"Looking for blueprints with names: {blueprint_names}")
        
        # Filter blueprints if names are provided
        filtered_blueprints = []
        if blueprint_names:
            # Convert blueprint names to lowercase for case-insensitive comparison
            
            for blueprint in all_blueprints:
                blueprint_name = blueprint["name"]
                # Try exact match first
                if blueprint_name in blueprint_names:
                    filtered_blueprints.append({
                        "blueprintArn": blueprint["arn"],
                        "blueprintStage": "LIVE"
                    })
                    logger.info(f"Including blueprint: {blueprint_name} ({blueprint['arn']})")
            
            logger.info(f"Filtered to {len(filtered_blueprints)} blueprints based on provided names")
            
            # If we still have no matches, log more details for debugging
            if not filtered_blueprints:
                logger.warning("No matching blueprints found. Available blueprint names:")
                for blueprint in all_blueprints:
                    logger.warning(f"  - {blueprint['name']}")
        
        return filtered_blueprints
    
    except Exception as e:
        logger.error(f"Error retrieving public blueprints: {str(e)}")
        return []


def create_or_update_custom_blueprint(project_name):
    """Create or update the custom homeowners-insurance-application blueprint"""
    blueprint_name = f'{project_name}-homeowners-insurance-application'
    blueprint_schema = """{
        "$schema": "http://json-schema.org/draft-07/schema#",
        "description": "default",
        "documentClass": "homeowners-insurance-application",
        "type": "object",
        "definitions": {
            "Applicant": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "inferenceType": "extractive",
                        "description": "The applicant name"
                    },
                    "date_of_birth": {
                        "type": "string",
                        "inferenceType": "extractive",
                        "description": "The applicant date of birth"
                    },
                    "gender": {
                        "type": "string",
                        "inferenceType": "extractive",
                        "description": "The applicant gender"
                    },
                    "marital_status": {
                        "type": "string",
                        "inferenceType": "extractive",
                        "description": "The applicant marital status"
                    },
                    "education_level": {
                        "type": "string",
                        "inferenceType": "extractive",
                        "description": "The applicant education level"
                    },
                    "existing_policy": {
                        "type": "string",
                        "inferenceType": "extractive",
                        "description": "Existing policy details if any"
                    },
                    "drivers_license": {
                        "type": "string",
                        "inferenceType": "extractive",
                        "description": "Drivers license details"
                    },
                    "dl_state": {
                        "type": "string",
                        "inferenceType": "extractive",
                        "description": "Drivers license state"
                    },
                    "current_auto_insurer": {
                        "type": "string",
                        "inferenceType": "extractive",
                        "description": "Current auto insurance details"
                    },
                    "time_with_current_insurer": {
                        "type": "string",
                        "inferenceType": "extractive",
                        "description": "Time with current auto insurer"
                    },
                    "time_with_prior_insurer": {
                        "type": "string",
                        "inferenceType": "extractive",
                        "description": "Time with prior auto insurer"
                    }
                }
            },
            "primary_applicant": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "inferenceType": "extractive",
                        "description": "The applicant name"
                    },
                    "date_of_birth": {
                        "type": "string",
                        "inferenceType": "extractive",
                        "description": "The applicant date of birth"
                    },
                    "gender": {
                        "type": "string",
                        "inferenceType": "extractive",
                        "description": "The applicant gender"
                    },
                    "marital_status": {
                        "type": "string",
                        "inferenceType": "extractive",
                        "description": "The applicant marital status"
                    },
                    "education_level": {
                        "type": "string",
                        "inferenceType": "extractive",
                        "description": "The applicant education level"
                    },
                    "existing_policy": {
                        "type": "string",
                        "inferenceType": "extractive",
                        "description": "Existing policy details if any"
                    },
                    "drivers_license": {
                        "type": "string",
                        "inferenceType": "extractive",
                        "description": "Drivers license details"
                    },
                    "dl_state": {
                        "type": "string",
                        "inferenceType": "extractive",
                        "description": "Drivers license state"
                    },
                    "current_auto_insurer": {
                        "type": "string",
                        "inferenceType": "extractive",
                        "description": "Current auto insurance details"
                    },
                    "time_with_current_insurer": {
                        "type": "string",
                        "inferenceType": "extractive",
                        "description": "Time with current auto insurer"
                    },
                    "time_with_prior_insurer": {
                        "type": "string",
                        "inferenceType": "extractive",
                        "description": "Time with prior auto insurer"
                    }
                }
            }
        },
        "properties": {
            "named_insured": {
                "type": "string",
                "inferenceType": "extractive",
                "description": "The named insured(s) and their mailing address extracted from the first section"
            },
            "insurance_company": {
                "type": "string",
                "inferenceType": "extractive",
                "description": "The insurance company name and address extracted from the second section"
            },
            "primary_email": {
                "type": "string",
                "inferenceType": "extractive",
                "description": "The primary email extracted from the third section"
            },
            "primary_phone": {
                "type": "string",
                "inferenceType": "extractive",
                "description": "The primary phone number extracted from the third section"
            },
            "alternate_phone": {
                "type": "string",
                "inferenceType": "extractive",
                "description": "The alternate phone number extracted from the third section"
            },
            "insured_property": {
                "type": "string",
                "inferenceType": "extractive",
                "description": "The insured property address extracted from the fourth section"
            },
            "primary_applicant": {
                "type": "array",
                "description": "The primary applicant information table",
                "items": {
                    "$ref": "#/definitions/primary_applicant"
                }
            }
        }
    }"""
    
    try:
        # Check if the blueprint already exists
        existing_blueprint_arn = None
        try:
            response = bedrock_client.list_blueprints(
                resourceOwner='ACCOUNT',
                maxResults=100
            )
            
            for blueprint in response.get('blueprints', []):
                if blueprint.get('blueprintName') == blueprint_name:
                    existing_blueprint_arn = blueprint.get('blueprintArn')
                    break
                    
        except Exception as e:
            logger.warning(f"Error checking for existing blueprint: {str(e)}")
        
        # Update the existing blueprint if it exists, otherwise create a new one
        if existing_blueprint_arn:
            try:
                logger.info(f"Updating existing blueprint: {existing_blueprint_arn}")
                response = bedrock_client.update_blueprint(
                    blueprintArn=existing_blueprint_arn,
                    schema=blueprint_schema,
                    blueprintStage='LIVE'
                )
                updated_blueprint_arn = existing_blueprint_arn
                logger.info(f"Updated custom blueprint with ARN: {updated_blueprint_arn}")
                
                # Return the blueprint config for project creation/update
                return {
                    "blueprintArn": updated_blueprint_arn,
                    "blueprintStage": "LIVE"
                }
            except Exception as e:
                logger.warning(f"Error updating existing blueprint: {str(e)}")
                # Fall back to creating a new blueprint if update fails
        
        # Create a new blueprint if one doesn't exist or update failed
        logger.info(f"Creating new blueprint: {blueprint_name}")
        response = bedrock_client.create_blueprint(
            blueprintName=blueprint_name,
            schema=blueprint_schema,
            type='DOCUMENT',
            blueprintStage='LIVE'
        )
        
        new_blueprint_arn = response.get('blueprint').get('blueprintArn')
        logger.info(f"Created custom blueprint with ARN: {new_blueprint_arn}")
        
        # Return the blueprint config for project creation/update
        return {
            "blueprintArn": new_blueprint_arn,
            "blueprintStage": "LIVE"
        }
        
    except Exception as e:
        logger.error(f"Error creating or updating custom blueprint: {str(e)}")
        return None

def get_project_config(project_description, all_blueprint_configs, project_name=None, project_arn=None ):
    """Get the project configuration for the given blueprints - project_name is used for create, project_arn for updates."""
    project_config = {
        "projectName": project_name,
        "projectArn": project_arn,
        "projectDescription": project_description,
        "projectStage": "LIVE",
        "standardOutputConfiguration": {
            "document": {
                "extraction": {
                    "granularity": {
                        "types": [
                            "PAGE",
                            "ELEMENT"
                        ]
                    },
                    "boundingBox": {
                        "state": "DISABLED"
                    }
                },
                "generativeField": {
                    "state": "DISABLED"
                },
                "outputFormat": {
                    "textFormat": {
                        "types": [
                            "MARKDOWN"
                        ]
                    },
                    "additionalFileFormat": {
                        "state": "DISABLED"
                    }
                }
            },
            "image": {
                "extraction": {
                    "category": {
                        "state": "ENABLED",
                        "types": [
                            "TEXT_DETECTION"
                        ]
                    },
                    "boundingBox": {
                        "state": "ENABLED"
                    }
                },
                "generativeField": {
                    "state": "ENABLED",
                    "types": [
                        "IMAGE_SUMMARY"
                    ]
                }
            },
            "video": {
                "extraction": {
                    "category": {
                        "state": "ENABLED",
                        "types": [
                            "TEXT_DETECTION"
                        ]
                    },
                    "boundingBox": {
                        "state": "ENABLED"
                    }
                },
                "generativeField": {
                    "state": "ENABLED",
                    "types": [
                        "VIDEO_SUMMARY",
                        "SCENE_SUMMARY"
                    ]
                }
            },
            "audio": {
                "extraction": {
                    "category": {
                        "state": "ENABLED",
                        "types": [
                            "TRANSCRIPT"
                        ]
                    }
                },
                "generativeField": {
                    "state": "DISABLED"
                }
            }
        },
        "customOutputConfiguration": {
            "blueprints": all_blueprint_configs
        },
        "overrideConfiguration": {
            "document": {
                "splitter": {
                    "state": "ENABLED"
                }
            }
        }
    }
    return project_config

def create_project(event):
    """Create a Bedrock Data Automation project or update if it already exists"""
    properties = event['ResourceProperties']
    project_name = properties.get('ProjectName')
    project_description = properties.get('ProjectDescription', 'Project for processing lending package documents')
    blueprint_names = properties.get('BlueprintNames')
    create_custom_blueprint = properties.get('CustomHomeApplicationBlueprint', 'false').lower() == 'true'
    
    # Check if a project with the same name already exists
    existing_project_arn = None
    try:
        logger.info(f"Checking if project with name '{project_name}' already exists")
        response = bedrock_client.list_data_automation_projects(resourceOwner='ACCOUNT', maxResults=100)
        
        for project in response.get('projects', []):
            if project.get('projectName') == project_name:
                existing_project_arn = project.get('projectArn')
                logger.info(f"Found existing project with name '{project_name}' and ARN: {existing_project_arn}")
                break

    except Exception as e:
        logger.warning(f"Error checking for existing project: {str(e)}")

    # If project exists, update it instead of creating a new one
    if existing_project_arn:
        logger.info(f"Project '{project_name}' already exists, updating instead of creating")
        return update_project(event, existing_project_arn)
    
    # Get all public blueprints
    public_blueprint_configs = get_filtered_public_blueprints(blueprint_names)
    
    # Create or update the custom homeowners-insurance-application blueprint only if specified
    custom_blueprint_config = None
    if create_custom_blueprint:
        logger.info("Creating custom homeowners insurance application blueprint")
        custom_blueprint_config = create_or_update_custom_blueprint(project_name)
    else:
        logger.info("Skipping custom blueprint creation as it was not requested")
    
    # Combine all blueprint configs
    all_blueprint_configs = public_blueprint_configs
    if custom_blueprint_config:
        all_blueprint_configs.append(custom_blueprint_config)
    
    # Create project
    project_config = get_project_config(project_description, all_blueprint_configs, project_name)
    project_config.pop('projectArn')
    logger.info(f"Creating project with {len(all_blueprint_configs)} blueprints - config: {json.dumps(project_config)}")
    response = bedrock_client.create_data_automation_project(**project_config)
    project_arn = response.get('projectArn')
    logger.info(f"Project created with ARN: {project_arn}")
    
    # Extract blueprint ARNs for response
    blueprint_arns = [config.get('blueprintArn') for config in all_blueprint_configs]
    
    return {
        'projectArn': project_arn,
        'blueprintArns': blueprint_arns
    }

def update_project(event, project_arn):
    """Update a Bedrock Data Automation project"""
    properties = event['ResourceProperties']
    project_name = properties.get('ProjectName')
    project_description = properties.get('ProjectDescription', 'GenAI IDP Sample project')
    blueprint_names = properties.get('BlueprintNames')
    create_custom_blueprint = properties.get('CustomHomeApplicationBlueprint', 'false').lower() == 'true'
    
    # Get all public blueprints
    public_blueprint_configs = get_filtered_public_blueprints(blueprint_names)
    
    # Create or update the custom homeowners-insurance-application blueprint only if specified
    custom_blueprint_config = None
    if create_custom_blueprint:
        logger.info("Creating custom homeowners insurance application blueprint")
        custom_blueprint_config = create_or_update_custom_blueprint(project_name)
    else:
        logger.info("Skipping custom blueprint creation as it was not requested")
    
    # Combine all blueprint configs
    all_blueprint_configs = public_blueprint_configs
    if custom_blueprint_config:
        all_blueprint_configs.append(custom_blueprint_config)
    
    update_config = get_project_config(project_description, all_blueprint_configs, project_arn=project_arn)
    update_config.pop('projectName')
    
    logger.info(f"Updating project with config: {json.dumps(update_config)}")
    response = bedrock_client.update_data_automation_project(**update_config)
    
    # Extract blueprint ARNs for response
    blueprint_arns = [config.get('blueprintArn') for config in all_blueprint_configs]
    
    return {
        'projectArn': project_arn,
        'blueprintArns': blueprint_arns
    }

def delete_project(project_arn):
    """Delete a Bedrock Data Automation project"""
    if not project_arn:
        logger.warning("No project ARN provided for deletion")
        return
        
    try:
        logger.info(f"Deleting project: {project_arn}")
        bedrock_client.delete_data_automation_project(projectArn=project_arn)
        logger.info(f"Project deleted: {project_arn}")
    except Exception as e:
        logger.error(f"Error deleting project: {str(e)}")
        raise e