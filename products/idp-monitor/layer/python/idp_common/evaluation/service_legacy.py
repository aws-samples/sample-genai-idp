# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Evaluation service for document extraction results.

This module provides a service for evaluating the extraction results of a document
by comparing them against expected values.
"""

import concurrent.futures
import logging
import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Generator, List, Optional, Tuple, Union

from idp_common import s3
from idp_common.config.models import IDPConfig
from idp_common.config.schema_constants import (
    SCHEMA_DESCRIPTION,
    SCHEMA_ITEMS,
    SCHEMA_PROPERTIES,
    SCHEMA_TYPE,
    TYPE_ARRAY,
    TYPE_OBJECT,
    X_AWS_IDP_DOCUMENT_TYPE,
    X_AWS_IDP_EVALUATION_METHOD,
)
from idp_common.evaluation.comparator import compare_values
from idp_common.evaluation.metrics import calculate_metrics
from idp_common.evaluation.models import (
    AttributeEvaluationResult,
    DocumentEvaluationResult,
    EvaluationAttribute,
    EvaluationMethod,
    SectionEvaluationResult,
)
from idp_common.models import Document, Section, Status

logger = logging.getLogger(__name__)


class EvaluationService:
    """Service for evaluating document extraction results."""

    def __init__(
        self,
        region: Optional[str] = None,
        config: Optional[Union[Dict[str, Any], IDPConfig]] = None,
        max_workers: int = 10,
    ):
        """
        Initialize the evaluation service.

        Args:
            region: AWS region
            config: Configuration dictionary or IDPConfig model containing evaluation settings
            max_workers: Maximum number of concurrent workers for section evaluation
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
        self.max_workers = max_workers

        # Set default LLM evaluation settings from typed config
        self.default_model = self.config.evaluation.llm_method.model
        self.default_temperature = self.config.evaluation.llm_method.temperature
        self.default_top_k = self.config.evaluation.llm_method.top_k
        self.default_top_p = self.config.evaluation.llm_method.top_p
        self.default_max_tokens = self.config.evaluation.llm_method.max_tokens
        self.default_system_prompt = (
            self.config.evaluation.llm_method.system_prompt
            or """You are an evaluator that helps determine if the predicted and expected values match for document attribute extraction. You will consider the context and meaning rather than just exact string matching."""
        )

        self.default_task_prompt = (
            self.config.evaluation.llm_method.task_prompt
            or """I need to evaluate attribute extraction for a document of class: {DOCUMENT_CLASS}.

For the attribute named "{ATTRIBUTE_NAME}" described as "{ATTRIBUTE_DESCRIPTION}":
- Expected value: {EXPECTED_VALUE}
- Actual value: {ACTUAL_VALUE}

Do these values match in meaning, taking into account formatting differences, word order, abbreviations, and semantic equivalence?
Provide your assessment as a JSON with three fields:
- "match": boolean (true if they match, false if not)
- "score": number between 0 and 1 representing the confidence/similarity score
- "reason": brief explanation of your decision

IMPORTANT: Respond ONLY with a valid JSON object and nothing else. Here's the exact format:
{
  "match": true or false,
  "score": 0.0 to 1.0,
  "reason": "Your explanation here"
}
            """
        )

        logger.info(
            "Initialized evaluation service with LLM configuration and max_workers=%d",
            self.max_workers,
        )

    def _get_attributes_for_class(self, class_name: str) -> List[EvaluationAttribute]:
        """
        Get attribute configurations for a document class from JSON Schema.

        Args:
            class_name: Document class name

        Returns:
            List of attribute configurations (flattened for nested structures)
        """
        classes = self.config.classes
        for schema in classes:
            if (
                isinstance(schema, dict)
                and schema.get(X_AWS_IDP_DOCUMENT_TYPE, "").lower()
                == class_name.lower()
            ):
                properties = schema.get(SCHEMA_PROPERTIES, {})
                return list(self._walk_properties(properties))

        logger.warning(f"No attribute configuration found for class: {class_name}")
        return []

    def _walk_properties(
        self, properties: Dict[str, Any], parent_path: str = ""
    ) -> Generator[EvaluationAttribute, None, None]:
        """
        Walk JSON Schema properties and yield evaluation attributes (generator pattern).

        Args:
            properties: Schema properties dict
            parent_path: Parent path for nested properties

        Yields:
            EvaluationAttribute objects for each leaf property
        """
        for prop_name, prop_schema in properties.items():
            prop_type = prop_schema.get(SCHEMA_TYPE)
            full_path = f"{parent_path}.{prop_name}" if parent_path else prop_name

            if prop_type == TYPE_OBJECT:
                # Recurse into nested object properties
                yield from self._walk_properties(
                    prop_schema.get(SCHEMA_PROPERTIES, {}), full_path
                )

            elif prop_type == TYPE_ARRAY:
                # Handle array items
                items_schema = prop_schema.get(SCHEMA_ITEMS, {})
                if items_schema.get(SCHEMA_TYPE) == TYPE_OBJECT:
                    # Recurse with [] notation for list items
                    yield from self._walk_properties(
                        items_schema.get(SCHEMA_PROPERTIES, {}), f"{full_path}[]"
                    )

            else:
                # Leaf property - yield evaluation attribute
                method_str = prop_schema.get(X_AWS_IDP_EVALUATION_METHOD, "LLM")
                try:
                    eval_method = EvaluationMethod(method_str.upper())
                except (ValueError, KeyError):
                    logger.warning(
                        f"Unknown evaluation method for '{full_path}': '{method_str}' (using LLM)"
                    )
                    eval_method = EvaluationMethod.LLM

                # Get threshold if specified
                threshold = 0.8
                if "evaluation_threshold" in prop_schema:
                    try:
                        threshold = float(prop_schema["evaluation_threshold"])
                    except (ValueError, TypeError):
                        logger.warning(
                            f"Invalid evaluation threshold for '{full_path}' (using default)"
                        )

                # Get comparator type for Hungarian method
                comparator_type = None
                if eval_method == EvaluationMethod.HUNGARIAN:
                    comparator_type = prop_schema.get("hungarian_comparator", "EXACT")

                yield EvaluationAttribute(
                    name=full_path,
                    description=prop_schema.get(SCHEMA_DESCRIPTION, ""),
                    evaluation_method=eval_method,
                    evaluation_threshold=threshold,
                    comparator_type=comparator_type,
                )

    def _flatten_nested_data(
        self, data: Dict[str, Any], parent_key: str = ""
    ) -> Dict[str, Any]:
        """
        Flatten nested data structures for evaluation.

        Args:
            data: Nested data dictionary
            parent_key: Parent key for building flattened keys

        Returns:
            Flattened dictionary with dot notation for nested keys
        """
        flattened = {}

        for key, value in data.items():
            # Build the full key
            full_key = f"{parent_key}.{key}" if parent_key else key

            if isinstance(value, dict):
                # Recursively flatten nested dictionaries (group attributes)
                flattened.update(self._flatten_nested_data(value, full_key))
            elif isinstance(value, list):
                # Handle list attributes - create entries for each item
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        # For dict items in lists, flatten each item
                        item_key = f"{full_key}[{i}]"
                        flattened.update(self._flatten_nested_data(item, item_key))
                    else:
                        # For simple items in lists
                        flattened[f"{full_key}[{i}]"] = item
            else:
                # Simple value
                flattened[full_key] = value

        return flattened

    def _flatten_confidence_scores(
        self, confidence_data: Dict[str, Any], parent_key: str = ""
    ) -> Dict[str, Dict[str, Any]]:
        """
        Flatten nested confidence scores for evaluation.

        Args:
            confidence_data: Nested confidence data
            parent_key: Parent key for building flattened keys

        Returns:
            Flattened confidence scores dictionary
        """
        flattened = {}

        for key, value in confidence_data.items():
            # Build the full key
            full_key = f"{parent_key}.{key}" if parent_key else key

            if isinstance(value, dict):
                if "confidence" in value:
                    # This is a confidence assessment
                    flattened[full_key] = {
                        "confidence": float(value["confidence"]),
                        "confidence_threshold": (
                            float(
                                value.get("confidence_threshold", None)  # type: ignore[arg-type]
                            )
                            if value.get("confidence_threshold") is not None
                            else None
                        ),
                    }
                else:
                    # Nested group - recurse
                    flattened.update(self._flatten_confidence_scores(value, full_key))
            elif isinstance(value, list):
                # Handle list confidence assessments
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        item_key = f"{full_key}[{i}]"
                        flattened.update(
                            self._flatten_confidence_scores(item, item_key)
                        )

        return flattened

    def _load_extraction_results(
        self, uri: str
    ) -> Tuple[Dict[str, Any], Dict[str, float]]:
        """
        Load extraction results from S3 and flatten nested structures.

        Args:
            uri: S3 URI to the extraction results

        Returns:
            Tuple of (flattened_extraction_results, flattened_confidence_scores)
        """
        try:
            content = s3.get_json_content(uri)
            extraction_results = {}
            confidence_scores = {}

            # Check if results are wrapped in inference_result key
            if isinstance(content, dict) and "inference_result" in content:
                raw_extraction_results = content["inference_result"]
            else:
                raw_extraction_results = content

            # Flatten the extraction results to handle nested structures
            extraction_results = self._flatten_nested_data(raw_extraction_results)

            # Extract confidence scores from explainability_info if present
            if isinstance(content, dict) and "explainability_info" in content:
                explainability_info = content["explainability_info"]
                if (
                    isinstance(explainability_info, list)
                    and len(explainability_info) > 0
                ):
                    # Get the first explainability entry (should be the main one)
                    confidence_data = explainability_info[0]
                    if isinstance(confidence_data, dict):
                        confidence_scores = self._flatten_confidence_scores(
                            confidence_data
                        )

            return extraction_results, confidence_scores  # type: ignore[return-value]
        except Exception:
            logger.error(
                f"Error loading extraction results from {uri}: {traceback.format_exc()}"
            )
            return {}, {}

    def _count_classifications(
        self,
        attr_name: str,
        expected: Any,
        actual: Any,
        evaluation_method: EvaluationMethod,
        threshold: float,
        document_class: Optional[str] = None,
        attr_description: Optional[str] = None,
        comparator_type: Optional[str] = None,
    ) -> Tuple[int, int, int, int, int, int, float, Optional[str]]:
        """
        Count true/false positives/negatives for an attribute.

        Args:
            attr_name: Attribute name
            expected: Expected value
            actual: Actual value
            evaluation_method: Method to use for comparison
            threshold: Evaluation threshold for fuzzy methods
            document_class: Document class for LLM evaluation
            attr_description: Attribute description for LLM evaluation
            comparator_type: Type of comparator for Hungarian method

        Returns:
            Tuple of (tn, fp, fn, tp, fp1, fp2, score, reason)
        """
        # Initialize counters
        tn = fp = fn = tp = fp1 = fp2 = 0
        score = 0.0
        reason = None

        # Case 1: Expected value is None/empty
        if expected is None or (isinstance(expected, str) and not expected.strip()):
            if actual is None or (isinstance(actual, str) and not actual.strip()):
                tn = 1  # Correctly didn't predict a value
                score = 1.0
                # Set reason to explain automatic match when both are empty
                reason = (
                    "Both actual and expected values are missing, so they are matched."
                )
            else:
                fp = fp1 = 1  # Incorrectly predicted a value when none expected
                score = 0.0

        # Case 2: Expected value exists but actual doesn't
        elif actual is None or (isinstance(actual, str) and not actual.strip()):
            fn = 1  # Missing prediction (false negative)
            score = 0.0

        # Case 3: Both values exist, compare them
        else:
            # Prepare LLM config if needed
            llm_config = None
            if evaluation_method == EvaluationMethod.LLM:
                llm_config = {
                    "model": self.default_model,
                    "temperature": self.default_temperature,
                    "top_k": self.default_top_k,
                    "system_prompt": self.default_system_prompt,
                    "task_prompt": self.default_task_prompt,
                }

            # Use compare_values for all evaluation methods
            matched, score, reason = compare_values(
                expected=expected,
                actual=actual,
                method=evaluation_method,
                threshold=threshold,
                document_class=document_class,
                attr_name=attr_name,
                attr_description=attr_description,
                llm_config=llm_config,
                comparator_type=comparator_type,
            )

            if matched:
                tp = 1  # Correct prediction
            else:
                fp = fp2 = 1  # Incorrect prediction

        return tn, fp, fn, tp, fp1, fp2, score, reason

    def _evaluate_single_attribute(
        self,
        attr_name: str,
        expected_value: Any,
        actual_value: Any,
        evaluation_method: EvaluationMethod,
        evaluation_threshold: float,
        document_class: str,
        attr_description: str,
        comparator_type: Optional[str] = None,
        is_unconfigured: bool = False,
    ) -> Tuple[AttributeEvaluationResult, Dict[str, int]]:
        """
        Evaluate a single attribute and return its result and metrics.

        Args:
            attr_name: Attribute name
            expected_value: Expected value
            actual_value: Actual value
            evaluation_method: Method for evaluation
            evaluation_threshold: Threshold for fuzzy matching
            document_class: Document class
            attr_description: Attribute description
            comparator_type: Comparator type for Hungarian method
            is_unconfigured: Whether this attribute is unconfigured

        Returns:
            Tuple of (attribute_result, metrics)
        """
        # Count classifications
        logger.info(
            f"Comparing: {attr_name} using {evaluation_method} - from class {document_class}"
        )

        attr_tn, attr_fp, attr_fn, attr_tp, attr_fp1, attr_fp2, score, reason = (
            self._count_classifications(
                attr_name=attr_name,
                expected=expected_value,
                actual=actual_value,
                evaluation_method=evaluation_method,
                threshold=evaluation_threshold,
                document_class=document_class,
                attr_description=attr_description,
                comparator_type=comparator_type,
            )
        )

        # Determine if this is a match
        # Case where both values are empty - should always be a match
        if (
            expected_value is None
            or (isinstance(expected_value, str) and not expected_value.strip())
        ) and (
            actual_value is None
            or (isinstance(actual_value, str) and not actual_value.strip())
        ):
            matched = True
        # For other cases, we use the logic based on tp, fp, fn
        elif attr_tp > 0:
            matched = True
        else:
            matched = False

        # Add note about unconfigured attribute to reason if applicable
        if is_unconfigured:
            if reason:
                reason = f"{reason} [Default method - attribute not specified in the configuration]"
            else:
                reason = (
                    "[Default method - attribute not specified in the configuration]"
                )

        # Determine when to include the evaluation threshold
        include_threshold = evaluation_method in [
            EvaluationMethod.FUZZY,
            EvaluationMethod.SEMANTIC,
        ] or (
            evaluation_method == EvaluationMethod.HUNGARIAN
            and comparator_type == "FUZZY"
        )

        # Create attribute result
        attribute_result = AttributeEvaluationResult(
            name=attr_name,
            expected=expected_value,
            actual=actual_value,
            matched=matched,
            score=score,
            reason=reason,
            evaluation_method=evaluation_method.value,
            evaluation_threshold=evaluation_threshold if include_threshold else None,
            comparator_type=(
                comparator_type
                if evaluation_method == EvaluationMethod.HUNGARIAN
                else None
            ),
        )

        # Create metrics dictionary
        metrics = {
            "tn": attr_tn,
            "fp": attr_fp,
            "fn": attr_fn,
            "tp": attr_tp,
            "fp1": attr_fp1,
            "fp2": attr_fp2,
        }

        return attribute_result, metrics

    def evaluate_section(
        self,
        section: Section,
        expected_results: Dict[str, Any],
        actual_results: Dict[str, Any],
        confidence_scores: Optional[Dict[str, float]] = None,
    ) -> SectionEvaluationResult:
        """
        Evaluate extraction results for a document section.

        Args:
            section: Document section
            expected_results: Expected extraction results
            actual_results: Actual extraction results
            confidence_scores: Confidence scores for actual values from assessment

        Returns:
            Evaluation results for the section
        """
        class_name = section.classification
        configured_attributes = self._get_attributes_for_class(class_name)
        logger.debug(
            f"Evaluating Section {section.section_id} - class: {class_name}, content: {section}"
        )

        # Evaluation counters
        tp = fp = fn = tn = fp1 = fp2 = 0

        # Track tasks for parallel and sequential evaluation
        parallel_tasks = []  # For LLM evaluations (slow operations)
        sequential_tasks = []  # For non-LLM evaluations (fast operations)

        # Create a set of attribute names already processed from configuration
        processed_attr_names = set()

        # Create a mapping for list attribute patterns
        list_attribute_configs = {}
        for attr_config in configured_attributes:
            if "[]" in attr_config.name:
                # Store list attribute config for pattern matching
                pattern = attr_config.name.replace("[]", r"\[\d+\]")
                list_attribute_configs[pattern] = attr_config

        # Prepare configured attributes evaluation tasks
        for attr_config in configured_attributes:
            attr_name = attr_config.name

            if "[]" in attr_name:
                # This is a list attribute template - find all matching actual attributes
                import re

                pattern = attr_name.replace("[]", r"\[\d+\]")
                all_data_names = set(expected_results.keys()).union(
                    set(actual_results.keys())
                )

                for data_attr_name in all_data_names:
                    if re.match(f"^{pattern}$", data_attr_name):
                        expected_value = expected_results.get(data_attr_name)
                        actual_value = actual_results.get(data_attr_name)
                        processed_attr_names.add(data_attr_name)

                        # Create a task for this specific list item
                        task = {
                            "attr_name": data_attr_name,
                            "expected_value": expected_value,
                            "actual_value": actual_value,
                            "evaluation_method": attr_config.evaluation_method,
                            "evaluation_threshold": attr_config.evaluation_threshold,
                            "document_class": class_name,
                            "attr_description": attr_config.description,
                            "comparator_type": attr_config.comparator_type,
                            "is_unconfigured": False,
                        }

                        # Separate tasks based on evaluation method
                        if attr_config.evaluation_method in [
                            EvaluationMethod.LLM,
                            EvaluationMethod.SEMANTIC,
                        ]:
                            # These methods are expensive (API calls), so parallelize them
                            parallel_tasks.append(task)
                        else:
                            # These methods are fast, so run them sequentially
                            sequential_tasks.append(task)
            else:
                # Regular non-list attribute
                expected_value = expected_results.get(attr_name)
                actual_value = actual_results.get(attr_name)
                processed_attr_names.add(attr_name)

                # Create a task for this attribute
                task = {
                    "attr_name": attr_name,
                    "expected_value": expected_value,
                    "actual_value": actual_value,
                    "evaluation_method": attr_config.evaluation_method,
                    "evaluation_threshold": attr_config.evaluation_threshold,
                    "document_class": class_name,
                    "attr_description": attr_config.description,
                    "comparator_type": attr_config.comparator_type,
                    "is_unconfigured": False,
                }

                # Separate tasks based on evaluation method
                if attr_config.evaluation_method in [
                    EvaluationMethod.LLM,
                    EvaluationMethod.SEMANTIC,
                ]:
                    # These methods are expensive (API calls), so parallelize them
                    parallel_tasks.append(task)
                else:
                    # These methods are fast, so run them sequentially
                    sequential_tasks.append(task)

        # Now find attributes that exist in the data but not in configuration
        # Get all attribute names from both expected and actual results
        all_attr_names = set(expected_results.keys()).union(set(actual_results.keys()))

        # Filter out attributes already processed from configuration
        unconfigured_attr_names = all_attr_names - processed_attr_names

        # Add tasks for unconfigured attributes
        for attr_name in unconfigured_attr_names:
            expected_value = expected_results.get(attr_name)
            actual_value = actual_results.get(attr_name)

            # Use LLM as the default evaluation method for unconfigured attributes
            default_method = EvaluationMethod.LLM
            default_threshold = 0.8
            default_description = "Attribute found in data but not in configuration"

            # Unconfigured attributes use LLM by default, so add to parallel tasks
            parallel_tasks.append(
                {
                    "attr_name": attr_name,
                    "expected_value": expected_value,
                    "actual_value": actual_value,
                    "evaluation_method": default_method,
                    "evaluation_threshold": default_threshold,
                    "document_class": class_name,
                    "attr_description": default_description,
                    "comparator_type": None,
                    "is_unconfigured": True,
                }
            )

        attribute_results = []

        # First, process fast sequential tasks
        for task in sequential_tasks:
            try:
                attribute_result, metrics = self._evaluate_single_attribute(
                    task["attr_name"],
                    task["expected_value"],
                    task["actual_value"],
                    task["evaluation_method"],
                    task["evaluation_threshold"],
                    task["document_class"],
                    task["attr_description"],
                    task["comparator_type"],
                    task["is_unconfigured"],
                )

                # Set confidence scores if available
                if confidence_scores:
                    confidence_info = confidence_scores.get(task["attr_name"])
                    if isinstance(confidence_info, dict):
                        attribute_result.confidence = confidence_info.get("confidence")
                        attribute_result.confidence_threshold = confidence_info.get(
                            "confidence_threshold"
                        )

                # Add to attribute results
                attribute_results.append(attribute_result)

                # Update overall metrics
                tn += metrics["tn"]
                fp += metrics["fp"]
                fn += metrics["fn"]
                tp += metrics["tp"]
                fp1 += metrics["fp1"]
                fp2 += metrics["fp2"]

            except Exception:
                logger.error(
                    f"Error evaluating attribute {task['attr_name']}: {traceback.format_exc()}"
                )

        # Then, process slow parallel tasks with ThreadPoolExecutor if there are any
        if parallel_tasks:
            # Only create threads for operations that benefit from parallelization
            max_workers = min(len(parallel_tasks), self.max_workers)

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit tasks
                future_to_attr = {
                    executor.submit(
                        self._evaluate_single_attribute,
                        task["attr_name"],
                        task["expected_value"],
                        task["actual_value"],
                        task["evaluation_method"],
                        task["evaluation_threshold"],
                        task["document_class"],
                        task["attr_description"],
                        task["comparator_type"],
                        task["is_unconfigured"],
                    ): task["attr_name"]
                    for task in parallel_tasks
                }

                # Collect results
                for future in concurrent.futures.as_completed(future_to_attr):
                    attr_name = future_to_attr[future]
                    try:
                        attribute_result, metrics = future.result()

                        # Set confidence scores if available
                        # Find the corresponding task for this attribute
                        task = next(
                            (t for t in parallel_tasks if t["attr_name"] == attr_name),
                            None,
                        )
                        if task:
                            if confidence_scores:
                                confidence_info = confidence_scores.get(
                                    task["attr_name"]
                                )
                                if isinstance(confidence_info, dict):
                                    attribute_result.confidence = confidence_info.get(
                                        "confidence"
                                    )
                                    attribute_result.confidence_threshold = (
                                        confidence_info.get("confidence_threshold")
                                    )

                        # Add to attribute results
                        attribute_results.append(attribute_result)

                        # Update overall metrics
                        tn += metrics["tn"]
                        fp += metrics["fp"]
                        fn += metrics["fn"]
                        tp += metrics["tp"]
                        fp1 += metrics["fp1"]
                        fp2 += metrics["fp2"]

                    except Exception:
                        logger.error(
                            f"Error evaluating attribute {attr_name}: {traceback.format_exc()}"
                        )

        # Sort attribute results with proper numerical ordering for list indices
        def sort_key(attr_result):
            """
            Custom sort key that handles list indices numerically.

            Examples:
            - "Account Number" -> ("Account Number", -1, "")
            - "Account Holder Address.City" -> ("Account Holder Address", -1, "City")
            - "Transactions[0].Date" -> ("Transactions", 0, "Date")
            - "Transactions[10].Amount" -> ("Transactions", 10, "Amount")
            """
            import re

            name = attr_result.name

            # Check if this is a list attribute with index notation
            list_match = re.match(r"^([^[]+)\[(\d+)\]\.(.+)$", name)
            if list_match:
                base_name = list_match.group(1)
                index = int(list_match.group(2))
                attr_name = list_match.group(3)
                return (base_name, index, attr_name)

            # Check if this is a group attribute with dot notation
            if "." in name and "[" not in name:
                parts = name.split(".", 1)
                base_name = parts[0]
                attr_name = parts[1]
                return (base_name, -1, attr_name)

            # Simple attribute
            return (name, -1, "")

        attribute_results.sort(key=sort_key)

        # Calculate metrics
        metrics = calculate_metrics(tp=tp, fp=fp, fn=fn, tn=tn, fp1=fp1, fp2=fp2)

        return SectionEvaluationResult(
            section_id=section.section_id,
            document_class=class_name,
            attributes=attribute_results,
            metrics=metrics,
        )

    def _process_section(
        self, actual_section: Section, expected_section: Section
    ) -> Tuple[Optional[SectionEvaluationResult], Dict[str, int]]:
        """
        Process a single section for evaluation.

        Args:
            actual_section: Section with actual extraction results
            expected_section: Section with expected extraction results

        Returns:
            Tuple of (section_result, metrics_count)
        """
        # Track section metrics
        section_tp = section_fp = section_fn = section_tn = section_fp1 = (
            section_fp2
        ) = 0

        # Load extraction results
        actual_uri = actual_section.extraction_result_uri
        expected_uri = expected_section.extraction_result_uri

        if not actual_uri or not expected_uri:
            logger.warning(
                f"Missing extraction URI for section: {actual_section.section_id}"
            )
            # Return empty result
            return None, {}

        actual_results, confidence_scores = self._load_extraction_results(actual_uri)
        expected_results, expected_confidence_scores = self._load_extraction_results(
            expected_uri
        )

        # Evaluate section
        section_result = self.evaluate_section(
            section=actual_section,
            expected_results=expected_results,
            actual_results=actual_results,
            confidence_scores=confidence_scores,
        )

        # Count matches and mismatches in the attributes
        for attr in section_result.attributes:
            # Check if both are None/Empty - this should always be a match
            is_expected_empty = attr.expected is None or (
                isinstance(attr.expected, str) and not attr.expected.strip()
            )
            is_actual_empty = attr.actual is None or (
                isinstance(attr.actual, str) and not attr.actual.strip()
            )

            if is_expected_empty and is_actual_empty:
                # Both values are None/Empty, this should be considered a match (TN)
                section_tn += 1
                # Make sure the matched flag is set correctly
                attr.matched = True  # Force the matched flag to True if not already
            elif attr.matched:
                section_tp += 1
            else:
                # Handle different error cases
                if is_expected_empty:
                    # Expected None/Empty, got a value
                    section_fp += 1
                    section_fp1 += 1
                elif is_actual_empty:
                    # Expected a value, got None/Empty
                    section_fn += 1
                else:
                    # Both have values but don't match
                    section_fp += 1
                    section_fp2 += 1

        # Return the section result and metrics
        metrics = {
            "tp": section_tp,
            "fp": section_fp,
            "fn": section_fn,
            "tn": section_tn,
            "fp1": section_fp1,
            "fp2": section_fp2,
        }

        return section_result, metrics

    def evaluate_document(
        self,
        actual_document: Document,
        expected_document: Document,
        store_results: bool = True,
    ) -> Document:
        """
        Evaluate extraction results for an entire document and store results in S3.

        Args:
            actual_document: Document with actual extraction results
            expected_document: Document with expected extraction results
            store_results: Whether to store results in S3 (default: True)

        Returns:
            Updated actual document with evaluation results
        """
        try:
            # Start timing
            start_time = time.time()

            # Track overall metrics
            total_tp = total_fp = total_fn = total_tn = total_fp1 = total_fp2 = 0

            # Create a list of section pairs to evaluate
            section_pairs = []
            for actual_section in actual_document.sections:
                section_id = actual_section.section_id

                # Find corresponding section in expected document
                expected_section = next(
                    (
                        s
                        for s in expected_document.sections
                        if s.section_id == section_id
                    ),
                    None,
                )

                if not expected_section:
                    logger.warning(
                        f"No matching section found for section_id: {section_id}"
                    )
                    continue

                section_pairs.append((actual_section, expected_section))

            section_results = []

            # Process sections in parallel using ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                # Submit all section evaluations to the executor
                future_to_section = {
                    executor.submit(
                        self._process_section, actual_section, expected_section
                    ): actual_section.section_id
                    for actual_section, expected_section in section_pairs
                }

                # Collect results as they complete
                for future in concurrent.futures.as_completed(future_to_section):
                    section_id = future_to_section[future]
                    try:
                        result, metrics = future.result()
                        if result is None:
                            logger.warning(
                                f"Section {section_id} evaluation returned no result"
                            )
                            continue

                        # Add to section results
                        section_results.append(result)

                        # Update overall metrics
                        total_tp += metrics["tp"]
                        total_fp += metrics["fp"]
                        total_fn += metrics["fn"]
                        total_tn += metrics["tn"]
                        total_fp1 += metrics["fp1"]
                        total_fp2 += metrics["fp2"]

                    except Exception as e:
                        logger.error(
                            f"Error evaluating section {section_id}: {traceback.format_exc()}"
                        )
                        actual_document.errors.append(
                            f"Error evaluating section {section_id}: {str(e)}"
                        )

            # Sort section results by section_id for consistent output
            section_results.sort(key=lambda x: x.section_id)

            # Calculate overall metrics
            overall_metrics = calculate_metrics(
                tp=total_tp,
                fp=total_fp,
                fn=total_fn,
                tn=total_tn,
                fp1=total_fp1,
                fp2=total_fp2,
            )

            execution_time = time.time() - start_time

            # Create evaluation result
            evaluation_result = DocumentEvaluationResult(
                document_id=actual_document.id or "",  # type: ignore[arg-type]
                section_results=section_results,
                overall_metrics=overall_metrics,
                execution_time=execution_time,
            )

            # Store results if requested
            if store_results:
                # Generate output path
                output_bucket = actual_document.output_bucket
                output_key = f"{actual_document.input_key}/evaluation/results.json"

                # Store evaluation results in S3
                result_dict = evaluation_result.to_dict()
                s3.write_content(
                    content=result_dict,
                    bucket=output_bucket or "",  # type: ignore[arg-type]
                    key=output_key,
                    content_type="application/json",
                )

                # Generate Markdown report
                markdown_report = evaluation_result.to_markdown()
                report_key = f"{actual_document.input_key}/evaluation/report.md"
                s3.write_content(
                    content=markdown_report,
                    bucket=output_bucket or "",  # type: ignore[arg-type]
                    key=report_key,
                    content_type="text/markdown",
                )

                # Update document with evaluation report and results URIs
                actual_document.evaluation_report_uri = (
                    f"s3://{output_bucket}/{report_key}"
                )
                actual_document.evaluation_results_uri = (
                    f"s3://{output_bucket}/{output_key}"
                )
                actual_document.status = Status.COMPLETED

                logger.info(
                    f"Evaluation complete for document {actual_document.id} in {execution_time:.2f} seconds"
                )

            # Attach evaluation result to document for immediate use
            actual_document.evaluation_result = evaluation_result

            return actual_document

        except Exception as e:
            logger.error(f"Error evaluating document: {traceback.format_exc()}")
            actual_document.errors.append(f"Evaluation error: {str(e)}")
            return actual_document
