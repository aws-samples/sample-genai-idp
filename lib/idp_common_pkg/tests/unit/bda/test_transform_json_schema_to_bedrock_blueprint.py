# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for the _transform_json_schema_to_bedrock_blueprint method in BdaBlueprintService.
"""

from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest

from idp_common.bda.bda_blueprint_service import BdaBlueprintService


@pytest.mark.unit
class TestTransformJsonSchemaToBedrock:
    """Tests for the _transform_json_schema_to_bedrock_blueprint method."""

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

            service = BdaBlueprintService(
                dataAutomationProjectArn="arn:aws:bedrock:us-west-2:123456789012:project/test-project"
            )

            # Replace the blueprint_creator with a mock to avoid actual Bedrock calls
            mock_blueprint_creator = MagicMock()
            service.blueprint_creator = mock_blueprint_creator

            return service

    @pytest.fixture
    def input_1040_schema(self):
        """Load the input 1040 schema from test resources."""
        # This is a simplified version based on the file content we saw
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "Form-1040",
            "x-aws-idp-document-type": "Form-1040",
            "type": "object",
            "description": "U.S. Individual Income Tax Return",
            "properties": {
                "PersonalInformation": {
                    "type": "object",
                    "description": "Personal information of the taxpayer",
                    "properties": {
                        "FirstName": {
                            "type": "string",
                            "description": "First name of the taxpayer",
                        },
                        "LastName": {
                            "type": "string",
                            "description": "Last name of the taxpayer",
                        },
                        "SocialSecurityNumber": {
                            "type": "string",
                            "description": "Social security number of the taxpayer",
                        },
                    },
                },
                "Income": {
                    "type": "object",
                    "description": "Income details of the taxpayer",
                    "properties": {
                        "Wages": {
                            "type": "number",
                            "description": "Wages reported on Form(s) W-2",
                        },
                        "TaxableIncome": {
                            "type": "number",
                            "description": "Taxable income",
                        },
                    },
                },
                "Dependents": {
                    "type": "array",
                    "description": "Dependents of the taxpayer",
                    "items": {
                        "type": "object",
                        "properties": {
                            "FirstName": {
                                "type": "string",
                                "description": "First name of the dependent",
                            },
                            "LastName": {
                                "type": "string",
                                "description": "Last name of the dependent",
                            },
                            "SocialSecurityNumber": {
                                "type": "string",
                                "description": "Social security number of the dependent",
                            },
                        },
                    },
                },
            },
        }

    @pytest.fixture
    def input_1099b_schema(self):
        """Load the input 1099B schema from test resources."""
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "Form-1099B",
            "x-aws-idp-document-type": "Form-1099B",
            "type": "object",
            "description": "Proceeds From Broker and Barter Exchange Transactions",
            "properties": {
                "PayerInformation": {
                    "type": "object",
                    "description": "Payer information section",
                    "properties": {
                        "PayerName": {
                            "type": "string",
                            "description": "Name of the payer",
                        },
                        "PayerTIN": {
                            "type": "string",
                            "description": "Payer's taxpayer identification number",
                        },
                    },
                },
                "Transactions": {
                    "type": "array",
                    "description": "List of transactions",
                    "items": {
                        "type": "object",
                        "properties": {
                            "Description": {
                                "type": "string",
                                "description": "Description of property",
                            },
                            "GrossProceeds": {
                                "type": "number",
                                "description": "Gross proceeds",
                            },
                        },
                    },
                },
            },
        }

    @pytest.fixture
    def schema_with_defs(self):
        """Schema with $defs that should be converted to definitions."""
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "Document-With-Defs",
            "x-aws-idp-document-type": "Document-With-Defs",
            "type": "object",
            "description": "Document with definitions",
            "properties": {
                "address": {"$ref": "#/$defs/Address"},
                "contact": {"$ref": "#/$defs/Contact"},
            },
            "$defs": {
                "Address": {
                    "type": "object",
                    "description": "Address information",
                    "properties": {
                        "street": {"type": "string", "description": "Street address"},
                        "city": {"type": "string", "description": "City name"},
                    },
                },
                "Contact": {
                    "type": "object",
                    "description": "Contact information",
                    "properties": {
                        "phone": {"type": "string", "description": "Phone number"},
                        "email": {"type": "string", "description": "Email address"},
                    },
                },
            },
        }

    def test_transform_basic_schema_structure(self, service, input_1040_schema):
        """Test that the basic schema structure is correctly transformed."""
        result = service._transform_json_schema_to_bedrock_blueprint(input_1040_schema)

        # Verify basic BDA structure
        assert result["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert result["class"] == "Form-1040"
        assert result["description"] == "U.S. Individual Income Tax Return"
        assert result["type"] == "object"
        assert "properties" in result
        assert "definitions" in result
        print(result)

    def test_transform_extracts_complex_objects_to_definitions(
        self, service, input_1040_schema
    ):
        """Test that complex objects are extracted to definitions."""
        result = service._transform_json_schema_to_bedrock_blueprint(input_1040_schema)

        # Verify complex objects are extracted to definitions
        assert "PersonalInformation" in result["definitions"]
        assert "Income" in result["definitions"]

        # Verify main properties reference definitions
        assert (
            result["properties"]["PersonalInformation"]["$ref"]
            == "#/definitions/PersonalInformation"
        )
        assert result["properties"]["Income"]["$ref"] == "#/definitions/Income"

    def test_transform_adds_bda_fields_to_leaf_properties(
        self, service, input_1040_schema
    ):
        """Test that BDA fields (inferenceType, instruction) are added to leaf properties."""
        result = service._transform_json_schema_to_bedrock_blueprint(input_1040_schema)

        # Check leaf properties in PersonalInformation definition
        personal_info = result["definitions"]["PersonalInformation"]
        first_name = personal_info["properties"]["FirstName"]

        assert first_name["type"] == "string"
        assert first_name["inferenceType"] == "explicit"
        assert first_name["instruction"] == "First name of the taxpayer"
        assert "description" not in first_name  # Description should be removed

        # Check leaf properties in Income definition
        income = result["definitions"]["Income"]
        wages = income["properties"]["Wages"]

        assert wages["type"] == "number"
        assert wages["inferenceType"] == "explicit"
        assert wages["instruction"] == "Wages reported on Form(s) W-2"

    def test_transform_handles_arrays_correctly(self, service, input_1040_schema):
        """Test that arrays are handled correctly with item definitions."""
        result = service._transform_json_schema_to_bedrock_blueprint(input_1040_schema)

        # Verify array property structure
        dependents = result["properties"]["Dependents"]
        assert dependents["type"] == "array"
        assert dependents["items"]["$ref"] == "#/definitions/DependentsItem"

        # Verify array item definition exists
        assert "DependentsItem" in result["definitions"]
        dependents_item = result["definitions"]["DependentsItem"]
        assert dependents_item["type"] == "object"
        assert "properties" in dependents_item

        # Verify leaf properties in array item have BDA fields
        first_name = dependents_item["properties"]["FirstName"]
        assert first_name["inferenceType"] == "explicit"
        assert first_name["instruction"] == "First name of the dependent"

    def test_transform_converts_defs_to_definitions(self, service, schema_with_defs):
        """Test that $defs is converted to definitions and $ref paths are updated."""
        result = service._transform_json_schema_to_bedrock_blueprint(schema_with_defs)

        # Verify $defs was converted to definitions
        assert "definitions" in result
        assert "$defs" not in result
        assert "Address" in result["definitions"]
        assert "Contact" in result["definitions"]

        # Verify $ref paths were updated
        assert result["properties"]["address"]["$ref"] == "#/definitions/Address"
        assert result["properties"]["contact"]["$ref"] == "#/definitions/Contact"

        # Verify definitions have correct structure
        address_def = result["definitions"]["Address"]
        assert address_def["type"] == "object"
        assert "inferenceType" not in address_def  # Objects should not have BDA fields
        assert "instruction" not in address_def

        # Verify leaf properties in definitions have BDA fields
        street = address_def["properties"]["street"]
        assert street["inferenceType"] == "explicit"
        assert street["instruction"] == "Street address"

    def test_transform_removes_descriptions_from_objects(
        self, service, input_1040_schema
    ):
        """Test that descriptions are removed from object types but preserved as instructions for leaf types."""
        result = service._transform_json_schema_to_bedrock_blueprint(input_1040_schema)

        # Object definitions should not have description
        personal_info = result["definitions"]["PersonalInformation"]
        assert "description" not in personal_info
        assert personal_info["type"] == "object"

        # Leaf properties should have instruction (converted from description)
        first_name = personal_info["properties"]["FirstName"]
        assert "description" not in first_name
        assert first_name["instruction"] == "First name of the taxpayer"

    def test_transform_preserves_class_from_id_field(self, service):
        """Test that class field is correctly set from $id or x-aws-idp-document-type."""
        schema1 = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "W-4",
            "type": "object",
            "description": "Test document",
            "properties": {},
        }

        result1 = service._transform_json_schema_to_bedrock_blueprint(schema1)
        assert result1["class"] == "W-4"

        schema2 = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "x-aws-idp-document-type": "I-9",
            "type": "object",
            "description": "Test document",
            "properties": {},
        }

        result2 = service._transform_json_schema_to_bedrock_blueprint(schema2)
        assert result2["class"] == "I-9"

    def test_transform_handles_empty_properties(self, service):
        """Test transformation with empty properties."""
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "Empty-Doc",
            "type": "object",
            "description": "Empty document",
            "properties": {},
        }

        result = service._transform_json_schema_to_bedrock_blueprint(schema)

        assert result["properties"] == {}
        assert "definitions" not in result or result.get("definitions") == {}

    def test_transform_does_not_mutate_input(self, service, input_1040_schema):
        """Test that the transformation does not mutate the input schema."""
        original = deepcopy(input_1040_schema)

        service._transform_json_schema_to_bedrock_blueprint(input_1040_schema)

        assert input_1040_schema == original

    def test_transform_validates_against_correct_format_structure(
        self, service, input_1099b_schema
    ):
        """Test that the transformed schema follows the correct BDA format structure."""
        result = service._transform_json_schema_to_bedrock_blueprint(input_1099b_schema)

        # Verify it matches the expected BDA structure from correct_format.json
        assert result["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert "class" in result
        assert "description" in result
        assert result["type"] == "object"

        if "definitions" in result:
            # Verify definitions structure
            for def_name, definition in result["definitions"].items():
                assert definition["type"] == "object"
                assert "properties" in definition

                # Verify leaf properties have BDA fields
                for prop_name, prop_value in definition["properties"].items():
                    if prop_value.get("type") in ["string", "number", "boolean"]:
                        assert "inferenceType" in prop_value
                        assert "instruction" in prop_value
                        assert "description" not in prop_value

        # Verify properties structure
        for prop_name, prop_value in result["properties"].items():
            if "$ref" in prop_value:
                # Reference properties should point to definitions
                assert prop_value["$ref"].startswith("#/definitions/")
            elif prop_value.get("type") == "array":
                # Array properties should have items with $ref
                if "items" in prop_value and "$ref" in prop_value["items"]:
                    assert prop_value["items"]["$ref"].startswith("#/definitions/")

    def test_transform_handles_nested_objects_correctly(self, service):
        """Test that deeply nested objects are flattened correctly."""
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "Nested-Doc",
            "type": "object",
            "description": "Document with nested objects",
            "properties": {
                "Level1": {
                    "type": "object",
                    "description": "First level object",
                    "properties": {
                        "simpleField": {
                            "type": "string",
                            "description": "Simple field",
                        },
                        "numberField": {
                            "type": "number",
                            "description": "Number field",
                        },
                    },
                }
            },
        }

        result = service._transform_json_schema_to_bedrock_blueprint(schema)

        # Verify Level1 is extracted to definitions
        assert "Level1" in result["definitions"]
        assert result["properties"]["Level1"]["$ref"] == "#/definitions/Level1"

        # Verify leaf properties have BDA fields
        level1_def = result["definitions"]["Level1"]
        simple_field = level1_def["properties"]["simpleField"]
        assert simple_field["inferenceType"] == "explicit"
        assert simple_field["instruction"] == "Simple field"

        number_field = level1_def["properties"]["numberField"]
        assert number_field["inferenceType"] == "explicit"
        assert number_field["instruction"] == "Number field"

    def test_transform_with_missing_descriptions(self, service):
        """Test transformation when some fields are missing descriptions."""
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "Missing-Desc",
            "type": "object",
            "description": "Document with missing descriptions",
            "properties": {
                "Section1": {
                    "type": "object",
                    "description": "Section with mixed descriptions",
                    "properties": {
                        "fieldWithDesc": {
                            "type": "string",
                            "description": "Field with description",
                        },
                        "fieldWithoutDesc": {"type": "string"},
                    },
                }
            },
        }

        result = service._transform_json_schema_to_bedrock_blueprint(schema)

        section1_def = result["definitions"]["Section1"]

        # Field with description should use it as instruction
        field_with_desc = section1_def["properties"]["fieldWithDesc"]
        assert field_with_desc["instruction"] == "Field with description"

        # Field without description should get default instruction
        field_without_desc = section1_def["properties"]["fieldWithoutDesc"]
        assert (
            field_without_desc["instruction"] == "Extract this field from the document"
        )

    def test_transform_ignores_deeply_nested_objects(self, service):
        """Test that deeply nested objects are ignored since BDA doesn't support nested objects."""
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "Deeply-Nested-Doc",
            "type": "object",
            "description": "Document with deeply nested objects that should be ignored",
            "properties": {
                "Level1": {
                    "type": "object",
                    "description": "First level object",
                    "properties": {
                        "simpleField": {
                            "type": "string",
                            "description": "Simple field at level 1",
                        },
                        "Level2": {
                            "type": "object",
                            "description": "Second level nested object - should be ignored",
                            "properties": {
                                "nestedField": {
                                    "type": "string",
                                    "description": "Field in nested object",
                                },
                                "Level3": {
                                    "type": "object",
                                    "description": "Third level nested object - should be ignored",
                                    "properties": {
                                        "deeplyNestedField": {
                                            "type": "string",
                                            "description": "Deeply nested field",
                                        }
                                    },
                                },
                            },
                        },
                    },
                },
                "SimpleTopLevel": {
                    "type": "string",
                    "description": "Simple top-level field",
                },
            },
        }

        result = service._transform_json_schema_to_bedrock_blueprint(schema)

        # Since Level1 has nested complex structures, it should be skipped entirely
        # Only simple top-level properties should remain
        assert "properties" in result

        # Verify simple top-level field is handled correctly
        simple_top_level = result["properties"]["SimpleTopLevel"]
        assert simple_top_level["type"] == "string"
        assert simple_top_level["inferenceType"] == "explicit"
        assert simple_top_level["instruction"] == "Simple top-level field"

        # Level1 should be skipped due to nested complex structures
        assert "Level1" not in result["properties"]

        # No definitions should be created since complex objects are skipped
        assert "definitions" not in result or len(result.get("definitions", {})) == 0

        print(result)
