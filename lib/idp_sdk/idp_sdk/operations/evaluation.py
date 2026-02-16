# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Evaluation operations for IDP SDK."""

from typing import Dict, Optional

from idp_sdk.exceptions import IDPProcessingError, IDPResourceNotFoundError
from idp_sdk.models import (
    EvaluationBaselineListResult,
    EvaluationMetrics,
    EvaluationReport,
)


class EvaluationOperation:
    """Evaluation and baseline management operations."""

    def __init__(self, client):
        self._client = client

    def create_baseline(
        self,
        document_id: str,
        baseline_data: Dict,
        metadata: Optional[Dict] = None,
        stack_name: Optional[str] = None,
        **kwargs,
    ) -> Dict:
        """Create evaluation baseline for a document.

        Args:
            document_id: Document identifier (S3 key)
            baseline_data: Baseline data structure (sections with expected fields)
            metadata: Optional metadata
            stack_name: Optional stack name override
            **kwargs: Additional parameters

        Returns:
            Dictionary with baseline creation result
        """
        from idp_sdk.core.evaluation_processor import EvaluationProcessor

        name = self._client._require_stack(stack_name)

        try:
            processor = EvaluationProcessor(
                stack_name=name, region=self._client._region
            )
            return processor.create_baseline(
                document_id=document_id, baseline_data=baseline_data, metadata=metadata
            )
        except Exception as e:
            raise IDPProcessingError(f"Failed to create baseline: {e}") from e

    def get_report(
        self,
        document_id: str,
        section_id: int = 1,
        stack_name: Optional[str] = None,
        **kwargs,
    ) -> EvaluationReport:
        """Get evaluation report for a document section.

        Args:
            document_id: Document identifier (S3 key)
            section_id: Section number (default: 1)
            stack_name: Optional stack name override
            **kwargs: Additional parameters

        Returns:
            EvaluationReport with accuracy and field results
        """
        from idp_sdk.core.evaluation_processor import EvaluationProcessor

        name = self._client._require_stack(stack_name)

        try:
            processor = EvaluationProcessor(
                stack_name=name, region=self._client._region
            )
            result = processor.get_report(
                document_id=document_id, section_id=section_id
            )

            return EvaluationReport(
                document_id=result["document_id"],
                section_id=result["section_id"],
                accuracy=result["accuracy"],
                field_results=result["field_results"],
                summary=result.get("summary"),
            )
        except FileNotFoundError as e:
            raise IDPResourceNotFoundError(str(e)) from e
        except Exception as e:
            raise IDPProcessingError(f"Failed to get evaluation report: {e}") from e

    def get_metrics(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        document_class: Optional[str] = None,
        batch_id: Optional[str] = None,
        stack_name: Optional[str] = None,
        **kwargs,
    ) -> EvaluationMetrics:
        """Get aggregated evaluation metrics.

        Args:
            start_date: Start date filter (ISO format)
            end_date: End date filter (ISO format)
            document_class: Document class filter
            batch_id: Batch ID filter
            stack_name: Optional stack name override
            **kwargs: Additional parameters

        Returns:
            EvaluationMetrics with aggregated statistics
        """
        from idp_sdk.core.evaluation_processor import EvaluationProcessor

        name = self._client._require_stack(stack_name)

        try:
            processor = EvaluationProcessor(
                stack_name=name, region=self._client._region
            )
            result = processor.get_metrics(
                start_date=start_date,
                end_date=end_date,
                document_class=document_class,
                batch_id=batch_id,
            )

            return EvaluationMetrics(
                total_evaluations=result["total_evaluations"],
                average_accuracy=result["average_accuracy"],
                by_document_class=result["by_document_class"],
            )
        except Exception as e:
            raise IDPProcessingError(f"Failed to get evaluation metrics: {e}") from e

    def list_baselines(
        self,
        limit: int = 100,
        next_token: Optional[str] = None,
        stack_name: Optional[str] = None,
        **kwargs,
    ) -> EvaluationBaselineListResult:
        """List evaluation baselines with pagination.

        Args:
            limit: Maximum number of baselines to return (default: 100)
            next_token: Pagination token from previous request
            stack_name: Optional stack name override
            **kwargs: Additional parameters

        Returns:
            EvaluationBaselineListResult with baselines and optional next_token
        """
        from idp_sdk.core.evaluation_processor import EvaluationProcessor

        name = self._client._require_stack(stack_name)

        try:
            processor = EvaluationProcessor(
                stack_name=name, region=self._client._region
            )
            result = processor.list_baselines(limit=limit, next_token=next_token)

            return EvaluationBaselineListResult(
                baselines=result["baselines"],
                count=result["count"],
                next_token=result.get("next_token"),
            )
        except Exception as e:
            raise IDPProcessingError(f"Failed to list baselines: {e}") from e

    def delete_baseline(
        self,
        document_id: str,
        stack_name: Optional[str] = None,
        **kwargs,
    ) -> Dict:
        """Delete evaluation baseline for a document.

        Args:
            document_id: Document identifier (S3 key)
            stack_name: Optional stack name override
            **kwargs: Additional parameters

        Returns:
            Dictionary with deletion result
        """
        from idp_sdk.core.evaluation_processor import EvaluationProcessor

        name = self._client._require_stack(stack_name)

        try:
            processor = EvaluationProcessor(
                stack_name=name, region=self._client._region
            )
            return processor.delete_baseline(document_id=document_id)
        except Exception as e:
            raise IDPProcessingError(f"Failed to delete baseline: {e}") from e
