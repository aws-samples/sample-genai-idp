# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Models for document evaluation.

This module provides data models for evaluation results and comparison methods.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class EvaluationMethod(Enum):
    """Evaluation method types for different field comparison approaches."""

    EXACT = "EXACT"  # Exact string match after stripping punctuation and whitespace
    NUMERIC_EXACT = "NUMERIC_EXACT"  # Exact numeric match after normalizing
    SEMANTIC = "SEMANTIC"  # Semantic similarity comparison using embeddings
    HUNGARIAN = "HUNGARIAN"  # Bipartite matching for lists of values
    FUZZY = "FUZZY"  # Fuzzy string matching
    LLM = "LLM"  # LLM-based comparison using Bedrock models


@dataclass
class EvaluationAttribute:
    """Configuration for a single attribute to be evaluated."""

    name: str
    description: str
    evaluation_method: EvaluationMethod = EvaluationMethod.EXACT
    evaluation_threshold: float = 0.8  # Used for SEMANTIC, and FUZZY methods
    comparator_type: Optional[str] = None  # Used for HUNGARIAN method


@dataclass
class AttributeEvaluationResult:
    """Result of evaluation for a single attribute."""

    name: str
    expected: Any
    actual: Any
    matched: bool
    score: float = 1.0  # Score between 0 and 1 for fuzzy matching methods
    reason: Optional[str] = None  # Explanation from LLM evaluation
    error_details: Optional[str] = None
    evaluation_method: str = "EXACT"
    evaluation_threshold: Optional[float] = None
    comparator_type: Optional[str] = None  # Used for HUNGARIAN methods
    expected_confidence: Optional[float] = (
        None  # Confidence score from assessment for expected values
    )
    actual_confidence: Optional[float] = (
        None  # Confidence score from assessment for actual values
    )


@dataclass
class SectionEvaluationResult:
    """Result of evaluation for a document section."""

    section_id: str
    document_class: str
    attributes: List[AttributeEvaluationResult]
    metrics: Dict[str, float] = field(default_factory=dict)

    def get_attribute_results(self) -> Dict[str, AttributeEvaluationResult]:
        """Get results indexed by attribute name."""
        return {attr.name: attr for attr in self.attributes}


