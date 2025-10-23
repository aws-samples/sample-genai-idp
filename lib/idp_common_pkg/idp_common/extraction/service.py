# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Extraction service for documents using LLMs.

This module provides a service for extracting fields and values from documents
using LLMs, with support for text and image content.
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field, create_model

from idp_common import bedrock, image, metrics, s3, utils
from idp_common.models import Document

# Conditional import for agentic extraction (requires Python 3.10+ dependencies)
try:
    from idp_common.extraction.agentic_idp import structured_output

    AGENTIC_AVAILABLE = True
except ImportError:
    AGENTIC_AVAILABLE = False
from idp_common.utils import extract_json_from_text

logger = logging.getLogger(__name__)


logger = logging.getLogger(__name__)


class ExtractionService:
    """Service for extracting fields from documents using LLMs."""

    def __init__(self, region: str = None, config: Dict[str, Any] = None):
        """
        Initialize the extraction service.

        Args:
            region: AWS region for Bedrock
            config: Configuration dictionary
        """
        self.config = config or {}
        self.region = (
            region or self.config.get("region") or os.environ.get("AWS_REGION")
        )

        # Get model_id from config for logging
        model_id = self.config.get("model_id") or self.config.get("extraction", {}).get(
            "model"
        )
        logger.info(f"Initialized extraction service with model {model_id}")

    def _get_class_attributes(self, class_label: str) -> List[Dict[str, Any]]:
        """
        Get attributes for a specific document class from configuration.

        Args:
            class_label: The document class name

        Returns:
            List of attribute configurations
        """
        classes_config = self.config.get("classes", [])
        class_config = next(
            (
                class_obj
                for class_obj in classes_config
                if class_obj.get("name", "").lower() == class_label.lower()
            ),
            None,
        )
        if class_config is None:
            return []

        # Get attributes and ensure it's always a list, never None
        attributes = class_config.get("attributes", [])
        return attributes if attributes is not None else []

    def _create_pydantic_model_from_attributes(
        self, class_label: str, attributes: List[Dict[str, Any]]
    ) -> Type[BaseModel]:
        """
        Dynamically create a Pydantic model from configuration attributes.

        Args:
            class_label: The document class name
            attributes: List of attribute configurations

        Returns:
            Dynamically created Pydantic model class
        """
        if not attributes:
            # Return a minimal model for empty attributes
            return create_model(f"{class_label}Model", __base__=BaseModel)

        fields = {}

        for attr in attributes:
            attr_name = attr.get("name", "")
            attr_description = attr.get("description", "")
            attr_type = attr.get("attributeType", "simple")

            if not attr_name:
                continue

            # Determine field type and default
            if attr_type == "group":
                # For group attributes, create nested model
                group_attributes = attr.get("groupAttributes", [])
                if group_attributes:
                    nested_model = self._create_pydantic_model_from_attributes(
                        f"{class_label}_{attr_name}", group_attributes
                    )
                    fields[attr_name] = (
                        Optional[nested_model],
                        Field(None, description=attr_description),
                    )
                else:
                    fields[attr_name] = (
                        Optional[str],
                        Field(None, description=attr_description),
                    )

            elif attr_type == "list":
                # For list attributes, create list of items
                list_template = attr.get("listItemTemplate", {})
                item_attributes = list_template.get("itemAttributes", [])

                if item_attributes:
                    item_model = self._create_pydantic_model_from_attributes(
                        f"{class_label}_{attr_name}_Item", item_attributes
                    )
                    fields[attr_name] = (
                        Optional[List[item_model]],
                        Field(None, description=attr_description),
                    )
                else:
                    fields[attr_name] = (
                        Optional[List[str]],
                        Field(None, description=attr_description),
                    )

            else:
                # Simple attribute - default to optional string
                fields[attr_name] = (
                    Optional[str],
                    Field(None, description=attr_description),
                )

        # Create the model with proper name
        model_name = f"{class_label.replace(' ', '').replace('-', '_')}ExtractionModel"
        return create_model(model_name, **fields, __base__=BaseModel)

    def _format_attribute_descriptions(self, attributes: List[Dict[str, Any]]) -> str:
        """
        Format attribute descriptions for the prompt, supporting nested structures.

        Args:
            attributes: List of attribute configurations

        Returns:
            Formatted attribute descriptions as a string
        """
        # Defensive coding: handle None input
        if attributes is None:
            return ""

        formatted_lines = []

        for attr in attributes:
            attr_name = attr.get("name", "")
            attr_description = attr.get("description", "")
            attr_type = attr.get("attributeType", "simple")

            if attr_type == "group":
                # Handle group attributes with nested groupAttributes
                formatted_lines.append(f"{attr_name}  \t[ {attr_description} ]")
                group_attributes = attr.get("groupAttributes", [])
                for group_attr in group_attributes:
                    group_name = group_attr.get("name", "")
                    group_desc = group_attr.get("description", "")
                    formatted_lines.append(f"  - {group_name}  \t[ {group_desc} ]")

            elif attr_type == "list":
                # Handle list attributes with listItemTemplate
                formatted_lines.append(f"{attr_name}  \t[ {attr_description} ]")
                list_template = attr.get("listItemTemplate", {})
                item_description = list_template.get("itemDescription", "")
                if item_description:
                    formatted_lines.append(f"  Each item: {item_description}")

                item_attributes = list_template.get("itemAttributes", [])
                for item_attr in item_attributes:
                    item_name = item_attr.get("name", "")
                    item_desc = item_attr.get("description", "")
                    formatted_lines.append(f"  - {item_name}  \t[ {item_desc} ]")

            else:
                # Handle simple attributes (default case for backward compatibility)
                formatted_lines.append(f"{attr_name}  \t[ {attr_description} ]")

        return "\n".join(formatted_lines)

    def _create_dynamic_model_from_attributes(
        self, attributes: List[Dict[str, Any]], class_label: str
    ) -> Type[BaseModel]:
        """
        Create a dynamic Pydantic model from configuration attributes.

        Args:
            attributes: List of attribute configurations from the class config
            class_label: The document class name (for model naming)

        Returns:
            Dynamically created Pydantic model class
        """
        if not attributes:
            # Create a simple model with just a raw_output field if no attributes defined
            return create_model(
                f"{class_label}ExtractionModel",
                raw_output=(
                    Optional[str],
                    Field(None, description="Raw extraction output"),
                ),
            )

        model_fields = {}

        for attr in attributes:
            attr_name = attr.get("name", "").replace(" ", "_").replace("-", "_")
            if not attr_name:
                continue

            attr_description = attr.get("description", "")
            attr_type = attr.get("attributeType", "simple")

            if attr_type == "group":
                # Handle group attributes - create nested model
                group_fields = {}
                group_attributes = attr.get("groupAttributes", [])

                for group_attr in group_attributes:
                    group_name = (
                        group_attr.get("name", "").replace(" ", "_").replace("-", "_")
                    )
                    if group_name:
                        group_desc = group_attr.get("description", "")
                        group_fields[group_name] = (
                            Optional[str],
                            Field(None, description=group_desc),
                        )

                if group_fields:
                    # Create nested model for the group
                    nested_model = create_model(
                        f"{attr_name.title()}Group", **group_fields
                    )
                    model_fields[attr_name] = (
                        Optional[nested_model],
                        Field(None, description=attr_description),
                    )
                else:
                    # Fallback to optional string if no group attributes
                    model_fields[attr_name] = (
                        Optional[str],
                        Field(None, description=attr_description),
                    )

            elif attr_type == "list":
                # Handle list attributes - create list of nested items
                list_template = attr.get("listItemTemplate", {})
                item_attributes = list_template.get("itemAttributes", [])

                if item_attributes:
                    # Create model for list items
                    item_fields = {}
                    for item_attr in item_attributes:
                        item_name = (
                            item_attr.get("name", "")
                            .replace(" ", "_")
                            .replace("-", "_")
                        )
                        if item_name:
                            item_desc = item_attr.get("description", "")
                            item_fields[item_name] = (
                                Optional[str],
                                Field(None, description=item_desc),
                            )

                    if item_fields:
                        # Create nested model for list items
                        item_model = create_model(
                            f"{attr_name.title()}Item", **item_fields
                        )
                        model_fields[attr_name] = (
                            Optional[List[item_model]],
                            Field(None, description=attr_description),
                        )
                    else:
                        # Fallback to list of strings
                        model_fields[attr_name] = (
                            Optional[List[str]],
                            Field(None, description=attr_description),
                        )
                else:
                    # Simple list of strings
                    model_fields[attr_name] = (
                        Optional[List[str]],
                        Field(None, description=attr_description),
                    )

            else:
                # Handle simple attributes (default case)
                model_fields[attr_name] = (
                    Optional[str],
                    Field(None, description=attr_description),
                )

        # Add a fallback field for any additional data
        model_fields["additional_data"] = (
            Optional[Dict[str, Any]],
            Field(
                None,
                description="Any additional extracted data not covered by specific fields",
            ),
        )

        # Create the dynamic model
        model_name = f"{class_label.replace(' ', '').replace('-', '')}ExtractionModel"
        dynamic_model = create_model(model_name, **model_fields)

        logger.info(
            f"Created dynamic Pydantic model '{model_name}' with {len(model_fields)} fields"
        )

        return dynamic_model

    def _prepare_prompt_from_template(
        self,
        prompt_template: str,
        substitutions: Dict[str, str],
        required_placeholders: List[str] = None,
    ) -> str:
        """
        Prepare prompt from template by replacing placeholders with values.

        Args:
            prompt_template: The prompt template with placeholders
            substitutions: Dictionary of placeholder values
            required_placeholders: List of placeholder names that must be present in the template

        Returns:
            String with placeholders replaced by values

        Raises:
            ValueError: If a required placeholder is missing from the template
        """
        from idp_common.bedrock import format_prompt

        return format_prompt(prompt_template, substitutions, required_placeholders)

    def _build_content_with_or_without_image_placeholder(
        self,
        prompt_template: str,
        document_text: str,
        class_label: str,
        attribute_descriptions: str,
        image_content: Any = None,
    ) -> List[Dict[str, Any]]:
        """
        Build content array, automatically deciding whether to use image placeholder processing.

        If the prompt contains {DOCUMENT_IMAGE}, the image will be inserted at that location.
        If the prompt does NOT contain {DOCUMENT_IMAGE}, the image will NOT be included at all.

        Args:
            prompt_template: The prompt template that may contain {DOCUMENT_IMAGE}
            document_text: The document text content
            class_label: The document class label
            attribute_descriptions: Formatted attribute names and descriptions
            image_content: Optional image content to insert (only used when {DOCUMENT_IMAGE} is present)

        Returns:
            List of content items with text and image content properly ordered based on presence of placeholder
        """
        if "{DOCUMENT_IMAGE}" in prompt_template:
            return self._build_content_with_image_placeholder(
                prompt_template,
                document_text,
                class_label,
                attribute_descriptions,
                image_content,
            )
        else:
            return self._build_content_without_image_placeholder(
                prompt_template,
                document_text,
                class_label,
                attribute_descriptions,
                image_content,
            )

    def _build_content_with_image_placeholder(
        self,
        prompt_template: str,
        document_text: str,
        class_label: str,
        attribute_descriptions: str,
        image_content: Any = None,
    ) -> List[Dict[str, Any]]:
        """
        Build content array with image inserted at DOCUMENT_IMAGE placeholder if present.

        Args:
            prompt_template: The prompt template that may contain {DOCUMENT_IMAGE}
            document_text: The document text content
            class_label: The document class label
            attribute_descriptions: Formatted attribute names and descriptions
            image_content: Optional image content to insert

        Returns:
            List of content items with text and image content properly ordered
        """
        # Split the prompt at the DOCUMENT_IMAGE placeholder
        parts = prompt_template.split("{DOCUMENT_IMAGE}")

        if len(parts) != 2:
            logger.warning(
                "Invalid DOCUMENT_IMAGE placeholder usage, falling back to standard processing"
            )
            # Fallback to standard processing
            return self._build_content_without_image_placeholder(
                prompt_template,
                document_text,
                class_label,
                attribute_descriptions,
                image_content,
            )

        # Process the parts before and after the image placeholder
        before_image = self._prepare_prompt_from_template(
            parts[0],
            {
                "DOCUMENT_TEXT": document_text,
                "DOCUMENT_CLASS": class_label,
                "ATTRIBUTE_NAMES_AND_DESCRIPTIONS": attribute_descriptions,
            },
            required_placeholders=[],  # Don't enforce required placeholders for partial templates
        )

        after_image = self._prepare_prompt_from_template(
            parts[1],
            {
                "DOCUMENT_TEXT": document_text,
                "DOCUMENT_CLASS": class_label,
                "ATTRIBUTE_NAMES_AND_DESCRIPTIONS": attribute_descriptions,
            },
            required_placeholders=[],  # Don't enforce required placeholders for partial templates
        )

        # Build content array with image in the middle
        content = []

        # Add the part before the image
        if before_image.strip():
            content.append({"text": before_image})

        # Add the image if available
        if image_content:
            if isinstance(image_content, list):
                # Multiple images (limit to 20 as per Bedrock constraints)
                if len(image_content) > 20:
                    logger.warning(
                        f"Found {len(image_content)} images, truncating to 20 due to Bedrock constraints. "
                        f"{len(image_content) - 20} images will be dropped."
                    )
                for img in image_content[:20]:
                    content.append(image.prepare_bedrock_image_attachment(img))
            else:
                # Single image
                content.append(image.prepare_bedrock_image_attachment(image_content))

        # Add the part after the image
        if after_image.strip():
            content.append({"text": after_image})

        return content

    def _build_content_without_image_placeholder(
        self,
        prompt_template: str,
        document_text: str,
        class_label: str,
        attribute_descriptions: str,
        image_content: Any = None,
    ) -> List[Dict[str, Any]]:
        """
        Build content array without DOCUMENT_IMAGE placeholder (standard processing).

        Note: This method does NOT attach the image content when no placeholder is present.

        Args:
            prompt_template: The prompt template
            document_text: The document text content
            class_label: The document class label
            attribute_descriptions: Formatted attribute names and descriptions
            image_content: Optional image content (not used when no placeholder is present)

        Returns:
            List of content items with text content only (no image)
        """
        # Prepare the full prompt
        task_prompt = self._prepare_prompt_from_template(
            prompt_template,
            {
                "DOCUMENT_TEXT": document_text,
                "DOCUMENT_CLASS": class_label,
                "ATTRIBUTE_NAMES_AND_DESCRIPTIONS": attribute_descriptions,
            },
            required_placeholders=[],
        )

        content = [{"text": task_prompt}]

        # No longer adding image content when no placeholder is present

        return content

    def _build_content_with_few_shot_examples(
        self,
        task_prompt_template: str,
        document_text: str,
        class_label: str,
        attribute_descriptions: str,
        image_content: Any = None,
    ) -> List[Dict[str, Any]]:
        """
        Build content array with few-shot examples inserted at the FEW_SHOT_EXAMPLES placeholder.
        Also supports DOCUMENT_IMAGE placeholder for image positioning.

        Args:
            task_prompt_template: The task prompt template containing {FEW_SHOT_EXAMPLES}
            document_text: The document text content
            class_label: The document class label
            attribute_descriptions: Formatted attribute names and descriptions
            image_content: Optional image content to insert

        Returns:
            List of content items with text and image content properly ordered
        """
        # Split the task prompt at the FEW_SHOT_EXAMPLES placeholder
        parts = task_prompt_template.split("{FEW_SHOT_EXAMPLES}")

        if len(parts) != 2:
            # Fallback to regular prompt processing if placeholder not found or malformed
            return self._build_content_with_or_without_image_placeholder(
                task_prompt_template,
                document_text,
                class_label,
                attribute_descriptions,
                image_content,
            )

        # Process each part using the unified function
        before_examples_content = self._build_content_with_or_without_image_placeholder(
            parts[0], document_text, class_label, attribute_descriptions, image_content
        )

        # Only pass image_content if it wasn't already used in the first part
        image_for_second_part = (
            None if "{DOCUMENT_IMAGE}" in parts[0] else image_content
        )
        after_examples_content = self._build_content_with_or_without_image_placeholder(
            parts[1],
            document_text,
            class_label,
            attribute_descriptions,
            image_for_second_part,
        )

        # Build content array
        content = []

        # Add the part before examples (may include image if DOCUMENT_IMAGE was in the first part)
        content.extend(before_examples_content)

        # Add few-shot examples from config for this specific class
        examples_content = self._build_few_shot_examples_content(class_label)
        content.extend(examples_content)

        # Add the part after examples (may include image if DOCUMENT_IMAGE was in the second part)
        content.extend(after_examples_content)

        # No longer appending image content when no placeholder is found

        return content

    def _build_few_shot_examples_content(
        self, class_label: str
    ) -> List[Dict[str, Any]]:
        """
        Build content items for few-shot examples from the configuration for a specific class.

        Args:
            class_label: The document class label to get examples for

        Returns:
            List of content items containing text and image content for examples
        """
        content = []
        classes = self.config.get("classes", [])

        # Find the specific class that matches the class_label
        target_class = None
        for class_obj in classes:
            if class_obj.get("name", "").lower() == class_label.lower():
                target_class = class_obj
                break

        if not target_class:
            logger.warning(
                f"No class found matching '{class_label}' for few-shot examples"
            )
            return content

        # Get examples from the target class only
        examples = target_class.get("examples", [])
        for example in examples:
            attributes_prompt = example.get("attributesPrompt")

            # Only process this example if it has a non-empty attributesPrompt
            if not attributes_prompt or not attributes_prompt.strip():
                logger.info(
                    f"Skipping example with empty attributesPrompt: {example.get('name')}"
                )
                continue

            content.append({"text": attributes_prompt})

            image_path = example.get("imagePath")
            if image_path:
                try:
                    # Load image content from the path

                    from idp_common import image, s3

                    # Get list of image files from the path (supports directories/prefixes)
                    image_files = self._get_image_files_from_path(image_path)

                    # Process each image file
                    for image_file_path in image_files:
                        try:
                            # Load image content
                            if image_file_path.startswith("s3://"):
                                # Direct S3 URI
                                image_content = s3.get_binary_content(image_file_path)
                            else:
                                # Local file
                                with open(image_file_path, "rb") as f:
                                    image_content = f.read()

                            # Prepare image content for Bedrock
                            image_attachment = image.prepare_bedrock_image_attachment(
                                image_content
                            )
                            content.append(image_attachment)

                        except Exception as e:
                            logger.warning(
                                f"Failed to load image {image_file_path}: {e}"
                            )
                            continue

                except Exception as e:
                    raise ValueError(
                        f"Failed to load example images from {image_path}: {e}"
                    )

        return content

    def _get_image_files_from_path(self, image_path: str) -> List[str]:
        """
        Get list of image files from a path that could be a single file, directory, or S3 prefix.

        Args:
            image_path: Path to image file, directory, or S3 prefix

        Returns:
            List of image file paths/URIs sorted by filename
        """
        import os

        from idp_common import s3

        # Handle S3 URIs
        if image_path.startswith("s3://"):
            # Check if it's a direct file or a prefix
            if image_path.endswith(
                (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp")
            ):
                # Direct S3 file
                return [image_path]
            else:
                # S3 prefix - list all images
                return s3.list_images_from_path(image_path)
        else:
            # Handle local paths
            config_bucket = os.environ.get("CONFIGURATION_BUCKET")
            root_dir = os.environ.get("ROOT_DIR")

            if config_bucket:
                # Use environment bucket with imagePath as key
                s3_uri = f"s3://{config_bucket}/{image_path}"

                # Check if it's a direct file or a prefix
                if image_path.endswith(
                    (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp")
                ):
                    # Direct S3 file
                    return [s3_uri]
                else:
                    # S3 prefix - list all images
                    return s3.list_images_from_path(s3_uri)
            elif root_dir:
                # Use relative path from ROOT_DIR
                full_path = os.path.join(root_dir, image_path)
                full_path = os.path.normpath(full_path)

                if os.path.isfile(full_path):
                    # Single local file
                    return [full_path]
                elif os.path.isdir(full_path):
                    # Local directory - list all images
                    return s3.list_images_from_path(full_path)
                else:
                    # Path doesn't exist
                    logger.warning(f"Image path does not exist: {full_path}")
                    return []
            else:
                raise ValueError(
                    "No CONFIGURATION_BUCKET or ROOT_DIR set. Cannot read example images from local filesystem."
                )

    def _make_json_serializable(self, obj):
        """
        Recursively convert any object to a JSON-serializable format.

        Args:
            obj: Object to make JSON serializable

        Returns:
            JSON-serializable version of the object
        """
        from enum import Enum

        if isinstance(obj, dict):
            return {
                key: self._make_json_serializable(value) for key, value in obj.items()
            }
        elif isinstance(obj, (list, tuple)):
            return [self._make_json_serializable(item) for item in obj]
        elif isinstance(obj, Enum):
            return obj.value
        elif hasattr(obj, "__dict__"):
            # Handle custom objects by converting to dict
            return self._make_json_serializable(obj.__dict__)
        elif hasattr(obj, "to_dict"):
            # Handle objects with to_dict method
            return self._make_json_serializable(obj.to_dict())
        elif isinstance(obj, bytes):
            # Convert bytes to base64 string or placeholder
            return f"<bytes_object_{len(obj)}_bytes>"
        else:
            try:
                # Test if it's already JSON serializable
                json.dumps(obj)
                return obj
            except (TypeError, ValueError):
                # Convert non-serializable objects to string representation
                return str(obj)

    def _convert_image_bytes_to_uris_in_content(
        self, content: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Convert image bytes to URIs in content array for JSON serialization.

        Args:
            content: Content array that may contain image objects with bytes

        Returns:
            Content array with image URIs instead of bytes
        """
        converted_content = []

        for item in content:
            if "image" in item and isinstance(item["image"], dict):
                # Extract image URI if it exists, or use placeholder
                if "source" in item["image"] and "bytes" in item["image"]["source"]:
                    # This is a bytes-based image - replace with URI reference
                    # In practice, we need to store these bytes somewhere accessible
                    # For now, we'll use a placeholder that indicates bytes were present
                    converted_item = {
                        "image_uri": f"<image_bytes_placeholder_{len(converted_content)}>"
                    }
                else:
                    # Keep other image formats as-is
                    converted_item = item.copy()
            else:
                # Keep non-image items as-is
                converted_item = item.copy()

            converted_content.append(converted_item)

        return converted_content

    def _convert_image_uris_to_bytes_in_content(
        self, content: List[Dict[str, Any]], original_images: List[Any]
    ) -> List[Dict[str, Any]]:
        """
        Convert image URIs back to bytes in content array after Lambda processing.

        Args:
            content: Content array from Lambda that may contain image URIs
            original_images: Original image data to restore

        Returns:
            Content array with image bytes restored
        """
        converted_content = []
        image_index = 0

        for item in content:
            if "image_uri" in item:
                # Convert image URI back to bytes format
                if image_index < len(original_images):
                    # Restore original image bytes
                    converted_item = image.prepare_bedrock_image_attachment(
                        original_images[image_index]
                    )
                    image_index += 1
                else:
                    # Skip if no original image data
                    logger.warning(
                        "No original image data available for URI conversion"
                    )
                    continue
            elif "image" in item:
                # Keep existing image objects as-is
                converted_item = item.copy()
            else:
                # Keep non-image items as-is
                converted_item = item.copy()

            converted_content.append(converted_item)

        return converted_content

    def _invoke_custom_prompt_lambda(
        self, lambda_arn: str, payload: dict, original_images: List[Any] = None
    ) -> dict:
        """
        Invoke custom prompt generator Lambda function with JSON-serializable payload.

        Args:
            lambda_arn: ARN of the Lambda function to invoke
            payload: Payload to send to Lambda function (must be JSON serializable)
            original_images: Original image data for restoration after Lambda processing

        Returns:
            Dict containing system_prompt and task_prompt_content with images restored

        Raises:
            Exception: If Lambda invocation fails or returns invalid response
        """
        import boto3

        lambda_client = boto3.client("lambda", region_name=self.region)

        try:
            logger.info(f"Invoking custom prompt Lambda: {lambda_arn}")
            response = lambda_client.invoke(
                FunctionName=lambda_arn,
                InvocationType="RequestResponse",
                Payload=json.dumps(payload),
            )

            if response.get("FunctionError"):
                error_payload = response.get("Payload", b"").read().decode()
                error_msg = f"Custom prompt Lambda failed: {error_payload}"
                logger.error(error_msg)
                raise Exception(error_msg)

            result = json.loads(response["Payload"].read())
            logger.info("Custom prompt Lambda invoked successfully")

            # Validate response structure
            if not isinstance(result, dict):
                error_msg = f"Custom prompt Lambda returned invalid response format: expected dict, got {type(result)}"
                logger.error(error_msg)
                raise Exception(error_msg)

            if "system_prompt" not in result:
                error_msg = "Custom prompt Lambda response missing required field: system_prompt"
                logger.error(error_msg)
                raise Exception(error_msg)

            if "task_prompt_content" not in result:
                error_msg = "Custom prompt Lambda response missing required field: task_prompt_content"
                logger.error(error_msg)
                raise Exception(error_msg)

            # Convert image URIs back to bytes in the response
            if original_images:
                result["task_prompt_content"] = (
                    self._convert_image_uris_to_bytes_in_content(
                        result["task_prompt_content"], original_images
                    )
                )

            return result

        except Exception as e:
            error_msg = f"Failed to invoke custom prompt Lambda {lambda_arn}: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def process_document_section(self, document: Document, section_id: str) -> Document:
        """
        Process a single section from a Document object.

        Args:
            document: Document object containing section to process
            section_id: ID of the section to process

        Returns:
            Document: Updated Document object with extraction results for the section
        """
        # Validate input document
        if not document:
            logger.error("No document provided")
            return document

        if not document.sections:
            logger.error("Document has no sections to process")
            document.errors.append("Document has no sections to process")
            return document

        # Find the section with the given ID
        section = None
        for s in document.sections:
            if s.section_id == section_id:
                section = s
                break

        if not section:
            error_msg = f"Section {section_id} not found in document"
            logger.error(error_msg)
            document.errors.append(error_msg)
            return document

        # Extract information about the section
        class_label = section.classification
        output_bucket = document.output_bucket
        output_prefix = document.input_key
        output_key = f"{output_prefix}/sections/{section.section_id}/result.json"
        output_uri = f"s3://{output_bucket}/{output_key}"

        # Check if the section has required pages
        if not section.page_ids:
            error_msg = f"Section {section_id} has no page IDs"
            logger.error(error_msg)
            document.errors.append(error_msg)
            return document

        # Sort pages by page number
        sorted_page_ids = sorted(section.page_ids, key=int)
        start_page = int(sorted_page_ids[0])
        end_page = int(sorted_page_ids[-1])

        # Find minimum page ID across all sections in the document to determine offset
        min_page_id = min(
            int(page_id) for sec in document.sections for page_id in sec.page_ids
        )

        # Adjust page indices to be zero-based if document pages start at 1
        page_indices = [int(page_id) - min_page_id for page_id in sorted_page_ids]

        logger.info(
            f"Processing {len(sorted_page_ids)} pages, class {class_label}: {start_page}-{end_page}"
        )

        # Track metrics
        metrics.put_metric("InputDocuments", 1)
        metrics.put_metric("InputDocumentPages", len(section.page_ids))

        try:
            # Read document text from all pages in order
            t0 = time.time()
            document_texts = []
            for page_id in sorted_page_ids:
                if page_id not in document.pages:
                    error_msg = f"Page {page_id} not found in document"
                    logger.error(error_msg)
                    document.errors.append(error_msg)
                    continue

                page = document.pages[page_id]
                text_path = page.parsed_text_uri
                page_text = s3.get_text_content(text_path)
                document_texts.append(page_text)

            document_text = "\n".join(document_texts)
            t1 = time.time()
            logger.info(f"Time taken to read text content: {t1 - t0:.2f} seconds")

            # Read page images with configurable dimensions
            extraction_config = self.config.get("extraction", {})
            image_config = extraction_config.get("image", {})
            target_width = image_config.get("target_width")
            target_height = image_config.get("target_height")

            page_images = []
            for page_id in sorted_page_ids:
                if page_id not in document.pages:
                    continue

                page = document.pages[page_id]
                image_uri = page.image_uri
                # Just pass the values directly - prepare_image handles empty strings/None
                image_content = image.prepare_image(
                    image_uri, target_width, target_height
                )
                page_images.append(image_content)

            t2 = time.time()
            logger.info(f"Time taken to read images: {t2 - t1:.2f} seconds")

            # Get extraction configuration
            model_id = self.config.get("model_id") or extraction_config.get("model")
            temperature = float(extraction_config.get("temperature", 0))
            top_k = float(extraction_config.get("top_k", 5))
            top_p = float(extraction_config.get("top_p", 0.1))
            max_tokens = (
                int(extraction_config.get("max_tokens", 4096))
                if extraction_config.get("max_tokens")
                else None
            )
            system_prompt = extraction_config.get("system_prompt", "")

            # Get attributes for this document class
            attributes = self._get_class_attributes(class_label)
            attribute_descriptions = self._format_attribute_descriptions(attributes)

            # Check if attributes list is empty - if so, skip LLM invocation entirely
            if not attributes or not attribute_descriptions.strip():
                logger.info(
                    f"No attributes defined for class {class_label}, skipping LLM extraction"
                )

                # Create empty result structure without invoking LLM
                extracted_fields = {}
                metering = {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "invocation_count": 0,
                    "total_cost": 0.0,
                }
                total_duration = 0.0
                parsing_succeeded = True

                # Write to S3 with empty extraction result
                output = {
                    "document_class": {"type": class_label},
                    "split_document": {"page_indices": page_indices},
                    "inference_result": extracted_fields,
                    "metadata": {
                        "parsing_succeeded": parsing_succeeded,
                        "extraction_time_seconds": total_duration,
                        "skipped_due_to_empty_attributes": True,
                    },
                }
                s3.write_content(
                    output, output_bucket, output_key, content_type="application/json"
                )

                # Update the section with extraction result URI
                section.extraction_result_uri = output_uri

                # Update document with zero metering data
                document.metering = utils.merge_metering_data(
                    document.metering, metering
                )

                t3 = time.time()
                logger.info(
                    f"Skipped extraction for section {section_id} due to empty attributes: {t3 - t0:.2f} seconds"
                )
                return document

            # Check for custom prompt Lambda function
            custom_lambda_arn = extraction_config.get("custom_prompt_lambda_arn")

            if custom_lambda_arn and custom_lambda_arn.strip():
                logger.info(f"Using custom prompt Lambda: {custom_lambda_arn}")

                # Prepare prompt placeholders including image URIs
                image_uris = []
                for page_id in sorted_page_ids:
                    if page_id in document.pages:
                        page = document.pages[page_id]
                        if page.image_uri:
                            image_uris.append(page.image_uri)

                prompt_placeholders = {
                    "DOCUMENT_TEXT": document_text,
                    "DOCUMENT_CLASS": class_label,
                    "ATTRIBUTE_NAMES_AND_DESCRIPTIONS": attribute_descriptions,
                    "DOCUMENT_IMAGE": image_uris,
                }

                logger.info(
                    f"Lambda will receive {len(image_uris)} image URIs in DOCUMENT_IMAGE placeholder"
                )

                # Build default content for Lambda input
                prompt_template = extraction_config.get("task_prompt", "")
                if prompt_template:
                    # Check if task prompt contains FEW_SHOT_EXAMPLES placeholder
                    if "{FEW_SHOT_EXAMPLES}" in prompt_template:
                        default_content = self._build_content_with_few_shot_examples(
                            prompt_template,
                            document_text,
                            class_label,
                            attribute_descriptions,
                            page_images,
                        )
                    else:
                        # Use the unified content builder for DOCUMENT_IMAGE placeholder support
                        default_content = (
                            self._build_content_with_or_without_image_placeholder(
                                prompt_template,
                                document_text,
                                class_label,
                                attribute_descriptions,
                                page_images,
                            )
                        )
                else:
                    # Default content if no template
                    task_prompt = f"""
                    Extract the following fields from this {class_label} document:
                    
                    {attribute_descriptions}
                    
                    Document text:
                    {document_text}
                    
                    Respond with a JSON object containing each field name and its extracted value.
                    """
                    default_content = [{"text": task_prompt}]
                    if page_images:
                        for img in page_images[:20]:
                            default_content.append(
                                image.prepare_bedrock_image_attachment(img)
                            )

                # Prepare Lambda payload with JSON-serializable content
                try:
                    # Use Document's built-in to_dict() method which properly handles Status enum conversion
                    document_dict = document.to_dict()
                except Exception as e:
                    logger.warning(
                        f"Error serializing document for Lambda payload: {e}"
                    )
                    document_dict = {"id": getattr(document, "id", "unknown")}

                # Convert image bytes to URIs in default content for JSON serialization
                serializable_default_content = (
                    self._convert_image_bytes_to_uris_in_content(default_content)
                )

                # Create fully serializable payload using comprehensive helper
                payload = {
                    "config": self._make_json_serializable(self.config),
                    "prompt_placeholders": prompt_placeholders,
                    "default_task_prompt_content": serializable_default_content,
                    "serialized_document": document_dict,
                }

                # Test JSON serialization before sending to Lambda to catch any remaining issues
                try:
                    json.dumps(payload)
                    logger.info("Lambda payload successfully serialized")
                except (TypeError, ValueError) as e:
                    logger.error(
                        f"Lambda payload still contains non-serializable data: {e}"
                    )
                    logger.info("Using comprehensive serialization as fallback")
                    # Apply comprehensive serialization to entire payload
                    payload = self._make_json_serializable(payload)
                    try:
                        json.dumps(payload)
                        logger.info("Comprehensive serialization successful")
                    except (TypeError, ValueError) as e2:
                        logger.error(f"Even comprehensive serialization failed: {e2}")
                        # Ultimate fallback to minimal payload
                        payload = {
                            "config": {
                                "extraction": {
                                    "model": extraction_config.get("model", "")
                                }
                            },
                            "prompt_placeholders": prompt_placeholders,
                            "default_task_prompt_content": [
                                {"text": "Fallback content"}
                            ],
                            "serialized_document": {
                                "id": str(document.id),
                                "status": "PROCESSING",
                            },
                        }

                # Invoke custom Lambda and get result (pass original images for restoration)
                lambda_result = self._invoke_custom_prompt_lambda(
                    custom_lambda_arn, payload, page_images
                )

                # Use Lambda results
                system_prompt = lambda_result.get("system_prompt", system_prompt)
                content = lambda_result.get("task_prompt_content", default_content)

                logger.info("Successfully applied custom prompt from Lambda function")

            else:
                # Use default prompt logic when no custom Lambda is configured
                logger.info(
                    "No custom prompt Lambda configured - using default prompt generation"
                )
                prompt_template = extraction_config.get("task_prompt", "")

                if not prompt_template:
                    # Default prompt if template not found
                    task_prompt = f"""
                    Extract the following fields from this {class_label} document:
                    
                    {attribute_descriptions}
                    
                    Document text:
                    {document_text}
                    
                    Respond with a JSON object containing each field name and its extracted value.
                    """
                    content = [{"text": task_prompt}]

                    # Add image attachments to the content (limit to 20 images as per Bedrock constraints)
                    if page_images:
                        logger.info(
                            f"Attaching images to prompt, for {len(page_images)} pages."
                        )
                        # Limit to 20 images as per Bedrock constraints
                        for img in page_images[:20]:
                            content.append(image.prepare_bedrock_image_attachment(img))
                else:
                    # Check if task prompt contains FEW_SHOT_EXAMPLES placeholder
                    if "{FEW_SHOT_EXAMPLES}" in prompt_template:
                        content = self._build_content_with_few_shot_examples(
                            prompt_template,
                            document_text,
                            class_label,
                            attribute_descriptions,
                            page_images,  # Pass images to the content builder
                        )
                    else:
                        # Use the unified content builder for DOCUMENT_IMAGE placeholder support
                        try:
                            content = (
                                self._build_content_with_or_without_image_placeholder(
                                    prompt_template,
                                    document_text,
                                    class_label,
                                    attribute_descriptions,
                                    page_images,  # Pass images to the content builder
                                )
                            )
                        except ValueError as e:
                            logger.warning(
                                f"Error formatting prompt template: {str(e)}. Using default prompt."
                            )
                            # Fall back to default prompt if template validation fails
                            task_prompt = f"""
                            Extract the following fields from this {class_label} document:
                            
                            {attribute_descriptions}
                            
                            Document text:
                            {document_text}
                            
                            Respond with a JSON object containing each field name and its extracted value.
                            """
                            content = [{"text": task_prompt}]

                            # Add image attachments for fallback case
                            if page_images:
                                logger.info(
                                    f"Attaching images to prompt, for {len(page_images)} pages."
                                )
                                # Limit to 20 images as per Bedrock constraints
                                for img in page_images[:20]:
                                    content.append(
                                        image.prepare_bedrock_image_attachment(img)
                                    )

            logger.info(
                f"Extracting fields for {class_label} document, section {section_id}"
            )

            # Time the model invocation
            request_start_time = time.time()

            if (
                self.config.get("extraction", {})
                .get("agentic", {})
                .get("enabled", False)
            ):
                if not AGENTIC_AVAILABLE:
                    raise ImportError(
                        "Agentic extraction requires Python 3.10+ and strands-agents dependencies. "
                        "Install with: pip install 'idp_common[agents]' or use agentic=False"
                    )

                # Create dynamic Pydantic model from configuration attributes
                dynamic_model = self._create_pydantic_model_from_attributes(
                    class_label, attributes
                )

                # Log the Pydantic model schema for debugging
                model_schema = dynamic_model.model_json_schema()
                logger.debug(f"Pydantic model schema for {class_label}:")
                logger.debug(json.dumps(model_schema, indent=2))

                # Use agentic extraction with the dynamic model
                # Wrap content list in proper Message format for agentic_idp compatibility
                if isinstance(content, list):
                    message_prompt = {"role": "user", "content": content}
                else:
                    message_prompt = content
                logger.info("Using Agentic extraction")
                logger.debug(f"Using input: {str(message_prompt)}")
                structured_data, response_with_metering = structured_output(  # pyright: ignore[reportPossiblyUnboundVariable]
                    model_id=model_id,
                    data_format=dynamic_model,
                    prompt=message_prompt,  # pyright: ignore[reportArgumentType]
                    custom_instruction=system_prompt,
                    review_agent=self.config.get("extraction", {}).get(
                        "review_agent", False
                    ),
                    context="Extraction",
                )

                # Extract the structured data as dict for compatibility with existing code
                extracted_fields = structured_data.model_dump()
                # Extract metering from BedrockInvokeModelResponse
                metering = response_with_metering["metering"]
                parsing_succeeded = True  # Agentic approach always succeeds in parsing since it returns structured data

            else:
                # Invoke Bedrock with the common library
                response_with_metering = bedrock.invoke_model(
                    model_id=model_id,
                    system_prompt=system_prompt,
                    content=content,
                    temperature=temperature,
                    top_k=top_k,
                    top_p=top_p,
                    max_tokens=max_tokens,
                    context="Extraction",
                )
                # For non-agentic approach, response_with_metering is BedrockInvokeModelResponse
                # Extract text from response for non-agentic approach
                extracted_text = bedrock.extract_text_from_response(
                    dict(response_with_metering)
                )
                metering = response_with_metering["metering"]

                # Parse response into JSON
                extracted_fields = {}
                parsing_succeeded = True  # Flag to track if parsing was successful

                try:
                    # Try to parse the extracted text as JSON
                    extracted_fields = json.loads(
                        extract_json_from_text(extracted_text)
                    )
                except Exception as e:
                    # Handle parsing error
                    logger.error(
                        f"Error parsing LLM output - invalid JSON?: {extracted_text} - {e}"
                    )
                    logger.info("Using unparsed LLM output.")
                    extracted_fields = {"raw_output": extracted_text}
                    parsing_succeeded = False  # Mark that parsing failed

            total_duration = time.time() - request_start_time
            logger.info(f"Time taken for extraction: {total_duration:.2f} seconds")

            # Write to S3
            output = {
                "document_class": {"type": class_label},
                "split_document": {"page_indices": page_indices},
                "inference_result": extracted_fields,
                "metadata": {
                    "parsing_succeeded": parsing_succeeded,
                    "extraction_time_seconds": total_duration,
                },
            }
            s3.write_content(
                output, output_bucket, output_key, content_type="application/json"
            )

            # Update the section with extraction result URI only (not the attributes themselves)
            section.extraction_result_uri = output_uri

            # Update document with metering data
            document.metering = utils.merge_metering_data(
                document.metering, metering or {}
            )

            t3 = time.time()
            logger.info(
                f"Total extraction time for section {section_id}: {t3 - t0:.2f} seconds"
            )

        except Exception as e:
            error_msg = f"Error processing section {section_id}: {str(e)}"
            logger.error(error_msg)
            document.errors.append(error_msg)
            raise

        return document
