# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Document Processor Module

Handles document metadata retrieval and listing operations.
"""

import json
import logging
from typing import Dict, Optional

import boto3
from botocore.exceptions import ClientError

from idp_sdk.core.stack_info import StackInfo

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """Processes document metadata and listing operations"""

    def __init__(self, stack_name: str, region: Optional[str] = None):
        """
        Initialize document processor

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
        logger.info(f"Initialized document processor for stack: {stack_name}")

    def get_metadata(self, document_id: str, section_id: int = 1) -> Dict:
        """
        Get extracted metadata and fields for a document section

        Args:
            document_id: Document identifier (S3 key)
            section_id: Section number (default: 1)

        Returns:
            Dictionary with extracted fields and metadata
        """
        output_bucket = self.resources["OutputBucket"]

        try:
            # Download section result.json
            result_key = f"{document_id}/sections/{section_id}/result.json"
            response = self.s3.get_object(Bucket=output_bucket, Key=result_key)
            result_data = json.loads(response["Body"].read())

            # Extract fields and metadata
            inference_result = result_data.get("inference_result", {})
            document_class_data = result_data.get("document_class", {})
            split_document = result_data.get("split_document", {})
            explainability_info = result_data.get("explainability_info", [])

            # Extract confidence scores if available
            confidence = {}
            if explainability_info:
                for info in explainability_info:
                    if isinstance(info, dict):
                        for key, value in info.items():
                            if isinstance(value, dict) and "confidence" in value:
                                confidence[key] = value["confidence"]

            return {
                "document_id": document_id,
                "section_id": section_id,
                "document_class": document_class_data.get("type"),
                "fields": inference_result,
                "confidence": confidence if confidence else None,
                "page_count": len(split_document.get("page_indices", [])),
                "metadata": {
                    "document_class_confidence": document_class_data.get("confidence"),
                    "page_indices": split_document.get("page_indices", []),
                },
            }
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                raise FileNotFoundError(
                    f"Results not found for document: {document_id}, section: {section_id}"
                )
            raise

    def list_documents(
        self, limit: int = 100, next_token: Optional[str] = None
    ) -> Dict:
        """
        List documents from DynamoDB tracking table with pagination

        Args:
            limit: Maximum number of documents to return (default: 100)
            next_token: Pagination token from previous request

        Returns:
            Dictionary with documents list and optional next_token
        """
        documents_table_name = self.resources.get("DocumentsTable")
        if not documents_table_name:
            raise ValueError("DocumentsTable not found in stack resources")

        table = self.dynamodb.Table(documents_table_name)

        try:
            # Build scan parameters
            scan_params = {"Limit": limit}

            if next_token:
                # Decode next_token (base64 encoded JSON)
                import base64

                decoded = base64.b64decode(next_token).decode("utf-8")
                scan_params["ExclusiveStartKey"] = json.loads(decoded)

            # Scan table
            response = table.scan(**scan_params)

            # Extract documents
            items = response.get("Items", [])
            documents = []

            for item in items:
                documents.append(
                    {
                        "document_id": item.get("object_key", ""),
                        "status": item.get("status", "UNKNOWN"),
                        "timestamp": item.get("timestamp", ""),
                        "batch_id": item.get("batch_id"),
                    }
                )

            # Prepare result
            result = {"documents": documents, "count": len(documents)}

            # Add next_token if more results available
            if "LastEvaluatedKey" in response:
                # Encode LastEvaluatedKey as base64 JSON
                import base64

                encoded = base64.b64encode(
                    json.dumps(response["LastEvaluatedKey"]).encode("utf-8")
                ).decode("utf-8")
                result["next_token"] = encoded

            return result

        except Exception as e:
            logger.error(f"Error listing documents: {e}")
            raise
