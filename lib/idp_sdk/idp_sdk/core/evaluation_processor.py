# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Evaluation Processor Module

Handles evaluation baseline management and report operations.
"""

import json
import logging
from datetime import datetime
from typing import Dict, Optional

import boto3
from botocore.exceptions import ClientError

from idp_sdk.core.stack_info import StackInfo

logger = logging.getLogger(__name__)


class EvaluationProcessor:
    """Processes evaluation baselines and reports"""

    def __init__(self, stack_name: str, region: Optional[str] = None):
        """
        Initialize evaluation processor

        Args:
            stack_name: Name of the CloudFormation stack
            region: AWS region (optional)
        """
        self.stack_name = stack_name
        self.region = region

        # Initialize AWS clients
        self.s3 = boto3.client("s3", region_name=region)
        self.dynamodb = boto3.resource("dynamodb", region_name=region)

        # Get stack resources
        stack_info = StackInfo(stack_name, region)
        if not stack_info.validate_stack():
            raise ValueError(
                f"Stack '{stack_name}' is not in a valid state for operations"
            )

        self.resources = stack_info.get_resources()
        logger.info(f"Initialized evaluation processor for stack: {stack_name}")

    def create_baseline(
        self, document_id: str, baseline_data: Dict, metadata: Optional[Dict] = None
    ) -> Dict:
        """
        Create evaluation baseline for a document

        Args:
            document_id: Document identifier (S3 key)
            baseline_data: Baseline data structure (sections with expected fields)
            metadata: Optional metadata

        Returns:
            Dictionary with baseline creation result
        """
        baseline_bucket = self.resources.get("EvaluationBaselineBucket")
        if not baseline_bucket:
            raise ValueError("EvaluationBaselineBucket not found in stack resources")

        try:
            # Store baseline structure matching expected format
            for section_id, section_data in baseline_data.items():
                section_key = f"{document_id}/sections/{section_id}/result.json"
                self.s3.put_object(
                    Bucket=baseline_bucket,
                    Key=section_key,
                    Body=json.dumps(section_data),
                    ContentType="application/json",
                )

            # Store metadata if provided
            if metadata:
                metadata_key = f"{document_id}/metadata.json"
                self.s3.put_object(
                    Bucket=baseline_bucket,
                    Key=metadata_key,
                    Body=json.dumps(metadata),
                    ContentType="application/json",
                )

            return {
                "document_id": document_id,
                "sections_created": len(baseline_data),
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error creating baseline: {e}")
            raise

    def get_report(self, document_id: str, section_id: int = 1) -> Dict:
        """
        Get evaluation report for a document section

        Args:
            document_id: Document identifier (S3 key)
            section_id: Section number (default: 1)

        Returns:
            Dictionary with evaluation report
        """
        output_bucket = self.resources["OutputBucket"]

        try:
            # Download evaluation report
            eval_key = f"{document_id}/sections/{section_id}/evaluation.json"
            response = self.s3.get_object(Bucket=output_bucket, Key=eval_key)
            eval_data = json.loads(response["Body"].read())

            return {
                "document_id": document_id,
                "section_id": section_id,
                "accuracy": eval_data.get("accuracy"),
                "field_results": eval_data.get("field_results", {}),
                "summary": eval_data.get("summary", {}),
            }

        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                raise FileNotFoundError(
                    f"Evaluation report not found for document: {document_id}, section: {section_id}"
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
        Get aggregated evaluation metrics

        Args:
            start_date: Start date filter (ISO format)
            end_date: End date filter (ISO format)
            document_class: Document class filter
            batch_id: Batch ID filter

        Returns:
            Dictionary with aggregated metrics
        """
        output_bucket = self.resources["OutputBucket"]

        try:
            # List evaluation files based on filters
            prefix = f"{batch_id}/" if batch_id else ""
            paginator = self.s3.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=output_bucket, Prefix=prefix)

            metrics = {
                "total_evaluations": 0,
                "average_accuracy": 0.0,
                "by_document_class": {},
            }

            total_accuracy = 0.0
            count = 0

            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if not key.endswith("/evaluation.json"):
                        continue

                    # Apply date filter
                    if start_date or end_date:
                        obj_date = obj["LastModified"].isoformat()
                        if start_date and obj_date < start_date:
                            continue
                        if end_date and obj_date > end_date:
                            continue

                    # Download and aggregate
                    response = self.s3.get_object(Bucket=output_bucket, Key=key)
                    eval_data = json.loads(response["Body"].read())

                    accuracy = eval_data.get("accuracy", 0.0)
                    doc_class = eval_data.get("document_class", "unknown")

                    # Apply document class filter
                    if document_class and doc_class != document_class:
                        continue

                    total_accuracy += accuracy
                    count += 1

                    # Aggregate by class
                    if doc_class not in metrics["by_document_class"]:
                        metrics["by_document_class"][doc_class] = {
                            "count": 0,
                            "total_accuracy": 0.0,
                        }
                    metrics["by_document_class"][doc_class]["count"] += 1
                    metrics["by_document_class"][doc_class]["total_accuracy"] += (
                        accuracy
                    )

            metrics["total_evaluations"] = count
            metrics["average_accuracy"] = total_accuracy / count if count > 0 else 0.0

            # Calculate averages by class
            for doc_class in metrics["by_document_class"]:
                class_data = metrics["by_document_class"][doc_class]
                class_data["average_accuracy"] = (
                    class_data["total_accuracy"] / class_data["count"]
                    if class_data["count"] > 0
                    else 0.0
                )
                del class_data["total_accuracy"]

            return metrics

        except Exception as e:
            logger.error(f"Error getting metrics: {e}")
            raise

    def list_baselines(
        self, limit: int = 100, next_token: Optional[str] = None
    ) -> Dict:
        """
        List evaluation baselines with pagination

        Args:
            limit: Maximum number of baselines to return
            next_token: Pagination token from previous request

        Returns:
            Dictionary with baselines list and optional next_token
        """
        baseline_bucket = self.resources.get("EvaluationBaselineBucket")
        if not baseline_bucket:
            raise ValueError("EvaluationBaselineBucket not found in stack resources")

        try:
            # Build list parameters
            list_params = {
                "Bucket": baseline_bucket,
                "Delimiter": "/",
                "MaxKeys": limit,
            }

            if next_token:
                import base64

                decoded = base64.b64decode(next_token).decode("utf-8")
                list_params["ContinuationToken"] = decoded

            # List top-level prefixes (document IDs)
            response = self.s3.list_objects_v2(**list_params)

            baselines = []
            for prefix in response.get("CommonPrefixes", []):
                doc_id = prefix["Prefix"].rstrip("/")
                baselines.append({"document_id": doc_id})

            result = {"baselines": baselines, "count": len(baselines)}

            # Add next_token if more results available
            if response.get("IsTruncated"):
                import base64

                encoded = base64.b64encode(
                    response["NextContinuationToken"].encode("utf-8")
                ).decode("utf-8")
                result["next_token"] = encoded

            return result

        except Exception as e:
            logger.error(f"Error listing baselines: {e}")
            raise

    def delete_baseline(self, document_id: str) -> Dict:
        """
        Delete evaluation baseline for a document

        Args:
            document_id: Document identifier (S3 key)

        Returns:
            Dictionary with deletion result
        """
        baseline_bucket = self.resources.get("EvaluationBaselineBucket")
        if not baseline_bucket:
            raise ValueError("EvaluationBaselineBucket not found in stack resources")

        try:
            # List all objects for this document
            prefix = f"{document_id}/"
            paginator = self.s3.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=baseline_bucket, Prefix=prefix)

            deleted_count = 0
            for page in pages:
                objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
                if objects:
                    self.s3.delete_objects(
                        Bucket=baseline_bucket, Delete={"Objects": objects}
                    )
                    deleted_count += len(objects)

            return {"document_id": document_id, "deleted_count": deleted_count}

        except Exception as e:
            logger.error(f"Error deleting baseline: {e}")
            raise
