# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Extraction service for documents using LLMs.

This module provides a service for extracting fields and values from documents
using LLMs, with support for text and image content.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from idp_common import bedrock, image, metrics, s3, utils
from idp_common.bedrock import format_prompt
from idp_common.config.models import IDPConfig
from idp_common.config.schema_constants import (
    ID_FIELD,
    SCHEMA_PROPERTIES,
    X_AWS_IDP_DOCUMENT_TYPE,
    X_AWS_IDP_EXTRACTION_MODEL,
)
from idp_common.models import Document
from idp_common.utils.few_shot_example_builder import (
    build_few_shot_extraction_examples_content,
)

# Conditional import for agentic extraction (requires Python 3.12+ dependencies)
try:
    from idp_common.extraction.agentic_idp import (
        concurrent_structured_output_async,
        set_confidence_data,
        structured_output,
    )
    from idp_common.schema import create_pydantic_model_from_json_schema

    AGENTIC_AVAILABLE = True
except ImportError:
    AGENTIC_AVAILABLE = False
from pydantic import BaseModel

from idp_common.utils import extract_json_from_text, repair_truncated_json

logger = logging.getLogger(__name__)


# Pydantic models for internal data transfer
class SectionInfo(BaseModel):
    """Metadata about a document section being processed."""

    class_label: str
    sorted_page_ids: list[str]
    page_indices: list[int]
    output_bucket: str
    output_key: str
    output_uri: str
    start_page: int
    end_page: int


class ExtractionConfig(BaseModel):
    """Configuration for model invocation."""

    model_id: str
    temperature: float
    top_k: float
    top_p: float
    max_tokens: int | None
    system_prompt: str


class ExtractionResult(BaseModel):
    """Result from model extraction."""

    extracted_fields: dict[str, Any]
    metering: dict[str, Any]
    parsing_succeeded: bool
    total_duration: float
    output_truncated: bool = False
    output_repaired: bool = False
    repair_method: str | None = None
    schema_analysis: dict[str, Any] | None = None
    ocr_analysis: dict[str, Any] | None = None


