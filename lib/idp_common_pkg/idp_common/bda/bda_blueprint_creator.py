"""
Create Bedrock Document Analysis (BDA) blueprints based on extracted labels.
"""

import json
import logging

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class BDABlueprintCreator:
    def __init__(self):
        """Initialize Bedrock client."""
        self.bedrock_client = boto3.client(service_name="bedrock-data-automation")

    def update_data_automation_project(self, projectArn: str, blueprint):
        """
        Update an existing Bedrock Data Automation project with the provided blueprint.

        Args:
            projectArn (str): ARN of the project to update
            blueprint (dict): Blueprint configuration to apply

        Returns:
            dict: Updated project details or None if error
        """
        try:
            print(f"blueprint to update {blueprint}")
            project = self.bedrock_client.get_data_automation_project(
                projectArn=projectArn, projectStage="LIVE"
            )
            project = project.get("project", None)
            logger.info(f"Updating project: {project}")
            customOutputConfiguration = project.get("customOutputConfiguration", None)
            if customOutputConfiguration is None:
                customOutputConfiguration = {"blueprints": []}
                project["customOutputConfiguration"] = customOutputConfiguration

            blueprints = customOutputConfiguration.get("blueprints")
            if blueprints is None:
                blueprints = []
                customOutputConfiguration["blueprints"] = blueprints
            _blueprint = {
                "blueprintArn": blueprint.get("blueprintArn"),
            }
            if blueprint.get("blueprintStage"):
                _blueprint["blueprintStage"] = blueprint.get("blueprintStage")
            if blueprint.get("blueprintVersion"):
                _blueprint["blueprintVersion"] = blueprint.get("blueprintVersion")

            for _blueprint_tmp in blueprints:
                if _blueprint_tmp.get("blueprintArn") == blueprint.get("blueprintArn"):
                    blueprints.remove(_blueprint_tmp)
                    break
            blueprints.append(_blueprint)
            logger.info(f"Updating updated data automation project: {projectArn}")
            self.bedrock_client.update_data_automation_project(
                projectArn=projectArn,
                projectDescription=project.get("projectDescription"),
                projectStage=project.get("projectStage"),
                customOutputConfiguration=customOutputConfiguration,
                standardOutputConfiguration=project.get(
                    "standardOutputConfiguration", None
                ),
            )
            logger.info(f"Successfully updated data automation project: {projectArn}")
            return _blueprint
        except ClientError as e:
            logger.error(f"Failed to update data automation project: {e}")
            return None

    def update_project_with_custom_configurations(
        self, projectArn: str, customConfiguration
    ):
        """
        Update an existing Bedrock Data Automation project with the provided blueprint.

        Args:
            projectArn (str): ARN of the project to update
            blueprint (dict): Blueprint configuration to apply

        Returns:
            dict: Updated project details or None if error
        """
        try:
            project = self.bedrock_client.get_data_automation_project(
                projectArn=projectArn, projectStage="LIVE"
            )
            project = project.get("project", None)
            logger.info(f"Updating project: {project}")

            logger.info(f"Updating updated data automation project: {projectArn}")
            response = self.bedrock_client.update_data_automation_project(
                projectArn=projectArn,
                projectDescription=project.get("projectDescription"),
                projectStage=project.get("projectStage"),
                customOutputConfiguration=customConfiguration,
                standardOutputConfiguration=project.get(
                    "standardOutputConfiguration", None
                ),
            )
            logger.info(f"Successfully updated data automation project: {projectArn}")
            return response
        except ClientError as e:
            logger.error(f"Failed to update data automation project: {e}")
            return None

    def create_data_automation_project(self, project_name, description, blueprint_arn):
        """
        Create a Bedrock Data Automation project.

        Args:
            project_name (str): Name of the project
            description (str, optional): Project description

        Returns:
            dict: Created project details or None if error
            TODO: Fix the signature accept blueprint object instead of schema
        """
        try:
            params = {"name": project_name}

            if description:
                params["description"] = description

            response = self.bedrock_client.create_data_automation_project(
                projectName=project_name,
                projectDescription=description,
                projectStage="LIVE",
                standardOutputConfiguration={
                    "document": {
                        "extraction": {
                            "granularity": {
                                "types": [
                                    "DOCUMENT",
                                ]
                            },
                            "boundingBox": {"state": "ENABLED"},
                        },
                        "generativeField": {"state": "ENABLED"},
                        "outputFormat": {
                            "textFormat": {"types": ["PLAIN_TEXT"]},
                            "additionalFileFormat": {"state": "ENABLED"},
                        },
                    },
                    "image": {
                        "extraction": {
                            "category": {
                                "state": "ENABLED",
                                "types": ["TEXT_DETECTION"],
                            },
                            "boundingBox": {"state": "ENABLED"},
                        },
                        "generativeField": {
                            "state": "ENABLED",
                            "types": ["IMAGE_SUMMARY"],
                        },
                    },
                    "video": {
                        "extraction": {
                            "category": {
                                "state": "ENABLED",
                                "types": [
                                    "CONTENT_MODERATION",
                                    "TEXT_DETECTION",
                                ],
                            },
                            "boundingBox": {"state": "ENABLED"},
                        },
                        "generativeField": {
                            "state": "ENABLED",
                            "types": ["VIDEO_SUMMARY"],
                        },
                    },
                    "audio": {
                        "extraction": {
                            "category": {"state": "ENABLED", "types": ["TRANSCRIPT"]}
                        },
                        "generativeField": {
                            "state": "ENABLED",
                            "types": [
                                "AUDIO_SUMMARY",
                            ],
                        },
                    },
                },
                customOutputConfiguration={
                    "blueprints": [
                        {"blueprintArn": blueprint_arn, "blueprintStage": "LIVE"},
                    ]
                },
                overrideConfiguration={"document": {"splitter": {"state": "ENABLED"}}},
            )

            return response
        except ClientError as e:
            logger.error(f"Error creating Data Automation project: {e}")
            return None

    def create_blueprint(self, document_type, blueprint_name, schema=None):
        """
        Create a Bedrock Document Analysis blueprint.

        Args:
            document_type (str): Type of document
            blueprint_name (str): Name for the blueprint
            labels (list, optional): List of labels for the document

        Returns:
            dict: Created blueprint details or None if error
        """
        try:
            if schema is None:
                raise ValueError(
                    "Schema cannot be None. Please provide a valid schema."
                )
            # Print schema for debugging
            logger.info(f"Schema: {json.dumps(schema, indent=2)}")

            # Create the blueprint
            response = self.bedrock_client.create_blueprint(
                blueprintName=blueprint_name,
                type=document_type,
                blueprintStage="LIVE",
                schema=schema,
            )
            blueprint_response = response["blueprint"]
            if blueprint_response is None:
                raise ValueError(
                    "Blueprint creation failed. No blueprint response received."
                )

            logger.info(
                f"Blueprint created successfully: {blueprint_response['blueprintArn']}"
            )
            return {"status": "success", "blueprint": blueprint_response}
        except ClientError as e:
            logger.error(f"Error creating BDA blueprint: {e}")
            raise e
        except Exception as e:
            logger.error(f"Error creating blueprint: {e}")
            raise e

    def create_blueprint_version(self, blueprint_arn, project_arn):
        """
        Create a version of a Bedrock Document Analysis blueprint.

        Args:
            blueprint_name (str): Name of the blueprint
            schema (dict): Schema for the blueprint

        Returns:
            dict: Created blueprint version details or None if error
        """
        try:
            response = self.bedrock_client.create_blueprint_version(
                blueprintArn=blueprint_arn
            )
            blueprint_response = response["blueprint"]
            if blueprint_response is None:
                raise ValueError(
                    "Blueprint version creation failed. No blueprint response received."
                )

            self.update_data_automation_project(project_arn, blueprint_response)

            logger.info(
                f"Blueprint version created successfully: {blueprint_response['blueprintArn']}"
            )
            return {"status": "success", "blueprint": blueprint_response}
        except ClientError as e:
            logger.error(f"Error creating BDA blueprint version: {e}")
            raise e
        except Exception as e:
            logger.error(f"Error creating blueprint version: {e}")
            raise e

    def update_blueprint(self, blueprint_arn, stage, schema):
        """
        Update a Bedrock Document Analysis blueprint.

        Args:
            blueprint_name (str): Name of the blueprint
            schema (dict): Updated schema for the blueprint

        Returns:
            dict: Updated blueprint details or None if error
        """
        try:
            """
            version_response = self.bedrock_client.create_blueprint_version(
                blueprintArn=blueprint_arn
            )
            if "blueprint" not in version_response:
                raise ValueError("Blueprint update failed. No blueprint response received.")
            new_blueprint = version_response["blueprint"]
            version = new_blueprint.get("blueprintVersion", None)
            """
            response = self.bedrock_client.update_blueprint(
                blueprintArn=blueprint_arn, blueprintStage=stage, schema=schema
            )
            blueprint_response = response["blueprint"]
            if blueprint_response is None:
                raise ValueError(
                    "Blueprint update failed. No blueprint response received."
                )

            logger.info(
                f"Blueprint updated successfully: {blueprint_response['blueprintArn']}"
            )
            return {"status": "success", "blueprint": blueprint_response}
        except ClientError as e:
            logger.error(f"Error Updating BDA blueprint: {e}")
            raise e
        except Exception as e:
            logger.error(f"Error updating blueprint: {e}")
            raise e

    def get_blueprint(self, blueprint_arn, stage):
        """
        Update a Bedrock Document Analysis blueprint.

        Args:
            blueprint_name (str): Name of the blueprint
            schema (dict): Updated schema for the blueprint

        Returns:
            dict: Updated blueprint details or None if error
        """
        try:
            response = self.bedrock_client.get_blueprint(
                blueprintArn=blueprint_arn, blueprintStage=stage
            )
            blueprint_response = response["blueprint"]
            if blueprint_response is None:
                raise ValueError(
                    "Blueprint update failed. No blueprint response received."
                )

            logger.info(
                f"Blueprint updated successfully: {blueprint_response['blueprintArn']}"
            )
            return {"status": "success", "blueprint": blueprint_response}
        except ClientError as e:
            logger.error(f"Error Updating BDA blueprint: {e}")
            raise e
        except Exception as e:
            logger.error(f"Error updating blueprint: {e}")
            raise e

    def list_blueprints(self, projectArn, projectStage):
        try:
            project = self.bedrock_client.get_data_automation_project(
                projectArn=projectArn, projectStage="LIVE"
            )
            project = project.get("project", None)
            logger.info(f"Updating project: {project}")
            customOutputConfiguration = project.get("customOutputConfiguration", None)

            return customOutputConfiguration

        except Exception as e:
            logger.error(f"Error updating blueprint: {e}")
            raise e

    def delete_blueprint(self, blueprint_arn, blueprint_version):
        try:
            return self.bedrock_client.delete_blueprint(
                blueprintArn=blueprint_arn, blueprintVersion=blueprint_version
            )

        except Exception as e:
            logger.error(f"Error delete_blueprint: {e}")
            raise e
