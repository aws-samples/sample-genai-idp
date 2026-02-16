# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Assessment Analyzer Module

Handles confidence scores, geometry extraction, and quality metrics analysis.
"""

import json
import logging
from typing import Dict, Optional

import boto3
from botocore.exceptions import ClientError

from idp_sdk.core.stack_info import StackInfo

logger = logging.getLogger(__name__)


class AssessmentAnalyzer:
    """Analyzes document quality, confidence, and geometry"""

    def __init__(self, stack_name: str, region: Optional[str] = None):
        """
        Initialize assessment analyzer

        Args:
            stack_name: Name of the CloudFormation stack
            region: AWS region (optional)
        """
        self.stack_name = stack_name
        self.region = region

        # Initialize AWS clients
        self.s3 = boto3.client("s3", region_name=region)

        # Get stack resources
        stack_info = StackInfo(stack_name, region)
        if not stack_info.validate_stack():
            raise ValueError(
                f"Stack '{stack_name}' is not in a valid state for operations"
            )

        self.resources = stack_info.get_resources()
        logger.info(f"Initialized assessment analyzer for stack: {stack_name}")

    def get_confidence(self, document_id: str, section_id: int = 1) -> Dict:
        """
        Get confidence scores for document section fields

        Args:
            document_id: Document identifier (S3 key)
            section_id: Section number (default: 1)

        Returns:
            Dictionary with confidence data for each attribute
        """
        output_bucket = self.resources["OutputBucket"]

        try:
            result_key = f"{document_id}/sections/{section_id}/result.json"
            response = self.s3.get_object(Bucket=output_bucket, Key=result_key)
            result_data = json.loads(response["Body"].read())

            explainability_info = result_data.get("explainability_info", [])
            attributes = {}

            for info in explainability_info:
                if isinstance(info, dict):
                    for key, value in info.items():
                        if isinstance(value, dict) and "confidence" in value:
                            attributes[key] = {
                                "confidence": value["confidence"],
                                "confidence_threshold": value.get(
                                    "confidence_threshold"
                                ),
                                "reason": value.get("reason", ""),
                                "meets_threshold": value.get("meets_threshold"),
                            }

            return {
                "document_id": document_id,
                "section_id": section_id,
                "attributes": attributes,
            }

        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                raise FileNotFoundError(
                    f"Results not found for document: {document_id}, section: {section_id}"
                )
            raise

    def get_geometry(self, document_id: str, section_id: int = 1) -> Dict:
        """
        Get bounding box geometry for document section fields

        Args:
            document_id: Document identifier (S3 key)
            section_id: Section number (default: 1)

        Returns:
            Dictionary with geometry data for each attribute
        """
        output_bucket = self.resources["OutputBucket"]

        try:
            result_key = f"{document_id}/sections/{section_id}/result.json"
            response = self.s3.get_object(Bucket=output_bucket, Key=result_key)
            result_data = json.loads(response["Body"].read())

            explainability_info = result_data.get("explainability_info", [])
            attributes = {}

            for info in explainability_info:
                if isinstance(info, dict):
                    for key, value in info.items():
                        if isinstance(value, dict) and "geometry" in value:
                            geometry = value["geometry"]
                            attributes[key] = {
                                "page": geometry.get("page", 1),
                                "bbox": geometry.get("bbox", []),
                                "bounding_box": geometry.get("bounding_box", {}),
                            }

            return {
                "document_id": document_id,
                "section_id": section_id,
                "attributes": attributes,
            }

        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                raise FileNotFoundError(
                    f"Results not found for document: {document_id}, section: {section_id}"
                )
            raise

    def get_metrics(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        document_class: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> Dict:
        """
        Get aggregated quality metrics

        Args:
            start_date: Start date filter (ISO format)
            end_date: End date filter (ISO format)
            document_class: Document class filter
            batch_id: Batch ID filter

        Returns:
            Dictionary with aggregated quality metrics
        """
        output_bucket = self.resources["OutputBucket"]

        try:
            prefix = f"{batch_id}/" if batch_id else ""
            paginator = self.s3.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=output_bucket, Prefix=prefix)

            metrics = {
                "total_documents": 0,
                "average_confidence": 0.0,
                "low_confidence_count": 0,
                "by_document_class": {},
            }

            total_confidence = 0.0
            total_fields = 0

            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if not key.endswith("/result.json"):
                        continue

                    # Apply date filter
                    if start_date or end_date:
                        obj_date = obj["LastModified"].isoformat()
                        if start_date and obj_date < start_date:
                            continue
                        if end_date and obj_date > end_date:
                            continue

                    # Download and analyze
                    response = self.s3.get_object(Bucket=output_bucket, Key=key)
                    result_data = json.loads(response["Body"].read())

                    doc_class = result_data.get("document_class", {}).get(
                        "type", "unknown"
                    )

                    # Apply document class filter
                    if document_class and doc_class != document_class:
                        continue

                    # Extract confidence scores
                    explainability_info = result_data.get("explainability_info", [])
                    doc_confidences = []

                    for info in explainability_info:
                        if isinstance(info, dict):
                            for value in info.values():
                                if isinstance(value, dict) and "confidence" in value:
                                    conf = value["confidence"]
                                    doc_confidences.append(conf)
                                    if conf < 0.8:
                                        metrics["low_confidence_count"] += 1

                    if doc_confidences:
                        avg_conf = sum(doc_confidences) / len(doc_confidences)
                        total_confidence += avg_conf
                        total_fields += len(doc_confidences)
                        metrics["total_documents"] += 1

                        # Aggregate by class
                        if doc_class not in metrics["by_document_class"]:
                            metrics["by_document_class"][doc_class] = {
                                "count": 0,
                                "total_confidence": 0.0,
                            }
                        metrics["by_document_class"][doc_class]["count"] += 1
                        metrics["by_document_class"][doc_class]["total_confidence"] += (
                            avg_conf
                        )

            metrics["average_confidence"] = (
                total_confidence / metrics["total_documents"]
                if metrics["total_documents"] > 0
                else 0.0
            )

            # Calculate averages by class
            for doc_class in metrics["by_document_class"]:
                class_data = metrics["by_document_class"][doc_class]
                class_data["average_confidence"] = (
                    class_data["total_confidence"] / class_data["count"]
                    if class_data["count"] > 0
                    else 0.0
                )
                del class_data["total_confidence"]

            return metrics

        except Exception as e:
            logger.error(f"Error getting assessment metrics: {e}")
            raise