class ExtractionService:
    """Service for extracting fields from documents using LLMs."""

    def __init__(
        self,
        region: str | None = None,
        config: dict[str, Any] | IDPConfig | None = None,
    ):
        """
        Initialize the extraction service.

        Args:
            region: AWS region for Bedrock
            config: Configuration dictionary or IDPConfig model
        """
        # Convert dict to IDPConfig if needed
        if config is not None and isinstance(config, dict):
            config_model: IDPConfig = IDPConfig(**config)
        elif config is None:
            config_model = IDPConfig()
        else:
            config_model = config

        self.config = config_model
        self.region = region or os.environ.get("AWS_REGION")

        # Instance variables for prompt context
        # These are initialized here and populated during each process_document_section call
        # This allows methods to access context without passing multiple parameters
        self._document_text: str = ""
        self._class_label: str = ""
        self._attribute_descriptions: str = ""
        self._class_schema: dict[str, Any] = {}
        self._page_images: list[bytes] = []
        self._image_uris: list[str] = []
        # Optional checkpoint callback for incremental saves during agentic extraction.
        # When set, called after each successful extraction_tool or apply_json_patches
        # invocation with the current extraction dict, enabling resume on Lambda timeout.
        self._checkpoint_callback: Any | None = None

        # Get model_id from config for logging (type-safe access with fallback)
        model_id = (
            self.config.extraction.model if self.config.extraction else "not configured"
        )
        logger.info(f"Initialized extraction service with model {model_id}")

    @property
    def _substitutions(self) -> dict[str, str]:
        """Get prompt placeholder substitutions from stored context."""
        return {
            "DOCUMENT_TEXT": self._document_text,
            "DOCUMENT_CLASS": self._class_label,
            "ATTRIBUTE_NAMES_AND_DESCRIPTIONS": self._attribute_descriptions,
        }

    def _get_default_prompt_content(self) -> list[dict[str, Any]]:
        """
        Build default fallback prompt content when no template is provided.

        Returns:
            List of content items with default prompt text and images
        """
        task_prompt = f"""
        Extract the following fields from this {self._class_label} document:
        
        {self._attribute_descriptions}
        
        Document text:
        {self._document_text}
        
        Respond with a JSON object containing each field name and its extracted value.
        """
        content = [{"text": task_prompt}]

        # Add image attachments to the content - no limit with latest Bedrock API
        if self._page_images:
            logger.info(
                f"Attaching {len(self._page_images)} images to default extraction prompt"
            )
            for img in self._page_images:
                content.append(image.prepare_bedrock_image_attachment(img))

        return content

    def _get_class_schema(self, class_label: str) -> dict[str, Any]:
        """
        Get JSON Schema for a specific document class from configuration.

        Args:
            class_label: The document class name

        Returns:
            JSON Schema for the class, or empty dict if not found
        """
        # Access classes through IDPConfig - returns List of dicts
        classes_config = self.config.classes

        # Find class by $id or x-aws-idp-document-type using constants
        for class_obj in classes_config:
            class_id = class_obj.get(ID_FIELD, "") or class_obj.get(
                X_AWS_IDP_DOCUMENT_TYPE, ""
            )
            if class_id.lower() == class_label.lower():
                return class_obj

        return {}

    def _clean_schema_for_prompt(self, schema: dict[str, Any]) -> dict[str, Any]:
        """
        Clean JSON Schema by removing IDP custom fields (x-aws-idp-*) for the prompt.
        Keeps all standard JSON Schema fields including descriptions.

        Args:
            schema: JSON Schema definition

        Returns:
            Cleaned JSON Schema
        """
        cleaned = {}

        for key, value in schema.items():
            # Skip IDP custom fields
            if key.startswith("x-aws-idp-"):
                continue

            # Recursively clean nested objects and arrays
            if isinstance(value, dict):
                cleaned[key] = self._clean_schema_for_prompt(value)
            elif isinstance(value, list):
                cleaned[key] = [
                    (
                        self._clean_schema_for_prompt(item)
                        if isinstance(item, dict)
                        else item
                    )
                    for item in value
                ]
            else:
                cleaned[key] = value

        return cleaned

    def _format_schema_for_prompt(self, schema: dict[str, Any]) -> str:
        """
        Format JSON Schema for inclusion in the extraction prompt.

        Args:
            schema: JSON Schema definition

        Returns:
            Formatted JSON Schema as a string with IDP custom fields removed
        """
        # Clean the schema to remove IDP custom fields
        cleaned_schema = self._clean_schema_for_prompt(schema)

        # Return the cleaned JSON Schema with nice formatting
        return json.dumps(cleaned_schema, indent=2)

    def _prepare_prompt_from_template(
        self,
        prompt_template: str,
        substitutions: dict[str, str],
        required_placeholders: list[str] | None = None,
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

        return format_prompt(prompt_template, substitutions, required_placeholders)

    def _build_prompt_content(
        self,
        prompt_template: str,
        image_content: Any = None,
    ) -> list[dict[str, Any]]:
        """
        Build prompt content array handling FEW_SHOT_EXAMPLES and DOCUMENT_IMAGE placeholders.

        This consolidated method handles all placeholder types and combinations:
        - {FEW_SHOT_EXAMPLES}: Inserts few-shot examples from config
        - {DOCUMENT_IMAGE}: Inserts images at specific location
        - Regular text placeholders: DOCUMENT_TEXT, DOCUMENT_CLASS, etc.

        Args:
            prompt_template: The prompt template with optional placeholders
            image_content: Optional image content to insert (only used with {DOCUMENT_IMAGE})

        Returns:
            List of content items with text and image content properly ordered
        """
        content: list[dict[str, Any]] = []

        # Handle FEW_SHOT_EXAMPLES placeholder first
        if "{FEW_SHOT_EXAMPLES}" in prompt_template:
            parts = prompt_template.split("{FEW_SHOT_EXAMPLES}")
            if len(parts) == 2:
                # Process before examples
                content.extend(
                    self._build_text_and_image_content(parts[0], image_content)
                )

                # Add few-shot examples
                content.extend(self._build_few_shot_examples_content())

                # Process after examples (only pass images if not already used)
                image_for_after = (
                    None if "{DOCUMENT_IMAGE}" in parts[0] else image_content
                )
                content.extend(
                    self._build_text_and_image_content(parts[1], image_for_after)
                )

                return content

        # No FEW_SHOT_EXAMPLES, just handle text and images
        return self._build_text_and_image_content(prompt_template, image_content)

    def _build_text_and_image_content(
        self,
        prompt_template: str,
        image_content: Any = None,
    ) -> list[dict[str, Any]]:
        """
        Build content array with text and optionally images based on DOCUMENT_IMAGE placeholder.

        Args:
            prompt_template: Template that may contain {DOCUMENT_IMAGE}
            image_content: Optional image content

        Returns:
            List of content items
        """
        content: list[dict[str, Any]] = []

        # Handle DOCUMENT_IMAGE placeholder
        if "{DOCUMENT_IMAGE}" in prompt_template:
            parts = prompt_template.split("{DOCUMENT_IMAGE}")
            if len(parts) == 2:
                # Add text before image
                before_text = self._prepare_prompt_from_template(
                    parts[0], self._substitutions, required_placeholders=[]
                )
                if before_text.strip():
                    content.append({"text": before_text})

                # Add images
                if image_content:
                    content.extend(self._prepare_image_attachments(image_content))

                # Add text after image
                after_text = self._prepare_prompt_from_template(
                    parts[1], self._substitutions, required_placeholders=[]
                )
                if after_text.strip():
                    content.append({"text": after_text})

                return content
            else:
                logger.warning("Invalid DOCUMENT_IMAGE placeholder usage")

        # No image placeholder, just text
        task_prompt = self._prepare_prompt_from_template(
            prompt_template, self._substitutions, required_placeholders=[]
        )
        content.append({"text": task_prompt})

        return content

    def _prepare_image_attachments(self, image_content: Any) -> list[dict[str, Any]]:
        """
        Prepare image attachments for Bedrock - no image limit.

        Args:
            image_content: Single image or list of images

        Returns:
            List of image attachment dicts
        """
        attachments: list[dict[str, Any]] = []

        if isinstance(image_content, list):
            # Multiple images - no limit with latest Bedrock API
            logger.info(f"Attaching {len(image_content)} images to extraction prompt")
            for img in image_content:
                attachments.append(image.prepare_bedrock_image_attachment(img))
        else:
            # Single image
            attachments.append(image.prepare_bedrock_image_attachment(image_content))

        return attachments

    def _build_few_shot_examples_content(self) -> list[dict[str, Any]]:
        """
        Build content items for few-shot examples from the configuration for a specific class.

        Returns:
            List of content items containing text and image content for examples
        """
        content: list[dict[str, Any]] = []

        # Use the stored class schema
        if not self._class_schema:
            logger.warning(
                f"No class schema found for '{self._class_label}' for few-shot examples"
            )
            return content

        # Get examples from the JSON Schema for this specific class
        content = build_few_shot_extraction_examples_content(self._class_schema)

        return content

    def _make_json_serializable(self, obj: Any) -> Any:
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

    def _invoke_custom_prompt_lambda(
        self, lambda_arn: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Invoke custom prompt generator Lambda function with JSON-serializable payload.

        Args:
            lambda_arn: ARN of the Lambda function to invoke
            payload: Payload to send to Lambda function (must be JSON serializable)

        Returns:
            Dict containing system_prompt and task_prompt_content

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

            return result

        except Exception as e:
            error_msg = f"Failed to invoke custom prompt Lambda {lambda_arn}: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def _reset_context(self) -> None:
        """Reset instance variables for clean state before processing."""
        self._document_text = ""
        self._class_label = ""
        self._attribute_descriptions = ""
        self._class_schema = {}
        self._page_images = []
        self._image_uris = []

    def _validate_and_find_section(
        self, document: Document, section_id: str
    ) -> Any | None:
        """
        Validate document and find section by ID.

        Args:
            document: Document to validate
            section_id: ID of section to find

        Returns:
            Section if found, None otherwise (errors added to document)
        """
        if not document:
            logger.error("No document provided")
            return None

        if not document.sections:
            logger.error("Document has no sections to process")
            document.errors.append("Document has no sections to process")
            return None

        # Find the section with the given ID
        for section in document.sections:
            if section.section_id == section_id:
                return section

        error_msg = f"Section {section_id} not found in document"
        logger.error(error_msg)
        document.errors.append(error_msg)
        return None

    def _prepare_section_info(self, document: Document, section: Any) -> SectionInfo:
        """
        Prepare section metadata and output paths.

        Args:
            document: Document being processed
            section: Section being processed

        Returns:
            SectionInfo with all metadata
        """
        class_label = section.classification
        output_bucket = document.output_bucket
        output_prefix = document.input_key
        output_key = f"{output_prefix}/sections/{section.section_id}/result.json"
        output_uri = f"s3://{output_bucket}/{output_key}"

        # Check if the section has required pages
        if not section.page_ids:
            error_msg = f"Section {section.section_id} has no page IDs"
            logger.error(error_msg)
            document.errors.append(error_msg)
            raise ValueError(error_msg)

        # Sort pages by page number
        sorted_page_ids = sorted(section.page_ids, key=int)
        start_page = int(sorted_page_ids[0])
        end_page = int(sorted_page_ids[-1])

        # Use pre-calculated page_indices from classification service if available
        # This ensures consistent page_indices calculation across all sections in a document packet
        if section.attributes and "page_indices" in section.attributes:
            page_indices = section.attributes["page_indices"]
            logger.info(
                f"Using pre-calculated page_indices from section attributes: {page_indices}"
            )
        else:
            # Fallback: calculate page_indices for backward compatibility
            # This handles sections processed before the fix was implemented
            try:
                # Find minimum page ID across all available sections
                all_page_ids = []
                for sec in document.sections:
                    all_page_ids.extend(sec.page_ids)

                if all_page_ids:
                    global_min_page_id = min(int(page_id) for page_id in all_page_ids)
                else:
                    global_min_page_id = 1

                page_indices = [
                    int(page_id) - global_min_page_id for page_id in sorted_page_ids
                ]
                logger.warning(
                    f"page_indices not found in section attributes, calculated: {page_indices} (global_min_page_id={global_min_page_id})"
                )
            except (ValueError, TypeError) as e:
                # Final fallback: assume 1-indexed page IDs
                page_indices = [int(page_id) - 1 for page_id in sorted_page_ids]
                logger.warning(
                    f"Error calculating page_indices, using 1-indexed fallback: {page_indices} - {e}"
                )

        logger.info(
            f"Processing {len(sorted_page_ids)} pages, class {class_label}: {start_page}-{end_page}"
        )

        # Track metrics
        metrics.put_metric("InputDocuments", 1)
        metrics.put_metric("InputDocumentPages", len(section.page_ids))

        return SectionInfo(
            class_label=class_label,
            sorted_page_ids=sorted_page_ids,
            page_indices=page_indices,
            output_bucket=output_bucket,
            output_key=output_key,
            output_uri=output_uri,
            start_page=start_page,
            end_page=end_page,
        )

    def _load_document_text(
        self, document: Document, sorted_page_ids: list[str]
    ) -> str:
        """
        Load and concatenate text from all pages.

        Args:
            document: Document containing pages
            sorted_page_ids: Sorted list of page IDs

        Returns:
            Concatenated document text
        """
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

        # Join with page markers so batch agents can extract their page range
        page_separator_parts = []
        for idx, text in enumerate(document_texts):
            page_num = idx + 1
            page_separator_parts.append(f"--- PAGE {page_num} ---\n{text}")
        document_text = "\n".join(page_separator_parts)
        t1 = time.time()
        logger.info(f"Time taken to read text content: {t1 - t0:.2f} seconds")

        return document_text

    def _load_confidence_data(
        self, document: Document, sorted_page_ids: list[str]
    ) -> dict[str, str]:
        """
        Load OCR confidence data for pages in a section.

        Reads text_confidence_uri from each page to provide confidence scores
        to the table parsing tool.

        Args:
            document: Document containing pages
            sorted_page_ids: Sorted list of page IDs

        Returns:
            Dict mapping page IDs to confidence data strings
        """
        confidence_data: dict[str, str] = {}
        for page_id in sorted_page_ids:
            if page_id not in document.pages:
                continue
            page = document.pages[page_id]
            confidence_uri = getattr(page, "text_confidence_uri", None)
            if confidence_uri:
                try:
                    conf_text = s3.get_text_content(confidence_uri)
                    if conf_text:
                        confidence_data[page_id] = conf_text
                except Exception as e:
                    logger.warning(
                        f"Failed to load confidence data for page {page_id}: {e}"
                    )
        return confidence_data

    def _load_document_images(
        self, document: Document, sorted_page_ids: list[str]
    ) -> list[Any]:
        """
        Load images from all pages.

        Args:
            document: Document containing pages
            sorted_page_ids: Sorted list of page IDs

        Returns:
            List of prepared images
        """
        t0 = time.time()
        target_width = self.config.extraction.image.target_width
        target_height = self.config.extraction.image.target_height

        page_images = []
        for page_id in sorted_page_ids:
            if page_id not in document.pages:
                continue

            page = document.pages[page_id]
            image_uri = page.image_uri
            image_content = image.prepare_image(image_uri, target_width, target_height)
            page_images.append(image_content)

        t1 = time.time()
        logger.info(f"Time taken to read images: {t1 - t0:.2f} seconds")

        return page_images

    def _initialize_extraction_context(
        self,
        class_label: str,
        document_text: str,
        page_images: list[Any],
        sorted_page_ids: list[str],
        document: Document,
    ) -> tuple[dict[str, Any], str]:
        """
        Initialize extraction context and set instance variables.

        Args:
            class_label: Document class
            document_text: Text content
            page_images: Prepared images
            sorted_page_ids: Sorted page IDs
            document: Document being processed

        Returns:
            Tuple of (class_schema, attribute_descriptions)
        """
        # Get JSON Schema for this document class
        class_schema = self._get_class_schema(class_label)
        attribute_descriptions = self._format_schema_for_prompt(class_schema)

        # Store context in instance variables
        self._document_text = document_text
        self._class_label = class_label
        self._attribute_descriptions = attribute_descriptions
        self._class_schema = class_schema
        self._page_images = page_images

        # Prepare image URIs for Lambda
        image_uris = []
        for page_id in sorted_page_ids:
            if page_id in document.pages:
                page = document.pages[page_id]
                if page.image_uri:
                    image_uris.append(page.image_uri)
        self._image_uris = image_uris

        return class_schema, attribute_descriptions

    def _handle_empty_schema(
        self,
        document: Document,
        section: Any,
        section_info: SectionInfo,
        section_id: str,
        t0: float,
    ) -> Document:
        """
        Handle case when schema has no attributes - skip LLM and return empty result.

        Args:
            document: Document being processed
            section: Section being processed
            section_info: Section metadata
            section_id: Section ID
            t0: Start time

        Returns:
            Updated document
        """
        logger.info(
            f"No attributes defined for class {section_info.class_label}, skipping LLM extraction"
        )

        # Create empty result structure
        extracted_fields = {}
        metering = {
            "input_tokens": 0,
            "output_tokens": 0,
            "invocation_count": 0,
            "total_cost": 0.0,
        }
        total_duration = 0.0
        parsing_succeeded = True

        # Write to S3
        output = {
            "document_class": {"type": section_info.class_label},
            "split_document": {"page_indices": section_info.page_indices},
            "inference_result": extracted_fields,
            "metadata": {
                "parsing_succeeded": parsing_succeeded,
                "extraction_time_seconds": total_duration,
                "skipped_due_to_empty_attributes": True,
            },
        }
        s3.write_content(
            output,
            section_info.output_bucket,
            section_info.output_key,
            content_type="application/json",
        )

        # Update section and document
        section.extraction_result_uri = section_info.output_uri
        document.metering = utils.merge_metering_data(document.metering, metering)

        t3 = time.time()
        logger.info(
            f"Skipped extraction for section {section_id} due to empty attributes: {t3 - t0:.2f} seconds"
        )
        return document

    def _build_extraction_content(
        self,
        document: Document,
        page_images: list[Any],
    ) -> tuple[list[dict[str, Any]], str]:
        """
        Build prompt content (with or without custom Lambda).

        Args:
            document: Document being processed
            page_images: Prepared page images

        Returns:
            Tuple of (content, system_prompt)
        """
        system_prompt = self.config.extraction.system_prompt
        custom_lambda_arn = self.config.extraction.custom_prompt_lambda_arn

        if custom_lambda_arn and custom_lambda_arn.strip():
            logger.info(f"Using custom prompt Lambda: {custom_lambda_arn}")

            prompt_placeholders = {
                "DOCUMENT_TEXT": self._document_text,
                "DOCUMENT_CLASS": self._class_label,
                "ATTRIBUTE_NAMES_AND_DESCRIPTIONS": self._attribute_descriptions,
                "DOCUMENT_IMAGE": self._image_uris,
            }

            logger.info(
                f"Lambda will receive {len(self._image_uris)} image URIs in DOCUMENT_IMAGE placeholder"
            )

            # Build default content for Lambda input
            prompt_template = self.config.extraction.task_prompt
            if prompt_template:
                default_content = self._build_prompt_content(
                    prompt_template, page_images
                )
            else:
                default_content = self._get_default_prompt_content()

            # Prepare Lambda payload
            try:
                document_dict = document.to_dict()
            except Exception as e:
                logger.warning(f"Error serializing document for Lambda payload: {e}")
                document_dict = {"id": getattr(document, "id", "unknown")}

            payload = {
                "config": self._make_json_serializable(self.config),
                "prompt_placeholders": prompt_placeholders,
                "default_task_prompt_content": self._make_json_serializable(
                    default_content
                ),
                "serialized_document": document_dict,
            }

            # Invoke custom Lambda
            lambda_result = self._invoke_custom_prompt_lambda(
                custom_lambda_arn, payload
            )

            # Use Lambda results
            system_prompt = lambda_result.get("system_prompt", system_prompt)
            content = lambda_result.get("task_prompt_content", default_content)

            logger.info("Successfully applied custom prompt from Lambda function")
        else:
            # Use default prompt logic
            logger.info(
                "No custom prompt Lambda configured - using default prompt generation"
            )
            prompt_template = self.config.extraction.task_prompt

            if not prompt_template:
                content = self._get_default_prompt_content()
            else:
                try:
                    content = self._build_prompt_content(prompt_template, page_images)
                except ValueError as e:
                    logger.warning(
                        f"Error formatting prompt template: {str(e)}. Using default prompt."
                    )
                    content = self._get_default_prompt_content()

        return content, system_prompt

    def _analyze_schema_for_table_requirements(
        self, schema: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Analyze schema to detect large array fields that require table parsing.

        NOTE: This is OPTIONAL - minItems is not required for tool usage.
        OCR analysis is the primary adaptive trigger. Schema analysis only
        provides additional signal when minItems is explicitly set.

        Returns:
            Dict with analysis results including whether tool usage is recommended
        """
        large_arrays = []
        max_min_items = 0

        properties = schema.get(SCHEMA_PROPERTIES, {})
        for field_name, field_def in properties.items():
            if field_def.get("type") == "array":
                min_items = field_def.get("minItems", 0)
                if min_items > 50:  # Match OCR threshold for consistency
                    large_arrays.append(
                        {
                            "field": field_name,
                            "min_items": min_items,
                            "description": field_def.get("description", ""),
                        }
                    )
                    max_min_items = max(max_min_items, min_items)

        recommendation = len(large_arrays) > 0

        return {
            "large_array_fields": [arr["field"] for arr in large_arrays],
            "max_min_items": max_min_items,
            "field_details": large_arrays,
            "tool_usage_recommended": recommendation,
            "recommendation_reason": (
                f"Schema has {len(large_arrays)} array field(s) with minItems > 50"
                if recommendation
                else "No large array constraints detected"
            ),
            "recommendation_strength": (
                "MANDATORY"
                if max_min_items >= 500  # Match OCR threshold
                else "STRONGLY_RECOMMENDED"
                if max_min_items >= 100  # Medium-large
                else "RECOMMENDED"
                if max_min_items >= 50  # Medium
                else "OPTIONAL"
            ),
        }

    def _analyze_ocr_for_tables(self, ocr_text: str) -> dict[str, Any]:
        """
        Analyze OCR text to detect large Markdown tables.

        This is the PRIMARY trigger for table parsing tool guidance, adapting
        automatically to documents of any size without requiring specific minItems.

        Returns:
            Dict with table detection results
        """
        import re

        # Detect Markdown table rows (lines with | delimiters)
        table_rows = []
        lines = ocr_text.split("\n")

        for i, line in enumerate(lines):
            stripped = line.strip()
            # Skip separator rows (e.g., |---|---|)
            if "|" in stripped and not re.match(r"^[\s|:-]+$", stripped):
                table_rows.append(i)

        # Estimate table count by gaps
        tables_detected = 0
        estimated_total_rows = 0
        if table_rows:
            tables_detected = 1
            gap_threshold = 5
            for i in range(1, len(table_rows)):
                if table_rows[i] - table_rows[i - 1] > gap_threshold:
                    tables_detected += 1
            estimated_total_rows = len(table_rows)

        # Adaptive thresholds - lower for better real-world coverage
        # These are optimized for automatic detection without minItems requirement
        recommendation = estimated_total_rows > 30

        return {
            "tables_detected": tables_detected,
            "estimated_row_count": estimated_total_rows,
            "tool_usage_recommended": recommendation,
            "recommendation_reason": (
                f"Detected {tables_detected} table(s) with ~{estimated_total_rows} total rows"
                if recommendation
                else "No large tables detected in OCR text"
            ),
            "recommendation_strength": (
                "MANDATORY"
                if estimated_total_rows >= 500  # Large documents
                else "STRONGLY_RECOMMENDED"
                if estimated_total_rows >= 100  # Medium-large tables
                else "RECOMMENDED"
                if estimated_total_rows >= 50  # Medium tables
                else "OPTIONAL"
            ),
        }

    def _build_table_parsing_guidance(
        self, schema_analysis: dict[str, Any], ocr_analysis: dict[str, Any]
    ) -> str:
        """Build custom table parsing guidance based on pre-flight analysis."""

        # Determine overall recommendation strength
        strengths = [
            schema_analysis.get("recommendation_strength", "OPTIONAL"),
            ocr_analysis.get("recommendation_strength", "OPTIONAL"),
        ]

        # Get the strongest recommendation
        strength_order = [
            "OPTIONAL",
            "RECOMMENDED",
            "STRONGLY_RECOMMENDED",
            "MANDATORY",
        ]
        max_strength = max(
            strengths,
            key=lambda x: strength_order.index(x) if x in strength_order else 0,
        )

        if max_strength == "MANDATORY":
            # For very large tables (500+ rows detected by OCR)
            guidance = """
**CRITICAL - MANDATORY TABLE PARSING TOOL USAGE**:
This document contains a large table with {row_count}+ rows detected by OCR analysis.
You MUST use the parse_table tool for complete and accurate extraction:

1. IMMEDIATELY call parse_table with the full document text or table section
2. DO NOT attempt manual row-by-row LLM extraction for large tables
3. Verify parse_table returned ALL expected rows (check row_count in response)
4. If parse_table returns fewer rows than expected, investigate warnings and ensure all
   table fragments are parsed (tables may be split across pages)

FAILURE TO USE parse_table will result in:
- Incomplete extraction (missing rows) - you will miss hundreds of data points
- Schema validation failures
- Excessive token usage (may hit context limits)
- Poor extraction performance

This is not optional - use the tool immediately for any tabular data.
"""
            return guidance.format(
                row_count=ocr_analysis.get("estimated_row_count", "500"),
            )

        elif max_strength == "STRONGLY_RECOMMENDED":
            # For medium-large tables (100-499 rows) - still use explicit instructions
            guidance = """
**IMPORTANT - USE TABLE PARSING TOOL**:
This document contains tabular data with {row_count}+ rows detected.
You MUST use the parse_table tool for accurate and complete extraction:

1. Call parse_table with the document text containing the table
2. The tool handles OCR artifacts (empty lines, page breaks) automatically
3. Verify the row_count matches your expectation
4. Review any warnings about table fragmentation
5. Map the parsed columns to the required schema fields

Using the tool ensures:
- Complete data extraction (no missing rows)
- Faster processing (10x more efficient than manual)
- Better accuracy (deterministic parsing of well-structured tables)

Do NOT attempt manual row-by-row extraction for tables with 100+ rows.
"""
            return guidance.format(
                row_count=ocr_analysis.get("estimated_row_count", "100"),
            )

        elif max_strength == "RECOMMENDED":
            # For medium tables (50-99 rows) - gentler guidance
            guidance = """
**RECOMMENDED - TABLE PARSING TOOL**:
Detected a table with {row_count}+ rows. Consider using the parse_table tool:

1. Call parse_table to extract the table data efficiently
2. Review the quality metrics and warnings
3. Fall back to LLM extraction if parse quality is poor

Benefits: Faster, more accurate, handles OCR artifacts automatically.
"""
            return guidance.format(
                row_count=ocr_analysis.get("estimated_row_count", "50"),
            )

        # Return empty for optional cases (standard TABLE_PARSING_PROMPT_ADDENDUM will be used)
        return ""

    def _explain_tool_usage_decision(
        self,
        expected: bool,
        actual: bool,
        schema_analysis: dict[str, Any] | None,
        ocr_analysis: dict[str, Any] | None,
    ) -> str:
        """Generate human-readable explanation of tool usage."""

        if expected and actual:
            return "Tool was recommended and used as expected"
        elif expected and not actual:
            reasons = []
            if schema_analysis and schema_analysis.get("tool_usage_recommended"):
                reasons.append(schema_analysis.get("recommendation_reason", ""))
            if ocr_analysis and ocr_analysis.get("tool_usage_recommended"):
                reasons.append(ocr_analysis.get("recommendation_reason", ""))
            return (
                f"Tool was recommended but NOT used. Reasons: {'; '.join(reasons)}. "
                f"This may indicate incomplete extraction."
            )
        elif not expected and actual:
            return "Tool was used even though not required (agent chose to use it)"
        else:
            return "Tool usage was not required and was not used"

    def _check_completeness_detailed(
        self,
        extracted_fields: dict[str, Any],
        schema: dict[str, Any],
        tool_used: bool,
    ) -> dict[str, Any]:
        """Detailed completeness check with violations."""

        violations = []
        properties = schema.get(SCHEMA_PROPERTIES, {})

        for field_name, field_def in properties.items():
            if field_def.get("type") == "array":
                min_items = field_def.get("minItems", 0)
                actual_items = len(extracted_fields.get(field_name) or [])

                if min_items > 0 and actual_items < min_items:
                    violations.append(
                        {
                            "field": field_name,
                            "constraint": f"minItems: {min_items}",
                            "actual": actual_items,
                            "shortfall": min_items - actual_items,
                            "completeness_pct": round(
                                100 * actual_items / min_items, 1
                            ),
                            "message": (
                                f"Extracted {actual_items} items but schema requires "
                                f"minimum {min_items} ({100 * actual_items / min_items:.1f}% complete)"
                            ),
                            "possible_cause": (
                                "Agent did not use table parsing tool"
                                if not tool_used
                                else "Table parsing may have stopped early"
                            ),
                        }
                    )

        return {
            "schema_constraints_met": len(violations) == 0,
            "violations": violations,
            "summary": (
                "All schema constraints satisfied"
                if not violations
                else f"{len(violations)} constraint violation(s) detected - extraction may be incomplete"
            ),
        }

    def _generate_processing_report(self, metadata: dict[str, Any]) -> str:
        """Generate user-friendly processing report."""

        report_lines = [
            "=== EXTRACTION PROCESSING REPORT ===",
            "",
            f"Extraction Method: {metadata.get('extraction_method', 'N/A').upper()}",
            f"Processing Time: {metadata.get('extraction_time_seconds', 0):.1f} seconds",
            f"Status: {'SUCCESS' if metadata.get('parsing_succeeded') else 'FAILED'}",
            "",
        ]

        # Schema analysis
        if "schema_analysis" in metadata:
            schema_info = metadata["schema_analysis"]
            report_lines.extend(
                [
                    "Schema Analysis:",
                    f"  - Large array fields detected: {len(schema_info.get('large_array_fields', []))}",
                    f"  - Maximum minItems constraint: {schema_info.get('max_min_items', 0)}",
                    f"  - Tool usage recommendation: {schema_info.get('recommendation_strength', 'N/A')}",
                    "",
                ]
            )

        # OCR analysis
        if "ocr_analysis" in metadata:
            ocr_info = metadata["ocr_analysis"]
            report_lines.extend(
                [
                    "OCR Table Detection:",
                    f"  - Tables detected: {ocr_info.get('tables_detected', 0)}",
                    f"  - Estimated total rows: {ocr_info.get('estimated_row_count', 0)}",
                    f"  - Tool usage recommendation: {ocr_info.get('recommendation_strength', 'N/A')}",
                    "",
                ]
            )

        # Tool usage decision
        if "tool_usage_decision" in metadata:
            decision = metadata["tool_usage_decision"]
            status_icon = "✓" if not decision.get("mismatch") else "⚠"
            report_lines.extend(
                [
                    f"{status_icon} Table Parsing Tool Decision:",
                    f"  - Expected usage: {'YES' if decision.get('expected') else 'NO'}",
                    f"  - Actual usage: {'YES' if decision.get('actual') else 'NO'}",
                    f"  - Explanation: {decision.get('explanation', 'N/A')}",
                    "",
                ]
            )

        # Completeness check
        if "completeness_check" in metadata:
            check = metadata["completeness_check"]
            status_icon = "✓" if check.get("schema_constraints_met") else "✗"
            report_lines.extend(
                [
                    f"{status_icon} Completeness Validation:",
                    f"  - {check.get('summary', 'N/A')}",
                    "",
                ]
            )

            if check.get("violations"):
                report_lines.append("  Detected Issues:")
                for v in check["violations"]:
                    report_lines.append(f"    • Field '{v['field']}': {v['message']}")
                    report_lines.append(f"      Possible cause: {v['possible_cause']}")
                report_lines.append("")

        # Table parsing stats (if used)
        if (
            metadata.get("table_parsing_tool_used")
            and "table_parsing_stats" in metadata
        ):
            stats = metadata["table_parsing_stats"]
            report_lines.extend(
                [
                    "✓ Table Parsing Tool Results:",
                    f"  - Tables parsed: {stats.get('tables_parsed', 0)}",
                    f"  - Total rows extracted: {stats.get('rows_parsed', 0)}",
                    f"  - Parse success rate: {stats.get('parse_success_rate') or 0:.1%}",
                    f"  - Avg OCR confidence: {stats.get('avg_confidence') or 0:.1f}%",
                    "",
                ]
            )

            if stats.get("warnings"):
                report_lines.append("  Warnings:")
                for w in stats["warnings"]:
                    report_lines.append(f"    {w}")
                report_lines.append("")

        report_lines.append("=" * 40)

        return "\n".join(report_lines)

    def _check_extraction_completeness(
        self,
        extracted_data: Any,
        data_model: Any,
        section_label: str,
    ) -> None:
        """
        Check if extraction meets schema constraints (e.g., min_length for arrays).

        Logs warnings if extracted data appears incomplete based on schema constraints.
        This helps catch cases where table parsing or extraction stopped early.

        Args:
            extracted_data: The extracted data instance (Pydantic model)
            data_model: The Pydantic model class with constraints
            section_label: Section label for logging context
        """
        if not hasattr(data_model, "model_fields"):
            return

        for field_name, field_info in data_model.model_fields.items():
            field_value = getattr(extracted_data, field_name, None)

            # Check array min_length constraints
            if isinstance(field_value, list) and hasattr(field_info, "metadata"):
                for constraint in field_info.metadata:
                    if hasattr(constraint, "min_length"):
                        expected_min = constraint.min_length
                        actual_count = len(field_value)

                        if actual_count < expected_min:
                            logger.warning(
                                f"Extraction may be INCOMPLETE for {section_label}: "
                                f"field '{field_name}' has {actual_count} items, "
                                f"but schema expects at least {expected_min}. "
                                f"Verify all table rows were extracted.",
                                extra={
                                    "field": field_name,
                                    "actual_count": actual_count,
                                    "expected_min": expected_min,
                                    "completeness_ratio": f"{actual_count}/{expected_min}",
                                },
                            )
                        elif actual_count == expected_min:
                            logger.info(
                                f"Extraction meets minimum constraint for {section_label}: "
                                f"field '{field_name}' has exactly {actual_count} items "
                                f"(minimum: {expected_min})"
                            )
                        else:
                            logger.debug(
                                f"Extraction exceeds minimum constraint for {section_label}: "
                                f"field '{field_name}' has {actual_count} items "
                                f"(minimum: {expected_min})"
                            )

    def _invoke_extraction_model(
        self,
        content: list[dict[str, Any]],
        system_prompt: str,
        section_info: SectionInfo,
        checkpoint_data: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        """
        Invoke Bedrock model (agentic or standard) and parse response.

        Args:
            content: Prompt content
            system_prompt: System prompt
            section_info: Section metadata

        Returns:
            ExtractionResult with extracted fields and metering
        """
        logger.info(
            f"Extracting fields for {section_info.class_label} document, section"
        )

        # Get extraction config — use per-class model override if specified,
        # otherwise fall back to the global extraction model.
        class_model_override = self._class_schema.get(X_AWS_IDP_EXTRACTION_MODEL)
        model_id = class_model_override or self.config.extraction.model
        if class_model_override:
            logger.info(
                f"Using per-class extraction model override for "
                f"'{section_info.class_label}': {model_id}"
            )
        temperature = self.config.extraction.temperature
        top_k = self.config.extraction.top_k
        top_p = self.config.extraction.top_p
        max_tokens = (
            self.config.extraction.max_tokens
            if self.config.extraction.max_tokens
            else None
        )

        # Time the model invocation
        request_start_time = time.time()

        # Initialize repair tracking variables
        output_truncated = False
        output_repaired = False
        repair_method = None

        # Initialize analysis tracking
        schema_analysis: dict[str, Any] | None = None
        ocr_analysis: dict[str, Any] | None = None

        if self.config.extraction.agentic.enabled:
            if not AGENTIC_AVAILABLE:
                raise ImportError(
                    "Agentic extraction requires Python 3.12+ and strands-agents dependencies. "
                    "Install with: pip install 'idp_common[agents]' or use agentic=False"
                )

            # Pre-flight analysis: Detect large tables and assess tool requirements
            schema_analysis = self._analyze_schema_for_table_requirements(
                self._class_schema
            )
            ocr_analysis = self._analyze_ocr_for_tables(self._document_text)

            logger.info(
                "Pre-flight analysis complete",
                extra={
                    "schema_recommendation": schema_analysis.get(
                        "recommendation_strength"
                    ),
                    "ocr_recommendation": ocr_analysis.get("recommendation_strength"),
                    "schema_max_min_items": schema_analysis.get("max_min_items"),
                    "ocr_estimated_rows": ocr_analysis.get("estimated_row_count"),
                },
            )

            # Create dynamic Pydantic model from JSON Schema
            dynamic_model = create_pydantic_model_from_json_schema(
                schema=self._class_schema,
                class_label=section_info.class_label,
                clean_schema=False,  # Already cleaned
            )

            # Log schema for debugging
            model_schema = dynamic_model.model_json_schema()
            logger.debug(f"Pydantic model schema for {section_info.class_label}:")
            logger.debug(json.dumps(model_schema, indent=2))

            # Use agentic extraction
            if isinstance(content, list):
                message_prompt = {"role": "user", "content": content}
            else:
                message_prompt = content

            logger.info("Using Agentic extraction")
            logger.debug(f"Using input: {str(message_prompt)}")

            # Convert checkpoint data for resume-on-timeout
            existing_data_model = None
            checkpoint_buffer = None
            if checkpoint_data:
                # Check if this is a buffer checkpoint (from intermediate_extraction)
                checkpoint_source = checkpoint_data.pop(
                    "_checkpoint_source", "current_extraction"
                )
                if checkpoint_source == "intermediate_extraction":
                    # Buffer checkpoint — load into agent's intermediate_extraction state
                    checkpoint_buffer = checkpoint_data
                    logger.info(
                        "Resuming agentic extraction from buffer checkpoint "
                        "(intermediate_extraction)"
                    )
                else:
                    # Validated extraction checkpoint — load as existing_data
                    try:
                        existing_data_model = dynamic_model(**checkpoint_data)
                        logger.info("Resuming agentic extraction from checkpoint data")
                    except Exception as e:
                        logger.warning(
                            f"Failed to validate checkpoint data, starting fresh: {e}"
                        )
                        existing_data_model = None

            # Build dynamic custom instruction based on pre-flight analysis
            custom_instruction = None
            if schema_analysis and ocr_analysis:
                dynamic_guidance = self._build_table_parsing_guidance(
                    schema_analysis=schema_analysis, ocr_analysis=ocr_analysis
                )
                if dynamic_guidance:
                    custom_instruction = dynamic_guidance
                    logger.info(
                        "Injecting dynamic table parsing guidance into agent instructions",
                        extra={
                            "schema_strength": schema_analysis.get(
                                "recommendation_strength"
                            ),
                            "ocr_strength": ocr_analysis.get("recommendation_strength"),
                        },
                    )

            # Pre-flight table parsing: parse all tables BEFORE LLM to avoid
            # the LLM having to call parse_table and then generate JSON row-by-row.
            # The LLM only needs to provide a column-to-field mapping, and the
            # map_table_to_schema tool does the bulk transformation instantly.
            preflight_parse_result = None
            if (
                self.config.extraction.agentic.table_parsing.enabled
                and ocr_analysis.get("estimated_row_count", 0) >= 50
            ):
                from idp_common.extraction.tools.table_parser import (
                    parse_markdown_tables,
                )

                tp_config = self.config.extraction.agentic.table_parsing
                preflight_parse_result = parse_markdown_tables(
                    text=self._document_text,
                    max_empty_line_gap=tp_config.max_empty_line_gap,
                    auto_merge_adjacent_tables=tp_config.auto_merge_adjacent_tables,
                )

                if preflight_parse_result.get("status") == "success":
                    total_rows = sum(
                        t.get("row_count", 0)
                        for t in preflight_parse_result.get("tables", [])
                    )
                    columns = preflight_parse_result.get("columns", [])
                    table_count = preflight_parse_result.get("table_count", 0)

                    logger.info(
                        "Pre-flight table parsing complete",
                        extra={
                            "total_rows": total_rows,
                            "table_count": table_count,
                            "columns": columns,
                        },
                    )

                    # Build efficient extraction guidance with pre-parsed summary
                    preflight_guidance = (
                        f"\n\n**PRE-PARSED TABLE DATA AVAILABLE**:\n"
                        f"Found {table_count} table(s) with {total_rows} total rows.\n"
                        f"Table columns: {columns}\n\n"
                        f"PAGE MARKERS: The document text contains '--- PAGE N ---' "
                        f"markers between pages. When you are assigned a page range, "
                        f"extract ONLY text between markers for your pages before "
                        f"calling parse_table.\n\n"
                        f"EFFICIENT EXTRACTION WORKFLOW:\n"
                        f"1. Extract scalar fields from your pages' text\n"
                        f"2. Call parse_table with your pages' text\n"
                        f"3. Call map_table_to_schema with column_mapping + static_fields\n"
                        f"   (merged rows are auto-split — no manual handling needed)\n"
                        f"4. Call finalize_table_extraction with table_array_field + "
                        f"scalar_fields\n\n"
                        f"finalize reads mapped rows from state — no JSON generation needed."
                    )

                    if custom_instruction:
                        custom_instruction += preflight_guidance
                    else:
                        custom_instruction = preflight_guidance

            # Determine if images should be sent to the agentic model.
            # If the task prompt does not reference {DOCUMENT_IMAGE}, sending
            # page images is wasteful and can cause context-window overflow
            # on large documents.
            prompt_template = self.config.extraction.task_prompt or ""
            send_images = "{DOCUMENT_IMAGE}" in prompt_template
            agentic_images = self._page_images if send_images else []
            num_pages = len(self._page_images) or len(section_info.sorted_page_ids)

            if not send_images and self._page_images:
                logger.info(
                    "Skipping image attachment for agentic extraction "
                    "(task prompt does not reference {DOCUMENT_IMAGE})",
                    extra={"page_count": num_pages},
                )

            # Use concurrent batch extraction if configured and enough pages
            num_batches = self.config.extraction.agentic.max_concurrent_batches

            if (
                num_batches > 1
                and num_pages >= num_batches
                and not existing_data_model  # Don't use concurrent mode for resume
                and not checkpoint_buffer
            ):
                import asyncio as _asyncio

                logger.info(
                    f"Using concurrent batch extraction with {num_batches} batches "
                    f"for {num_pages} pages"
                )
                structured_data, response_with_metering = _asyncio.run(
                    concurrent_structured_output_async(
                        model_id=model_id,
                        data_format=dynamic_model,
                        prompt=message_prompt,
                        page_images=agentic_images,
                        num_batches=num_batches,
                        config=self.config,
                        context="Extraction",
                        checkpoint_callback=self._checkpoint_callback,
                        custom_instruction=custom_instruction,
                        total_pages=num_pages,
                    )
                )
            else:
                structured_data, response_with_metering = structured_output(
                    model_id=model_id,
                    data_format=dynamic_model,
                    prompt=message_prompt,
                    existing_data=existing_data_model,
                    page_images=agentic_images,
                    config=self.config,
                    context="Extraction",
                    checkpoint_callback=self._checkpoint_callback,
                    checkpoint_buffer_data=checkpoint_buffer,
                    custom_instruction=custom_instruction,
                )

            extracted_fields = structured_data.model_dump(mode="json")
            metering = response_with_metering["metering"]
            parsing_succeeded = True

            # Check extraction completeness (warns if schema constraints not met)
            self._check_extraction_completeness(
                extracted_data=structured_data,
                data_model=dynamic_model,
                section_label=section_info.class_label,
            )
        else:
            # Standard Bedrock invocation
            response_with_metering = bedrock.invoke_model(
                model_id=model_id,
                system_prompt=system_prompt,
                content=content,
                temperature=temperature,
                top_k=top_k,
                top_p=top_p,
                max_tokens=max_tokens,
                context="Extraction",
                model_lambda_hook_arn=self.config.extraction.model_lambda_hook_arn,
            )

            extracted_text = bedrock.extract_text_from_response(
                dict(response_with_metering)
            )
            metering = response_with_metering["metering"]

            # Parse response into JSON
            extracted_fields = {}
            parsing_succeeded = True
            output_truncated = False
            output_repaired = False
            repair_method = None

            try:
                extracted_fields = json.loads(extract_json_from_text(extracted_text))
            except Exception as e:
                logger.warning(
                    f"Error parsing LLM output - attempting JSON repair: {e}"
                )

                # Attempt to repair truncated JSON
                repaired_data, repair_info = repair_truncated_json(extracted_text)
                output_truncated = repair_info.get("was_truncated", False)

                if repaired_data:
                    # Repair succeeded
                    extracted_fields = repaired_data
                    output_repaired = True
                    repair_method = repair_info.get("repair_method")
                    parsing_succeeded = True
                    logger.info(
                        f"JSON repair successful using '{repair_method}': "
                        f"recovered {repair_info.get('fields_recovered', 0)} fields"
                    )
                else:
                    # Repair failed - store raw output
                    logger.error(
                        f"JSON repair failed: {repair_info.get('error', 'unknown error')}. "
                        f"Raw output preview: {extracted_text[:500]}..."
                    )
                    extracted_fields = {"raw_output": extracted_text}
                    parsing_succeeded = False

        total_duration = time.time() - request_start_time
        logger.info(f"Time taken for extraction: {total_duration:.2f} seconds")

        return ExtractionResult(
            extracted_fields=extracted_fields,
            metering=metering,
            parsing_succeeded=parsing_succeeded,
            total_duration=total_duration,
            output_truncated=output_truncated,
            output_repaired=output_repaired,
            repair_method=repair_method,
            schema_analysis=schema_analysis,
            ocr_analysis=ocr_analysis,
        )

    def _save_results(
        self,
        document: Document,
        section: Any,
        result: ExtractionResult,
        section_info: SectionInfo,
        section_id: str,
        t0: float,
    ) -> None:
        """
        Save extraction results to S3 and update document.

        Args:
            document: Document being processed
            section: Section being processed
            result: Extraction result
            section_info: Section metadata
            section_id: Section ID
            t0: Start time
        """
        # Determine extraction method
        extraction_method = (
            "agentic" if self.config.extraction.agentic.enabled else "traditional"
        )

        # Check if table parsing tool was used (extract from metering before building metadata)
        tool_used = False
        table_stats = None
        if extraction_method == "agentic" and result.metering:
            table_stats = result.metering.pop("_table_parsing_stats", None)
            tool_used = table_stats is not None

        # Build base metadata
        metadata: dict[str, Any] = {
            "parsing_succeeded": result.parsing_succeeded,
            "extraction_time_seconds": result.total_duration,
            "extraction_method": extraction_method,
        }

        # Add pre-flight analysis results (if agentic)
        if extraction_method == "agentic":
            if result.schema_analysis:
                metadata["schema_analysis"] = result.schema_analysis
            if result.ocr_analysis:
                metadata["ocr_analysis"] = result.ocr_analysis

            # Track tool usage decision
            tool_expected = False
            if result.schema_analysis or result.ocr_analysis:
                tool_expected = (
                    result.schema_analysis.get("tool_usage_recommended", False)
                    if result.schema_analysis
                    else False
                ) or (
                    result.ocr_analysis.get("tool_usage_recommended", False)
                    if result.ocr_analysis
                    else False
                )

                metadata["tool_usage_decision"] = {
                    "expected": tool_expected,
                    "actual": tool_used,
                    "mismatch": tool_expected != tool_used,
                    "explanation": self._explain_tool_usage_decision(
                        expected=tool_expected,
                        actual=tool_used,
                        schema_analysis=result.schema_analysis,
                        ocr_analysis=result.ocr_analysis,
                    ),
                }

            # Validate completeness
            if result.schema_analysis or result.ocr_analysis:
                metadata["completeness_check"] = self._check_completeness_detailed(
                    extracted_fields=result.extracted_fields,
                    schema=self._class_schema,
                    tool_used=tool_used,
                )

        # Add table parsing stats if tool was used
        if tool_used and table_stats:
            metadata["table_parsing_tool_used"] = True
            metadata["table_parsing_stats"] = table_stats
        elif (
            extraction_method == "agentic"
            and self.config.extraction.agentic.table_parsing.enabled
        ):
            metadata["table_parsing_tool_used"] = False

        # Add truncation/repair metadata when relevant
        if result.output_truncated:
            metadata["output_truncated"] = True
        if result.output_repaired:
            metadata["output_repaired"] = True
            metadata["repair_method"] = result.repair_method

        # Generate user-friendly processing report
        processing_report = self._generate_processing_report(metadata)
        logger.info(f"Processing Report:\n{processing_report}")

        # Write to S3 with processing report
        output = {
            "document_class": {"type": section_info.class_label},
            "split_document": {"page_indices": section_info.page_indices},
            "inference_result": result.extracted_fields,
            "metadata": metadata,
            "processing_report": processing_report,
        }
        s3.write_content(
            output,
            section_info.output_bucket,
            section_info.output_key,
            content_type="application/json",
        )

        # Update section and document
        section.extraction_result_uri = section_info.output_uri
        document.metering = utils.merge_metering_data(
            document.metering, result.metering or {}
        )

        t3 = time.time()
        logger.info(
            f"Total extraction time for section {section_id}: {t3 - t0:.2f} seconds"
        )

    def process_document_section(
        self,
        document: Document,
        section_id: str,
        checkpoint_data: dict[str, Any] | None = None,
    ) -> Document:
        """
        Process a single section from a Document object.

        Args:
            document: Document object containing section to process
            section_id: ID of the section to process
            checkpoint_data: Optional partial extraction data from a previous
                timed-out invocation.  When provided the agentic agent will
                resume from this state instead of starting from scratch.

        Returns:
            Document: Updated Document object with extraction results for the section
        """
        # Reset state
        self._reset_context()

        # Validate and get section
        section = self._validate_and_find_section(document, section_id)
        if not section:
            return document

        # Short-circuit: skip sections whose class is marked
        # x-aws-idp-exclude-from-processing=true (e.g., static instruction
        # pages). A stub result.json is written so reporting / UI can show
        # a meaningful message.
        from idp_common.section_exclusion import (
            is_section_excluded,
            write_skipped_stub,
        )

        if is_section_excluded(section):
            output_bucket = document.output_bucket
            output_key = (
                f"{document.input_key}/sections/{section.section_id}/result.json"
                if document.input_key
                else None
            )
            stub_uri = write_skipped_stub(
                document,
                section,
                stage="extraction",
                output_bucket=output_bucket,
                output_key=output_key,
            )
            if stub_uri:
                section.extraction_result_uri = stub_uri
            logger.info(
                "Extraction skipped for excluded section %s (class=%s, reason=%s)",
                section.section_id,
                section.classification,
                section.exclusion_reason or "excluded",
            )
            return document

        # Prepare section metadata
        try:
            section_info = self._prepare_section_info(document, section)
        except ValueError:
            return document

        try:
            t0 = time.time()

            # Load document content
            document_text = self._load_document_text(
                document, section_info.sorted_page_ids
            )
            page_images = self._load_document_images(
                document, section_info.sorted_page_ids
            )

            # Initialize extraction context
            class_schema, attribute_descriptions = self._initialize_extraction_context(
                section_info.class_label,
                document_text,
                page_images,
                section_info.sorted_page_ids,
                document,
            )

            # Handle empty schema case (early return)
            if (
                not class_schema.get(SCHEMA_PROPERTIES)
                or not attribute_descriptions.strip()
            ):
                return self._handle_empty_schema(
                    document, section, section_info, section_id, t0
                )

            # Build prompt content
            content, system_prompt = self._build_extraction_content(
                document, page_images
            )

            # Load OCR confidence data for table parsing tool (if enabled)
            # Confidence data is only available from Textract OCR backend.
            # For Bedrock OCR or other backends, skip loading — the tool
            # handles missing confidence gracefully (confidence_available=false).
            if (
                AGENTIC_AVAILABLE
                and self.config.extraction.agentic.enabled
                and self.config.extraction.agentic.table_parsing.enabled
                and self.config.extraction.agentic.table_parsing.use_confidence_data
                and self.config.ocr.backend == "textract"
            ):
                confidence_data_by_page = self._load_confidence_data(
                    document, section_info.sorted_page_ids
                )
                set_confidence_data(confidence_data_by_page)
                logger.info(
                    f"Loaded OCR confidence data for table parsing tool: "
                    f"{len(confidence_data_by_page)} pages"
                )
            elif AGENTIC_AVAILABLE and self.config.extraction.agentic.enabled:
                set_confidence_data(None)
                if (
                    self.config.extraction.agentic.table_parsing.enabled
                    and self.config.ocr.backend != "textract"
                ):
                    logger.info(
                        "Table parsing tool enabled without confidence data "
                        f"(OCR backend: {self.config.ocr.backend})"
                    )

            # Invoke model (pass checkpoint_data for agentic resume-on-timeout)
            result = self._invoke_extraction_model(
                content, system_prompt, section_info, checkpoint_data=checkpoint_data
            )

            # Save results
            self._save_results(document, section, result, section_info, section_id, t0)

        except Exception as e:
            error_msg = f"Error processing section {section_id}: {str(e)}"
            logger.error(error_msg)
            document.errors.append(error_msg)
            raise

        return document
