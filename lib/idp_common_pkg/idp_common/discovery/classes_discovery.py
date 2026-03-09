# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
import json
import logging
import os
from typing import Any, Dict, Optional, cast

import jsonschema
from jsonschema import Draft202012Validator

from idp_common import bedrock, image
from idp_common.config import ConfigurationReader
from idp_common.config.configuration_manager import ConfigurationManager
from idp_common.config.models import IDPConfig
from idp_common.utils.s3util import S3Util

logger = logging.getLogger(__name__)


class ClassesDiscovery:
    def __init__(
        self,
        input_bucket: str,
        input_prefix: str,
        region: Optional[str] = None,
        version: Optional[str] = None,
    ):
        self.input_bucket = input_bucket
        self.input_prefix = input_prefix
        self.region = region or os.environ.get("AWS_REGION")
        self.version = version
        try:
            self.config_reader = ConfigurationReader()
            self.config_manager = ConfigurationManager()
            self.config: IDPConfig = cast(
                IDPConfig,
                self.config_reader.get_merged_configuration(
                    as_model=True, version=self.version
                ),
            )
        except Exception as e:
            logger.error(f"Failed to load configuration from DynamoDB: {e}")
            raise Exception(f"Failed to load configuration from DynamoDB: {str(e)}")

        # Get discovery configuration from IDPConfig model
        self.discovery_config = self.config.discovery

        # Get model configuration for both scenarios
        self.without_gt_config = self.discovery_config.without_ground_truth
        self.with_gt_config = self.discovery_config.with_ground_truth

        # Initialize Bedrock client using the common pattern
        self.bedrock_client = bedrock.BedrockClient(region=self.region)

        return

    def discovery_classes_with_document(self, input_bucket: str, input_prefix: str):
        """
        Create blueprint for document discovery.
        Process document/image:
            1. Extract labels from document
            2. Create Blueprint for the document.
            3. Create/Update blueprint with BDA project.

        Args:
            input_bucket: S3 bucket name
            input_prefix: S3 prefix

        Returns:
            status of blueprint creation

        Raises:
            Exception: If blueprint creation fails
        """
        logger.info(
            f"Creating blueprint for document discovery: s3://{input_bucket}/{input_prefix}"
        )

        try:
            file_in_bytes = S3Util.get_bytes(bucket=input_bucket, key=input_prefix)

            # Extract labels
            file_extension = os.path.splitext(input_prefix)[1].lower()
            # remove the .
            file_extension = file_extension[1:]

            logger.info(f" document len: {len(file_in_bytes)}")

            model_response = self._extract_data_from_document(
                file_in_bytes, file_extension
            )
            logger.info(f"Extracted data from document: {model_response}")

            if model_response is None:
                raise Exception("Failed to extract data from document")

            # Model response is now a JSON Schema
            # No need to transform - it's already in the right format
            current_class = model_response

            # Add the discovered class to the target version's config
            self._merge_and_save_class(current_class)

            return {"status": "SUCCESS"}

        except Exception as e:
            logger.error(
                f"Error processing document {input_prefix}: {e}", exc_info=True
            )
            # Re-raise the exception to be handled by the caller
            raise Exception(f"Failed to process document {input_prefix}: {str(e)}")

    def discovery_classes_with_document_and_ground_truth(
        self, input_bucket: str, input_prefix: str, ground_truth_key: str
    ):
        """
        Create optimized blueprint using ground truth data.

        Args:
            input_bucket: S3 bucket name
            input_prefix: S3 prefix for document
            ground_truth_s3_uri: S3 URI for JSON file with ground truth data

        Returns:
            status of blueprint creation

        Raises:
            Exception: If blueprint creation fails
        """
        logger.info(
            f"Creating optimized blueprint with ground truth: s3://{input_bucket}/{input_prefix}"
        )

        try:
            # Load ground truth data
            ground_truth_data = self._load_ground_truth(input_bucket, ground_truth_key)

            file_in_bytes = S3Util.get_bytes(bucket=input_bucket, key=input_prefix)

            file_extension = os.path.splitext(input_prefix)[1].lower()[1:]

            model_response = self._extract_data_from_document_with_ground_truth(
                file_in_bytes, file_extension, ground_truth_data
            )

            if model_response is None:
                raise Exception("Failed to extract data from document")

            # Model response is now a JSON Schema
            # No need to transform - it's already in the right format
            current_class = model_response

            # Add the discovered class to the target version's config
            self._merge_and_save_class(current_class)

            return {"status": "SUCCESS"}

        except Exception as e:
            logger.error(
                f"Error processing document with ground truth {input_prefix}: {e}",
                exc_info=True,
            )
            raise Exception(f"Failed to process document {input_prefix}: {str(e)}")

    def _merge_and_save_class(self, new_class: Dict[str, Any]) -> None:
        """
        Merge a new discovered class into the target version's configuration.

        This method only adds/updates the discovered class within the target version's
        own class list. It does NOT pull in classes from the default configuration version,
        keeping the target version's classes exactly as the user curated them, plus the
        newly discovered class.

        Steps:
        1. Read existing classes from the target version
        2. Add/update the new discovered class (deduplicate by $id)
        3. Save back to the target version

        Args:
            new_class: The newly discovered class schema to add/update
        """
        # Get class identifier for the new class
        new_class_id = new_class.get("$id") or new_class.get("x-aws-idp-document-type")
        logger.info(f"Merging discovered class: {new_class_id}")

        # Read existing config for the target version (raw, no Pydantic defaults)
        existing_custom = (
            self.config_manager.get_raw_configuration("Config", version=self.version)
            or {}
        )
        custom_classes = list(existing_custom.get("classes", []))
        logger.info(
            f"Found {len(custom_classes)} existing classes in version '{self.version}'"
        )

        # Build class list from existing version classes, deduplicating by ID
        classes_by_id: Dict[str, Dict[str, Any]] = {}
        for cls in custom_classes:
            cls_id = cls.get("$id") or cls.get("x-aws-idp-document-type")
            if cls_id:
                classes_by_id[cls_id] = cls

        # Add/update the new discovered class
        if new_class_id:
            classes_by_id[new_class_id] = new_class

        # Convert back to list
        merged_classes = list(classes_by_id.values())
        logger.info(f"Saving {len(merged_classes)} classes to version '{self.version}'")

        # Save to version config
        existing_custom["classes"] = merged_classes
        self.config_manager.save_raw_configuration(
            "Config", existing_custom, version=self.version
        )

    def _validate_json_schema(self, schema: Dict[str, Any]) -> tuple[bool, str]:
        """
        Validate that the response is a valid JSON Schema.

        Args:
            schema: The schema to validate

        Returns:
            tuple: (is_valid, error_message)
        """
        try:
            # Check required fields for our document schema
            required_fields = ["$schema", "$id", "type", "properties"]
            for field in required_fields:
                if field not in schema:
                    return False, f"Missing required field: {field}"

            # Validate it's a proper JSON Schema
            Draft202012Validator.check_schema(schema)

            # Check our AWS IDP specific requirements
            if "x-aws-idp-document-type" not in schema:
                return False, "Missing x-aws-idp-document-type field"

            if schema.get("type") != "object":
                return False, "Root type must be 'object'"

            if not isinstance(schema.get("properties"), dict):
                return False, "Properties must be an object"

            return True, ""

        except jsonschema.SchemaError as e:
            return False, f"Invalid JSON Schema: {str(e)}"
        except Exception as e:
            return False, f"Validation error: {str(e)}"

    def _remove_duplicates(self, groups):
        for group in groups:
            groupAttributes = []
            groupAttributesArray = []
            if "groupAttributes" not in group:
                continue
            for groupAttribute in group["groupAttributes"]:
                groupAttributeName = groupAttribute.get("name")
                if groupAttributeName in groupAttributes:
                    logger.info(
                        f"ignoring the duplicate attribute {groupAttributeName}"
                    )
                    continue
                groupAttributes.append(groupAttributeName)
                groupAttributesArray.append(groupAttribute)
            group["groupAttributes"] = groupAttributesArray
        return groups

    def _load_ground_truth(self, bucket: str, key: str):
        """Load ground truth JSON data from S3."""
        try:
            ground_truth_bytes = S3Util.get_bytes(bucket=bucket, key=key)
            return json.loads(ground_truth_bytes.decode("utf-8"))
        except Exception as e:
            logger.error(f"Failed to load ground truth from s3://{bucket}/{key}: {e}")
            raise

    def _extract_data_from_document(
        self, document_content, file_extension, max_retries: int = 3
    ):
        """Extract data from document with retry logic for invalid schemas."""
        # Get configuration for without ground truth
        model_id = self.without_gt_config.model_id
        system_prompt = (
            self.without_gt_config.system_prompt
            or "You are an expert in processing forms. Extracting data from images and documents"
        )
        temperature = self.without_gt_config.temperature
        top_p = self.without_gt_config.top_p
        max_tokens = self.without_gt_config.max_tokens

        # Create user prompt with sample format
        user_prompt = (
            self.without_gt_config.user_prompt or self._prompt_classes_discovery()
        )
        sample_format = self._sample_output_format()
        logger.info(f"config prompt is : {self.without_gt_config.user_prompt}")
        logger.info(f"prompt is : {user_prompt}")
        logger.info(f"sample format is : {sample_format}")

        validation_feedback = ""
        for attempt in range(max_retries):
            try:
                # Add validation feedback if this is a retry
                retry_prompt = ""
                if attempt > 0 and validation_feedback:
                    retry_prompt = f"\n\nPREVIOUS ATTEMPT FAILED: {validation_feedback}\nPlease fix the issue and generate a valid JSON Schema.\n\n"

                full_prompt = f"{retry_prompt}{user_prompt}\nFormat the extracted data using the below JSON format:\n{sample_format}"
                # Create content for the user message
                content = self._create_content_list(
                    prompt=full_prompt,
                    document_content=document_content,
                    file_extension=file_extension,
                )

                # Use the configured parameters
                response = self.bedrock_client.invoke_model(
                    model_id=model_id,
                    system_prompt=system_prompt,
                    content=content,
                    temperature=temperature,
                    top_p=top_p,
                    max_tokens=max_tokens,
                    context="ClassesDiscovery",
                )

                # Extract text from response using the common pattern
                content_text = bedrock.extract_text_from_response(response)
                logger.debug(
                    f"Bedrock response (attempt {attempt + 1}): {content_text}"
                )

                # Parse JSON response
                schema = json.loads(content_text)

                # Validate the schema
                is_valid, error_msg = self._validate_json_schema(schema)
                if is_valid:
                    logger.info(
                        f"Successfully generated valid JSON Schema on attempt {attempt + 1}"
                    )
                    return schema
                else:
                    validation_feedback = error_msg
                    logger.warning(
                        f"Invalid schema on attempt {attempt + 1}: {error_msg}"
                    )
                    if attempt == max_retries - 1:
                        logger.error(
                            f"Failed to generate valid schema after {max_retries} attempts"
                        )
                        return None

            except json.JSONDecodeError as e:
                validation_feedback = f"Invalid JSON format: {str(e)}"
                logger.warning(f"JSON parse error on attempt {attempt + 1}: {e}")
                if attempt == max_retries - 1:
                    logger.error(
                        f"Failed to generate valid JSON after {max_retries} attempts"
                    )
                    return None
            except Exception as e:
                logger.error(
                    f"Error extracting data with Bedrock on attempt {attempt + 1}: {e}"
                )
                if attempt == max_retries - 1:
                    return None

        return None

    def _create_content_list(self, prompt, document_content, file_extension):
        """Create content list for BedrockClient API."""
        if file_extension == "pdf":
            content = [
                {
                    "document": {
                        "format": "pdf",
                        "name": "document_messages",
                        "source": {"bytes": document_content},
                    }
                },
                {"text": prompt},
            ]
        else:
            # Prepare image for Bedrock
            image_content = image.prepare_bedrock_image_attachment(document_content)
            content = [
                image_content,
                {"text": prompt},
            ]

        return content

    def _extract_data_from_document_with_ground_truth(
        self, document_content, file_extension, ground_truth_data, max_retries: int = 3
    ):
        """Extract data from document using ground truth as reference with retry logic."""
        # Get configuration for with ground truth
        model_id = self.with_gt_config.model_id
        system_prompt = (
            self.with_gt_config.system_prompt
            or "You are an expert in processing forms. Extracting data from images and documents"
        )
        temperature = self.with_gt_config.temperature
        top_p = self.with_gt_config.top_p
        max_tokens = self.with_gt_config.max_tokens

        # Create enhanced prompt with ground truth
        user_prompt = (
            self.with_gt_config.user_prompt
            or self._prompt_classes_discovery_with_ground_truth(ground_truth_data)
        )

        # If user_prompt contains placeholder, replace it with ground truth
        if "{ground_truth_json}" in user_prompt:
            ground_truth_json = json.dumps(ground_truth_data, indent=2)
            base_prompt = user_prompt.replace("{ground_truth_json}", ground_truth_json)
        else:
            base_prompt = self._prompt_classes_discovery_with_ground_truth(
                ground_truth_data
            )

        sample_format = self._sample_output_format()

        validation_feedback = ""
        for attempt in range(max_retries):
            try:
                # Add validation feedback if this is a retry
                retry_prompt = ""
                if attempt > 0 and validation_feedback:
                    retry_prompt = f"\n\nPREVIOUS ATTEMPT FAILED: {validation_feedback}\nPlease fix the issue and generate a valid JSON Schema.\n\n"

                full_prompt = f"{retry_prompt}{base_prompt}\nFormat the extracted data using the below JSON format:\n{sample_format}"

                # Create content for the user message
                content = self._create_content_list(
                    prompt=full_prompt,
                    document_content=document_content,
                    file_extension=file_extension,
                )

                # Use the configured parameters
                response = self.bedrock_client.invoke_model(
                    model_id=model_id,
                    system_prompt=system_prompt,
                    content=content,
                    temperature=temperature,
                    top_p=top_p,
                    max_tokens=max_tokens,
                    context="ClassesDiscoveryWithGroundTruth",
                )

                # Extract text from response using the common pattern
                content_text = bedrock.extract_text_from_response(response)
                logger.debug(
                    f"Bedrock response with ground truth (attempt {attempt + 1}): {content_text}"
                )

                # Parse JSON response
                schema = json.loads(content_text)

                # Validate the schema
                is_valid, error_msg = self._validate_json_schema(schema)
                if is_valid:
                    logger.info(
                        f"Successfully generated valid JSON Schema with ground truth on attempt {attempt + 1}"
                    )
                    return schema
                else:
                    validation_feedback = error_msg
                    logger.warning(
                        f"Invalid schema with ground truth on attempt {attempt + 1}: {error_msg}"
                    )
                    if attempt == max_retries - 1:
                        logger.error(
                            f"Failed to generate valid schema with ground truth after {max_retries} attempts"
                        )
                        return None

            except json.JSONDecodeError as e:
                validation_feedback = f"Invalid JSON format: {str(e)}"
                logger.warning(
                    f"JSON parse error with ground truth on attempt {attempt + 1}: {e}"
                )
                if attempt == max_retries - 1:
                    logger.error(
                        f"Failed to generate valid JSON with ground truth after {max_retries} attempts"
                    )
                    return None
            except Exception as e:
                logger.error(
                    f"Error extracting data with ground truth on attempt {attempt + 1}: {e}"
                )
                if attempt == max_retries - 1:
                    return None

        return None

    def _prompt_classes_discovery_with_ground_truth(self, ground_truth_data):
        ground_truth_json = json.dumps(ground_truth_data, indent=2)
        sample_output_format = self._sample_output_format()
        return f"""
                        This image contains unstructured data. Analyze the data line by line using the provided ground truth as reference.
                        <GROUND_TRUTH_REFERENCE>
                        {ground_truth_json}
                        </GROUND_TRUTH_REFERENCE>

                        Generate a JSON Schema that describes the document structure using the ground truth as reference:
                        - Use "$schema": "https://json-schema.org/draft/2020-12/schema"
                        - Set "$id" to a short document class name (e.g., "W4", "I-9", "Paystub")
                        - Set "x-aws-idp-document-type" to the same document class name
                        - Set "type": "object"
                        - Add "description" with a brief summary of the document (less than 50 words)

                        For the "properties" object:
                        - Preserve the exact field names and groupings from ground truth
                        - Use nested objects (type: "object") for grouped fields with their own "properties"
                        - For repeating/table data, use type: "array" with "items" containing object schema
                        - Each field should have appropriate "type" based on ground truth values
                        - Add "description" for each field with extraction instructions and location hints
                        
                        Nesting Groups:
                        - Do not nest the groups i.e. groups within groups.
                        - All groups should be directly associated under main "properties".
                        

                        Match field names, data types, and structure from the ground truth reference.
                        Image may contain multiple pages, process all pages.
                        Do not extract the actual values, only the schema structure.

                        Return the extracted schema in the exact JSON Schema format below:
                        {sample_output_format}
                        """

    def _prompt_classes_discovery(self):
        sample_output_format = self._sample_output_format()
        return f"""
                        This image contains forms data. Analyze the form line by line.
                        Image may contains multiple pages, process all the pages.
                        Form may contain multiple name value pair in one line.
                        Extract all the names in the form including the name value pair which doesn't have value.

                        Generate a JSON Schema that describes the document structure:
                        - Use "$schema": "https://json-schema.org/draft/2020-12/schema"
                        - Set "$id" to a short document class name (e.g., "W4", "I-9", "Paystub")
                        - Set "x-aws-idp-document-type" to the same document class name
                        - Set "type": "object"
                        - Add "description" with a brief summary of the document (less than 50 words)

                        For the "properties" object:
                        - Group related fields as objects (type: "object") with their own "properties"
                        - For repeating/table data, use type: "array" with "items" containing object schema
                        - Each field should have "type" (string, number, boolean, etc.) and "description"
                        - Field names should be less than 30 characters, use camelCase or snake_case, name should not start with number and name should not have special characters.
                        - Field descriptions should include location hints (box number, line number, section)

                        Nesting Groups:
                        - Do not nest the groups i.e. groups within groups.
                        - All groups should be directly associated under main "properties".
                        
                        Do not extract the actual values, only the schema structure.
                        Return the extracted schema in the exact JSON Schema format below:
                        {sample_output_format}
                    """

    def _sample_output_format(self):
        return """
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id" : "Form-1040",
            "x-aws-idp-document-type" : "Form-1040",
            "type": "object",
            "description" : "Brief summary of the document",
            "properties" : {
                "PersonalInformation": {
                    "type": "object",
                    "description" : "Personal information of Tax payer",
                    "properties" : {
                        "FirstName": {
                            "type": "string",
                            "description" : "First Name of Taxpayer"
                        },
                        "Age": {
                            "type": "number",
                            "description" : "Age of Taxpayer"
                        }
                    }
                },
                "Dependents": {
                    "type": "array",
                    "description" : "Dependents of taxpayer",
                    "items": {
                        "type": "object",
                        "properties" : {
                            "FirstName": {
                                "type": "string",
                                "description" : "Dependent first name"
                            },
                            "Age": {
                                "type": "number",
                                "description" : "Dependent Age"
                            }
                        }
                    }
                }
            }
        }
        """
