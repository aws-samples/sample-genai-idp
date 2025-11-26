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
)
from idp_common.models import Document
from idp_common.utils.few_shot_example_builder import (
    build_few_shot_extraction_examples_content,
)

# Conditional import for agentic extraction (requires Python 3.10+ dependencies)
try:
    from idp_common.extraction.agentic_idp import structured_output
    from idp_common.schema import create_pydantic_model_from_json_schema

    AGENTIC_AVAILABLE = True
except ImportError:
    AGENTIC_AVAILABLE = False
from pydantic import BaseModel

from idp_common.utils import extract_json_from_text

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

        # Add image attachments to the content (limit to 20 images as per Bedrock constraints)
        if self._page_images:
            logger.info(
                f"Attaching images to default prompt, for {len(self._page_images)} pages."
            )
            # Limit to 20 images as per Bedrock constraints
            for img in self._page_images[:20]:
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
                    self._clean_schema_for_prompt(item)
                    if isinstance(item, dict)
                    else item
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
        Prepare image attachments for Bedrock, limiting to 20 images.

        Args:
            image_content: Single image or list of images

        Returns:
            List of image attachment dicts
        """
        attachments: list[dict[str, Any]] = []

        if isinstance(image_content, list):
            # Multiple images (limit to 20 as per Bedrock constraints)
            if len(image_content) > 20:
                logger.warning(
                    f"Found {len(image_content)} images, truncating to 20 due to Bedrock constraints. "
                    f"{len(image_content) - 20} images will be dropped."
                )
            for img in image_content[:20]:
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

        # Find minimum page ID across all sections
        min_page_id = min(
            int(page_id) for sec in document.sections for page_id in sec.page_ids
        )

        # Adjust page indices to be zero-based
        page_indices = [int(page_id) - min_page_id for page_id in sorted_page_ids]

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

        document_text = "\n".join(document_texts)
        t1 = time.time()
        logger.info(f"Time taken to read text content: {t1 - t0:.2f} seconds")

        return document_text

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

    def _invoke_extraction_model(
        self,
        content: list[dict[str, Any]],
        system_prompt: str,
        section_info: SectionInfo,
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

        # Get extraction config
        model_id = self.config.extraction.model
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

        if self.config.extraction.agentic.enabled:
            if not AGENTIC_AVAILABLE:
                raise ImportError(
                    "Agentic extraction requires Python 3.10+ and strands-agents dependencies. "
                    "Install with: pip install 'idp_common[agents]' or use agentic=False"
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

            structured_data, response_with_metering = structured_output(
                model_id=model_id,
                data_format=dynamic_model,
                prompt=message_prompt,
                page_images=self._page_images,
                config=self.config,
                context="Extraction",
            )

            extracted_fields = structured_data.model_dump(mode="json")
            metering = response_with_metering["metering"]
            parsing_succeeded = True
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
            )

            extracted_text = bedrock.extract_text_from_response(
                dict(response_with_metering)
            )
            metering = response_with_metering["metering"]

            # Parse response into JSON
            extracted_fields = {}
            parsing_succeeded = True

            try:
                extracted_fields = json.loads(extract_json_from_text(extracted_text))
            except Exception as e:
                logger.error(
                    f"Error parsing LLM output - invalid JSON?: {extracted_text} - {e}"
                )
                logger.info("Using unparsed LLM output.")
                extracted_fields = {"raw_output": extracted_text}
                parsing_succeeded = False

        total_duration = time.time() - request_start_time
        logger.info(f"Time taken for extraction: {total_duration:.2f} seconds")

        return ExtractionResult(
            extracted_fields=extracted_fields,
            metering=metering,
            parsing_succeeded=parsing_succeeded,
            total_duration=total_duration,
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
        # Write to S3
        output = {
            "document_class": {"type": section_info.class_label},
            "split_document": {"page_indices": section_info.page_indices},
            "inference_result": result.extracted_fields,
            "metadata": {
                "parsing_succeeded": result.parsing_succeeded,
                "extraction_time_seconds": result.total_duration,
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
        document.metering = utils.merge_metering_data(
            document.metering, result.metering or {}
        )

        t3 = time.time()
        logger.info(
            f"Total extraction time for section {section_id}: {t3 - t0:.2f} seconds"
        )

    def process_document_section(self, document: Document, section_id: str) -> Document:
        """
        Process a single section from a Document object.

        Args:
            document: Document object containing section to process
            section_id: ID of the section to process

        Returns:
            Document: Updated Document object with extraction results for the section
        """
        # Reset state
        self._reset_context()

        # Validate and get section
        section = self._validate_and_find_section(document, section_id)
        if not section:
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

            # Invoke model
            result = self._invoke_extraction_model(content, system_prompt, section_info)

            # Save results
            self._save_results(document, section, result, section_info, section_id, t0)

        except Exception as e:
            error_msg = f"Error processing section {section_id}: {str(e)}"
            logger.error(error_msg)
            document.errors.append(error_msg)
            raise

        return document
