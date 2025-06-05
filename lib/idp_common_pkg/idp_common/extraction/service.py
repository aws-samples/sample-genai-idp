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
from typing import Any, Dict, List

from idp_common import bedrock, image, metrics, s3, utils
from idp_common.models import Document

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
        return class_config.get("attributes", []) if class_config else []

    def _format_attribute_descriptions(self, attributes: List[Dict[str, Any]]) -> str:
        """
        Format attribute descriptions for the prompt.

        Args:
            attributes: List of attribute configurations

        Returns:
            Formatted attribute descriptions as a string
        """
        return "\n".join(
            [
                f"{attr.get('name', '')}  \t[ {attr.get('description', '')} ]"
                for attr in attributes
            ]
        )

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

        Args:
            prompt_template: The prompt template that may contain {DOCUMENT_IMAGE}
            document_text: The document text content
            class_label: The document class label
            attribute_descriptions: Formatted attribute names and descriptions
            image_content: Optional image content to insert

        Returns:
            List of content items with text and image content properly ordered
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

        Args:
            prompt_template: The prompt template
            document_text: The document text content
            class_label: The document class label
            attribute_descriptions: Formatted attribute names and descriptions
            image_content: Optional image content to append at the end

        Returns:
            List of content items with text and image content
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

        # Add image at the end if available
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

        # If no DOCUMENT_IMAGE placeholder was found in either part and we have image content,
        # append it at the end (fallback behavior)
        if image_content and "{DOCUMENT_IMAGE}" not in task_prompt_template:
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

            # Read page images
            page_images = []
            for page_id in sorted_page_ids:
                if page_id not in document.pages:
                    continue

                page = document.pages[page_id]
                image_uri = page.image_uri
                image_content = image.prepare_image(image_uri)
                page_images.append(image_content)

            t2 = time.time()
            logger.info(f"Time taken to read images: {t2 - t1:.2f} seconds")

            # Get extraction configuration
            extraction_config = self.config.get("extraction", {})
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

            # Prepare prompt
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
                        content = self._build_content_with_or_without_image_placeholder(
                            prompt_template,
                            document_text,
                            class_label,
                            attribute_descriptions,
                            page_images,  # Pass images to the content builder
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

            total_duration = time.time() - request_start_time
            logger.info(f"Time taken for extraction: {total_duration:.2f} seconds")

            # Extract text from response
            extracted_text = bedrock.extract_text_from_response(response_with_metering)
            metering = response_with_metering.get("metering", {})

            # Parse response into JSON
            extracted_fields = {}
            parsing_succeeded = True  # Flag to track if parsing was successful

            try:
                # Try to parse the extracted text as JSON
                extracted_fields = json.loads(self._extract_json(extracted_text))
            except Exception as e:
                # Handle parsing error
                logger.error(
                    f"Error parsing LLM output - invalid JSON?: {extracted_text} - {e}"
                )
                logger.info("Using unparsed LLM output.")
                extracted_fields = {"raw_output": extracted_text}
                parsing_succeeded = False  # Mark that parsing failed

            # Write to S3
            output = {
                "document_class": {"type": class_label},
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

    def _extract_json(self, text: str) -> str:
        """
        Extract JSON string from text response.

        Args:
            text: The text response from the model

        Returns:
            Extracted JSON string
        """
        # Check for code block format
        if "```json" in text:
            start_idx = text.find("```json") + len("```json")
            end_idx = text.find("```", start_idx)
            if end_idx > start_idx:
                return text[start_idx:end_idx].strip()
        elif "```" in text:
            start_idx = text.find("```") + len("```")
            end_idx = text.find("```", start_idx)
            if end_idx > start_idx:
                return text[start_idx:end_idx].strip()

        # Check for simple JSON
        if "{" in text and "}" in text:
            start_idx = text.find("{")
            # Find matching closing brace
            open_braces = 0
            for i in range(start_idx, len(text)):
                if text[i] == "{":
                    open_braces += 1
                elif text[i] == "}":
                    open_braces -= 1
                    if open_braces == 0:
                        return text[start_idx : i + 1].strip()

        # If we can't find JSON, return the text as-is
        return text
