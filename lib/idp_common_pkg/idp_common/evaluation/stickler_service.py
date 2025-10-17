# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Stickler-based evaluation service for document extraction results.

This module provides a service for evaluating extraction results using the
Stickler library for advanced validation rules and custom evaluation criteria.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from idp_common import s3
from idp_common.evaluation.metrics import calculate_metrics
from idp_common.evaluation.models import (
    AttributeEvaluationResult,
    DocumentEvaluationResult,
    SectionEvaluationResult,
)
from idp_common.models import Document, Section

try:
    from stickler.structured_object_evaluator.models.structured_model import (
        StructuredModel,
    )

    STICKLER_AVAILABLE = True
except ImportError:
    STICKLER_AVAILABLE = False
    StructuredModel = None

logger = logging.getLogger(__name__)


class SticklerEvaluationService:
    """Evaluation service using Stickler library for custom validation rules."""

    def __init__(self, region: str = None, config: Dict[str, Any] = None):
        """
        Initialize the stickler evaluation service.

        Args:
            region: AWS region (for S3 access)
            config: Configuration dictionary containing stickler evaluation settings

        Raises:
            ImportError: If stickler library is not installed
        """
        if not STICKLER_AVAILABLE:
            raise ImportError(
                "Stickler library is not installed. "
                "Install it with: pip install stickler-eval"
            )

        self.config = config or {}
        self.region = region
        self.stickler_models = {}  # Cache for dynamically created Stickler models

        # Load Stickler model configurations from config
        self._load_stickler_models()

        logger.info("Initialized SticklerEvaluationService")

    def _load_stickler_models(self) -> None:
        """Load Stickler model configurations from the config."""
        stickler_config = self.config.get("stickler_models", {})

        for class_name, model_config in stickler_config.items():
            try:
                # Create dynamic Stickler model from JSON configuration
                model_class = StructuredModel.model_from_json(model_config)
                self.stickler_models[class_name.lower()] = {
                    "model_class": model_class,
                    "config": model_config,
                }
                logger.info(f"Loaded Stickler model for class: {class_name}")
            except Exception as e:
                logger.error(
                    f"Error loading Stickler model for {class_name}: {str(e)}"
                )

    def _load_extraction_results(self, uri: str) -> Dict[str, Any]:
        """
        Load extraction results from S3.

        Args:
            uri: S3 URI to the extraction results

        Returns:
            Dictionary of extraction results
        """
        try:
            content = s3.get_json_content(uri)

            # Check if results are wrapped in inference_result key
            if isinstance(content, dict) and "inference_result" in content:
                return content["inference_result"]
            else:
                return content
        except Exception as e:
            logger.error(f"Error loading extraction results from {uri}: {str(e)}")
            return {}

    def _flatten_comparison_result(
        self, comparison_result: Dict[str, Any], prefix: str = ""
    ) -> List[Tuple[str, float, Any]]:
        """
        Flatten nested comparison results from Stickler into attribute-level scores.

        Args:
            comparison_result: Result from Stickler's compare_with method
            prefix: Prefix for nested field names

        Returns:
            List of tuples (field_name, score, details)
        """
        flattened = []

        # Extract field scores
        field_scores = comparison_result.get("field_scores", {})
        for field_name, score in field_scores.items():
            full_name = f"{prefix}.{field_name}" if prefix else field_name
            flattened.append((full_name, score, None))

        # Extract nested scores
        nested_scores = comparison_result.get("nested_scores", {})
        for field_name, nested_result in nested_scores.items():
            full_name = f"{prefix}.{field_name}" if prefix else field_name
            if isinstance(nested_result, dict):
                # Recursively flatten nested structures
                nested_flattened = self._flatten_comparison_result(
                    nested_result, full_name
                )
                flattened.extend(nested_flattened)

        # Extract list scores
        list_scores = comparison_result.get("list_scores", {})
        for field_name, list_result in list_scores.items():
            full_name = f"{prefix}.{field_name}" if prefix else field_name
            if isinstance(list_result, dict):
                # For lists, use the overall list score
                list_score = list_result.get("overall_score", 0.0)
                flattened.append((full_name, list_score, list_result))

        return flattened

    def _create_attribute_result(
        self,
        attr_name: str,
        expected_value: Any,
        actual_value: Any,
        score: float,
        details: Any = None,
    ) -> AttributeEvaluationResult:
        """
        Create an AttributeEvaluationResult from Stickler comparison.

        Args:
            attr_name: Attribute name
            expected_value: Expected value
            actual_value: Actual value
            score: Similarity score from Stickler (0.0 to 1.0)
            details: Additional details from Stickler comparison

        Returns:
            AttributeEvaluationResult
        """
        # Determine if values match based on score
        # Use a threshold of 0.8 for matching (can be made configurable)
        matched = score >= 0.8

        # Generate reason based on score
        if score == 1.0:
            reason = "Exact match according to Stickler validation"
        elif score >= 0.8:
            reason = f"Values match with similarity score {score:.3f}"
        else:
            reason = f"Values do not match (similarity score: {score:.3f})"

        # Add list matching details if available
        if details and isinstance(details, dict):
            matched_pairs = details.get("matched_pairs", [])
            unmatched_expected = details.get("unmatched_expected", [])
            unmatched_actual = details.get("unmatched_actual", [])

            if matched_pairs or unmatched_expected or unmatched_actual:
                reason += f" | Matched: {len(matched_pairs)}, "
                reason += f"Missing: {len(unmatched_expected)}, "
                reason += f"Extra: {len(unmatched_actual)}"

        return AttributeEvaluationResult(
            name=attr_name,
            expected=expected_value,
            actual=actual_value,
            matched=matched,
            score=score,
            reason=reason,
            evaluation_method="STICKLER",
        )

    def evaluate_section(
        self,
        section: Section,
        expected_results: Dict[str, Any],
        actual_results: Dict[str, Any],
    ) -> SectionEvaluationResult:
        """
        Evaluate extraction results for a document section using Stickler.

        Args:
            section: Document section
            expected_results: Expected extraction results
            actual_results: Actual extraction results

        Returns:
            Evaluation results for the section
        """
        class_name = section.classification.lower()

        logger.debug(
            f"Evaluating Section {section.section_id} - class: {class_name}"
        )

        # Check if we have a Stickler model for this class
        if class_name not in self.stickler_models:
            logger.warning(
                f"No Stickler model configured for class: {class_name}. "
                f"Available models: {list(self.stickler_models.keys())}"
            )
            # Return empty result if no model configured
            return SectionEvaluationResult(
                section_id=section.section_id,
                document_class=section.classification,
                attributes=[],
                metrics={},
            )

        model_info = self.stickler_models[class_name]
        model_class = model_info["model_class"]

        try:
            # Create Stickler model instances from the data
            expected_instance = model_class(**expected_results)
            actual_instance = model_class(**actual_results)

            # Perform comparison using Stickler
            comparison_result = expected_instance.compare_with(actual_instance)

            # Flatten the comparison results to attribute-level scores
            flattened_results = self._flatten_comparison_result(comparison_result)

            # Create AttributeEvaluationResult for each field
            attribute_results = []
            for attr_name, score, details in flattened_results:
                # Get the actual values for this attribute
                expected_value = self._get_nested_value(expected_results, attr_name)
                actual_value = self._get_nested_value(actual_results, attr_name)

                attr_result = self._create_attribute_result(
                    attr_name, expected_value, actual_value, score, details
                )
                attribute_results.append(attr_result)

            # Calculate metrics from attribute results
            metrics = self._calculate_section_metrics(attribute_results)

            return SectionEvaluationResult(
                section_id=section.section_id,
                document_class=section.classification,
                attributes=attribute_results,
                metrics=metrics,
            )

        except Exception as e:
            logger.error(
                f"Error evaluating section {section.section_id} with Stickler: {str(e)}"
            )
            # Return empty result on error
            return SectionEvaluationResult(
                section_id=section.section_id,
                document_class=section.classification,
                attributes=[],
                metrics={},
            )

    def _get_nested_value(self, data: Dict[str, Any], path: str) -> Any:
        """
        Get a nested value from a dictionary using dot notation.

        Args:
            data: Dictionary to extract value from
            path: Dot-separated path (e.g., "customer.name")

        Returns:
            Value at the path, or None if not found
        """
        keys = path.split(".")
        value = data

        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    return None
            else:
                return None

        return value

    def _calculate_section_metrics(
        self, attribute_results: List[AttributeEvaluationResult]
    ) -> Dict[str, float]:
        """
        Calculate metrics for a section from attribute results.

        Args:
            attribute_results: List of attribute evaluation results

        Returns:
            Dictionary of metrics
        """
        if not attribute_results:
            return {}

        # Count true/false positives/negatives
        tp = fp = fn = tn = fp1 = fp2 = 0

        for attr_result in attribute_results:
            expected = attr_result.expected
            actual = attr_result.actual
            matched = attr_result.matched

            # Case 1: Expected value is None/empty
            if expected is None or (isinstance(expected, str) and not expected.strip()):
                if actual is None or (isinstance(actual, str) and not actual.strip()):
                    tn += 1  # Correctly didn't predict a value
                else:
                    fp += 1  # Incorrectly predicted a value
                    fp1 += 1

            # Case 2: Expected value exists but actual doesn't
            elif actual is None or (isinstance(actual, str) and not actual.strip()):
                fn += 1  # Missing prediction

            # Case 3: Both values exist
            else:
                if matched:
                    tp += 1  # Correct prediction
                else:
                    fp += 1  # Incorrect prediction
                    fp2 += 1

        # Calculate metrics using the common metrics function
        metrics = calculate_metrics(tn, fp, fn, tp, fp1, fp2)

        return metrics

    def evaluate_document(
        self,
        document_id: str,
        sections: List[Section],
        expected_results_uri: str,
        actual_results_uri: str,
    ) -> DocumentEvaluationResult:
        """
        Evaluate a document using Stickler validation rules.

        Args:
            document_id: Document identifier
            sections: List of document sections
            expected_results_uri: S3 URI to expected results (ground truth)
            actual_results_uri: S3 URI to actual extraction results

        Returns:
            Document evaluation result with Stickler validation
        """
        start_time = time.time()

        # Load expected and actual results
        expected_results = self._load_extraction_results(expected_results_uri)
        actual_results = self._load_extraction_results(actual_results_uri)

        section_results = []

        for section in sections:
            section_result = self.evaluate_section(
                section=section,
                expected_results=expected_results,
                actual_results=actual_results,
            )
            section_results.append(section_result)

        # Calculate overall metrics from section results
        overall_metrics = self._calculate_overall_metrics(section_results)

        execution_time = time.time() - start_time

        return DocumentEvaluationResult(
            document_id=document_id,
            section_results=section_results,
            overall_metrics=overall_metrics,
            execution_time=execution_time,
        )

    def _calculate_overall_metrics(
        self, section_results: List[SectionEvaluationResult]
    ) -> Dict[str, float]:
        """
        Calculate overall metrics from section results.

        Args:
            section_results: List of section evaluation results

        Returns:
            Dictionary of overall metrics
        """
        if not section_results:
            return {}

        # Aggregate attribute results across all sections to recalculate metrics
        all_attributes = []
        for section_result in section_results:
            all_attributes.extend(section_result.attributes)

        # Recalculate metrics from all attributes
        if all_attributes:
            overall_metrics = self._calculate_section_metrics(all_attributes)
        else:
            overall_metrics = {}

        return overall_metrics
