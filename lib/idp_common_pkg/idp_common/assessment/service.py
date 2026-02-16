# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Assessment service for evaluating document extraction confidence using LLMs.

This module provides a service for assessing the confidence and accuracy of
extraction results by analyzing them against source documents using LLMs,
with support for text and image content.

The service supports both:
1. Original approach: Single inference for all attributes in a section
2. Granular approach: Multiple focused inferences with caching and parallelization
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Union

from idp_common import bedrock, image, metrics, s3, utils
from idp_common.config.models import IDPConfig
from idp_common.config.schema_constants import (
    SCHEMA_DESCRIPTION,
    SCHEMA_ITEMS,
    SCHEMA_PROPERTIES,
    SCHEMA_TYPE,
    TYPE_ARRAY,
    TYPE_OBJECT,
    TYPE_STRING,
    X_AWS_IDP_CONFIDENCE_THRESHOLD,
    X_AWS_IDP_DOCUMENT_TYPE,
    X_AWS_IDP_LIST_ITEM_DESCRIPTION,
)
from idp_common.models import Document
from idp_common.utils import extract_json_from_text

logger = logging.getLogger(__name__)


def _safe_float_conversion(value: Any, default: float = 0.0) -> float:
    """
    Safely convert a value to float, handling strings and None values.

    Args:
        value: Value to convert to float
        default: Default value if conversion fails

    Returns:
        Float value or default if conversion fails
    """
    if value is None:
        return default

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        # Handle empty strings
        if not value.strip():
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            logger.warning(
                f"Could not convert string '{value}' to float, using default {default}"
            )
            return default

    # Handle other types by attempting conversion
    try:
        return float(value)
    except (ValueError, TypeError):
        logger.warning(
            f"Could not convert {type(value)} '{value}' to float, using default {default}"
        )
        return default


