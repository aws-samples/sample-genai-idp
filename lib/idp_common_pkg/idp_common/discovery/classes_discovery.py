# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
import json
import logging
import os
from typing import Optional

from idp_common import bedrock, image
from idp_common.config import ConfigurationReader
from idp_common.config.configuration_manager import ConfigurationManager
from idp_common.utils.s3util import S3Util

logger = logging.getLogger(__name__)


class ClassesDiscovery:
    def __init__(
        self,
        input_bucket: str,
        input_prefix: str,
        region: Optional[str] = None,
    ):
        self.input_bucket = input_bucket
        self.input_prefix = input_prefix
        self.region = region or os.environ.get("AWS_REGION")

        try:
            self.config_reader = ConfigurationReader()
            self.config_manager = ConfigurationManager()
            self.config = self.config_reader.get_merged_configuration()
        except Exception as e:
            logger.error(f"Failed to load configuration from DynamoDB: {e}")
            raise Exception(f"Failed to load configuration from DynamoDB: {str(e)}")

        # Get discovery configuration
        self.discovery_config = self.config.get("discovery", {})

        # Get model configuration for both scenarios
        self.without_gt_config = self.discovery_config.get("without_ground_truth", {})
        self.with_gt_config = self.discovery_config.get("with_ground_truth", {})

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

            document_class = model_response.pop("document_class")
            document_description = model_response.pop("document_description")
            # Add/Update custom configuration
            current_class = {}
            current_class["name"] = document_class
            current_class["description"] = document_description
            groups = model_response.get("groups")
            # remove duplicates
            groups = self._remove_duplicates(groups)
            current_class["attributes"] = groups

            custom_item = self.config_manager.get_configuration("Custom")
            classes = []
            if custom_item and "classes" in custom_item:
                classes = custom_item["classes"]
                for class_obj in classes:
                    if class_obj["name"] == current_class["name"]:
                        classes.remove(class_obj)
                        break
            classes.append(current_class)

            # Update configuration with new classes
            config_data = {"classes": classes}
            self.config_manager.update_configuration("Custom", config_data)

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

            document_class = model_response.pop("document_class")
            document_description = model_response.pop("document_description")

            # Add/Update custom configuration
            current_class = {}
            current_class["name"] = document_class
            current_class["description"] = document_description
            groups = model_response.get("groups")
            # remove duplicates
            groups = self._remove_duplicates(groups)
            current_class["attributes"] = groups

            custom_item = self.config_manager.get_configuration("Custom")
            classes = []
            if custom_item and "classes" in custom_item:
                classes = custom_item["classes"]
                for class_obj in classes:
                    if class_obj["name"] == current_class["name"]:
                        classes.remove(class_obj)
                        break
            classes.append(current_class)

            # Update configuration with new classes
            config_data = {"classes": classes}
            self.config_manager.update_configuration("Custom", config_data)

            return {"status": "SUCCESS"}

        except Exception as e:
            logger.error(
                f"Error processing document with ground truth {input_prefix}: {e}",
                exc_info=True,
            )
            raise Exception(f"Failed to process document {input_prefix}: {str(e)}")

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

    def _extract_data_from_document(self, document_content, file_extension):
        try:
            # Get configuration for without ground truth
            model_id = self.without_gt_config.get("model_id", "eu.amazon.nova-pro-v1:0")
            system_prompt = self.without_gt_config.get(
                "system_prompt",
                "You are an expert in processing forms. Extracting data from images and documents",
            )
            temperature = self.without_gt_config.get("temperature", 1.0)
            top_p = self.without_gt_config.get("top_p", 0.1)
            max_tokens = self.without_gt_config.get("max_tokens", 10000)

            # Create user prompt with sample format
            user_prompt = self.without_gt_config.get(
                "user_prompt", self._prompt_classes_discovery()
            )
            sample_format = self.discovery_config.get("output_format", {}).get(
                "sample_json", self._sample_output_format()
            )
            full_prompt = f"{user_prompt}\nFormat the extracted data using the below JSON format:\n{sample_format}"

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

            logger.debug(f"Bedrock response: {content_text}")
            return json.loads(content_text)

        except Exception as e:
            logger.error(f"Error extracting data with Bedrock: {e}")
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
        self, document_content, file_extension, ground_truth_data
    ):
        """Extract data from document using ground truth as reference."""
        try:
            # Get configuration for with ground truth
            model_id = self.with_gt_config.get("model_id", "eu.amazon.nova-pro-v1:0")
            system_prompt = self.with_gt_config.get(
                "system_prompt",
                "You are an expert in processing forms. Extracting data from images and documents",
            )
            temperature = self.with_gt_config.get("temperature", 1.0)
            top_p = self.with_gt_config.get("top_p", 0.1)
            max_tokens = self.with_gt_config.get("max_tokens", 10000)

            # Create enhanced prompt with ground truth
            user_prompt = self.with_gt_config.get(
                "user_prompt",
                self._prompt_classes_discovery_with_ground_truth(ground_truth_data),
            )

            # If user_prompt contains placeholder, replace it with ground truth
            if "{ground_truth_json}" in user_prompt:
                ground_truth_json = json.dumps(ground_truth_data, indent=2)
                prompt = user_prompt.replace("{ground_truth_json}", ground_truth_json)
            else:
                prompt = self._prompt_classes_discovery_with_ground_truth(
                    ground_truth_data
                )

            sample_format = self.discovery_config.get("output_format", {}).get(
                "sample_json", self._sample_output_format()
            )
            full_prompt = f"{prompt}\nFormat the extracted data using the below JSON format:\n{sample_format}"

            # Create content for the user message
            content = self._create_content_list(
                prompt=full_prompt,
                document_content=document_content,
                file_extension=file_extension,
            )

            # Use the configured parameters - Fix: use invoke_model not direct call
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

            logger.debug(f"Bedrock response with ground truth: {content_text}")
            return json.loads(content_text)

        except Exception as e:
            logger.error(f"Error extracting data with Bedrock using ground truth: {e}")
            return None

    def _prompt_classes_discovery_with_ground_truth(self, ground_truth_data):
        ground_truth_json = json.dumps(ground_truth_data, indent=2)
        sample_output_format = self._sample_output_format()
        return f"""
                        This image contains unstructured data. Analyze the data line by line using the provided ground truth as reference.                        
                        <GROUND_TRUTH_REFERENCE>
                        {ground_truth_json}
                        </GROUND_TRUTH_REFERENCE>
                        Ground truth reference JSON has the fields we are interested in extracting from the document/image. Use the ground truth to optimize field extraction. Match field names, data types, and groupings from the reference.
                        Image may contain multiple pages, process all pages.
                        Extract all field names including those without values.
                        Do not change the group name and field name from ground truth in the extracted data json.
                        Add field_description field for every field which will contain instruction to LLM to extract the field data from the image/document. Add data_type field for every field. 
                        Add two fields document_class and document_description. 
                        For document_class generate a short name based on the document content like W4, I-9, Paystub. 
                        For document_description generate a description about the document in less than 50 words.
                        If the group repeats and follows table format, update the attributeType as "list".                         
                        Do not extract the values.
                        Format the extracted data using the below JSON format:
                        Format the extracted groups and fields using the below JSON format:
                        {sample_output_format}
                        """

    def _prompt_classes_discovery(self):
        sample_output_format = self._sample_output_format()
        return f"""
                        This image contains forms data. Analyze the form line by line.
                        Image may contains multiple pages, process all the pages. 
                        Form may contain multiple name value pair in one line. 
                        Extract all the names in the form including the name value pair which doesn't have value. 
                        Organize them into groups, extract field_name, data_type and field description
                        Field_name should be less than 60 characters, should not have space use '-' instead of space.
                        field_description is a brief description of the field and the location of the field like box number or line number in the form and section of the form.
                        Field_name should be unique within the group.
                        Add two fields document_class and document_description. 
                        For document_class generate a short name based on the document content like W4, I-9, Paystub. 
                        For document_description generate a description about the document in less than 50 words. 

                        Group the fields based on the section they are grouped in the form. Group should have attributeType as "group".
                        If the group repeats and follows table format, update the attributeType as "list".
                        Do not extract the values.
                        Return the extracted data in JSON format.
                        Format the extracted data using the below JSON format:
                        Format the extracted groups and fields using the below JSON format:
                        {sample_output_format}
                    """

    def _sample_output_format(self):
        return """
        {
            "document_class" : "Form-1040",
            "document_description" : "Brief summary of the document",
            "groups" : [
                {
                    "name" : "PersonalInformation",
                    "description" : "Personal information of Tax payer",
                    "attributeType" : "group",
                    "groupAttributes" : [
                        {
                            "name": "FirstName",
                            "dataType" : "string",
                            "description" : "First Name of Taxpayer"
                        },
                        {
                            "name": "Age",
                            "dataType" : "number",
                            "description" : "Age of Taxpayer"
                        }
                    ]
                },
                {
                    "name" : "Dependents",
                    "description" : "Dependents of taxpayer",
                    "attributeType" : "list",
                    "listItemTemplate": {
                        "itemAttributes" : [
                            {
                                "name": "FirstName",
                                "dataType" : "string",
                                "description" : "Dependent first name"
                            },
                            {
                                "name": "Age",
                                "dataType" : "number",
                                "description" : "Dependent Age"
                            }
                        ]
                    }
                }
            ]
        }
        """
