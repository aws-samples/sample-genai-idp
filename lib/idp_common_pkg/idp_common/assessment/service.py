# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Assessment service for evaluating document extraction confidence using LLMs.

This module provides a service for assessing the confidence and accuracy of
extraction results by analyzing them against source documents using LLMs,
with support for text and image content.
"""

import json
import logging
import os
import time
from typing import Any, Dict, List

from idp_common import bedrock, image, metrics, s3, utils
from idp_common.models import Document

logger = logging.getLogger(__name__)


class AssessmentService:
    """Service for assessing extraction result confidence using LLMs."""

    def __init__(self, region: str = None, config: Dict[str, Any] = None):
        """
        Initialize the assessment service.

        Args:
            region: AWS region for Bedrock
            config: Configuration dictionary
        """
        self.config = config or {}
        self.region = (
            region or self.config.get("region") or os.environ.get("AWS_REGION")
        )

        # Get model_id from config for logging
        model_id = self.config.get("model_id") or self.config.get("assessment", {}).get(
            "model"
        )
        logger.info(f"Initialized assessment service with model {model_id}")

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

    def process_document_section(self, document: Document, section_id: str) -> Document:
        """
        Process a single section from a Document object to assess extraction confidence.

        Args:
            document: Document object containing section to process
            section_id: ID of the section to process

        Returns:
            Document: Updated Document object with assessment results appended to extraction results
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

            # Read page images
            page_images = []
            for page_id in sorted_page_ids:
                if page_id not in document.pages:
                    continue

                page = document.pages[page_id]
                image_uri = page.image_uri
                image_content = image.prepare_image(image_uri)
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

            # Get assessment configuration
            assessment_config = self.config.get("assessment", {})
            model_id = self.config.get("model_id") or assessment_config.get("model")
            temperature = float(assessment_config.get("temperature", 0))
            top_k = float(assessment_config.get("top_k", 5))
            top_p = float(assessment_config.get("top_p", 0.1))
            max_tokens = (
                int(assessment_config.get("max_tokens", 4096))
                if assessment_config.get("max_tokens")
                else None
            )
            system_prompt = assessment_config.get("system_prompt", "")

            # Get attributes for this document class
            attributes = self._get_class_attributes(class_label)
            attribute_descriptions = self._format_attribute_descriptions(attributes)

            # Prepare prompt
            prompt_template = assessment_config.get("task_prompt", "")
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
                        attribute_descriptions,
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

            # Invoke Bedrock with the common library
            response_with_metering = bedrock.invoke_model(
                model_id=model_id,
                system_prompt=system_prompt,
                content=content,
                temperature=temperature,
                top_k=top_k,
                top_p=top_p,
                max_tokens=max_tokens,
                context="Assessment",
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
                assessment_data = json.loads(self._extract_json(assessment_text))
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

            # Get confidence thresholds
            default_confidence_threshold = assessment_config.get(
                "default_confidence_threshold", 0.9
            )

            # Enhance assessment data with confidence thresholds and create confidence threshold alerts
            enhanced_assessment_data = {}
            confidence_threshold_alerts = []

            for attr_name, attr_assessment in assessment_data.items():
                # Get the attribute config to check for per-attribute confidence threshold
                attr_threshold = default_confidence_threshold
                for attr in attributes:
                    if attr.get("name") == attr_name:
                        attr_threshold = attr.get(
                            "confidence_threshold", default_confidence_threshold
                        )
                        break
                attr_threshold = float(attr_threshold)

                # Add confidence_threshold to the assessment data
                enhanced_assessment_data[attr_name] = {
                    **attr_assessment,
                    "confidence_threshold": attr_threshold,
                }

                # Check if confidence is below threshold and create alert
                confidence = attr_assessment.get("confidence", 0.0)
                if confidence < attr_threshold:
                    confidence_threshold_alerts.append(
                        {
                            "attribute_name": attr_name,
                            "confidence": confidence,
                            "confidence_threshold": attr_threshold,
                        }
                    )

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