class AssessmentService:
    """Service for assessing extraction result confidence using LLMs."""

    def __init__(
        self,
        region: str | None = None,
        config: Union[Dict[str, Any], IDPConfig, None] = None,
    ):
        """
        Initialize the assessment service.

        Args:
            region: AWS region for Bedrock
            config: Configuration dictionary or IDPConfig model
        """
        # Convert config to IDPConfig if needed
        if config is None:
            config_model = IDPConfig()
        elif isinstance(config, IDPConfig):
            config_model = config
        elif isinstance(config, dict):
            config_model = IDPConfig(**config)
        else:
            # Fallback: attempt conversion for other types
            try:
                config_model = IDPConfig(**config)
            except Exception as e:
                logger.error(f"Failed to convert config to IDPConfig: {e}")
                raise ValueError(
                    f"Invalid config type: {type(config)}. Expected None, dict, or IDPConfig instance."
                )

        self.config = config_model
        self.region = region or os.environ.get("AWS_REGION")

        # Get model_id from typed config for logging
        model_id = self.config.assessment.model
        logger.info(f"Initialized assessment service with model {model_id}")

    def _get_class_schema(self, class_label: str) -> Dict[str, Any]:
        """
        Get JSON Schema for a specific document class.

        Args:
            class_label: The document class name

        Returns:
            JSON Schema dict for the class, or empty dict if not found
        """
        # Type-safe access to classes
        classes = self.config.classes
        for schema in classes:
            if schema.get(X_AWS_IDP_DOCUMENT_TYPE, "").lower() == class_label.lower():
                return schema
        return {}

    def _format_property_descriptions(self, schema: Dict[str, Any]) -> str:
        """
        Format property descriptions from JSON Schema for the prompt.

        Args:
            schema: JSON Schema dict for the document class

        Returns:
            Formatted property descriptions as a string
        """
        properties = schema.get(SCHEMA_PROPERTIES, {})
        formatted_lines = []

        for prop_name, prop_schema in properties.items():
            prop_type = prop_schema.get(SCHEMA_TYPE)
            description = prop_schema.get(SCHEMA_DESCRIPTION, "")

            if prop_type == TYPE_OBJECT:
                formatted_lines.append(f"{prop_name}  \t[ {description} ]")
                nested_props = prop_schema.get(SCHEMA_PROPERTIES, {})
                for nested_name, nested_schema in nested_props.items():
                    nested_desc = nested_schema.get(SCHEMA_DESCRIPTION, "")
                    formatted_lines.append(f"  - {nested_name}  \t[ {nested_desc} ]")

            elif prop_type == TYPE_ARRAY:
                formatted_lines.append(f"{prop_name}  \t[ {description} ]")
                items_schema = prop_schema.get(SCHEMA_ITEMS, {})

                item_desc = prop_schema.get(X_AWS_IDP_LIST_ITEM_DESCRIPTION, "")
                if item_desc:
                    formatted_lines.append(f"  Each item: {item_desc}")

                if items_schema.get(SCHEMA_TYPE) == TYPE_OBJECT:
                    item_props = items_schema.get(SCHEMA_PROPERTIES, {})
                    for item_name, item_schema in item_props.items():
                        item_prop_desc = item_schema.get(SCHEMA_DESCRIPTION, "")
                        formatted_lines.append(
                            f"  - {item_name}  \t[ {item_prop_desc} ]"
                        )
            else:
                formatted_lines.append(f"{prop_name}  \t[ {description} ]")

        return "\n".join(formatted_lines)

    def _enhance_dict_assessment(
        self, assessment_dict: Dict[str, Any], threshold: float
    ) -> Dict[str, Any]:
        """
        Enhance an assessment dictionary by adding confidence thresholds to confidence assessments.

        Args:
            assessment_dict: Dictionary containing assessment data
            threshold: Confidence threshold to add

        Returns:
            Enhanced assessment dictionary
        """
        # Safety check: ensure assessment_dict is actually a dictionary
        if not isinstance(assessment_dict, dict):
            logger.warning(
                f"Expected dictionary for assessment enhancement, got {type(assessment_dict)}. "
                f"Creating default assessment structure."
            )
            return {
                "confidence": 0.5,
                "confidence_reason": f"LLM returned unexpected type {type(assessment_dict)} instead of dictionary. Using default confidence.",
                "confidence_threshold": threshold,
            }

        # Check if this dictionary itself is a confidence assessment
        if "confidence" in assessment_dict:
            # This is a direct confidence assessment - add threshold
            return {
                **assessment_dict,
                "confidence_threshold": threshold,
            }

        # Otherwise, check nested values for confidence assessments
        enhanced = {}
        for key, value in assessment_dict.items():
            if isinstance(value, dict) and "confidence" in value:
                # This is a nested confidence assessment - add threshold
                enhanced[key] = {
                    **value,
                    "confidence_threshold": threshold,
                }
            elif isinstance(value, dict):
                # Recursively process nested dictionaries
                enhanced[key] = self._enhance_dict_assessment(value, threshold)
            else:
                # Not a confidence assessment - pass through unchanged
                enhanced[key] = value
        return enhanced

    def _check_confidence_alerts(
        self,
        assessment_data: Dict[str, Any],
        attr_name: str,
        threshold: float,
        alerts_list: List[Dict[str, Any]],
    ) -> None:
        """
        Check assessment data for confidence threshold violations and add alerts.

        Args:
            assessment_data: Dictionary containing assessment data
            attr_name: Name of the attribute being assessed
            threshold: Confidence threshold to check against
            alerts_list: List to append alerts to (modified in place)
        """
        # Safety check: ensure assessment_data is actually a dictionary
        if not isinstance(assessment_data, dict):
            logger.warning(
                f"Expected dictionary for confidence alert checking, got {type(assessment_data)} for attribute '{attr_name}'. "
                f"Skipping confidence alert check."
            )
            return

        # Safety check: ensure threshold is a valid float
        safe_threshold = _safe_float_conversion(threshold, 0.9)

        # First check if this assessment_data itself is a direct confidence assessment
        if "confidence" in assessment_data:
            confidence = _safe_float_conversion(
                assessment_data.get("confidence", 0.0), 0.0
            )
            if confidence < safe_threshold:
                alerts_list.append(
                    {
                        "attribute_name": attr_name,
                        "confidence": confidence,
                        "confidence_threshold": safe_threshold,
                    }
                )

        # Then check for nested sub-attributes (for group/complex attributes)
        for sub_attr_name, sub_assessment in assessment_data.items():
            if isinstance(sub_assessment, dict) and "confidence" in sub_assessment:
                confidence = _safe_float_conversion(
                    sub_assessment.get("confidence", 0.0), 0.0
                )
                if confidence < safe_threshold:
                    full_attr_name = (
                        f"{attr_name}.{sub_attr_name}"
                        if "." not in attr_name
                        else f"{attr_name}.{sub_attr_name}"
                    )
                    alerts_list.append(
                        {
                            "attribute_name": full_attr_name,
                            "confidence": confidence,
                            "confidence_threshold": safe_threshold,
                        }
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
        extraction_results: str,
        ocr_text_confidence: str = "",
        image_content: Any = None,
    ) -> List[Dict[str, Any]]:
        """
        Build content array, automatically deciding whether to use image placeholder processing.

        Args:
            prompt_template: The prompt template that may contain {DOCUMENT_IMAGE}
            document_text: The document text content
            class_label: The document class label
            attribute_descriptions: Formatted attribute names and descriptions
            extraction_results: JSON string of extraction results to assess
            ocr_text_confidence: Raw OCR results with confidence scores
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
                extraction_results,
                ocr_text_confidence,
                image_content,
            )
        else:
            return self._build_content_without_image_placeholder(
                prompt_template,
                document_text,
                class_label,
                attribute_descriptions,
                extraction_results,
                ocr_text_confidence,
                image_content,
            )

    def _build_content_with_image_placeholder(
        self,
        prompt_template: str,
        document_text: str,
        class_label: str,
        attribute_descriptions: str,
        extraction_results: str,
        ocr_text_confidence: str,
        image_content: Any = None,
    ) -> List[Dict[str, Any]]:
        """
        Build content array with image inserted at DOCUMENT_IMAGE placeholder if present.

        Args:
            prompt_template: The prompt template that may contain {DOCUMENT_IMAGE}
            document_text: The document text content
            class_label: The document class label
            attribute_descriptions: Formatted attribute names and descriptions
            extraction_results: JSON string of extraction results to assess
            ocr_text_confidence: Raw OCR results with confidence scores
            image_content: Optional image content to insert

        Returns:
            List of content items with text and image content properly ordered
        """
        # Split the prompt at the DOCUMENT_IMAGE placeholder
        parts = prompt_template.split("{DOCUMENT_IMAGE}")

        if len(parts) != 2:
            raise ValueError(
                f"Invalid DOCUMENT_IMAGE placeholder usage: found {len(parts) - 1} occurrences, "
                f"but exactly 1 is required. The DOCUMENT_IMAGE placeholder must appear exactly once in the template."
            )

        # Process the parts before and after the image placeholder
        before_image = self._prepare_prompt_from_template(
            parts[0],
            {
                "DOCUMENT_TEXT": document_text,
                "DOCUMENT_CLASS": class_label,
                "ATTRIBUTE_NAMES_AND_DESCRIPTIONS": attribute_descriptions,
                "EXTRACTION_RESULTS": extraction_results,
                "OCR_TEXT_CONFIDENCE": ocr_text_confidence,
            },
            required_placeholders=[],  # Don't enforce required placeholders for partial templates
        )

        after_image = self._prepare_prompt_from_template(
            parts[1],
            {
                "DOCUMENT_TEXT": document_text,
                "DOCUMENT_CLASS": class_label,
                "ATTRIBUTE_NAMES_AND_DESCRIPTIONS": attribute_descriptions,
                "EXTRACTION_RESULTS": extraction_results,
                "OCR_TEXT_CONFIDENCE": ocr_text_confidence,
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
                # Multiple images - no limit with latest Bedrock API
                logger.info(
                    f"Attaching {len(image_content)} images to assessment prompt"
                )
                for img in image_content:
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
        extraction_results: str,
        ocr_text_confidence: str,
        image_content: Any = None,
    ) -> List[Dict[str, Any]]:
        """
        Build content array without DOCUMENT_IMAGE placeholder (text-only processing).

        Args:
            prompt_template: The prompt template
            document_text: The document text content
            class_label: The document class label
            attribute_descriptions: Formatted attribute names and descriptions
            extraction_results: JSON string of extraction results to assess
            ocr_text_confidence: Raw OCR results with confidence scores
            image_content: Ignored - images are only attached when DOCUMENT_IMAGE placeholder is present

        Returns:
            List of content items with text content only
        """
        # Prepare the full prompt
        task_prompt = self._prepare_prompt_from_template(
            prompt_template,
            {
                "DOCUMENT_TEXT": document_text,
                "DOCUMENT_CLASS": class_label,
                "ATTRIBUTE_NAMES_AND_DESCRIPTIONS": attribute_descriptions,
                "EXTRACTION_RESULTS": extraction_results,
                "OCR_TEXT_CONFIDENCE": ocr_text_confidence,
            },
            required_placeholders=[],
        )

        # Return text content only - no images unless DOCUMENT_IMAGE placeholder is used
        return [{"text": task_prompt}]

    def _get_text_confidence_data(self, page) -> str:
        """
        Get text confidence data for a page from pre-generated text confidence files.

        Args:
            page: Page object containing OCR URIs

        Returns:
            JSON string of text confidence data, or empty string if unavailable
        """
        # First try to use the pre-generated text confidence file
        if hasattr(page, "text_confidence_uri") and page.text_confidence_uri:
            try:
                text_confidence_data = s3.get_json_content(page.text_confidence_uri)
                return json.dumps(text_confidence_data, indent=2)
            except Exception as e:
                logger.warning(
                    f"Failed to read text confidence data for page {page.page_id}: {str(e)}"
                )

        # Fallback: use raw OCR data if text confidence is not available (for backward compatibility)
        if page.raw_text_uri:
            try:
                from idp_common.ocr.service import OcrService

                ocr_service = OcrService()
                raw_ocr_data = s3.get_json_content(page.raw_text_uri)
                text_confidence_data = ocr_service._generate_text_confidence_data(
                    raw_ocr_data
                )
                return json.dumps(text_confidence_data, indent=2)
            except Exception as e:
                logger.warning(
                    f"Failed to generate text confidence data for page {page.page_id}: {str(e)}"
                )

        return ""

    def _convert_bbox_to_geometry(
        self, bbox_coords: List[float], page_num: int
    ) -> Dict[str, Any]:
        """
        Convert [x1,y1,x2,y2] coordinates to geometry format.

        Args:
            bbox_coords: List of 4 coordinates [x1, y1, x2, y2] in 0-1000 scale
            page_num: Page number where the bounding box appears

        Returns:
            Dictionary in geometry format compatible with pattern-1 UI
        """
        if len(bbox_coords) != 4:
            raise ValueError(f"Expected 4 coordinates, got {len(bbox_coords)}")

        x1, y1, x2, y2 = bbox_coords

        # Ensure coordinates are in correct order
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)

        # Convert from normalized 0-1000 scale to 0-1
        left = x1 / 1000.0
        top = y1 / 1000.0
        width = (x2 - x1) / 1000.0
        height = (y2 - y1) / 1000.0

        return {
            "boundingBox": {"top": top, "left": left, "width": width, "height": height},
            "page": page_num,
        }

    def _process_single_assessment_geometry(
        self, attr_assessment: Dict[str, Any], attr_name: str = ""
    ) -> Dict[str, Any]:
        """
        Process geometry data for a single assessment (with confidence key).

        Args:
            attr_assessment: Single assessment dictionary with confidence data
            attr_name: Name of attribute for logging

        Returns:
            Enhanced assessment with geometry converted to proper format
        """
        enhanced_attr = attr_assessment.copy()

        # Check if this assessment includes bbox data
        if "bbox" in attr_assessment or "page" in attr_assessment:
            # Both bbox and page are required for valid geometry
            if "bbox" in attr_assessment and "page" in attr_assessment:
                try:
                    bbox_coords = attr_assessment["bbox"]
                    page_num = attr_assessment["page"]

                    # Validate bbox coordinates
                    if isinstance(bbox_coords, list) and len(bbox_coords) == 4:
                        # Convert to geometry format
                        geometry = self._convert_bbox_to_geometry(bbox_coords, page_num)
                        enhanced_attr["geometry"] = [geometry]

                        logger.debug(
                            f"Converted bounding box for {attr_name}: {bbox_coords} -> geometry format"
                        )
                    else:
                        logger.warning(
                            f"Invalid bounding box format for {attr_name}: {bbox_coords}"
                        )

                except Exception as e:
                    logger.warning(
                        f"Failed to process bounding box for {attr_name}: {str(e)}"
                    )
            else:
                # If only one of bbox/page exists, log a warning about incomplete data
                if "bbox" in attr_assessment and "page" not in attr_assessment:
                    logger.warning(
                        f"Found bbox without page for {attr_name} - removing incomplete bbox data"
                    )
                elif "page" in attr_assessment and "bbox" not in attr_assessment:
                    logger.warning(
                        f"Found page without bbox for {attr_name} - removing incomplete page data"
                    )

            # Always remove raw bbox/page data from output (whether processed or incomplete)
            enhanced_attr.pop("bbox", None)
            enhanced_attr.pop("page", None)

        return enhanced_attr

    def _extract_geometry_from_assessment(
        self, assessment_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Extract geometry data from assessment response and convert to proper format.
        Now supports recursive processing of nested group attributes.

        Args:
            assessment_data: Dictionary containing assessment results from LLM

        Returns:
            Enhanced assessment data with geometry information converted to proper format
        """
        enhanced_assessment = {}

        for attr_name, attr_assessment in assessment_data.items():
            if isinstance(attr_assessment, dict):
                # Check if this is a direct confidence assessment
                if "confidence" in attr_assessment:
                    # This is a direct assessment - process its geometry
                    enhanced_assessment[attr_name] = (
                        self._process_single_assessment_geometry(
                            attr_assessment, attr_name
                        )
                    )
                else:
                    # This is a group attribute (no direct confidence) - recursively process nested attributes
                    logger.debug(f"Processing group attribute: {attr_name}")
                    enhanced_assessment[attr_name] = (
                        self._extract_geometry_from_assessment(attr_assessment)
                    )

            elif isinstance(attr_assessment, list):
                # Handle list attributes - process each item recursively
                enhanced_list = []
                for i, item_assessment in enumerate(attr_assessment):
                    if isinstance(item_assessment, dict):
                        # Recursively process each list item
                        enhanced_item = self._extract_geometry_from_assessment(
                            item_assessment
                        )
                        enhanced_list.append(enhanced_item)
                    else:
                        # Non-dict items pass through unchanged
                        enhanced_list.append(item_assessment)
                enhanced_assessment[attr_name] = enhanced_list
            else:
                # Other types pass through unchanged
                enhanced_assessment[attr_name] = attr_assessment

        return enhanced_assessment

    def process_document_section(self, document: Document, section_id: str) -> Document:
        """
        Process a single section from a Document object to assess extraction confidence.

        Args:
            document: Document object containing section to process
            section_id: ID of the section to process

        Returns:
            Document: Updated Document object with assessment results appended to extraction results
        """
        # Check if assessment is enabled in typed configuration
        enabled = self.config.assessment.enabled
        if not enabled:
            logger.info("Assessment is disabled via configuration")
            return document

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

        # Check if section has extraction results to assess
        if not section.extraction_result_uri:
            error_msg = f"Section {section_id} has no extraction results to assess"
            logger.error(error_msg)
            document.errors.append(error_msg)
            return document

        # Extract information about the section
        class_label = section.classification

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
            f"Assessing {len(sorted_page_ids)} pages, class {class_label}: {start_page}-{end_page}"
        )

        # Track metrics
        metrics.put_metric("InputDocumentsForAssessment", 1)
        metrics.put_metric("InputDocumentPagesForAssessment", len(section.page_ids))

        try:
            # Read existing extraction results
            t0 = time.time()
            extraction_data = s3.get_json_content(section.extraction_result_uri)
            extraction_results = extraction_data.get("inference_result", {})

            # Skip assessment if no extraction results found
            if not extraction_results:
                logger.warning(f"No extraction results found for section {section_id}")
                return document

            t1 = time.time()
            logger.info(f"Time taken to read extraction results: {t1 - t0:.2f} seconds")

            # Read document text from all pages in order
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
            t2 = time.time()
            logger.info(f"Time taken to read text content: {t2 - t1:.2f} seconds")

            # Read page images with configurable dimensions (type-safe access)
            target_width = self.config.assessment.image.target_width
            target_height = self.config.assessment.image.target_height

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

            t3 = time.time()
            logger.info(f"Time taken to read images: {t3 - t2:.2f} seconds")

            # Read text confidence data for confidence information
            ocr_text_confidence = ""
            for page_id in sorted_page_ids:
                if page_id not in document.pages:
                    continue

                page = document.pages[page_id]
                text_confidence_data_str = self._get_text_confidence_data(page)
                if text_confidence_data_str:
                    ocr_text_confidence += (
                        f"\n--- Page {page_id} Text Confidence Data ---\n"
                    )
                    ocr_text_confidence += text_confidence_data_str

            t4 = time.time()
            logger.info(f"Time taken to read raw OCR results: {t4 - t3:.2f} seconds")

            # Get assessment configuration (type-safe access, Pydantic handles conversions)
            model_id = self.config.assessment.model
            temperature = self.config.assessment.temperature
            top_k = self.config.assessment.top_k
            top_p = self.config.assessment.top_p
            max_tokens = self.config.assessment.max_tokens
            system_prompt = self.config.assessment.system_prompt

            # Get schema for this document class
            class_schema = self._get_class_schema(class_label)
            if not class_schema:
                raise ValueError(f"No schema found for document class: {class_label}")

            property_descriptions = self._format_property_descriptions(class_schema)

            # Prepare prompt (type-safe access)
            prompt_template = self.config.assessment.task_prompt
            extraction_results_str = json.dumps(extraction_results, indent=2)

            if not prompt_template:
                raise ValueError(
                    "Assessment task_prompt is required in configuration but not found"
                )
            else:
                # Use the unified content builder for DOCUMENT_IMAGE placeholder support
                try:
                    content = self._build_content_with_or_without_image_placeholder(
                        prompt_template,
                        document_text,
                        class_label,
                        property_descriptions,
                        extraction_results_str,
                        ocr_text_confidence,
                        page_images,  # Pass images to the content builder
                    )
                except ValueError as e:
                    logger.error(f"Error formatting prompt template: {str(e)}")
                    raise ValueError(
                        f"Assessment prompt template formatting failed: {str(e)}"
                    )

            logger.info(
                f"Assessing extraction confidence for {class_label} document, section {section_id}"
            )

            # Time the model invocation
            request_start_time = time.time()

            # Invoke Bedrock (or LambdaHook) with the common library
            response_with_metering = bedrock.invoke_model(
                model_id=model_id,
                system_prompt=system_prompt,
                content=content,
                temperature=temperature,
                top_k=top_k,
                top_p=top_p,
                max_tokens=max_tokens,
                context="Assessment",
                model_lambda_hook_arn=self.config.assessment.model_lambda_hook_arn,
            )

            total_duration = time.time() - request_start_time
            logger.info(f"Time taken for assessment: {total_duration:.2f} seconds")

            # Extract text from response
            assessment_text = bedrock.extract_text_from_response(response_with_metering)
            metering = response_with_metering.get("metering", {})

            # Parse response into JSON
            assessment_data = {}
            parsing_succeeded = True  # Flag to track if parsing was successful

            try:
                # Try to parse the assessment text as JSON
                assessment_data = json.loads(extract_json_from_text(assessment_text))
            except Exception as e:
                # Handle parsing error
                logger.error(
                    f"Error parsing assessment LLM output - invalid JSON?: {assessment_text} - {e}"
                )
                logger.info("Using default confidence scores.")
                # Create default assessments for all extracted attributes
                assessment_data = {}
                for attr_name in extraction_results.keys():
                    assessment_data[attr_name] = {
                        "confidence": 0.5,
                        "confidence_reason": "Unable to parse assessment response - default score assigned",
                    }
                parsing_succeeded = False  # Mark that parsing failed

            # Process bounding boxes automatically if bbox data is present
            try:
                logger.debug("Checking for bounding box data in assessment response")
                assessment_data = self._extract_geometry_from_assessment(
                    assessment_data
                )
            except Exception as e:
                logger.warning(f"Failed to extract geometry data: {str(e)}")
                # Continue with assessment even if geometry extraction fails

            # Get confidence thresholds (type-safe, already float from Pydantic)
            default_confidence_threshold = (
                self.config.assessment.default_confidence_threshold
            )

            # Enhance assessment data with confidence thresholds and create confidence threshold alerts
            enhanced_assessment_data = {}
            confidence_threshold_alerts = []

            # Get properties dict once for efficient access
            properties = class_schema.get(SCHEMA_PROPERTIES, {})

            for attr_name, attr_assessment in assessment_data.items():
                # Get property schema (if it exists in schema)
                prop_schema = properties.get(attr_name, {})

                # Get threshold for this property
                attr_threshold = _safe_float_conversion(
                    prop_schema.get(
                        X_AWS_IDP_CONFIDENCE_THRESHOLD, default_confidence_threshold
                    ),
                    default_confidence_threshold,
                )

                # Get property type
                prop_type_json = prop_schema.get(SCHEMA_TYPE, TYPE_STRING)

                # Map JSON Schema type to legacy attribute type for existing logic
                if prop_type_json == TYPE_OBJECT:
                    attr_type = "group"
                elif prop_type_json == TYPE_ARRAY:
                    attr_type = "list"
                else:
                    attr_type = "simple"

                # Check if attr_assessment is a dictionary (expected format for simple/group attributes)
                if isinstance(attr_assessment, dict):
                    # For simple attributes or group attributes - add confidence_threshold to each confidence assessment
                    enhanced_assessment_data[attr_name] = self._enhance_dict_assessment(
                        attr_assessment, attr_threshold
                    )

                    # Check for confidence threshold alerts in the assessment
                    self._check_confidence_alerts(
                        attr_assessment,
                        attr_name,
                        attr_threshold,
                        confidence_threshold_alerts,
                    )

                elif isinstance(attr_assessment, list):
                    # Handle list attributes (expected format for LIST attributes like transactions)
                    if attr_type == "list":
                        # This is expected for list attributes - process each item in the list
                        enhanced_list = []
                        for i, item_assessment in enumerate(attr_assessment):
                            if isinstance(item_assessment, dict):
                                enhanced_item = self._enhance_dict_assessment(
                                    item_assessment, attr_threshold
                                )
                                enhanced_list.append(enhanced_item)

                                # Check for confidence threshold alerts in list items
                                self._check_confidence_alerts(
                                    item_assessment,
                                    f"{attr_name}[{i}]",
                                    attr_threshold,
                                    confidence_threshold_alerts,
                                )
                            else:
                                # Handle unexpected format within list
                                logger.warning(
                                    f"List item {i} in attribute '{attr_name}' is not a dictionary. "
                                    f"Expected dict, got {type(item_assessment)}. Using default confidence."
                                )
                                default_item = {
                                    "confidence": 0.5,
                                    "confidence_reason": f"List item {i} in '{attr_name}' has unexpected format. Using default confidence.",
                                    "confidence_threshold": attr_threshold,
                                }
                                enhanced_list.append(default_item)

                                # Add alert for default confidence
                                if 0.5 < attr_threshold:
                                    confidence_threshold_alerts.append(
                                        {
                                            "attribute_name": f"{attr_name}[{i}]",
                                            "confidence": 0.5,
                                            "confidence_threshold": attr_threshold,
                                        }
                                    )

                        enhanced_assessment_data[attr_name] = enhanced_list
                    else:
                        # List format for non-list attribute is unexpected
                        logger.warning(
                            f"Attribute '{attr_name}' (type: {attr_type}) assessment is a list but attribute is not configured as list type. "
                            f"Using default confidence."
                        )

                        # Create a default assessment structure
                        default_assessment = {
                            "confidence": 0.5,
                            "confidence_reason": f"LLM returned list format for non-list attribute '{attr_name}'. Using default confidence (0.5) and threshold ({attr_threshold}).",
                            "confidence_threshold": attr_threshold,
                        }
                        enhanced_assessment_data[attr_name] = default_assessment

                else:
                    # Handle other unexpected types
                    logger.warning(
                        f"Attribute '{attr_name}' assessment is of unexpected type {type(attr_assessment)}. "
                        f"Expected dictionary or list (for list attributes). Using default confidence."
                    )

                    # Create a default assessment structure
                    default_assessment = {
                        "confidence": 0.5,
                        "confidence_reason": f"LLM returned unexpected type {type(attr_assessment)} for attribute '{attr_name}'. Using default confidence (0.5) and threshold ({attr_threshold}).",
                        "confidence_threshold": attr_threshold,
                    }
                    enhanced_assessment_data[attr_name] = default_assessment

            # Update the existing extraction result with enhanced assessment data
            extraction_data["explainability_info"] = [enhanced_assessment_data]
            extraction_data["metadata"] = extraction_data.get("metadata", {})
            extraction_data["metadata"]["assessment_time_seconds"] = total_duration
            extraction_data["metadata"]["assessment_parsing_succeeded"] = (
                parsing_succeeded
            )

            # Write the updated result back to S3
            bucket, key = utils.parse_s3_uri(section.extraction_result_uri)
            s3.write_content(
                extraction_data, bucket, key, content_type="application/json"
            )

            # Update the section in the document with confidence threshold alerts
            for doc_section in document.sections:
                if doc_section.section_id == section_id:
                    doc_section.confidence_threshold_alerts = (
                        confidence_threshold_alerts
                    )
                    break

            # Update document with metering data
            document.metering = utils.merge_metering_data(
                document.metering, metering or {}
            )

            t5 = time.time()
            logger.info(
                f"Total assessment time for section {section_id}: {t5 - t0:.2f} seconds"
            )

        except Exception as e:
            error_msg = (
                f"Error processing assessment for section {section_id}: {str(e)}"
            )
            logger.error(error_msg)
            document.errors.append(error_msg)
            raise

        return document

    def assess_document(self, document: Document) -> Document:
        """
        Assess extraction confidence for all sections in a document.

        Args:
            document: Document object with extraction results

        Returns:
            Document: Updated Document object with assessment results
        """
        logger.info(f"Starting assessment for document {document.id}")

        for section in document.sections:
            if section.extraction_result_uri:
                logger.info(f"Assessing section {section.section_id}")
                document = self.process_document_section(document, section.section_id)
            else:
                logger.warning(
                    f"Section {section.section_id} has no extraction results to assess"
                )

        logger.info(f"Completed assessment for document {document.id}")
        return document
