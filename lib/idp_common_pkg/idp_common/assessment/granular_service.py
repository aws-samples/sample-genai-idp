# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Granular assessment service for evaluating document extraction confidence using LLMs.

This module provides a more scalable approach to assessment by:
1. Breaking down assessments into smaller, focused inferences
2. Leveraging prompt caching to reduce costs
3. Using multi-threading for parallel processing
4. Adapting batch sizes based on attribute complexity
"""

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from idp_common import bedrock, image, metrics, s3, utils
from idp_common.models import Document, Status
from idp_common.utils import check_token_limit, extract_json_from_text

logger = logging.getLogger(__name__)


@dataclass
class AssessmentTask:
    """Represents a single assessment task to be processed."""

    task_id: str
    task_type: str  # 'simple_batch', 'group', 'list_item'
    attributes: List[str]  # Attribute names to assess
    extraction_data: Dict[str, Any]  # Relevant extraction data
    confidence_thresholds: Dict[str, float]  # Attribute -> threshold mapping
    list_item_index: Optional[int] = None  # For list items


@dataclass
class AssessmentResult:
    """Result of a single assessment task."""

    task_id: str
    success: bool
    assessment_data: Dict[str, Any]
    confidence_alerts: List[Dict[str, Any]]
    error_message: Optional[str] = None
    processing_time: float = 0.0
    metering: Optional[Dict[str, Any]] = None


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


class GranularAssessmentService:
    """Enhanced assessment service with granular, cached, and parallel processing."""

    def __init__(
        self, region: str = None, config: Dict[str, Any] = None, cache_table: str = None
    ):
        """
        Initialize the granular assessment service.

        Args:
            region: AWS region for Bedrock
            config: Configuration dictionary
            cache_table: Optional DynamoDB table name for caching assessment task results
        """
        self.config = config or {}
        self.region = (
            region or self.config.get("region") or os.environ.get("AWS_REGION")
        )

        # Get assessment configuration
        self.assessment_config = self.config.get("assessment", {})

        # Granular processing configuration with safe defaults
        self.granular_config = self.assessment_config.get("granular", {})
        self.max_workers = int(self.granular_config.get("max_workers", 4))
        self.simple_batch_size = int(self.granular_config.get("simple_batch_size", 3))
        self.list_batch_size = int(self.granular_config.get("list_batch_size", 1))

        # Ensure safe minimum values
        self.max_workers = max(1, self.max_workers)
        self.simple_batch_size = max(1, self.simple_batch_size)
        self.list_batch_size = max(1, self.list_batch_size)

        # Auto-determine caching and parallel processing
        # Caching is automatically handled by the bedrock client based on model support
        # Parallel processing is enabled when max_workers > 1
        self.enable_parallel = self.max_workers > 1

        # Initialize caching for assessment tasks (similar to classification service)
        self.cache_table_name = cache_table or os.environ.get("TRACKING_TABLE")
        self.cache_table = None
        if self.cache_table_name:
            import boto3

            dynamodb = boto3.resource("dynamodb", region_name=self.region)
            self.cache_table = dynamodb.Table(self.cache_table_name)
            logger.info(
                f"Granular assessment caching enabled using table: {self.cache_table_name}"
            )
        else:
            logger.info("Granular assessment caching disabled")

        # Define throttling exceptions that should trigger retries
        self.throttling_exceptions = [
            "ThrottlingException",
            "ProvisionedThroughputExceededException",
            "ServiceQuotaExceededException",
            "TooManyRequestsException",
            "RequestLimitExceeded",
        ]

        # Get model_id from config for logging
        model_id = self.config.get("model_id") or self.assessment_config.get("model")
        logger.info(f"Initialized granular assessment service with model {model_id}")
        logger.info(
            f"Granular config: max_workers={self.max_workers}, "
            f"simple_batch_size={self.simple_batch_size}, "
            f"list_batch_size={self.list_batch_size}, "
            f"parallel={self.enable_parallel}, "
            f"caching={'enabled' if self.cache_table else 'disabled'}"
        )

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
        Format attribute descriptions for the prompt, supporting nested structures.

        Args:
            attributes: List of attribute configurations

        Returns:
            Formatted attribute descriptions as a string
        """
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

    def _get_attribute_confidence_threshold(
        self, attr_name: str, attributes: List[Dict[str, Any]], default_threshold: float
    ) -> float:
        """
        Get confidence threshold for a specific attribute, supporting nested structures.

        Args:
            attr_name: Name of the attribute to find threshold for
            attributes: List of attribute configurations
            default_threshold: Default threshold if not found

        Returns:
            Confidence threshold for the attribute
        """
        # First check top-level attributes
        for attr in attributes:
            if attr.get("name") == attr_name:
                return _safe_float_conversion(
                    attr.get("confidence_threshold", default_threshold),
                    default_threshold,
                )

        # Check nested group attributes
        for attr in attributes:
            if attr.get("attributeType") == "group":
                group_attributes = attr.get("groupAttributes", [])
                for group_attr in group_attributes:
                    if group_attr.get("name") == attr_name:
                        return _safe_float_conversion(
                            group_attr.get("confidence_threshold", default_threshold),
                            default_threshold,
                        )

        # Check nested list item attributes
        for attr in attributes:
            if attr.get("attributeType") == "list":
                list_template = attr.get("listItemTemplate", {})
                item_attributes = list_template.get("itemAttributes", [])
                for item_attr in item_attributes:
                    if item_attr.get("name") == attr_name:
                        return _safe_float_conversion(
                            item_attr.get("confidence_threshold", default_threshold),
                            default_threshold,
                        )

        # Return default if not found
        return default_threshold

    def _get_attribute_config(
        self, attr_name: str, attributes: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Get the configuration for a specific attribute, supporting nested structures.

        Args:
            attr_name: Name of the attribute to find
            attributes: List of attribute configurations

        Returns:
            Attribute configuration dictionary, or empty dict if not found
        """
        # First check top-level attributes
        for attr in attributes:
            if attr.get("name") == attr_name:
                return attr

        # Check nested group attributes
        for attr in attributes:
            if attr.get("attributeType") == "group":
                group_attributes = attr.get("groupAttributes", [])
                for group_attr in group_attributes:
                    if group_attr.get("name") == attr_name:
                        return group_attr

        # Check nested list item attributes
        for attr in attributes:
            if attr.get("attributeType") == "list":
                list_template = attr.get("listItemTemplate", {})
                item_attributes = list_template.get("itemAttributes", [])
                for item_attr in item_attributes:
                    if item_attr.get("name") == attr_name:
                        return item_attr

        # Return empty dict if not found
        return {}

    def _build_cached_prompt_base(
        self,
        document_text: str,
        class_label: str,
        attribute_descriptions: str,
        ocr_text_confidence: str,
        page_images: List[Any],
    ) -> List[Dict[str, Any]]:
        """
        Build the cacheable base portion of the assessment prompt using the configured task_prompt template.
        This will be the same for all tasks and can be cached.

        Args:
            document_text: The document text content
            class_label: The document class label
            attribute_descriptions: Formatted attribute names and descriptions (will be replaced per task)
            ocr_text_confidence: Raw OCR results with confidence scores
            page_images: List of page images

        Returns:
            List of content items for the cacheable portion
        """
        # Get the base task prompt template
        task_prompt_template = self.assessment_config.get("task_prompt", "")

        if not task_prompt_template:
            raise ValueError(
                "Assessment task_prompt is required in configuration but not found"
            )

        # For granular assessment, we need to build the base content that will be cached
        # and leave placeholders for task-specific content

        # Replace common placeholders but leave task-specific ones
        base_substitutions = {
            "DOCUMENT_TEXT": document_text,
            "DOCUMENT_CLASS": class_label,
            "OCR_TEXT_CONFIDENCE": ocr_text_confidence,
        }

        # Replace placeholders in the template
        base_prompt = task_prompt_template
        for placeholder, value in base_substitutions.items():
            base_prompt = base_prompt.replace(f"{{{placeholder}}}", value)

        # Handle {DOCUMENT_IMAGE} placeholder if present
        if "{DOCUMENT_IMAGE}" in base_prompt:
            # Split the prompt at the DOCUMENT_IMAGE placeholder
            parts = base_prompt.split("{DOCUMENT_IMAGE}")
            if len(parts) != 2:
                raise ValueError(
                    f"Invalid DOCUMENT_IMAGE placeholder usage: found {len(parts) - 1} occurrences, "
                    f"but exactly 1 is required."
                )

            content = []

            # Add the part before the image
            if parts[0].strip():
                content.append({"text": parts[0]})

            # Add the images if available
            if page_images:
                if isinstance(page_images, list):
                    # Multiple images (limit to 20 as per Bedrock constraints)
                    if len(page_images) > 20:
                        logger.warning(
                            f"Found {len(page_images)} images, truncating to 20 due to Bedrock constraints. "
                            f"{len(page_images) - 20} images will be dropped."
                        )
                    for img in page_images[:20]:
                        content.append(image.prepare_bedrock_image_attachment(img))
                else:
                    # Single image
                    content.append(image.prepare_bedrock_image_attachment(page_images))

            # Add the part after the image
            if parts[1].strip():
                content.append({"text": parts[1]})

        else:
            # No DOCUMENT_IMAGE placeholder - just add the base prompt
            content = []
            if base_prompt.strip():
                content.append({"text": base_prompt})

        return content

    def _get_task_specific_attribute_descriptions(
        self, task: AssessmentTask, all_attributes: List[Dict[str, Any]]
    ) -> str:
        """
        Get attribute descriptions specific to this task.

        Args:
            task: The assessment task
            all_attributes: All attribute configurations

        Returns:
            Formatted attribute descriptions for this specific task
        """
        if task.task_type == "simple_batch":
            # For simple batches, include only the attributes in this batch
            task_attributes = [
                attr
                for attr in all_attributes
                if attr.get("name", "") in task.attributes
            ]
            return self._format_attribute_descriptions(task_attributes)

        elif task.task_type == "group":
            # For groups, include the group attribute and its sub-attributes
            group_attr_name = task.attributes[0]
            group_attr = next(
                (
                    attr
                    for attr in all_attributes
                    if attr.get("name", "") == group_attr_name
                ),
                None,
            )
            if group_attr:
                return self._format_attribute_descriptions([group_attr])
            return ""

        elif task.task_type == "list_item":
            # For list items, include the list attribute template
            list_attr_name = task.attributes[0]
            list_attr = next(
                (
                    attr
                    for attr in all_attributes
                    if attr.get("name", "") == list_attr_name
                ),
                None,
            )
            if list_attr:
                # Create a simplified version showing just the item template
                list_template = list_attr.get("listItemTemplate", {})
                item_attributes = list_template.get("itemAttributes", [])
                return self._format_attribute_descriptions(item_attributes)
            return ""

        return ""

    def _build_specific_assessment_prompt(
        self,
        task: AssessmentTask,
        base_content: List[Dict[str, Any]],
        all_attributes: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Build the specific assessment prompt for a task by replacing the {EXTRACTION_RESULTS} placeholder
        in the base content with task-specific extraction data.

        Args:
            task: The assessment task
            base_content: The cached base content (which has empty {EXTRACTION_RESULTS})
            all_attributes: All attribute configurations for task-specific filtering

        Returns:
            Complete content list for the assessment
        """
        # Build extraction results for this specific task
        task_extraction_data = {}
        for attr_name in task.attributes:
            if attr_name in task.extraction_data:
                task_extraction_data[attr_name] = task.extraction_data[attr_name]

        # For list items, we need to handle the data differently
        if task.task_type == "list_item":
            extraction_results_str = json.dumps(task.extraction_data, indent=2)
            item_index = task.list_item_index if task.list_item_index is not None else 0
            extraction_results_str = f"Item #{item_index + 1}: {extraction_results_str}"
        else:
            extraction_results_str = json.dumps(task_extraction_data, indent=2)

        # Get task-specific attribute descriptions
        task_specific_attributes = self._get_task_specific_attribute_descriptions(
            task, all_attributes
        )

        # Create a new content list by replacing placeholders in the base content
        content = []
        for item in base_content:
            if "text" in item:
                # Replace any remaining placeholders in the text
                text = item["text"]

                # Replace EXTRACTION_RESULTS placeholder with task-specific data
                text = text.replace("{EXTRACTION_RESULTS}", extraction_results_str)

                # Replace ATTRIBUTE_NAMES_AND_DESCRIPTIONS with task-specific attributes if needed
                if "{ATTRIBUTE_NAMES_AND_DESCRIPTIONS}" in text:
                    text = text.replace(
                        "{ATTRIBUTE_NAMES_AND_DESCRIPTIONS}", task_specific_attributes
                    )

                # Only add non-empty text content (must have actual content, not just whitespace)
                if text.strip():
                    content.append({"text": text})
            else:
                # Non-text content (like images, cache points) - pass through unchanged
                content.append(item)

        return content

    def _create_assessment_tasks(
        self,
        extraction_results: Dict[str, Any],
        attributes: List[Dict[str, Any]],
        default_confidence_threshold: float,
    ) -> List[AssessmentTask]:
        """
        Create assessment tasks based on attribute types and extraction results.

        Args:
            extraction_results: The extraction results to assess
            attributes: List of attribute configurations
            default_confidence_threshold: Default confidence threshold

        Returns:
            List of assessment tasks
        """
        tasks = []
        task_counter = 0

        # Group attributes by type for efficient processing
        simple_attributes = []
        group_attributes = []
        list_attributes = []

        for attr in attributes:
            attr_name = attr.get("name", "")
            attr_type = attr.get("attributeType", "simple")

            if attr_name not in extraction_results:
                continue  # Skip attributes not in extraction results

            if attr_type == "simple":
                simple_attributes.append(attr)
            elif attr_type == "group":
                group_attributes.append(attr)
            elif attr_type == "list":
                list_attributes.append(attr)

        # Create tasks for simple attributes (batch them)
        for i in range(0, len(simple_attributes), self.simple_batch_size):
            batch = simple_attributes[i : i + self.simple_batch_size]
            attr_names = [attr.get("name", "") for attr in batch]

            # Build confidence thresholds for this batch
            confidence_thresholds = {}
            for attr in batch:
                attr_name = attr.get("name", "")
                threshold = self._get_attribute_confidence_threshold(
                    attr_name, attributes, default_confidence_threshold
                )
                confidence_thresholds[attr_name] = threshold

            # Extract relevant data for this batch
            batch_extraction_data = {
                name: extraction_results[name]
                for name in attr_names
                if name in extraction_results
            }

            task = AssessmentTask(
                task_id=f"simple_batch_{task_counter}",
                task_type="simple_batch",
                attributes=attr_names,
                extraction_data=batch_extraction_data,
                confidence_thresholds=confidence_thresholds,
            )
            tasks.append(task)
            task_counter += 1

        # Create tasks for group attributes (one per group)
        for attr in group_attributes:
            attr_name = attr.get("name", "")

            # Build confidence thresholds for group sub-attributes
            confidence_thresholds = {}
            group_attributes_list = attr.get("groupAttributes", [])
            for group_attr in group_attributes_list:
                sub_attr_name = group_attr.get("name", "")
                threshold = self._get_attribute_confidence_threshold(
                    sub_attr_name, attributes, default_confidence_threshold
                )
                confidence_thresholds[sub_attr_name] = threshold

            task = AssessmentTask(
                task_id=f"group_{task_counter}",
                task_type="group",
                attributes=[attr_name],
                extraction_data={attr_name: extraction_results[attr_name]},
                confidence_thresholds=confidence_thresholds,
            )
            tasks.append(task)
            task_counter += 1

        # Create tasks for list attributes (one per list item)
        for attr in list_attributes:
            attr_name = attr.get("name", "")
            list_data = extraction_results.get(attr_name, [])

            if not isinstance(list_data, list):
                logger.warning(f"List attribute {attr_name} is not a list, skipping")
                continue

            # Build confidence thresholds for list item attributes
            confidence_thresholds = {}
            list_template = attr.get("listItemTemplate", {})
            item_attributes = list_template.get("itemAttributes", [])
            for item_attr in item_attributes:
                item_attr_name = item_attr.get("name", "")
                threshold = self._get_attribute_confidence_threshold(
                    item_attr_name, attributes, default_confidence_threshold
                )
                confidence_thresholds[item_attr_name] = threshold

            # Create tasks for list items (batch them if configured)
            for i in range(0, len(list_data), self.list_batch_size):
                batch_end = min(i + self.list_batch_size, len(list_data))

                for j in range(i, batch_end):
                    item_data = list_data[j]

                    task = AssessmentTask(
                        task_id=f"list_{attr_name}_item_{j}",
                        task_type="list_item",
                        attributes=[attr_name],
                        extraction_data=item_data,
                        confidence_thresholds=confidence_thresholds,
                        list_item_index=j,
                    )
                    tasks.append(task)
                    task_counter += 1

        logger.info(
            f"Created {len(tasks)} assessment tasks: "
            f"{len([t for t in tasks if t.task_type == 'simple_batch'])} simple batches, "
            f"{len([t for t in tasks if t.task_type == 'group'])} groups, "
            f"{len([t for t in tasks if t.task_type == 'list_item'])} list items"
        )

        return tasks

    def _process_assessment_task(
        self,
        task: AssessmentTask,
        base_content: List[Dict[str, Any]],
        all_attributes: List[Dict[str, Any]],
        model_id: str,
        system_prompt: str,
        temperature: float,
        top_k: float,
        top_p: float,
        max_tokens: Optional[int],
    ) -> AssessmentResult:
        """
        Process a single assessment task.

        Args:
            task: The assessment task to process
            base_content: The cached base content
            all_attributes: All attribute configurations
            model_id: Bedrock model ID
            system_prompt: System prompt
            temperature: Temperature parameter
            top_k: Top-k parameter
            top_p: Top-p parameter
            max_tokens: Max tokens parameter

        Returns:
            Assessment result
        """
        start_time = time.time()

        try:
            # Build the complete prompt
            content = self._build_specific_assessment_prompt(
                task, base_content, all_attributes
            )

            logger.debug(
                f"Processing assessment task {task.task_id} with {len(task.attributes)} attributes"
            )

            # Invoke Bedrock
            response_with_metering = bedrock.invoke_model(
                model_id=model_id,
                system_prompt=system_prompt,
                content=content,
                temperature=temperature,
                top_k=top_k,
                top_p=top_p,
                max_tokens=max_tokens,
                context="GranularAssessment",
            )

            # Extract text from response
            assessment_text = bedrock.extract_text_from_response(response_with_metering)
            metering = response_with_metering.get("metering", {})

            # Parse response into JSON
            assessment_data = {}
            task_failed = False
            error_messages = []
            try:
                assessment_data = json.loads(extract_json_from_text(assessment_text))
            except Exception as e:
                logger.error(
                    f"Error parsing assessment LLM output for task {task.task_id}: {e}"
                )
                task_failed = True
                error_messages.append(
                    f"Error parsing assessment LLM output for task {task.task_id}"
                )
                # Create default assessments
                for attr_name in task.attributes:
                    if task.task_type == "list_item":
                        # For list items, create assessments for each sub-attribute
                        assessment_data = {}
                        for (
                            sub_attr_name,
                            threshold,
                        ) in task.confidence_thresholds.items():
                            assessment_data[sub_attr_name] = {
                                "confidence": 0.5,
                                "confidence_reason": f"Unable to parse assessment response for {sub_attr_name} - default score assigned",
                            }
                    else:
                        assessment_data[attr_name] = {
                            "confidence": 0.5,
                            "confidence_reason": f"Unable to parse assessment response for {attr_name} - default score assigned",
                        }

            # Process bounding boxes automatically if bbox data is present
            try:
                logger.debug(
                    f"Checking for bounding box data in granular assessment task {task.task_id}"
                )
                assessment_data = self._extract_geometry_from_assessment(
                    assessment_data
                )
            except Exception as e:
                logger.warning(
                    f"Failed to extract geometry data for task {task.task_id}: {str(e)}"
                )
                # Continue with assessment even if geometry extraction fails

            # Check for confidence threshold alerts
            confidence_alerts = []
            self._check_confidence_alerts_for_task(
                task, assessment_data, confidence_alerts
            )

            processing_time = time.time() - start_time
            if task_failed:
                return AssessmentResult(
                    task_id=task.task_id,
                    success=False,
                    assessment_data=assessment_data,
                    confidence_alerts=confidence_alerts,
                    error_message=self._convert_error_list_to_string(error_messages),
                    processing_time=processing_time,
                )
            else:
                return AssessmentResult(
                    task_id=task.task_id,
                    success=True,
                    assessment_data=assessment_data,
                    confidence_alerts=confidence_alerts,
                    processing_time=processing_time,
                    metering=metering,
                )

        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"Error processing assessment task {task.task_id}: {str(e)}")

            return AssessmentResult(
                task_id=task.task_id,
                success=False,
                assessment_data={},
                confidence_alerts=[],
                error_message=str(e),
                processing_time=processing_time,
            )

    def _check_confidence_alerts_for_task(
        self,
        task: AssessmentTask,
        assessment_data: Dict[str, Any],
        alerts_list: List[Dict[str, Any]],
    ) -> None:
        """
        Check assessment data for confidence threshold violations for a specific task.

        Args:
            task: The assessment task
            assessment_data: Dictionary containing assessment data
            alerts_list: List to append alerts to (modified in place)
        """
        if task.task_type == "simple_batch":
            for attr_name in task.attributes:
                if attr_name in assessment_data and isinstance(
                    assessment_data[attr_name], dict
                ):
                    confidence = _safe_float_conversion(
                        assessment_data[attr_name].get("confidence", 0.0), 0.0
                    )
                    threshold = task.confidence_thresholds.get(attr_name, 0.9)
                    if confidence < threshold:
                        alerts_list.append(
                            {
                                "attribute_name": attr_name,
                                "confidence": confidence,
                                "confidence_threshold": threshold,
                            }
                        )

        elif task.task_type == "group":
            attr_name = task.attributes[0]  # Group tasks have one attribute
            if attr_name in assessment_data and isinstance(
                assessment_data[attr_name], dict
            ):
                for sub_attr_name, sub_assessment in assessment_data[attr_name].items():
                    if (
                        isinstance(sub_assessment, dict)
                        and "confidence" in sub_assessment
                    ):
                        confidence = _safe_float_conversion(
                            sub_assessment.get("confidence", 0.0), 0.0
                        )
                        threshold = task.confidence_thresholds.get(sub_attr_name, 0.9)
                        if confidence < threshold:
                            alerts_list.append(
                                {
                                    "attribute_name": f"{attr_name}.{sub_attr_name}",
                                    "confidence": confidence,
                                    "confidence_threshold": threshold,
                                }
                            )

        elif task.task_type == "list_item":
            attr_name = task.attributes[0]  # List item tasks have one attribute
            item_index = task.list_item_index if task.list_item_index is not None else 0

            for item_attr_name, item_assessment in assessment_data.items():
                if (
                    isinstance(item_assessment, dict)
                    and "confidence" in item_assessment
                ):
                    confidence = _safe_float_conversion(
                        item_assessment.get("confidence", 0.0), 0.0
                    )
                    threshold = task.confidence_thresholds.get(item_attr_name, 0.9)
                    if confidence < threshold:
                        alerts_list.append(
                            {
                                "attribute_name": f"{attr_name}[{item_index}].{item_attr_name}",
                                "confidence": confidence,
                                "confidence_threshold": threshold,
                            }
                        )

    def _get_cache_key(
        self, document_id: str, workflow_execution_arn: str, section_id: str
    ) -> str:
        """
        Generate cache key for assessment tasks.

        Args:
            document_id: Document ID
            workflow_execution_arn: Workflow execution ARN
            section_id: Section ID

        Returns:
            Cache key string
        """
        workflow_id = (
            workflow_execution_arn.split(":")[-1]
            if workflow_execution_arn
            else "unknown"
        )
        return f"assesscache#{document_id}#{workflow_id}#{section_id}"

    def _get_cached_assessment_tasks(
        self, document_id: str, workflow_execution_arn: str, section_id: str
    ) -> Dict[str, AssessmentResult]:
        """
        Retrieve cached assessment task results for a document section.

        Args:
            document_id: Document ID
            workflow_execution_arn: Workflow execution ARN
            section_id: Section ID

        Returns:
            Dictionary mapping task_id to cached AssessmentResult, empty dict if no cache
        """
        logger.info(
            f"Attempting to retrieve cached assessment tasks for document {document_id} section {section_id}"
        )

        if not self.cache_table:
            return {}

        cache_key = self._get_cache_key(document_id, workflow_execution_arn, section_id)

        try:
            response = self.cache_table.get_item(Key={"PK": cache_key, "SK": "tasks"})

            if "Item" not in response:
                logger.info(
                    f"No cache entry found for document {document_id} section {section_id}"
                )
                return {}

            # Parse cached data from JSON
            cached_data = response["Item"]
            logger.debug(f"Cached data keys: {list(cached_data.keys())}")
            task_results = {}

            # Extract task results from JSON attribute
            if "task_results" in cached_data:
                try:
                    import json

                    task_data_list = json.loads(cached_data["task_results"])

                    for task_data in task_data_list:
                        task_id = task_data["task_id"]
                        task_results[task_id] = AssessmentResult(
                            task_id=task_id,
                            success=task_data["success"],
                            assessment_data=task_data["assessment_data"],
                            confidence_alerts=task_data["confidence_alerts"],
                            error_message=task_data.get("error_message"),
                            processing_time=task_data.get("processing_time", 0.0),
                            metering=task_data.get("metering"),
                        )

                    if task_results:
                        logger.info(
                            f"Retrieved {len(task_results)} cached assessment task results for document {document_id} section {section_id} (PK: {cache_key})"
                        )

                except json.JSONDecodeError as e:
                    logger.warning(
                        f"Failed to parse cached assessment task results JSON for document {document_id} section {section_id}: {e}"
                    )

            return task_results

        except Exception as e:
            logger.warning(
                f"Failed to retrieve cached assessment tasks for document {document_id} section {section_id}: {e}"
            )
            return {}

    def _cache_successful_assessment_tasks(
        self,
        document_id: str,
        workflow_execution_arn: str,
        section_id: str,
        task_results: List[AssessmentResult],
    ) -> None:
        """
        Cache successful assessment task results to DynamoDB as a JSON-serialized list.

        Args:
            document_id: Document ID
            workflow_execution_arn: Workflow execution ARN
            section_id: Section ID
            task_results: List of successful assessment task results
        """
        if not self.cache_table or not task_results:
            return

        cache_key = self._get_cache_key(document_id, workflow_execution_arn, section_id)

        try:
            # Filter out failed task results and prepare data for JSON serialization
            successful_tasks = []
            for task_result in task_results:
                # Only cache successful tasks
                if task_result.success:
                    task_data = {
                        "task_id": task_result.task_id,
                        "success": task_result.success,
                        "assessment_data": task_result.assessment_data,
                        "confidence_alerts": task_result.confidence_alerts,
                        "error_message": task_result.error_message,
                        "processing_time": task_result.processing_time,
                        "metering": task_result.metering,
                    }
                    successful_tasks.append(task_data)

            if len(successful_tasks) == 0:
                logger.debug(
                    f"No successful assessment task results to cache for document {document_id} section {section_id}"
                )
                return

            # Prepare item structure with JSON-serialized task results
            import json
            from datetime import datetime, timedelta, timezone

            item = {
                "PK": cache_key,
                "SK": "tasks",
                "cached_at": str(int(time.time())),
                "document_id": document_id,
                "workflow_execution_arn": workflow_execution_arn,
                "section_id": section_id,
                "task_results": json.dumps(successful_tasks),
                "ExpiresAfter": int(
                    (datetime.now(timezone.utc) + timedelta(days=1)).timestamp()
                ),
            }

            # Store in DynamoDB using Table resource with JSON serialization
            self.cache_table.put_item(Item=item)

            logger.info(
                f"Cached {len(successful_tasks)} successful assessment task results for document {document_id} section {section_id} (PK: {cache_key})"
            )

        except Exception as e:
            logger.warning(
                f"Failed to cache assessment task results for document {document_id} section {section_id}: {e}"
            )

    def _is_throttling_exception(self, exception: Exception) -> bool:
        """
        Check if an exception is a throttling-related error that should trigger retries.

        Args:
            exception: Exception to check

        Returns:
            True if exception indicates throttling, False otherwise
        """
        if hasattr(exception, "response") and "Error" in exception.response:
            error_code = exception.response["Error"]["Code"]
            return error_code in self.throttling_exceptions

        # Check exception class name and message for throttling indicators
        exception_name = type(exception).__name__
        exception_message = str(exception).lower()

        return exception_name in self.throttling_exceptions or any(
            throttle_term.lower() in exception_message
            for throttle_term in self.throttling_exceptions
        )

    def _aggregate_assessment_results(
        self,
        tasks: List[AssessmentTask],
        results: List[AssessmentResult],
        extraction_results: Dict[str, Any],
        attributes: List[Dict[str, Any]],
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
        """
        Aggregate individual task results into the final assessment structure.

        Args:
            tasks: List of assessment tasks
            results: List of assessment results
            extraction_results: Original extraction results
            attributes: List of attribute configurations

        Returns:
            Tuple of (enhanced_assessment_data, confidence_alerts, aggregated_metering)
        """
        enhanced_assessment_data = {}
        all_confidence_alerts = []
        aggregated_metering = {}

        # Create a mapping from task_id to result
        result_map = {result.task_id: result for result in results}

        # Process results by task type
        for task in tasks:
            result = result_map.get(task.task_id)
            if not result or not result.success:
                logger.warning(f"Task {task.task_id} failed or missing result")
                continue

            # Aggregate metering data using the same pattern as classification service
            if result.metering:
                aggregated_metering = utils.merge_metering_data(
                    aggregated_metering, result.metering
                )

            # Add confidence alerts
            all_confidence_alerts.extend(result.confidence_alerts)

            # Process assessment data based on task type
            if task.task_type == "simple_batch":
                for attr_name in task.attributes:
                    if attr_name in result.assessment_data:
                        # Add confidence threshold to the assessment
                        assessment_value = result.assessment_data[attr_name]
                        if isinstance(assessment_value, dict):
                            assessment = assessment_value.copy()
                            threshold = task.confidence_thresholds.get(attr_name, 0.9)
                            assessment["confidence_threshold"] = threshold
                            enhanced_assessment_data[attr_name] = assessment
                        else:
                            logger.warning(
                                f"Unexpected assessment data type for {attr_name}: {type(assessment_value)}"
                            )

            elif task.task_type == "group":
                attr_name = task.attributes[0]
                if attr_name in result.assessment_data:
                    assessment_value = result.assessment_data[attr_name]
                    if isinstance(assessment_value, dict):
                        group_assessment = {}
                        for sub_attr_name, sub_assessment in assessment_value.items():
                            if isinstance(sub_assessment, dict):
                                enhanced_sub_assessment = sub_assessment.copy()
                                threshold = task.confidence_thresholds.get(
                                    sub_attr_name, 0.9
                                )
                                enhanced_sub_assessment["confidence_threshold"] = (
                                    threshold
                                )
                                group_assessment[sub_attr_name] = (
                                    enhanced_sub_assessment
                                )
                            else:
                                logger.warning(
                                    f"Unexpected sub-assessment data type for {attr_name}.{sub_attr_name}: {type(sub_assessment)}"
                                )
                                group_assessment[sub_attr_name] = sub_assessment
                        enhanced_assessment_data[attr_name] = group_assessment
                    else:
                        logger.warning(
                            f"Unexpected group assessment data type for {attr_name}: {type(assessment_value)}"
                        )

            elif task.task_type == "list_item":
                attr_name = task.attributes[0]
                item_index = (
                    task.list_item_index if task.list_item_index is not None else 0
                )

                # Initialize list structure if not exists
                if attr_name not in enhanced_assessment_data:
                    enhanced_assessment_data[attr_name] = []

                # Ensure the list is long enough for this item
                while len(enhanced_assessment_data[attr_name]) <= item_index:
                    enhanced_assessment_data[attr_name].append({})

                # Add assessments for this list item
                item_assessment = {}
                for (
                    item_attr_name,
                    item_assessment_data,
                ) in result.assessment_data.items():
                    if isinstance(item_assessment_data, dict):
                        enhanced_item_assessment = item_assessment_data.copy()
                        threshold = task.confidence_thresholds.get(item_attr_name, 0.9)
                        enhanced_item_assessment["confidence_threshold"] = threshold
                        item_assessment[item_attr_name] = enhanced_item_assessment
                    else:
                        logger.warning(
                            f"Unexpected list item assessment data type for {attr_name}[{item_index}].{item_attr_name}: {type(item_assessment_data)}"
                        )
                        item_assessment[item_attr_name] = item_assessment_data

                enhanced_assessment_data[attr_name][item_index] = item_assessment

        return enhanced_assessment_data, all_confidence_alerts, aggregated_metering

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
                raise

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
                raise
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
                    raise
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
        Process a single section from a Document object to assess extraction confidence using granular approach.

        Args:
            document: Document object containing section to process
            section_id: ID of the section to process

        Returns:
            Document: Updated Document object with assessment results appended to extraction results
        """
        # Check if assessment is enabled in configuration
        assessment_config = self.config.get("assessment", {})
        from idp_common.utils import normalize_boolean_value

        enabled = normalize_boolean_value(assessment_config.get("enabled", True))
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
            f"Granular assessing {len(sorted_page_ids)} pages, class {class_label}: {start_page}-{end_page}"
        )

        # Track metrics
        metrics.put_metric("InputDocumentsForGranularAssessment", 1)
        metrics.put_metric(
            "InputDocumentPagesForGranularAssessment", len(section.page_ids)
        )

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

            # Read page images with configurable dimensions
            assessment_config = self.assessment_config
            image_config = assessment_config.get("image", {})
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
            model_id = self.config.get("model_id") or assessment_config.get("model")
            temperature = _safe_float_conversion(
                assessment_config.get("temperature", 0), 0.0
            )
            top_k = _safe_float_conversion(assessment_config.get("top_k", 5), 5.0)
            top_p = _safe_float_conversion(assessment_config.get("top_p", 0.1), 0.1)
            max_tokens = (
                int(
                    _safe_float_conversion(
                        assessment_config.get("max_tokens", 4096), 4096
                    )
                )
                if assessment_config.get("max_tokens")
                else None
            )
            system_prompt = assessment_config.get("system_prompt", "")

            # Get attributes for this document class
            attributes = self._get_class_attributes(class_label)

            # Get confidence thresholds
            default_confidence_threshold = _safe_float_conversion(
                assessment_config.get("default_confidence_threshold", 0.9), 0.9
            )

            # Build the cached base prompt (without attribute descriptions - those are task-specific)
            base_content = self._build_cached_prompt_base(
                document_text,
                class_label,
                "",  # Empty attribute descriptions - will be replaced per task
                ocr_text_confidence,
                page_images,
            )

            # Create assessment tasks
            tasks = self._create_assessment_tasks(
                extraction_results, attributes, default_confidence_threshold
            )

            if not tasks:
                logger.warning(f"No assessment tasks created for section {section_id}")
                return document

            # Check for cached assessment task results
            cached_task_results = self._get_cached_assessment_tasks(
                document.id, document.workflow_execution_arn, section_id
            )
            all_task_results = list(cached_task_results.values())
            combined_metering = {}

            # Use thread-safe error collection (similar to classification service)
            import threading

            errors_lock = threading.Lock()
            failed_task_exceptions = {}  # Store original exceptions for failed tasks

            # Determine which tasks need processing
            tasks_to_process = []
            for task in tasks:
                if task.task_id not in cached_task_results:
                    tasks_to_process.append(task)
                else:
                    # Task already cached - merge its metering data
                    cached_result = cached_task_results[task.task_id]
                    if cached_result.metering:
                        combined_metering = utils.merge_metering_data(
                            combined_metering, cached_result.metering
                        )

            if tasks_to_process:
                logger.info(
                    f"Found {len(cached_task_results)} cached assessment task results, processing {len(tasks_to_process)} remaining tasks"
                )

                # Time the model invocations
                request_start_time = time.time()

                # Process tasks (parallel or sequential based on configuration)
                if self.enable_parallel and len(tasks_to_process) > 1:
                    logger.info(
                        f"Processing {len(tasks_to_process)} assessment tasks in parallel with {self.max_workers} workers"
                    )

                    with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                        # Submit all uncached tasks
                        future_to_task = {
                            executor.submit(
                                self._process_assessment_task,
                                task,
                                base_content,
                                attributes,
                                model_id,
                                system_prompt,
                                temperature,
                                top_k,
                                top_p,
                                max_tokens,
                            ): task
                            for task in tasks_to_process
                        }

                        # Collect results with enhanced error handling
                        for future in as_completed(future_to_task):
                            task = future_to_task[future]
                            try:
                                result = future.result()
                                all_task_results.append(result)

                                # Merge metering data
                                if result.metering:
                                    combined_metering = utils.merge_metering_data(
                                        combined_metering, result.metering
                                    )
                            except Exception as e:
                                # Capture exception details for later use
                                error_msg = f"Error processing assessment task {task.task_id}: {str(e)}"
                                logger.error(error_msg)
                                with errors_lock:
                                    document.errors.append(error_msg)
                                    # Store the original exception for later analysis
                                    failed_task_exceptions[task.task_id] = e

                                # Create failed result
                                failed_result = AssessmentResult(
                                    task_id=task.task_id,
                                    success=False,
                                    assessment_data={},
                                    confidence_alerts=[],
                                    error_message=str(e),
                                )
                                all_task_results.append(failed_result)
                else:
                    logger.info(
                        f"Processing {len(tasks_to_process)} assessment tasks sequentially"
                    )
                    request_start_time = time.time()

                    for task in tasks_to_process:
                        try:
                            result = self._process_assessment_task(
                                task,
                                base_content,
                                attributes,
                                model_id,
                                system_prompt,
                                temperature,
                                top_k,
                                top_p,
                                max_tokens,
                            )
                            all_task_results.append(result)

                            # Merge metering data
                            if result.metering:
                                combined_metering = utils.merge_metering_data(
                                    combined_metering, result.metering
                                )
                        except Exception as e:
                            # Capture exception details for later use
                            error_msg = f"Error processing assessment task {task.task_id}: {str(e)}"
                            logger.error(error_msg)
                            document.errors.append(error_msg)
                            # Store the original exception for later analysis
                            failed_task_exceptions[task.task_id] = e

                            # Create failed result
                            failed_result = AssessmentResult(
                                task_id=task.task_id,
                                success=False,
                                assessment_data={},
                                confidence_alerts=[],
                                error_message=str(e),
                            )
                            all_task_results.append(failed_result)

                # Store failed task exceptions in document metadata for caller to access
                if failed_task_exceptions:
                    logger.info(
                        f"Processing {len(failed_task_exceptions)} failed assessment task exceptions for document {document.id} section {section_id}"
                    )

                    # Store the first throttling exception as the primary failure cause
                    throttling_exceptions = {
                        task_id: exc
                        for task_id, exc in failed_task_exceptions.items()
                        if self._is_throttling_exception(exc)
                    }

                    first_exception = next(iter(failed_task_exceptions.values()))
                    primary_exception = (
                        next(iter(throttling_exceptions.values()))
                        if throttling_exceptions
                        else first_exception
                    )

                    document.metadata = document.metadata or {}
                    document.metadata["failed_assessment_tasks"] = {
                        task_id: {
                            "exception_type": type(exc).__name__,
                            "exception_message": str(exc),
                            "exception_class": exc.__class__.__module__
                            + "."
                            + exc.__class__.__name__,
                            "is_throttling": self._is_throttling_exception(exc),
                        }
                        for task_id, exc in failed_task_exceptions.items()
                    }
                    # Store the primary exception for easy access by caller
                    document.metadata["primary_exception"] = primary_exception

                # Check for any failed tasks (both exceptions and unsuccessful results)
                failed_results = [r for r in all_task_results if not r.success]
                any_failures = bool(failed_task_exceptions or failed_results)

                # Cache successful tasks only when there are failures (for retry optimization)
                if any_failures:
                    successful_results = [r for r in all_task_results if r.success]
                    if successful_results:
                        logger.info(
                            f"Caching {len(successful_results)} successful assessment task results for document {document.id} section {section_id} due to {len(failed_results)} failed results + {len(failed_task_exceptions)} failed exceptions (retry scenario)"
                        )
                        self._cache_successful_assessment_tasks(
                            document.id,
                            document.workflow_execution_arn,
                            section_id,
                            successful_results,
                        )
                    else:
                        logger.warning(
                            f"No successful assessment task results to cache for document {document.id} section {section_id} - all tasks failed"
                        )
                else:
                    # All new tasks succeeded - no need to cache since there won't be retries
                    logger.info(
                        f"All new assessment tasks succeeded for document {document.id} section {section_id} - skipping cache (no retry needed)"
                    )
            else:
                logger.info(
                    f"All {len(cached_task_results)} assessment task results found in cache"
                )
                request_start_time = (
                    time.time()
                )  # For consistency in timing calculations

            # Use all_task_results instead of results for aggregation
            results = all_task_results

            total_duration = time.time() - request_start_time
            logger.info(
                f"Time taken for granular assessment: {total_duration:.2f} seconds"
            )

            # Aggregate results
            (
                enhanced_assessment_data,
                confidence_threshold_alerts,
                aggregated_metering,
            ) = self._aggregate_assessment_results(
                tasks, results, extraction_results, attributes
            )

            # Calculate success metrics
            successful_tasks = [r for r in results if r.success]
            failed_tasks = [r for r in results if not r.success]

            logger.info(
                f"Assessment completed: {len(successful_tasks)}/{len(tasks)} tasks successful"
            )

            # Handle failures - check if we should trigger state machine retries
            if failed_tasks:
                error_message = self._handle_parsing_errors(
                    document, failed_tasks, document_text, extraction_results
                )
                if error_message:
                    logger.error(f"Error: {error_message}")
                    document.status = Status.FAILED
                    document.errors.append(error_message)

                # Add task errors to document errors
                task_errors = [t.error_message for t in failed_tasks if t.error_message]
                if task_errors:
                    error_msg = self._convert_error_list_to_string(task_errors)
                    logger.error(f"Task Error: {error_msg}")
                    document.status = Status.FAILED
                    document.errors.append(error_msg)

                # Check if we should trigger state machine retries for throttling exceptions
                # This mirrors the classification service pattern
                if (
                    hasattr(document, "metadata")
                    and document.metadata
                    and "primary_exception" in document.metadata
                ):
                    primary_exception = document.metadata["primary_exception"]
                    if self._is_throttling_exception(primary_exception):
                        logger.error(
                            f"Re-raising throttling exception to trigger state machine retry: {type(primary_exception).__name__}"
                        )
                        # Update document status in AppSync before raising exception
                        # (this will be handled by the Lambda function)

                        # Re-raise the throttling exception to trigger state machine retries
                        raise primary_exception
                    else:
                        logger.warning(
                            f"Primary exception is not throttling-related: {type(primary_exception).__name__}. "
                            f"Document will be marked as failed without retry."
                        )

            # Update the existing extraction result with enhanced assessment data
            extraction_data["explainability_info"] = [enhanced_assessment_data]
            extraction_data["metadata"] = extraction_data.get("metadata", {})
            extraction_data["metadata"]["assessment_time_seconds"] = total_duration
            extraction_data["metadata"]["granular_assessment_used"] = True
            extraction_data["metadata"]["assessment_tasks_total"] = len(tasks)
            extraction_data["metadata"]["assessment_tasks_successful"] = len(
                successful_tasks
            )
            extraction_data["metadata"]["assessment_tasks_failed"] = len(failed_tasks)

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
                document.metering, aggregated_metering or {}
            )
            t5 = time.time()
            logger.info(
                f"Total granular assessment time for section {section_id}: {t5 - t0:.2f} seconds"
            )
        except Exception as e:
            # Error is processed in the final results step
            error_msg = f"Error processing granular assessment for section {section_id}: {str(e)}"
            logger.error(error_msg)
            document.status = Status.FAILED
            document.errors.append(error_msg)

            # Check if this is a throttling exception and populate metadata for retry handling
            if self._is_throttling_exception(e):
                logger.info(
                    f"Populating metadata for throttling exception: {type(e).__name__}"
                )
                document.metadata = document.metadata or {}
                document.metadata["failed_assessment_tasks"] = {
                    "granular_processing": {
                        "exception_type": type(e).__name__,
                        "exception_message": str(e),
                        "exception_class": e.__class__.__module__
                        + "."
                        + e.__class__.__name__,
                        "is_throttling": True,
                    }
                }
                document.metadata["primary_exception"] = e

        # Additional check: if document status is FAILED and contains throttling errors,
        # populate metadata even if no exceptions were thrown
        if (
            document.status == Status.FAILED
            and document.errors
            and not hasattr(document, "metadata")
            or not document.metadata
            or "failed_assessment_tasks" not in document.metadata
        ):
            # Check if any errors contain throttling keywords
            throttling_keywords = [
                "throttlingexception",
                "provisionedthroughputexceededexception",
                "servicequotaexceededexception",
                "toomanyrequestsexception",
                "requestlimitexceeded",
                "too many tokens",
                "please wait before trying again",
                "reached max retries",
            ]

            has_throttling_error = False
            throttling_error_msg = None
            for error_msg in document.errors:
                error_lower = str(error_msg).lower()
                if any(keyword in error_lower for keyword in throttling_keywords):
                    has_throttling_error = True
                    throttling_error_msg = error_msg
                    break

            if has_throttling_error:
                logger.info(
                    f"Populating metadata for throttling error found in document.errors: {throttling_error_msg}"
                )
                document.metadata = document.metadata or {}
                document.metadata["failed_assessment_tasks"] = {
                    "document_level_error": {
                        "exception_type": "ThrottlingError",
                        "exception_message": throttling_error_msg,
                        "exception_class": "DocumentLevelThrottlingError",
                        "is_throttling": True,
                    }
                }

        return document

    def assess_document(self, document: Document) -> Document:
        """
        Assess extraction confidence for all sections in a document using granular approach.

        Args:
            document: Document object with extraction results

        Returns:
            Document: Updated Document object with assessment results
        """
        logger.info(f"Starting granular assessment for document {document.id}")

        for section in document.sections:
            if section.extraction_result_uri:
                logger.info(f"Granular assessing section {section.section_id}")
                document = self.process_document_section(document, section.section_id)
            else:
                logger.warning(
                    f"Section {section.section_id} has no extraction results to assess"
                )

        logger.info(f"Completed granular assessment for document {document.id}")
        return document

    def _handle_parsing_errors(
        self,
        document: Document,
        failed_tasks: List[str],
        document_text: str,
        extraction_results: Dict,
    ) -> Optional[str]:
        """Handle multiple parsing errors with user-friendly messaging."""
        # Check for token limit issues
        token_warning = check_token_limit(
            document_text, extraction_results, self.config
        )
        logger.info(f"Token Warning: {token_warning}")
        error_count = len(failed_tasks)
        base_msg = f"Assessment failed for {error_count} tasks. "
        if token_warning:
            return base_msg + token_warning
        else:
            return None

    def is_parsing_error(self, error_message: str) -> bool:
        """Check if an error message is related to parsing issues."""
        parsing_errors = ["parsing"]
        return any(error.lower() in error_message.lower() for error in parsing_errors)

    def _convert_error_list_to_string(self, errors) -> str:
        """Convert list of error messages to a single user-friendly string."""
        if not errors:
            return ""

        # Handle single string input
        if isinstance(errors, str):
            return errors

        # Ensure we have a list of strings
        if not isinstance(errors, list):
            return str(errors)

        # Count different types of errors
        parsing_errors = [e for e in errors if "parsing" in e.lower()]
        other_errors = [e for e in errors if "parsing" not in e.lower()]

        if len(parsing_errors) > 10:
            # Too many parsing errors - summarize
            return (
                f"Multiple parsing errors occurred {len(parsing_errors)} parsing errors, "
                f"{len(other_errors)} other errors. This suggests document complexity or token limit issues."
            )
        elif len(errors) > 5:
            # Multiple errors - show first few and summarize
            first_errors = "; ".join(errors[:1])
            return f"{first_errors} and {len(errors) - 1} more errors"
        else:
            # Few errors - show all
            return "; ".join(errors)
