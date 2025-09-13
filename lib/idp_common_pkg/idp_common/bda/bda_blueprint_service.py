# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
import json
import logging
import os
import uuid
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from idp_common.bda.bda_blueprint_creator import BDABlueprintCreator
from idp_common.bda.schema_converter import SchemaConverter

logger = logging.getLogger(__name__)


class BdaBlueprintService:
    def __init__(self, dataAutomationProjectArn: Optional[str] = None):
        self.dataAutomationProjectArn = dataAutomationProjectArn
        self.blueprint_creator = BDABlueprintCreator()
        self.configuration_table_name = os.environ.get("CONFIGURATION_TABLE_NAME", "")
        dynamodb = boto3.resource("dynamodb")
        self.configuration_table = dynamodb.Table(self.configuration_table_name)
        self.blueprint_name_prefix = os.environ.get("STACK_NAME", "")

        return

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

    def _get_configuration_item(self, config_type):
        """
        Retrieve a configuration item from DynamoDB
        """
        try:
            response = self.configuration_table.get_item(
                Key={"Configuration": config_type}
            )
            return response.get("Item")
        except ClientError as e:
            logger.error(f"Error retrieving {config_type} configuration: {str(e)}")
            raise Exception(f"Failed to retrieve {config_type} configuration")

    def _handle_update_configuration(self, custom_config):
        """
        Handle the updateConfiguration GraphQL mutation
        Updates the Custom or Default configuration item in DynamoDB
        """
        try:
            # Handle empty configuration case
            stringified_config = self._stringify_values(custom_config)

            self.configuration_table.put_item(
                Item={"Configuration": "Custom", "classes": stringified_config}
            )

            logger.info("Updated Custom configuration")

            return True

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in customConfig: {str(e)}")
            raise Exception(f"Invalid configuration format: {str(e)}")
        except Exception as e:
            logger.error(f"Error in updateConfiguration: {str(e)}")
            raise e

    def _format_section_name(self, section_name: str) -> str:
        """Format section name to PascalCase for definitions."""
        words = section_name.replace(" ", "-").split()
        return "".join(word.capitalize() for word in words)

    def _format_field_name(self, field_name: str) -> str:
        """Format field name to snake_case for properties."""
        # Remove any non-alphanumeric characters except spaces
        field_name = "".join(
            c if c.isalnum() or c.isspace() else " " for c in field_name
        )
        # Convert to snake_case
        field_name = "".join(field_name.lower().split())
        return field_name.replace("_", "-")

    def _retrieve_all_blueprints(self, project_arn: str):
        """
        Retrieve all blueprints from the Bedrock Data Automation service.
        If project_arn is provided, retrieves blueprints associated with that project.

        Args:
            project_arn (Optional[str]): ARN of the data automation project to filter blueprints

        Returns:
            list: List of blueprint names and ARNs
        """
        try:
            all_blueprints = []

            # If project ARN is provided, get blueprints from the project
            if project_arn:
                try:
                    blueprint_response = self.blueprint_creator.list_blueprints(
                        projectArn=project_arn, projectStage="LIVE"
                    )

                    blueprints = blueprint_response.get("blueprints", [])
                    for blueprint in blueprints:
                        blueprint_arn = blueprint.get("blueprintArn", None)
                        if "aws:blueprint" in blueprint_arn:
                            continue
                        response = self.blueprint_creator.get_blueprint(
                            blueprint_arn=blueprint_arn, stage="LIVE"
                        )
                        _blueprint = response.get("blueprint")
                        _blueprint["blueprintVersion"] = blueprint["blueprintVersion"]
                        all_blueprints.append(_blueprint)
                    logger.info(
                        f"{len(all_blueprints)} blueprints retrieved for {project_arn}"
                    )
                    logger.info(
                        f"blueprints retrieved {json.dumps(all_blueprints, default=str)}"
                    )
                    return all_blueprints

                except ClientError as e:
                    logger.warning(f"Could not retrieve project {project_arn}: {e}")
                    # Fall through to list all blueprints
                    return []

        except Exception as e:
            logger.error(f"Error retrieving blueprints: {e}")
            return []

    def _check_for_updates(self, custom_class: dict, blueprint: dict):
        # get the schema
        schema = blueprint["schema"]
        schema = json.loads(schema)
        # get the document class
        definitions = schema["definitions"]
        groups = custom_class.get("attributes", None)
        # traverse thru definitions fist
        if groups is None:
            groups = []
        logger.info(f"number of groups {len(groups)}")
        _updatesFound = False
        if (
            custom_class["name"] != schema["class"]
            or custom_class["description"] != schema["description"]
        ):
            _updatesFound = True
            return _updatesFound
        for group in groups:
            groupName = group.get("name")
            formattedGroupName = self._format_section_name(groupName)
            definition = definitions.get(formattedGroupName, None)
            if not definition:
                logger.info(f"change found group {groupName} : {formattedGroupName}")
                return True
            group_type = group.get("attributeType")
            fields = group.get("groupAttributes", [])
            if group_type and group_type.lower() == "list":
                listItemTemplate = group.get("listItemTemplate", {})
                fields = listItemTemplate.get("itemAttributes", [])
            if definition:
                for field in fields:
                    field_name = field.get("name")
                    formatted_field_name = self._format_field_name(
                        field_name=field_name
                    )
                    blueprint_field = definition["properties"].get(
                        formatted_field_name, None
                    )
                    if not blueprint_field or blueprint_field[
                        "instruction"
                    ] != field.get("description", None):
                        _updatesFound = True
                        logger.info(
                            f"change found for field {groupName} : {formattedGroupName} {blueprint_field} {field}"
                        )
                        return _updatesFound

        return _updatesFound

    def _blueprint_lookup(self, existing_blueprints, doc_class):
        # Create a lookup dictionary for existing blueprints by name prefix
        _blueprint_prefix = f"{self.blueprint_name_prefix}-{doc_class}"
        logger.info(f"blueprint lookup using name {_blueprint_prefix}")
        for blueprint in existing_blueprints:
            blueprint_name = blueprint.get("blueprintName", "")
            if blueprint_name.startswith(_blueprint_prefix):
                return blueprint
        return None

    def create_blueprints_from_custom_configuration(self):
        """
        Create blueprint from custom configurations.
        Raises:
            Exception: If blueprint creation fails
        """
        logger.info("Creating blueprint for document ")

        try:
            config_item = self._get_configuration_item("Custom")

            if not config_item or "classes" not in config_item:
                logger.info("No Custom configuration to process")
                return {"status": "success", "message": "No classes to process"}

            classess = config_item["classes"]

            if not classess or len(classess) == 0:
                logger.info("No Custom configuration to process")
                return {"status": "success", "message": "No classes to process"}

            classess_status = []
            # retrieve all blueprints for this project.
            existing_blueprints = self._retrieve_all_blueprints(
                self.dataAutomationProjectArn
            )

            blueprints_updated = []

            for custom_class in classess:
                try:
                    blueprint_arn = custom_class.get("blueprint_arn", None)
                    blueprint_name = custom_class.get("blueprint_name", None)
                    docu_class = custom_class["name"]
                    docu_desc = custom_class["description"]
                    converter = SchemaConverter(
                        document_class=docu_class, description=docu_desc
                    )
                    blueprint_exists = self._blueprint_lookup(
                        existing_blueprints, docu_class
                    )
                    if blueprint_exists:
                        blueprint_arn = blueprint_exists.get("blueprintArn")
                        blueprint_name = blueprint_exists.get("blueprintName")
                        logger.info(
                            f"blueprint already exists for this class {docu_class} updating blueprint {blueprint_arn}"
                        )

                    if blueprint_arn:
                        # Use existing blueprint
                        custom_class["blueprint_arn"] = blueprint_arn
                        custom_class["blueprint_name"] = blueprint_name
                        logger.info(
                            f"Found existing blueprint for class {docu_class}: {blueprint_name}"
                        )
                        blueprints_updated.append(blueprint_arn)

                        # Check for updates on existing blueprint
                        if self._check_for_updates(
                            custom_class=custom_class, blueprint=blueprint_exists
                        ):
                            blueprint_schema = converter.convert(custom_class)
                            logger.info(
                                f"Blueprint schema generate:: for {json.dumps(custom_class, indent=2)}"
                            )
                            logger.info(json.dumps(blueprint_schema, indent=2))
                            logger.info("Blueprint schema generate:: END")

                            result = self.blueprint_creator.update_blueprint(
                                blueprint_arn=blueprint_arn,
                                stage="LIVE",
                                schema=json.dumps(blueprint_schema),
                            )
                            result = self.blueprint_creator.create_blueprint_version(
                                blueprint_arn=blueprint_arn,
                                project_arn=self.dataAutomationProjectArn,
                            )
                            custom_class["blueprint_version"] = result.get(
                                "blueprint"
                            ).get("blueprint_version")
                            logger.info(
                                f"Updated existing blueprint for class {docu_class}"
                            )
                        else:
                            logger.info(
                                f"No updates needed for existing blueprint {blueprint_name}"
                            )

                    else:
                        # create new blueprint
                        # Call the create_blueprint method
                        blueprint_name = f"{self.blueprint_name_prefix}-{docu_class}-{uuid.uuid4().hex[:8]}"

                        blueprint_schema = converter.convert(custom_class)
                        logger.info(
                            f"Blueprint schema generate:: for {json.dumps(custom_class, indent=2)}"
                        )
                        logger.info(json.dumps(blueprint_schema, indent=2))
                        logger.info("Blueprint schema generate:: END")

                        result = self.blueprint_creator.create_blueprint(
                            document_type="DOCUMENT",
                            blueprint_name=blueprint_name,
                            schema=json.dumps(blueprint_schema),
                        )
                        status = result["status"]
                        logger.info(f"blueprint created status {status}")
                        if status != "success":
                            raise Exception(f"Failed to create blueprint: {result}")

                        blueprint_arn = result["blueprint"]["blueprintArn"]
                        blueprint_name = result["blueprint"]["blueprintName"]
                        custom_class["blueprint_arn"] = blueprint_arn
                        custom_class["blueprint_name"] = blueprint_name
                        # update the project or create new project
                        # update the project with version
                        result = self.blueprint_creator.create_blueprint_version(
                            blueprint_arn=blueprint_arn,
                            project_arn=self.dataAutomationProjectArn,
                        )
                        custom_class["blueprint_version"] = result.get("blueprint").get(
                            "blueprint_version"
                        )
                        blueprints_updated.append(blueprint_arn)
                        logger.info(
                            f"Created new blueprint for class {docu_class}: {blueprint_name}"
                        )
                    classess_status.append(
                        {
                            "class": custom_class["name"],
                            "blueprint_arn": blueprint_arn,
                            "status": "success",
                        }
                    )

                except Exception as e:
                    class_name = (
                        custom_class.get("name", "unknown")
                        if custom_class
                        else "unknown"
                    )
                    logger.error(
                        f"Error processing blueprint creation/update for class {class_name}: {e}"
                    )
                    classess_status.append(
                        {
                            "class": class_name,
                            "status": "failed",
                            "error_message": f"Exception - {str(e)}",
                        }
                    )
            self._synchronize_deletes(
                existing_blueprints=existing_blueprints,
                blueprints_updated=blueprints_updated,
            )
            self._handle_update_configuration(classess)
            return classess_status

        except Exception as e:
            logger.error(f"Error processing blueprint creation: {e}", exc_info=True)
            # Re-raise the exception to be handled by the caller
            raise Exception(f"Failed to process blueprint creation: {str(e)}")

    def _synchronize_deletes(self, existing_blueprints, blueprints_updated):
        # remove all blueprints which are not in custom class
        blueprints_to_delete = []
        blueprints_arn_to_delete = []
        for blueprint in existing_blueprints:
            blueprint_name = blueprint.get("blueprintName", "")
            blueprint_arn = blueprint.get("blueprintArn", "")
            blueprint_version = blueprint.get("blueprintVersion", "")
            if blueprint_arn in blueprints_updated:
                continue
            if blueprint_name.startswith(self.blueprint_name_prefix):
                # delete detected - remove the blueprint
                logger.info(f"deleting blueprint not in custom class {blueprint_name}")
                blueprints_to_delete.append(blueprint)
                blueprints_arn_to_delete.append(blueprint_arn)

        if len(blueprints_to_delete) > 0:
            # remove the blueprints marked for deletion for the project first before deleting them.
            response = self.blueprint_creator.list_blueprints(
                self.dataAutomationProjectArn, "LIVE"
            )
            custom_configurations = response.get("blueprints", [])
            new_custom_configurations = []
            for custom_blueprint in custom_configurations:
                if custom_blueprint.get("blueprintArn") not in blueprints_arn_to_delete:
                    new_custom_configurations.append(custom_blueprint)
            new_custom_configurations = {"blueprints": new_custom_configurations}
            response = self.blueprint_creator.update_project_with_custom_configurations(
                self.dataAutomationProjectArn,
                customConfiguration=new_custom_configurations,
            )

            try:
                for _blueprint_delete in blueprints_to_delete:
                    self.blueprint_creator.delete_blueprint(
                        _blueprint_delete.get("blueprintArn"),
                        _blueprint_delete.get("blueprintVersion"),
                    )
            except Exception:
                logger.error(
                    f"Error during deleting blueprint {blueprint_name} {blueprint_arn} {blueprint_version}"
                )
            try:
                for _blueprint_delete in blueprints_to_delete:
                    self.blueprint_creator.delete_blueprint(
                        _blueprint_delete.get("blueprintArn"), None
                    )
            except Exception:
                logger.error(
                    f"Error during deleting blueprint {blueprint_name} {blueprint_arn} {blueprint_version}"
                )
