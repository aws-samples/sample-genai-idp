# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Batch reprocess tool for reprocessing documents from a specific step"""

import logging
import os
from typing import Any, Dict, Optional
from .base import IDPTool

logger = logging.getLogger(__name__)

# Version marker
TOOL_VERSION = "SDK-v2"
TOOL_UPDATED = "2025-01-09T19:30:00Z"


class BatchReprocessTool(IDPTool):
    """Reprocess documents from a specific pipeline step"""

    def __init__(self):
        """Initialize with stack name from environment"""
        # Try AWS_STACK_NAME first, then extract from Lambda function name
        self.stack_name = os.environ.get('AWS_STACK_NAME')
        if not self.stack_name:
            lambda_name = os.environ.get('AWS_LAMBDA_FUNCTION_NAME', '')
            # Extract stack name by removing -agentcore-analytics suffix
            if lambda_name.endswith('-agentcore-analytics'):
                self.stack_name = lambda_name.replace('-agentcore-analytics', '')
            else:
                self.stack_name = lambda_name
        logger.info(f"BatchReprocessTool initialized with stack_name: {self.stack_name}")

    def execute(
        self,
        step: str,
        document_ids: Optional[str] = None,
        batch_id: Optional[str] = None,
        region: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute batch reprocessing using SDK core modules"""
        logger.info(f"=== Batch Reprocess Tool ===")
        logger.info(f"Version: {TOOL_VERSION}")
        logger.info(f"Updated: {TOOL_UPDATED}")
        logger.info(f"Parameters: step={step}, document_ids={document_ids}, batch_id={batch_id}, region={region}")
        
        from idp_sdk.core.rerun_processor import RerunProcessor

        try:
            # Validate mutually exclusive options
            if not document_ids and not batch_id:
                raise ValueError("Must specify either document_ids or batch_id")
            
            if document_ids and batch_id:
                raise ValueError("Cannot specify both document_ids and batch_id")

            logger.info(f"Initializing RerunProcessor with stack: {self.stack_name}")
            processor = RerunProcessor(stack_name=self.stack_name, region=region)
            logger.info("RerunProcessor initialized successfully")
            
            # Get document IDs
            if document_ids:
                doc_id_list = [doc_id.strip() for doc_id in document_ids.split(",")]
                logger.info(f"Processing {len(doc_id_list)} specified documents")
            else:
                logger.info(f"Getting document IDs from batch: {batch_id}")
                doc_id_list = processor.get_batch_document_ids(batch_id)
                logger.info(f"Found {len(doc_id_list)} documents in batch")

            # Perform reprocessing
            logger.info(f"Reprocessing {len(doc_id_list)} documents from step: {step}")
            results = processor.rerun_documents(
                document_ids=doc_id_list,
                step=step,
                monitor=False
            )

            # Format response
            logger.info(f"Batch reprocessing completed. Result: {results}")
            return {
                "success": True,
                "batch_id": batch_id or "rerun",
                "documents_queued": results.get("documents_queued", 0),
                "documents_failed": results.get("documents_failed", 0),
                "step": step,
                "summary": {
                    "queued": results.get("documents_queued", 0),
                    "failed": results.get("documents_failed", 0)
                },
                "message": f"Successfully queued {results.get('documents_queued', 0)} documents for {step} reprocessing"
            }

        except Exception as e:
            logger.error(f"Batch reprocess failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "step": step
            }
