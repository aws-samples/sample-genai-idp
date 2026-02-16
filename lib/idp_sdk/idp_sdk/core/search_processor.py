# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Search Processor Module

Handles knowledge base query and search operations.
"""

import json
import logging
from typing import Dict, List, Optional

import boto3

from idp_sdk.core.stack_info import StackInfo

logger = logging.getLogger(__name__)


class SearchProcessor:
    """Processes knowledge base queries and searches"""

    def __init__(self, stack_name: str, region: Optional[str] = None):
        """
        Initialize search processor

        Args:
            stack_name: Name of the CloudFormation stack
            region: AWS region (optional)
        """
        self.stack_name = stack_name
        self.region = region

        # Initialize AWS clients
        self.lambda_client = boto3.client("lambda", region_name=region)

        # Get stack resources
        stack_info = StackInfo(stack_name, region)
        if not stack_info.validate_stack():
            raise ValueError(
                f"Stack '{stack_name}' is not in a valid state for operations"
            )

        self.resources = stack_info.get_resources()
        logger.info(f"Initialized search processor for stack: {stack_name}")

    def query(
        self,
        question: str,
        document_ids: Optional[List[str]] = None,
        limit: int = 10,
        next_token: Optional[str] = None,
    ) -> Dict:
        """
        Query knowledge base with natural language question

        Args:
            question: Natural language question
            document_ids: Optional list of document IDs to search within
            limit: Maximum number of results to return
            next_token: Pagination token from previous request

        Returns:
            Dictionary with search results and optional next_token
        """
        kb_function = self.resources.get("KnowledgeBaseFunctionName")
        if not kb_function:
            raise ValueError("KnowledgeBaseFunctionName not found in stack resources")

        try:
            # Build query payload
            payload = {
                "question": question,
                "limit": limit,
            }

            if document_ids:
                payload["document_ids"] = document_ids

            if next_token:
                import base64

                decoded = base64.b64decode(next_token).decode("utf-8")
                payload["next_token"] = decoded

            # Invoke Lambda function
            response = self.lambda_client.invoke(
                FunctionName=kb_function,
                InvocationType="RequestResponse",
                Payload=json.dumps(payload),
            )

            # Parse response
            result = json.loads(response["Payload"].read())

            # Handle Lambda error
            if response.get("FunctionError"):
                logger.error(f"Knowledge base query error: {result}")
                raise Exception(result.get("errorMessage", "Unknown query error"))

            # Extract results
            results = []
            for item in result.get("results", []):
                results.append(
                    {
                        "answer": item.get("answer", ""),
                        "confidence": item.get("confidence", 0.0),
                        "citations": item.get("citations", []),
                    }
                )

            output = {
                "question": question,
                "results": results,
                "count": len(results),
            }

            # Add next_token if available
            if result.get("next_token"):
                import base64

                encoded = base64.b64encode(result["next_token"].encode("utf-8")).decode(
                    "utf-8"
                )
                output["next_token"] = encoded

            return output

        except Exception as e:
            logger.error(f"Error querying knowledge base: {e}")
            raise
