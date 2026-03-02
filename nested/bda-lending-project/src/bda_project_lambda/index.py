# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import boto3
import cfnresponse
import logging
import os

# Get the logging level from environment variable with INFO as default
log_level = os.environ.get('LOG_LEVEL', 'INFO')
logger = logging.getLogger()
logger.setLevel(getattr(logging, log_level))

bedrock_client = boto3.client('bedrock-data-automation')


def handler(event, context):
    """CloudFormation custom resource handler for BDA project management.

    Creates an empty BDA project (no blueprints) on Create.
    No-op on Update (preserves existing project and user-configured blueprints).
    Deletes the BDA project on Delete.

    Blueprints are managed separately via the "Sync to BDA" feature in the UI,
    which pushes IDP config classes as BDA blueprints.
    """
    logger.info(f"Received event: {json.dumps(event)}")

    request_type = event['RequestType']
    physical_id = event.get('PhysicalResourceId', None)

    try:
        if request_type == 'Create':
            response_data = create_project(event)
            physical_id = response_data.get('projectArn')
            cfnresponse.send(event, context, cfnresponse.SUCCESS, response_data, physical_id)

        elif request_type == 'Update':
            # No-op: preserve existing project and any user-configured blueprints.
            # The update_configuration Lambda handles BDA project linking and sync status.
            logger.info(f"Update requested — preserving existing BDA project: {physical_id}")
            response_data = {'projectArn': physical_id}
            cfnresponse.send(event, context, cfnresponse.SUCCESS, response_data, physical_id)

        elif request_type == 'Delete':
            delete_project(physical_id)
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, physical_id)

        else:
            msg = f"Unknown request type: {request_type}"
            logger.error(msg)
            cfnresponse.send(event, context, cfnresponse.FAILED, {}, physical_id, reason=msg)

    except Exception as e:
        logger.error(f"Error: {str(e)}")
        cfnresponse.send(event, context, cfnresponse.FAILED, {"Error": str(e)}, physical_id, reason=str(e))


def create_project(event):
    """Create an empty BDA project (no blueprints).

    Blueprints will be populated later by the "Sync to BDA" feature,
    either automatically during initial deployment or manually via the UI.
    """
    properties = event['ResourceProperties']
    project_name = properties.get('ProjectName')
    project_description = properties.get('ProjectDescription', 'GenAI IDP Accelerator BDA Project')

    # Check if a project with the same name already exists
    try:
        logger.info(f"Checking if project with name '{project_name}' already exists")
        response = bedrock_client.list_data_automation_projects(resourceOwner='ACCOUNT', maxResults=100)

        for project in response.get('projects', []):
            if project.get('projectName') == project_name:
                existing_arn = project.get('projectArn')
                logger.info(f"Found existing project '{project_name}': {existing_arn} — reusing")
                return {'projectArn': existing_arn}

    except Exception as e:
        logger.warning(f"Error checking for existing project: {str(e)}")

    # Create empty project with standard output configuration (no blueprints)
    project_config = {
        "projectName": project_name,
        "projectDescription": project_description,
        "projectStage": "LIVE",
        "standardOutputConfiguration": {
            "document": {
                "extraction": {
                    "granularity": {
                        "types": ["PAGE", "ELEMENT"]
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
                        "types": ["MARKDOWN"]
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
                        "types": ["TEXT_DETECTION"]
                    },
                    "boundingBox": {
                        "state": "ENABLED"
                    }
                },
                "generativeField": {
                    "state": "ENABLED",
                    "types": ["IMAGE_SUMMARY"]
                }
            },
            "video": {
                "extraction": {
                    "category": {
                        "state": "ENABLED",
                        "types": ["TEXT_DETECTION"]
                    },
                    "boundingBox": {
                        "state": "ENABLED"
                    }
                },
                "generativeField": {
                    "state": "ENABLED",
                    "types": ["VIDEO_SUMMARY", "CHAPTER_SUMMARY"]
                }
            },
            "audio": {
                "extraction": {
                    "category": {
                        "state": "ENABLED",
                        "types": ["TRANSCRIPT"]
                    }
                },
                "generativeField": {
                    "state": "DISABLED"
                }
            }
        },
        "customOutputConfiguration": {
            "blueprints": []  # Empty — populated later by "Sync to BDA"
        },
        "overrideConfiguration": {
            "document": {
                "splitter": {
                    "state": "ENABLED"
                }
            }
        }
    }

    logger.info(f"Creating empty BDA project: {project_name}")
    response = bedrock_client.create_data_automation_project(**project_config)
    project_arn = response.get('projectArn')
    logger.info(f"Created BDA project: {project_arn}")

    return {'projectArn': project_arn}


def delete_project(project_arn):
    """No-op: Preserve the BDA project in Bedrock when the CloudFormation resource is deleted.

    During upgrades from Pattern-1 to Unified, the BDASAMPLEPROJECT nested stack is removed
    from the template. CloudFormation will trigger Delete on this custom resource, but we
    intentionally preserve the BDA project so the user can re-link it via "Sync from BDA" in the UI.
    """
    if not project_arn:
        logger.warning("No project ARN provided for deletion")
        return

    logger.info(f"Preserving BDA project (no-op delete): {project_arn}")
    logger.info("The BDA project has been retained in Bedrock. To re-link it, use 'Sync from BDA' in the IDP UI.")