@dataclass
class DocumentEvaluationResult:
    """Comprehensive evaluation result for a document."""

    document_id: str
    section_results: List[SectionEvaluationResult]
    overall_metrics: Dict[str, float] = field(default_factory=dict)
    execution_time: float = 0.0
    output_uri: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "document_id": self.document_id,
            "overall_metrics": self.overall_metrics,
            "execution_time": self.execution_time,
            "output_uri": self.output_uri,
            "section_results": [
                {
                    "section_id": sr.section_id,
                    "document_class": sr.document_class,
                    "metrics": sr.metrics,
                    "attributes": [
                        {
                            "name": ar.name,
                            "expected": ar.expected,
                            "actual": ar.actual,
                            "matched": ar.matched,
                            "score": ar.score,
                            "reason": ar.reason,
                            "error_details": ar.error_details,
                            "evaluation_method": ar.evaluation_method,
                            "evaluation_threshold": ar.evaluation_threshold,
                            "comparator_type": ar.comparator_type,
                            "expected_confidence": ar.expected_confidence,
                            "actual_confidence": ar.actual_confidence,
                        }
                        for ar in sr.attributes
                    ],
                }
                for sr in self.section_results
            ],
        }

    def to_markdown(self) -> str:
        """Convert evaluation results to markdown format."""
        sections = []

        # Add document overview with visual summary
        sections.append(f"# Document Evaluation: {self.document_id}")
        sections.append("")

        # Get overall stats for visual summary
        total_attributes = 0
        matched_attributes = 0
        for sr in self.section_results:
            for attr in sr.attributes:
                total_attributes += 1
                if attr.matched:
                    matched_attributes += 1

        match_rate = (
            matched_attributes / total_attributes if total_attributes > 0 else 0
        )
        precision = self.overall_metrics.get("precision", 0)
        recall = self.overall_metrics.get("recall", 0)
        f1_score = self.overall_metrics.get("f1_score", 0)

        # Create visual summary with emojis
        sections.append("## Summary")

        # Match rate indicator
        if match_rate >= 0.9:
            match_indicator = "🟢"
        elif match_rate >= 0.7:
            match_indicator = "🟡"
        elif match_rate >= 0.5:
            match_indicator = "🟠"
        else:
            match_indicator = "🔴"

        # F1 score indicator
        if f1_score >= 0.9:
            f1_indicator = "🟢"
        elif f1_score >= 0.7:
            f1_indicator = "🟡"
        elif f1_score >= 0.5:
            f1_indicator = "🟠"
        else:
            f1_indicator = "🔴"

        # Create a visual progress bar for match rate
        match_percent = int(match_rate * 100)
        progress_bar = f"[{'█' * (match_percent // 5)}{'░' * (20 - match_percent // 5)}] {match_percent}%"

        sections.append(
            f"- **Match Rate**: {match_indicator} {matched_attributes}/{total_attributes} attributes matched {progress_bar}"
        )
        sections.append(
            f"- **Precision**: {precision:.2f} | **Recall**: {recall:.2f} | **F1 Score**: {f1_indicator} {f1_score:.2f}"
        )
        sections.append("")

        # Add overall metrics with enhanced formatting
        sections.append("## Overall Metrics")
        metrics_table = "| Metric | Value | Rating |\n| ------ | :----: | :----: |\n"
        for metric, value in self.overall_metrics.items():
            # Add a visual indicator based on metric value
            if metric in ["precision", "recall", "f1_score", "accuracy"]:
                if value >= 0.9:
                    indicator = "🟢 Excellent"
                elif value >= 0.7:
                    indicator = "🟡 Good"
                elif value >= 0.5:
                    indicator = "🟠 Fair"
                else:
                    indicator = "🔴 Poor"
            elif metric in ["false_alarm_rate", "false_discovery_rate"]:
                # For error metrics, lower is better
                if value <= 0.1:
                    indicator = "🟢 Excellent"
                elif value <= 0.3:
                    indicator = "🟡 Good"
                elif value <= 0.5:
                    indicator = "🟠 Fair"
                else:
                    indicator = "🔴 Poor"
            else:
                indicator = ""  # No rating for other metrics

            metrics_table += f"| {metric} | {value:.4f} | {indicator} |\n"
        sections.append(metrics_table)
        sections.append("")

        # Add section results
        for sr in self.section_results:
            sections.append(f"## Section: {sr.section_id} ({sr.document_class})")

            # Section metrics with enhanced formatting
            sections.append("### Metrics")
            metrics_table = (
                "| Metric | Value | Rating |\n| ------ | :----: | :----: |\n"
            )
            for metric, value in sr.metrics.items():
                # Add a visual indicator based on metric value
                if metric in ["precision", "recall", "f1_score", "accuracy"]:
                    if value >= 0.9:
                        indicator = "🟢 Excellent"
                    elif value >= 0.7:
                        indicator = "🟡 Good"
                    elif value >= 0.5:
                        indicator = "🟠 Fair"
                    else:
                        indicator = "🔴 Poor"
                elif metric in ["false_alarm_rate", "false_discovery_rate"]:
                    # For error metrics, lower is better
                    if value <= 0.1:
                        indicator = "🟢 Excellent"
                    elif value <= 0.3:
                        indicator = "🟡 Good"
                    elif value <= 0.5:
                        indicator = "🟠 Fair"
                    else:
                        indicator = "🔴 Poor"
                else:
                    indicator = ""  # No rating for other metrics

                metrics_table += f"| {metric} | {value:.4f} | {indicator} |\n"
            sections.append(metrics_table)
            sections.append("")

            # Attribute results
            sections.append("### Attributes")
            attr_table = "| Status | Attribute | Expected | Actual | Expected Confidence | Actual Confidence | Score | Method | Reason |\n"
            attr_table += "| :----: | --------- | -------- | ------ | :-----------------: | :---------------: | ----- | ------ | ------ |\n"
            for ar in sr.attributes:
                expected = str(ar.expected).replace("\n", " ")
                actual = str(ar.actual).replace("\n", " ")
                # Don't truncate the reason field for the report
                reason = str(ar.reason).replace("\n", " ") if ar.reason else ""
                # Format the method with evaluation_threshold and comparator_type if applicable
                method_display = ar.evaluation_method

                # Add threshold for methods that use it directly
                if ar.evaluation_threshold is not None and ar.evaluation_method in [
                    "FUZZY",
                    "SEMANTIC",
                ]:
                    method_display = (
                        f"{ar.evaluation_method} (threshold: {ar.evaluation_threshold})"
                    )

                # Add comparator type for Hungarian method
                if (
                    ar.comparator_type is not None
                    and ar.evaluation_method == "HUNGARIAN"
                ):
                    # If comparator is FUZZY, also include the threshold
                    if (
                        ar.comparator_type == "FUZZY"
                        and ar.evaluation_threshold is not None
                    ):
                        method_display = f"{ar.evaluation_method} (comparator: {ar.comparator_type}, threshold: {ar.evaluation_threshold})"
                    else:
                        method_display = (
                            f"{ar.evaluation_method} (comparator: {ar.comparator_type})"
                        )

                # Add color-coded status symbols (will render in markdown-compatible viewers)
                if ar.matched:
                    # Green checkmark for matched
                    status_symbol = "✅"
                else:
                    # Red X for not matched
                    status_symbol = "❌"

                # Format confidence values
                expected_confidence_str = (
                    f"{ar.expected_confidence:.2f}"
                    if ar.expected_confidence is not None
                    else "N/A"
                )
                actual_confidence_str = (
                    f"{ar.actual_confidence:.2f}"
                    if ar.actual_confidence is not None
                    else "N/A"
                )

                attr_table += f"| {status_symbol} | {ar.name} | {expected} | {actual} | {expected_confidence_str} | {actual_confidence_str} | {ar.score:.2f} | {method_display} | {reason} |\n"
            sections.append(attr_table)
            sections.append("")

        # Add execution time
        sections.append(f"Execution time: {self.execution_time:.2f} seconds")

        # Add evaluation methods explanation
        sections.append("")
        sections.append("## Evaluation Methods Used")
        sections.append("")
        sections.append(
            "This evaluation used the following methods to compare expected and actual values:"
        )
        sections.append("")
        sections.append(
            "1. **EXACT** - Exact string match after stripping punctuation and whitespace"
        )
        sections.append("2. **NUMERIC_EXACT** - Exact numeric match after normalizing")
        sections.append(
            "3. **FUZZY** - Fuzzy string matching using string similarity metrics (with evaluation_threshold)"
        )
        sections.append(
            "4. **SEMANTIC** - Semantic similarity comparison using Bedrock Titan embeddings (with evaluation_threshold)"
        )
        sections.append(
            "5. **HUNGARIAN** - Bipartite matching algorithm for lists of values"
        )
        sections.append(
            "   - **EXACT** - Hungarian matching with exact string comparison"
        )
        sections.append(
            "   - **FUZZY** - Hungarian matching with fuzzy string comparison (with evaluation_threshold)"
        )
        sections.append("   - **NUMERIC** - Hungarian matching with numeric comparison")
        sections.append(
            "6. **LLM** - Advanced semantic evaluation using Bedrock large language models"
        )
        sections.append("")
        sections.append(
            "Each attribute is configured with a specific evaluation method based on the data type and comparison needs."
        )

        return "\n".join(sections)
