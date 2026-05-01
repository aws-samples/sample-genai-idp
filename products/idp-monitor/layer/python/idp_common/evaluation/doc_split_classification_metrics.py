# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Document Split Classification Metrics Module.

This module provides functionality to evaluate document split classification accuracy
by comparing ground truth and predicted document splits and classifications.
"""

import logging
from typing import Any, Dict, List, Optional

from idp_common import s3

logger = logging.getLogger(__name__)


class DocSplitClassificationMetrics:
    """
    Calculator for document split classification accuracy metrics.

    Evaluates three types of accuracy:
    1. Page Level Accuracy: Classification accuracy for individual pages
    2. Split Accuracy (Without Order): Correct page grouping regardless of order
    3. Split Accuracy (With Order): Correct page grouping with exact order
    """

    def __init__(self):
        """Initialize the metrics calculator."""
        self.page_classifications_gt: Dict[int, str] = {}  # page_index -> class
        self.page_classifications_pred: Dict[int, str] = {}  # page_index -> class
        self.sections_gt: List[Dict[str, Any]] = []
        self.sections_pred: List[Dict[str, Any]] = []
        self.errors: List[str] = []

    def _get_document_class(self, section_data: Dict[str, Any]) -> str:
        """
        Safely extract document class from section data.

        Args:
            section_data: Section data dictionary

        Returns:
            Document class name or "Unknown" if missing/invalid
        """
        if not section_data:
            return "Unknown"

        doc_class = section_data.get("document_class")
        if not doc_class or doc_class is None:
            return "Unknown"

        if isinstance(doc_class, dict):
            return doc_class.get("type", "Unknown")

        return str(doc_class) if doc_class else "Unknown"

    def _get_page_indices(self, section_data: Dict[str, Any]) -> List[int]:
        """
        Safely extract page indices from section data.

        Args:
            section_data: Section data dictionary

        Returns:
            List of page indices (0-based, may be non-sequential) or empty list
        """
        if not section_data:
            return []

        split_doc = section_data.get("split_document")
        if not split_doc or split_doc is None:
            return []

        page_indices = split_doc.get("page_indices", [])
        if not page_indices or page_indices is None:
            return []

        # Ensure all indices are integers
        try:
            return [int(idx) for idx in page_indices]
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid page indices format: {e}")
            return []

    def _load_section_data(self, uri: str) -> Optional[Dict[str, Any]]:
        """
        Load section data from S3 URI.

        Args:
            uri: S3 URI to section JSON file

        Returns:
            Section data dictionary or None if loading fails
        """
        try:
            return s3.get_json_content(uri)
        except Exception as e:
            error_msg = f"Error loading section data from {uri}: {str(e)}"
            logger.error(error_msg)
            self.errors.append(error_msg)
            return None

    def load_sections(
        self, ground_truth_sections: List[Any], predicted_sections: List[Any]
    ) -> None:
        """
        Load and parse ground truth and predicted sections.

        Args:
            ground_truth_sections: List of Section objects with ground truth data
            predicted_sections: List of Section objects with predicted data
        """
        # Load ground truth sections
        for section in ground_truth_sections:
            if not section.extraction_result_uri:
                logger.warning(
                    f"Section {section.section_id} has no extraction_result_uri"
                )
                continue

            section_data = self._load_section_data(section.extraction_result_uri)
            if not section_data:
                continue

            doc_class = self._get_document_class(section_data)
            page_indices = self._get_page_indices(section_data)

            if not page_indices:
                logger.warning(
                    f"Section {section.section_id} has no page indices in ground truth"
                )

            # Store section info
            self.sections_gt.append(
                {
                    "section_id": section.section_id,
                    "document_class": doc_class,
                    "page_indices": page_indices,
                }
            )

            # Build page-to-class mapping
            for page_idx in page_indices:
                self.page_classifications_gt[page_idx] = doc_class

        # Load predicted sections
        for section in predicted_sections:
            if not section.extraction_result_uri:
                logger.warning(
                    f"Section {section.section_id} has no extraction_result_uri"
                )
                continue

            section_data = self._load_section_data(section.extraction_result_uri)
            if not section_data:
                continue

            doc_class = self._get_document_class(section_data)
            page_indices = self._get_page_indices(section_data)

            if not page_indices:
                logger.warning(
                    f"Section {section.section_id} has no page indices in prediction"
                )

            # Store section info
            self.sections_pred.append(
                {
                    "section_id": section.section_id,
                    "document_class": doc_class,
                    "page_indices": page_indices,
                }
            )

            # Build page-to-class mapping
            for page_idx in page_indices:
                self.page_classifications_pred[page_idx] = doc_class

        logger.info(
            f"Loaded {len(self.sections_gt)} ground truth sections "
            f"and {len(self.sections_pred)} predicted sections"
        )

    def calculate_page_level_accuracy(self) -> Dict[str, Any]:
        """
        Calculate page-level classification accuracy.

        Compares document_class for each page index individually, regardless of
        which section it appears in.

        Returns:
            Dictionary with page-level accuracy metrics and per-page details
        """
        all_pages = set(self.page_classifications_gt.keys()) | set(
            self.page_classifications_pred.keys()
        )

        if not all_pages:
            return {
                "accuracy": 0.0,
                "total_pages": 0,
                "correct_pages": 0,
                "page_details": [],
            }

        correct_count = 0
        page_details = []

        for page_idx in sorted(all_pages):
            gt_class = self.page_classifications_gt.get(page_idx, "Missing")
            pred_class = self.page_classifications_pred.get(page_idx, "Missing")

            is_correct = gt_class == pred_class
            if is_correct:
                correct_count += 1

            page_details.append(
                {
                    "page_index": page_idx,
                    "ground_truth_class": gt_class,
                    "predicted_class": pred_class,
                    "correct": is_correct,
                }
            )

        accuracy = correct_count / len(all_pages) if all_pages else 0.0

        return {
            "accuracy": accuracy,
            "total_pages": len(all_pages),
            "correct_pages": correct_count,
            "page_details": page_details,
        }

    def calculate_split_accuracy_without_order(self) -> Dict[str, Any]:
        """
        Calculate document split accuracy without considering page order.

        For each ground truth section, checks if there's a predicted section with:
        - Same set of page indices (regardless of order)
        - Same document_class

        Returns:
            Dictionary with split accuracy metrics and per-section details
        """
        if not self.sections_gt:
            return {
                "accuracy": 0.0,
                "total_sections": 0,
                "correct_sections": 0,
                "section_details": [],
            }

        correct_count = 0
        section_details = []

        for gt_section in self.sections_gt:
            gt_pages_set = set(gt_section["page_indices"])
            gt_class = gt_section["document_class"]
            section_id = gt_section["section_id"]

            # Find if any predicted section matches (same pages set + same class)
            matched = False
            matched_pred_section = None

            for pred_section in self.sections_pred:
                pred_pages_set = set(pred_section["page_indices"])
                pred_class = pred_section["document_class"]

                if gt_pages_set == pred_pages_set and gt_class == pred_class:
                    matched = True
                    matched_pred_section = pred_section
                    break

            if matched:
                correct_count += 1

            section_details.append(
                {
                    "section_id": section_id,
                    "ground_truth_class": gt_class,
                    "ground_truth_pages": sorted(gt_section["page_indices"]),
                    "matched": matched,
                    "matched_section_id": (
                        matched_pred_section["section_id"]
                        if matched_pred_section
                        else None
                    ),
                    "predicted_class": (
                        matched_pred_section["document_class"]
                        if matched_pred_section
                        else "No Match"
                    ),
                    "predicted_pages": (
                        sorted(matched_pred_section["page_indices"])
                        if matched_pred_section
                        else []
                    ),
                }
            )

        accuracy = correct_count / len(self.sections_gt) if self.sections_gt else 0.0

        return {
            "accuracy": accuracy,
            "total_sections": len(self.sections_gt),
            "correct_sections": correct_count,
            "section_details": section_details,
        }

    def calculate_split_accuracy_with_order(self) -> Dict[str, Any]:
        """
        Calculate document split accuracy with page order consideration.

        For each ground truth section, checks if there's a predicted section with:
        - Exact same page indices list (same order)
        - Same document_class

        Returns:
            Dictionary with split accuracy metrics and per-section details
        """
        if not self.sections_gt:
            return {
                "accuracy": 0.0,
                "total_sections": 0,
                "correct_sections": 0,
                "section_details": [],
            }

        correct_count = 0
        section_details = []

        for gt_section in self.sections_gt:
            gt_pages = gt_section["page_indices"]
            gt_class = gt_section["document_class"]
            section_id = gt_section["section_id"]

            # Find if any predicted section matches (exact page order + same class)
            matched = False
            matched_pred_section = None
            order_matched = False

            for pred_section in self.sections_pred:
                pred_pages = pred_section["page_indices"]
                pred_class = pred_section["document_class"]

                # Check if pages match as sets first
                pages_match_as_set = set(gt_pages) == set(pred_pages)
                # Check if pages match in order
                pages_match_in_order = gt_pages == pred_pages
                # Check if class matches
                class_matches = gt_class == pred_class

                if pages_match_as_set and class_matches:
                    matched_pred_section = pred_section
                    order_matched = pages_match_in_order

                    if pages_match_in_order:
                        matched = True
                        break

            if matched:
                correct_count += 1

            section_details.append(
                {
                    "section_id": section_id,
                    "ground_truth_class": gt_class,
                    "ground_truth_pages": gt_pages,
                    "matched": matched,
                    "order_matched": order_matched,
                    "matched_section_id": (
                        matched_pred_section["section_id"]
                        if matched_pred_section
                        else None
                    ),
                    "predicted_class": (
                        matched_pred_section["document_class"]
                        if matched_pred_section
                        else "No Match"
                    ),
                    "predicted_pages": (
                        matched_pred_section["page_indices"]
                        if matched_pred_section
                        else []
                    ),
                }
            )

        accuracy = correct_count / len(self.sections_gt) if self.sections_gt else 0.0

        return {
            "accuracy": accuracy,
            "total_sections": len(self.sections_gt),
            "correct_sections": correct_count,
            "section_details": section_details,
        }

    def calculate_all_metrics(self) -> Dict[str, Any]:
        """
        Calculate all document split classification metrics.

        Returns:
            Dictionary containing all three accuracy types and detailed results
        """
        page_level = self.calculate_page_level_accuracy()
        split_without_order = self.calculate_split_accuracy_without_order()
        split_with_order = self.calculate_split_accuracy_with_order()

        return {
            "page_level_accuracy": page_level,
            "split_accuracy_without_order": split_without_order,
            "split_accuracy_with_order": split_with_order,
            "errors": self.errors,
        }

    def generate_markdown_report(self, metrics: Dict[str, Any]) -> str:
        """
        Generate a markdown report for document split classification metrics.

        Args:
            metrics: Dictionary containing all calculated metrics

        Returns:
            Formatted markdown report string
        """
        sections = []

        # Title
        sections.append("# Document Split Classification Evaluation")
        sections.append("")

        # Extract metrics
        page_level = metrics["page_level_accuracy"]
        split_no_order = metrics["split_accuracy_without_order"]
        split_with_order = metrics["split_accuracy_with_order"]

        # Helper function for visual indicator
        def get_indicator(accuracy: float) -> str:
            if accuracy >= 0.9:
                return "🟢"
            elif accuracy >= 0.7:
                return "🟡"
            elif accuracy >= 0.5:
                return "🟠"
            else:
                return "🔴"

        def get_rating(accuracy: float) -> str:
            if accuracy >= 0.9:
                return "🟢 Excellent"
            elif accuracy >= 0.7:
                return "🟡 Good"
            elif accuracy >= 0.5:
                return "🟠 Fair"
            else:
                return "🔴 Poor"

        # Summary section
        sections.append("## 🎯 Split Classification Summary")
        sections.append("")

        page_acc = page_level["accuracy"]
        split_no_ord_acc = split_no_order["accuracy"]
        split_ord_acc = split_with_order["accuracy"]

        # Create progress bars
        page_percent = int(page_acc * 100)
        page_progress = f"[{'█' * (page_percent // 5)}{'░' * (20 - page_percent // 5)}] {page_percent}%"

        split_no_ord_percent = int(split_no_ord_acc * 100)
        split_no_ord_progress = f"[{'█' * (split_no_ord_percent // 5)}{'░' * (20 - split_no_ord_percent // 5)}] {split_no_ord_percent}%"

        split_ord_percent = int(split_ord_acc * 100)
        split_ord_progress = f"[{'█' * (split_ord_percent // 5)}{'░' * (20 - split_ord_percent // 5)}] {split_ord_percent}%"

        sections.append(
            f"- **Page Level Accuracy**: {get_indicator(page_acc)} "
            f"{page_level['correct_pages']}/{page_level['total_pages']} pages "
            f"{page_progress}"
        )
        sections.append(
            f"- **Split Accuracy (Without Order)**: {get_indicator(split_no_ord_acc)} "
            f"{split_no_order['correct_sections']}/{split_no_order['total_sections']} sections "
            f"{split_no_ord_progress}"
        )
        sections.append(
            f"- **Split Accuracy (With Order)**: {get_indicator(split_ord_acc)} "
            f"{split_with_order['correct_sections']}/{split_with_order['total_sections']} sections "
            f"{split_ord_progress}"
        )
        sections.append("")

        # Detailed metrics table
        sections.append("## 📊 Split Classification Metrics")
        sections.append("")
        sections.append("| Metric | Accuracy | Rating | Correct/Total |")
        sections.append("| ------ | :------: | :----: | :-----------: |")
        sections.append(
            f"| Page Level Classification | {page_acc:.4f} | {get_rating(page_acc)} | "
            f"{page_level['correct_pages']}/{page_level['total_pages']} pages |"
        )
        sections.append(
            f"| Document Split (Without Page Order) | {split_no_ord_acc:.4f} | {get_rating(split_no_ord_acc)} | "
            f"{split_no_order['correct_sections']}/{split_no_order['total_sections']} sections |"
        )
        sections.append(
            f"| Document Split (With Page Order) | {split_ord_acc:.4f} | {get_rating(split_ord_acc)} | "
            f"{split_with_order['correct_sections']}/{split_with_order['total_sections']} sections |"
        )
        sections.append("")

        # Combined Section split analysis
        sections.append("## 📑 Section Split Analysis")
        sections.append("")

        if split_no_order["section_details"] or split_with_order["section_details"]:
            sections.append(
                "| Section Match | Page Order Match | Section ID | Expected Class | Expected Pages | Pred Class | Pred Pages | Matched Section |"
            )
            sections.append(
                "| :-----------: | :--------------: | ---------- | -------------- | -------------- | ---------- | ---------- | --------------- |"
            )

            # Track matched predicted section IDs
            matched_pred_section_ids = set()

            # Combine data from both metrics for ground truth sections
            for idx, section_with_order in enumerate(
                split_with_order["section_details"]
            ):
                # Get corresponding section from split_no_order
                section_no_order = (
                    split_no_order["section_details"][idx]
                    if idx < len(split_no_order["section_details"])
                    else None
                )

                # Section Match status (from split_no_order)
                section_match = (
                    "✅" if section_no_order and section_no_order["matched"] else "❌"
                )

                # Page Order Match status (from split_with_order)
                page_order_match = (
                    "✅" if section_with_order.get("order_matched", False) else "❌"
                )

                gt_pages = str(section_with_order["ground_truth_pages"])
                pred_pages = (
                    str(section_with_order["predicted_pages"])
                    if section_with_order["predicted_pages"]
                    else "N/A"
                )
                matched_id = (
                    section_with_order["matched_section_id"]
                    if section_with_order["matched_section_id"]
                    else "N/A"
                )

                # Track matched predicted section IDs
                if section_with_order["matched_section_id"]:
                    matched_pred_section_ids.add(
                        section_with_order["matched_section_id"]
                    )

                sections.append(
                    f"| {section_match} | {page_order_match} | {section_with_order['section_id']} | "
                    f"{section_with_order['ground_truth_class']} | {gt_pages} | {section_with_order['predicted_class']} | "
                    f"{pred_pages} | {matched_id} |"
                )

            # Add unmatched predicted sections
            for pred_section in self.sections_pred:
                if pred_section["section_id"] not in matched_pred_section_ids:
                    pred_pages = str(pred_section["page_indices"])
                    sections.append(
                        f"| ❌ | ❌ | N/A | No Match | N/A | "
                        f"{pred_section['document_class']} | {pred_pages} | {pred_section['section_id']} |"
                    )
        else:
            sections.append("*No section data available*")

        sections.append("")

        # Errors section if any
        if metrics.get("errors"):
            sections.append("## ⚠️ Errors Encountered")
            sections.append("")
            for error in metrics["errors"]:
                sections.append(f"- {error}")
            sections.append("")

        # Explanation section
        sections.append("## 📖 Metrics Explanation")
        sections.append("")
        sections.append("### Page Level Accuracy")
        sections.append("- Evaluates classification accuracy for **individual pages**")
        sections.append(
            "- Each page index is checked: does its predicted `document_class` match ground truth?"
        )
        sections.append("- Does not consider page grouping into sections")
        sections.append("")
        sections.append("### Section Split Analysis Table")
        sections.append(
            "- Combines all section-level evaluation metrics into a single comprehensive view"
        )
        sections.append(
            "- Shows both ground truth sections and unmatched predicted sections"
        )
        sections.append("")
        sections.append("**Column Definitions:**")
        sections.append("")
        sections.append(
            "- **Section Match**: ✅ if the expected section's pages (as a set) match any predicted section with the same document class, regardless of page order"
        )
        sections.append(
            "- **Page Order Match**: ✅ if Section Match is true AND the page order also matches exactly"
        )
        sections.append(
            "- **Section ID**: Ground truth section identifier (N/A for unmatched predicted sections)"
        )
        sections.append("- **Expected Class**: Document class from ground truth")
        sections.append("- **Expected Pages**: Page indices from ground truth section")
        sections.append("- **Pred Class**: Predicted document class")
        sections.append("- **Pred Pages**: Predicted page indices")
        sections.append(
            "- **Matched Section**: ID of the predicted section that matched the ground truth section"
        )
        sections.append("")
        sections.append("**Unmatched Predicted Sections:**")
        sections.append("")
        sections.append(
            "- Rows with N/A values represent predicted sections that don't correspond to any ground truth section"
        )
        sections.append(
            "- These indicate potential over-segmentation or incorrect classifications"
        )
        sections.append("")
        sections.append("### Document Split Accuracy Metrics")
        sections.append("")
        sections.append(
            "- **Without Page Order**: Counts sections where pages and class match (order doesn't matter)"
        )
        sections.append(
            "- **With Page Order**: Counts sections where pages, class, and page order all match exactly"
        )
        sections.append("")

        sections.append("---")
        sections.append("")

        return "\n".join(sections)
