# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for the BdaBlueprintService class.
"""

# ruff: noqa: E402, I001
# The above line disables E402 (module level import not at top of file) and I001 (import block sorting) for this file

import pytest

# Import standard library modules first
import json
from unittest.mock import MagicMock, patch

# Import third-party modules
from botocore.exceptions import ClientError

# Import application modules
from idp_common.bda.bda_blueprint_service import BdaBlueprintService


@pytest.mark.unit
class TestBdaBlueprintService:
    """Tests for the BdaBlueprintService class."""

    @pytest.fixture
    def mock_custom_configuration(self):
        """Fixture providing mock custom configuration data."""
        return {
            "Configuration": "Custom",
            "classes": [
                {
                    "name": "W-4",
                    "description": "Employee's Withholding Certificate form",
                    "attributes": [
                        {
                            "name": "PersonalInformation",
                            "description": "Personal information of employee",
                            "attributeType": "group",
                            "groupType": "normal",
                            "groupAttributes": [
                                {
                                    "name": "FirstName",
                                    "dataType": "string",
                                    "description": "First Name of Employee",
                                },
                                {
                                    "name": "LastName",
                                    "dataType": "string",
                                    "description": "Last Name of Employee",
                                },
                            ],
                        }
                    ],
                },
                {
                    "name": "I-9",
                    "description": "Employment Eligibility Verification",
                    "blueprint_arn": "arn:aws:bedrock:us-west-2:123456789012:blueprint/existing-i9-blueprint",
                    "attributes": [
                        {
                            "name": "EmployeeInfo",
                            "description": "Employee information section",
                            "attributeType": "group",
                            "groupType": "normal",
                            "groupAttributes": [
                                {
                                    "name": "FullName",
                                    "dataType": "string",
                                    "description": "Employee full name",
                                }
                            ],
                        }
                    ],
                },
            ],
        }

    @pytest.fixture
    def mock_blueprint_schema(self):
        """Fixture providing mock blueprint schema."""
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "description": "Employee's Withholding Certificate form",
            "class": "W-4",
            "type": "object",
            "definitions": {
                "PersonalInformation": {
                    "type": "object",
                    "properties": {
                        "firstname": {
                            "type": "string",
                            "instruction": "First Name of Employee",
                        },
                        "lastname": {
                            "type": "string",
                            "instruction": "Last Name of Employee",
                        },
                    },
                }
            },
            "properties": {
                "PersonalInformation": {"$ref": "#/definitions/PersonalInformation"}
            },
        }

    @pytest.fixture
    def mock_blueprint_response(self):
        """Fixture providing mock blueprint creation response."""
        return {
            "status": "success",
            "blueprint": {
                "blueprintArn": "arn:aws:bedrock:us-west-2:123456789012:blueprint/w4-12345678",
                "blueprintName": "W-4-12345678",
                "blueprintStage": "LIVE",
                "blueprintVersion": "1",
            },
        }

    @pytest.fixture
    def service(self):
        """Fixture providing a BdaBlueprintService instance with mocked dependencies."""
        with (
            patch("boto3.resource") as mock_dynamodb,
            patch("boto3.client") as mock_boto_client,
            patch.dict("os.environ", {"CONFIGURATION_TABLE_NAME": "test-config-table"}),
        ):
            # Mock DynamoDB table
            mock_table = MagicMock()
            mock_dynamodb.return_value.Table.return_value = mock_table

            # Mock boto3 client for BDABlueprintCreator
            mock_bedrock_client = MagicMock()
            mock_boto_client.return_value = mock_bedrock_client

            service = BdaBlueprintService(
                dataAutomationProjectArn="arn:aws:bedrock:us-west-2:123456789012:project/test-project"
            )

            # Store mocks for access in tests
            service._mock_table = mock_table

            # Replace the blueprint_creator with a mock
            mock_blueprint_creator = MagicMock()
            service.blueprint_creator = mock_blueprint_creator
            service._mock_blueprint_creator = mock_blueprint_creator

            return service

    def test_init(self):
        """Test initialization of BdaBlueprintService."""
        with (
            patch("boto3.resource") as mock_dynamodb,
            patch("boto3.client") as mock_boto_client,
            patch.dict(
                "os.environ",
                {
                    "CONFIGURATION_TABLE_NAME": "test-config-table",
                    "AWS_REGION": "us-east-1",
                },
            ),
        ):
            service = BdaBlueprintService(
                dataAutomationProjectArn="arn:aws:bedrock:us-west-2:123456789012:project/test-project"
            )

            assert (
                service.dataAutomationProjectArn
                == "arn:aws:bedrock:us-west-2:123456789012:project/test-project"
            )
            assert service.configuration_table_name == "test-config-table"

            # Verify boto3 client was called for BDABlueprintCreator
            mock_boto_client.assert_called_with(service_name="bedrock-data-automation")

            # Verify DynamoDB table was set up
            mock_dynamodb.assert_called_once_with("dynamodb")

    def test_stringify_values(self, service):
        """Test the _stringify_values method."""
        # Test with mixed data types
        input_data = {
            "string": "test",
            "number": 123,
            "float": 45.67,
            "boolean": True,
            "none": None,
            "list": [1, 2, "three", None],
            "nested_dict": {"inner_string": "inner", "inner_number": 456},
        }

        result = service._stringify_values(input_data)

        assert result["string"] == "test"
        assert result["number"] == "123"
        assert result["float"] == "45.67"
        assert result["boolean"] == "True"
        assert result["none"] is None
        assert result["list"] == ["1", "2", "three", None]
        assert result["nested_dict"]["inner_string"] == "inner"
        assert result["nested_dict"]["inner_number"] == "456"

    def test_get_configuration_item_success(self, service, mock_custom_configuration):
        """Test successful retrieval of configuration item."""
        service._mock_table.get_item.return_value = {"Item": mock_custom_configuration}

        result = service._get_configuration_item("Custom")

        assert result == mock_custom_configuration
        service._mock_table.get_item.assert_called_once_with(
            Key={"Configuration": "Custom"}
        )

    def test_get_configuration_item_not_found(self, service):
        """Test retrieval of non-existent configuration item."""
        service._mock_table.get_item.return_value = {}

        result = service._get_configuration_item("NonExistent")

        assert result is None

    def test_get_configuration_item_client_error(self, service):
        """Test handling of ClientError during configuration retrieval."""
        error_response = {
            "Error": {"Code": "ResourceNotFoundException", "Message": "Table not found"}
        }
        service._mock_table.get_item.side_effect = ClientError(
            error_response, "GetItem"
        )

        with pytest.raises(Exception, match="Failed to retrieve Custom configuration"):
            service._get_configuration_item("Custom")

    def test_handle_update_configuration_success(self, service):
        """Test successful configuration update."""
        custom_config = [
            {
                "name": "W-4",
                "description": "Employee's Withholding Certificate",
                "attributes": [],
            }
        ]

        result = service._handle_update_configuration(custom_config)

        assert result is True
        service._mock_table.put_item.assert_called_once()

        # Verify the put_item call
        call_args = service._mock_table.put_item.call_args[1]
        assert call_args["Item"]["Configuration"] == "Custom"
        assert call_args["Item"]["classes"] == custom_config

    def test_handle_update_configuration_exception(self, service):
        """Test handling of exception during configuration update."""
        service._mock_table.put_item.side_effect = Exception("DynamoDB error")

        with pytest.raises(Exception, match="DynamoDB error"):
            service._handle_update_configuration([])

    def test_create_blueprints_from_custom_configuration_no_config(self, service):
        """Test handling when no custom configuration exists."""
        # Mock empty configuration retrieval
        service._mock_table.get_item.return_value = {
            "Item": {"Configuration": "Custom", "classes": []}
        }

        # This should not raise an exception but should handle empty classes gracefully
        # Note: The current implementation has a bug with len(classess) < 0 which is never true
        # We'll test the actual behavior
        result = service.create_blueprints_from_custom_configuration()

        # Should complete without processing any classes
        assert result["status"] == "success"
        assert "No classes to process" in result["message"]
        service.blueprint_creator.create_blueprint.assert_not_called()
        service.blueprint_creator.update_blueprint.assert_not_called()

    def test_create_blueprints_from_custom_configuration_no_classes_key(self, service):
        """Test handling when configuration has no 'classes' key."""
        # Mock configuration without classes key
        service._mock_table.get_item.return_value = {
            "Item": {"Configuration": "Custom"}
        }

        # Should handle missing classes key gracefully
        result = service.create_blueprints_from_custom_configuration()

        assert result["status"] == "success"
        service.blueprint_creator.create_blueprint.assert_not_called()

    def test_create_blueprints_from_custom_configuration_dynamodb_error(self, service):
        """Test handling of DynamoDB error during configuration retrieval."""
        # Mock DynamoDB error
        error_response = {
            "Error": {"Code": "ResourceNotFoundException", "Message": "Table not found"}
        }
        service._mock_table.get_item.side_effect = ClientError(
            error_response, "GetItem"
        )

        # Should raise exception on DynamoDB error
        with pytest.raises(Exception, match="Failed to process blueprint creation"):
            service.create_blueprints_from_custom_configuration()

    def test_create_blueprints_from_custom_configuration_partial_failure(
        self, service, mock_custom_configuration
    ):
        """Test handling when one blueprint succeeds and another fails."""
        # Mock configuration retrieval
        service._mock_table.get_item.return_value = {"Item": mock_custom_configuration}

        # Mock first blueprint creation success, second failure
        success_response = {
            "status": "success",
            "blueprint": {
                "blueprintArn": "arn:aws:bedrock:us-west-2:123456789012:blueprint/w4-12345678",
                "blueprintName": "W-4-12345678",
            },
        }

        service.blueprint_creator.create_blueprint.return_value = success_response
        service.blueprint_creator.update_blueprint.side_effect = Exception(
            "Update failed"
        )
        service.blueprint_creator.create_blueprint_version.return_value = (
            success_response
        )

        # Should continue processing despite individual failures
        # The method should complete and update configuration with successful blueprints
        service.create_blueprints_from_custom_configuration()

        # Should still update configuration despite partial failure
        service._mock_table.put_item.assert_called_once()

    def test_stringify_values_edge_cases(self, service):
        """Test _stringify_values with edge cases."""
        # Test empty structures
        assert service._stringify_values({}) == {}
        assert service._stringify_values([]) == []

        # Test deeply nested structures
        deep_nested = {"level1": {"level2": {"level3": [1, 2, {"level4": True}]}}}
        result = service._stringify_values(deep_nested)
        assert result["level1"]["level2"]["level3"][2]["level4"] == "True"

        # Test with special values
        special_values = {"zero": 0, "empty_string": "", "false": False, "none": None}
        result = service._stringify_values(special_values)
        assert result["zero"] == "0"
        assert result["empty_string"] == ""
        assert result["false"] == "False"
        assert result["none"] is None

    def test_handle_update_configuration_with_complex_data(self, service):
        """Test configuration update with complex nested data."""
        complex_config = [
            {
                "name": "ComplexForm",
                "description": "A complex form with nested structures",
                "attributes": [
                    {
                        "name": "Section1",
                        "groupAttributes": [
                            {
                                "name": "Field1",
                                "dataType": "string",
                                "validations": ["required", "min_length:5"],
                            }
                        ],
                    }
                ],
            }
        ]

        result = service._handle_update_configuration(complex_config)

        assert result is True
        call_args = service._mock_table.put_item.call_args[1]

        # Verify complex data was stringified properly
        stored_config = call_args["Item"]["classes"]
        assert stored_config[0]["attributes"][0]["groupAttributes"][0][
            "validations"
        ] == ["required", "min_length:5"]

    def test_check_for_updates_no_changes(self, service):
        """Test _check_for_updates when no changes are detected."""
        # Mock custom class configuration
        custom_class = {
            "name": "W-4",
            "description": "Employee's Withholding Certificate form",
            "attributes": [
                {
                    "name": "PersonalInformation",
                    "description": "Personal info",
                    "groupAttributes": [
                        {
                            "name": "FirstName",
                            "dataType": "string",
                            "description": "First Name of Employee",
                        },
                        {
                            "name": "LastName",
                            "dataType": "string",
                            "description": "Last Name of Employee",
                        },
                    ],
                }
            ],
        }

        # Mock existing blueprint schema that matches the custom class
        existing_blueprint = {
            "schema": json.dumps(
                {
                    "class": "W-4",
                    "description": "Employee's Withholding Certificate form",
                    "definitions": {
                        "Personalinformation": {  # Formatted section name (capitalize)
                            "properties": {
                                "firstname": {  # Formatted field name (lowercase)
                                    "type": "string",
                                    "instruction": "First Name of Employee",
                                },
                                "lastname": {  # Formatted field name (lowercase)
                                    "type": "string",
                                    "instruction": "Last Name of Employee",
                                },
                            }
                        }
                    },
                }
            )
        }

        # Execute the method
        result = service._check_for_updates(custom_class, existing_blueprint)

        # Should return False (no updates needed)
        assert result is False

    def test_check_for_updates_class_name_changed(self, service):
        """Test _check_for_updates when class name has changed."""
        custom_class = {
            "name": "W-4-Updated",  # Changed name
            "description": "Employee's Withholding Certificate form",
            "attributes": [],
        }

        existing_blueprint = {
            "schema": json.dumps(
                {
                    "class": "W-4",  # Original name
                    "description": "Employee's Withholding Certificate form",
                    "definitions": {},
                }
            )
        }

        result = service._check_for_updates(custom_class, existing_blueprint)

        # Should return True (updates needed)
        assert result is True

    def test_check_for_updates_description_changed(self, service):
        """Test _check_for_updates when description has changed."""
        custom_class = {
            "name": "W-4",
            "description": "Updated Employee's Withholding Certificate form",  # Changed description
            "attributes": [],
        }

        existing_blueprint = {
            "schema": json.dumps(
                {
                    "class": "W-4",
                    "description": "Employee's Withholding Certificate form",  # Original description
                    "definitions": {},
                }
            )
        }

        result = service._check_for_updates(custom_class, existing_blueprint)

        # Should return True (updates needed)
        assert result is True

    def test_check_for_updates_new_group_added(self, service):
        """Test _check_for_updates when a new group is added."""
        custom_class = {
            "name": "W-4",
            "description": "Employee's Withholding Certificate form",
            "attributes": [
                {"name": "PersonalInformation", "groupAttributes": []},
                {
                    "name": "NewSection",  # New group not in existing blueprint
                    "groupAttributes": [],
                },
            ],
        }

        existing_blueprint = {
            "schema": json.dumps(
                {
                    "class": "W-4",
                    "description": "Employee's Withholding Certificate form",
                    "definitions": {
                        "Personalinformation": {  # Formatted section name (capitalize)
                            "properties": {}
                        }
                        # Newsection is missing
                    },
                }
            )
        }

        result = service._check_for_updates(custom_class, existing_blueprint)

        # Should return True (updates needed)
        assert result is True

    def test_check_for_updates_field_description_changed(self, service):
        """Test _check_for_updates when a field description has changed."""
        custom_class = {
            "name": "W-4",
            "description": "Employee's Withholding Certificate form",
            "attributes": [
                {
                    "name": "PersonalInformation",
                    "groupAttributes": [
                        {
                            "name": "FirstName",
                            "dataType": "string",
                            "description": "Updated first name description",  # Changed description
                        }
                    ],
                }
            ],
        }

        existing_blueprint = {
            "schema": json.dumps(
                {
                    "class": "W-4",
                    "description": "Employee's Withholding Certificate form",
                    "definitions": {
                        "Personalinformation": {  # Formatted section name (capitalize)
                            "properties": {
                                "firstname": {  # Formatted field name (lowercase)
                                    "type": "string",
                                    "instruction": "First Name of Employee",  # Original description
                                }
                            }
                        }
                    },
                }
            )
        }

        result = service._check_for_updates(custom_class, existing_blueprint)

        # Should return True (updates needed)
        assert result is True

    def test_check_for_updates_new_field_added(self, service):
        """Test _check_for_updates when a new field is added to existing group."""
        custom_class = {
            "name": "W-4",
            "description": "Employee's Withholding Certificate form",
            "attributes": [
                {
                    "name": "PersonalInformation",
                    "groupAttributes": [
                        {
                            "name": "FirstName",
                            "dataType": "string",
                            "description": "First Name of Employee",
                        },
                        {
                            "name": "MiddleName",  # New field
                            "dataType": "string",
                            "description": "Middle Name of Employee",
                        },
                    ],
                }
            ],
        }

        existing_blueprint = {
            "schema": json.dumps(
                {
                    "class": "W-4",
                    "description": "Employee's Withholding Certificate form",
                    "definitions": {
                        "Personalinformation": {  # Formatted section name (capitalize)
                            "properties": {
                                "firstname": {  # Formatted field name (lowercase)
                                    "type": "string",
                                    "instruction": "First Name of Employee",
                                }
                                # middlename is missing
                            }
                        }
                    },
                }
            )
        }

        result = service._check_for_updates(custom_class, existing_blueprint)

        # Should return True (updates needed)
        assert result is True

    def test_check_for_updates_blueprint_retrieval_error(self, service):
        """Test _check_for_updates when blueprint has invalid schema."""
        custom_class = {
            "name": "W-4",
            "description": "Employee's Withholding Certificate form",
            "attributes": [],
        }

        # Invalid blueprint with malformed schema
        invalid_blueprint = {"schema": "invalid json"}

        # Should raise the exception
        with pytest.raises(json.JSONDecodeError):
            service._check_for_updates(custom_class, invalid_blueprint)

    def test_check_for_updates_empty_attributes(self, service):
        """Test _check_for_updates with empty attributes list."""
        custom_class = {
            "name": "W-4",
            "description": "Employee's Withholding Certificate form",
            "attributes": [],  # Empty attributes
        }

        existing_blueprint = {
            "schema": json.dumps(
                {
                    "class": "W-4",
                    "description": "Employee's Withholding Certificate form",
                    "definitions": {},
                }
            )
        }

        result = service._check_for_updates(custom_class, existing_blueprint)

        # Should return False (no updates needed for empty attributes)
        assert result is False

    def test_check_for_updates_missing_attributes_key(self, service):
        """Test _check_for_updates when attributes key is missing."""
        custom_class = {
            "name": "W-4",
            "description": "Employee's Withholding Certificate form",
            # Missing attributes key
        }

        existing_blueprint = {
            "schema": json.dumps(
                {
                    "class": "W-4",
                    "description": "Employee's Withholding Certificate form",
                    "definitions": {},
                }
            )
        }

        # Should handle missing attributes gracefully
        result = service._check_for_updates(custom_class, existing_blueprint)

        # Should return False when attributes is None
        assert result is False
