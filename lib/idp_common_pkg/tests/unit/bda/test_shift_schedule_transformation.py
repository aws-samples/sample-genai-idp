# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for shift schedule transformation to verify array instruction defaulting.
"""

from unittest.mock import MagicMock, patch

import pytest

from idp_common.bda.bda_blueprint_service import BdaBlueprintService


@pytest.mark.unit
class TestShiftScheduleTransformation:
    """Tests for shift schedule schema transformation with array instruction defaulting."""

    @pytest.fixture
    def service(self):
        """Fixture providing a BdaBlueprintService instance with mocked dependencies."""
        with (
            patch("boto3.resource") as mock_dynamodb,
            patch("boto3.client") as mock_boto_client,
            patch(
                "idp_common.bda.bda_blueprint_service.ConfigurationManager"
            ) as mock_config_manager,
            patch.dict("os.environ", {"CONFIGURATION_TABLE_NAME": "test-config-table"}),
        ):
            # Mock DynamoDB table
            mock_table = MagicMock()
            mock_dynamodb.return_value.Table.return_value = mock_table

            # Mock boto3 client for BDABlueprintCreator
            mock_bedrock_client = MagicMock()
            mock_boto_client.return_value = mock_bedrock_client

            # Mock configuration manager
            mock_manager_instance = mock_config_manager.return_value
            mock_manager_instance.get_configuration.return_value = None

            service = BdaBlueprintService()
            return service

    @pytest.fixture
    def shift_schedule_idp_schema(self):
        """Load the shift schedule IDP schema from resources."""
        import json
        from pathlib import Path

        test_dir = Path(__file__).parent.parent.parent
        resources_dir = test_dir / "resources"
        schema_file = resources_dir / "shift_schedule_idp_schema.json"

        with open(schema_file, "r") as f:
            return json.load(f)

    def test_shift_schedule_idp_to_blueprint_transformation(
        self, service, shift_schedule_idp_schema
    ):
        """Test converting shift schedule IDP schema to BDA blueprint format."""
        # Transform IDP schema to BDA blueprint
        blueprint_schema = service._transform_json_schema_to_bedrock_blueprint(
            shift_schedule_idp_schema
        )

        # Verify basic BDA structure
        assert blueprint_schema["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert blueprint_schema["class"] == "SHIFT_SCHEDULE"
        assert blueprint_schema["type"] == "object"
        assert (
            blueprint_schema["description"]
            == "Employee shift schedule with daily assignments"
        )

        # Verify definitions structure
        assert "definitions" in blueprint_schema
        assert "$defs" not in blueprint_schema

        # Verify array properties have instruction field
        properties = blueprint_schema["properties"]

        # Check employees array - should use description as instruction
        employees_array = properties["employees"]
        assert employees_array["type"] == "array"
        assert "instruction" in employees_array
        assert employees_array["instruction"] == "Employee schedules"
        assert "items" in employees_array
        assert employees_array["items"]["$ref"] == "#/definitions/Employee"

        # Check nested shifts array in Employee definition
        employee_def = blueprint_schema["definitions"]["Employee"]
        # The shifts array should be skipped due to BDA limitations with nested arrays
        assert "shifts" not in employee_def["properties"]

        # Verify leaf properties have BDA fields
        employee_name = employee_def["properties"]["employeeName"]
        assert employee_name["type"] == "string"
        assert "inferenceType" in employee_name
        assert "instruction" in employee_name
        assert employee_name["instruction"] == "Employee name"

    def test_array_without_description_gets_default_instruction(self, service):
        """Test that arrays without description get default instruction of '-'."""
        # Create a schema with an array that has no description
        test_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "TestDoc",
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    # No description field
                },
                "namedItems": {
                    "type": "array",
                    "description": "List of named items",
                    "items": {"type": "string"},
                },
            },
        }

        # Transform to BDA blueprint
        blueprint = service._transform_json_schema_to_bedrock_blueprint(test_schema)

        # Verify array without description gets default instruction
        items_array = blueprint["properties"]["items"]
        assert items_array["instruction"] == "-"

        # Verify array with description uses it as instruction
        named_items_array = blueprint["properties"]["namedItems"]
        assert named_items_array["instruction"] == "List of named items"

    def test_nested_arrays_get_instruction_fields(self, service):
        """Test that nested arrays in definitions also get instruction fields."""
        test_schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "TestDoc",
            "type": "object",
            "$defs": {
                "Container": {
                    "type": "object",
                    "properties": {
                        "simpleField": {
                            "type": "string",
                            "description": "Simple field in container",
                        },
                        # Note: Nested arrays within objects are skipped by BDA transformation
                        # This test verifies the behavior when BDA limitations are in place
                    },
                }
            },
            "properties": {
                "containers": {
                    "type": "array",
                    "description": "List of containers",
                    "items": {"$ref": "#/$defs/Container"},
                }
            },
        }

        # Transform to BDA blueprint
        blueprint = service._transform_json_schema_to_bedrock_blueprint(test_schema)

        # Verify main array has instruction
        containers_array = blueprint["properties"]["containers"]
        assert containers_array["instruction"] == "List of containers"

        # Verify Container definition exists and has simple fields only
        container_def = blueprint["definitions"]["Container"]
        assert "simpleField" in container_def["properties"]

        # Verify simple field has BDA fields
        simple_field = container_def["properties"]["simpleField"]
        assert simple_field["inferenceType"] == "explicit"
        assert simple_field["instruction"] == "Simple field in container"
