# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Assessment operations for IDP SDK."""

from typing import Dict, Optional

from idp_sdk.exceptions import IDPProcessingError, IDPResourceNotFoundError
from idp_sdk.models import (
    AssessmentConfidenceResult,
    AssessmentFieldConfidence,
    AssessmentFieldGeometry,
    AssessmentGeometryResult,
)


class AssessmentOperation:
    """
    Quality assessment and confidence scoring operations.

    Business Context:
        After documents are processed and data is extracted, the assessment operations
        help you understand the quality and reliability of the extraction results.
        This is critical for:
        - Identifying low-confidence extractions that need human review
        - Understanding which fields are reliably extracted vs. error-prone
        - Locating extracted data on the original document pages
        - Monitoring extraction quality across batches and document types

    Use Cases:
        1. Human-in-the-Loop Workflows:
           Route low-confidence documents to human reviewers
           >>> confidence = client.assessment.get_confidence("invoice-001.pdf")
           >>> needs_review = [f for f, c in confidence.attributes.items()
           ...                 if not c.meets_threshold]

        2. Quality Monitoring:
           Track extraction confidence across document batches
           >>> metrics = client.assessment.get_metrics(batch_id="batch-123")
           >>> print(f"Average confidence: {metrics['average_confidence']:.2%}")

        3. UI Highlighting:
           Show bounding boxes around extracted fields in document viewer
           >>> geometry = client.assessment.get_geometry("invoice-001.pdf")
           >>> for field, geo in geometry.attributes.items():
           ...     draw_box(page=geo.page, bbox=geo.bbox)

    Typical Workflow:
        1. Process documents → 2. Check confidence → 3. Review low-confidence items
        >>> result = client.batch.run(directory="./invoices")
        >>> # Wait for processing...
        >>> for doc_id in result.document_ids:
        ...     conf = client.assessment.get_confidence(doc_id)
        ...     if any(not c.meets_threshold for c in conf.attributes.values()):
        ...         print(f"{doc_id} needs review")
    """

    def __init__(self, client):
        self._client = client

    def get_confidence(
        self,
        document_id: str,
        section_id: int = 1,
        stack_name: Optional[str] = None,
        **kwargs,
    ) -> AssessmentConfidenceResult:
        """
        Get confidence scores for all extracted fields in a document section.

        Business Context:
            Confidence scores indicate how certain the AI model is about each extracted
            field value. Higher confidence means the extraction is more reliable.
            Use this to:
            - Identify fields that need human verification
            - Route documents to appropriate review queues
            - Calculate SLA compliance (% of high-confidence extractions)
            - Improve model training by focusing on low-confidence patterns

        Args:
            document_id: Document identifier (S3 key from batch processing).
                        Example: "batch-20240115/invoice-001.pdf"
            section_id: Section number within the document (default: 1).
                       Multi-section documents (e.g., multi-page forms) may have
                       different classifications per section.
            stack_name: Override the default stack name from client initialization.
                       Useful when working with multiple IDP deployments.
            **kwargs: Reserved for future parameters.

        Returns:
            ConfidenceResult containing:
            - document_id: The document identifier
            - section_id: The section number
            - attributes: Dict[str, AttributeConfidence] with per-field scores:
                * confidence: Float 0.0-1.0 (e.g., 0.95 = 95% confident)
                * confidence_threshold: Minimum acceptable confidence (from config)
                * meets_threshold: Boolean indicating if confidence is acceptable
                * reason: Explanation for the confidence level

        Raises:
            IDPResourceNotFoundError: Document not found or not yet processed
            IDPProcessingError: Failed to retrieve confidence data
            IDPConfigurationError: Stack name not provided

        Examples:
            Check if any fields need review:
            >>> confidence = client.assessment.get_confidence("batch-001/invoice.pdf")
            >>> low_conf_fields = [
            ...     field for field, attr in confidence.attributes.items()
            ...     if not attr.meets_threshold
            ... ]
            >>> if low_conf_fields:
            ...     print(f"Review needed for: {', '.join(low_conf_fields)}")

            Get confidence for specific field:
            >>> confidence = client.assessment.get_confidence("batch-001/invoice.pdf")
            >>> total_amount = confidence.attributes.get("total_amount")
            >>> if total_amount:
            ...     print(f"Total amount confidence: {total_amount.confidence:.2%}")
            ...     print(f"Meets threshold: {total_amount.meets_threshold}")

            Route to review queue based on confidence:
            >>> confidence = client.assessment.get_confidence(doc_id)
            >>> avg_confidence = sum(a.confidence for a in confidence.attributes.values()) / len(confidence.attributes)
            >>> if avg_confidence < 0.85:
            ...     send_to_review_queue(doc_id, priority="high")

        Business Logic:
            - Confidence thresholds are defined in the pipeline configuration
            - Different document classes may have different thresholds
            - Confidence is calculated from multiple factors:
              * OCR quality and text clarity
              * Model prediction probability
              * Field validation rules (format, range, etc.)
              * Historical accuracy for similar documents
        """
        from idp_sdk.core.assessment_analyzer import AssessmentAnalyzer

        name = self._client._require_stack(stack_name)

        try:
            analyzer = AssessmentAnalyzer(stack_name=name, region=self._client._region)
            result = analyzer.get_confidence(
                document_id=document_id, section_id=section_id
            )

            attributes = {
                key: AssessmentFieldConfidence(
                    confidence=val["confidence"],
                    confidence_threshold=val["confidence_threshold"],
                    reason=val["reason"],
                    meets_threshold=val["meets_threshold"],
                )
                for key, val in result["attributes"].items()
            }

            return AssessmentConfidenceResult(
                document_id=result["document_id"],
                section_id=result["section_id"],
                attributes=attributes,
            )
        except FileNotFoundError as e:
            raise IDPResourceNotFoundError(str(e)) from e
        except Exception as e:
            raise IDPProcessingError(f"Failed to get confidence scores: {e}") from e

    def get_geometry(
        self,
        document_id: str,
        section_id: int = 1,
        stack_name: Optional[str] = None,
        **kwargs,
    ) -> AssessmentGeometryResult:
        """
        Get bounding box coordinates for all extracted fields in a document section.

        Business Context:
            Geometry data provides the exact location of each extracted field on the
            original document pages. This enables:
            - Visual highlighting in document viewers
            - Verification UI where users can see what was extracted
            - Debugging extraction issues by seeing what the model "saw"
            - Creating annotated PDFs with highlighted fields
            - Training data generation for model improvements

        Args:
            document_id: Document identifier (S3 key from batch processing).
                        Example: "batch-20240115/invoice-001.pdf"
            section_id: Section number within the document (default: 1).
            stack_name: Override the default stack name from client initialization.
            **kwargs: Reserved for future parameters.

        Returns:
            GeometryResult containing:
            - document_id: The document identifier
            - section_id: The section number
            - attributes: Dict[str, FieldGeometry] with per-field locations:
                * page: Page number where field was found (1-indexed)
                * bbox: Normalized bounding box [left, top, width, height] (0.0-1.0)
                * bounding_box: Absolute pixel coordinates {Left, Top, Width, Height}

        Raises:
            IDPResourceNotFoundError: Document not found or not yet processed
            IDPProcessingError: Failed to retrieve geometry data
            IDPConfigurationError: Stack name not provided

        Examples:
            Highlight fields in a document viewer:
            >>> geometry = client.assessment.get_geometry("batch-001/invoice.pdf")
            >>> for field_name, geo in geometry.attributes.items():
            ...     print(f"{field_name} found on page {geo.page}")
            ...     # Draw rectangle at normalized coordinates
            ...     draw_highlight(
            ...         page=geo.page,
            ...         left=geo.bbox[0],
            ...         top=geo.bbox[1],
            ...         width=geo.bbox[2],
            ...         height=geo.bbox[3]
            ...     )

            Create verification UI with field locations:
            >>> geometry = client.assessment.get_geometry(doc_id)
            >>> metadata = client.document.get_metadata(doc_id)
            >>> for field_name in metadata.fields:
            ...     value = metadata.fields[field_name]
            ...     location = geometry.attributes.get(field_name)
            ...     if location:
            ...         show_field_with_location(field_name, value, location)

            Export annotated PDF:
            >>> geometry = client.assessment.get_geometry(doc_id)
            >>> pdf = load_pdf(doc_id)
            >>> for field, geo in geometry.attributes.items():
            ...     pdf.add_annotation(
            ...         page=geo.page,
            ...         bbox=geo.bounding_box,
            ...         label=field
            ...     )
            >>> pdf.save("annotated_invoice.pdf")

        Coordinate Systems:
            - bbox: Normalized coordinates (0.0 to 1.0) relative to page dimensions
              * Independent of page size/resolution
              * Useful for responsive UIs
            - bounding_box: Absolute pixel coordinates
              * Depends on document resolution
              * Useful for exact pixel-level operations
        """
        from idp_sdk.core.assessment_analyzer import AssessmentAnalyzer

        name = self._client._require_stack(stack_name)

        try:
            analyzer = AssessmentAnalyzer(stack_name=name, region=self._client._region)
            result = analyzer.get_geometry(
                document_id=document_id, section_id=section_id
            )

            attributes = {
                key: AssessmentFieldGeometry(
                    page=val["page"],
                    bbox=val["bbox"],
                    bounding_box=val["bounding_box"],
                )
                for key, val in result["attributes"].items()
            }

            return AssessmentGeometryResult(
                document_id=result["document_id"],
                section_id=result["section_id"],
                attributes=attributes,
            )
        except FileNotFoundError as e:
            raise IDPResourceNotFoundError(str(e)) from e
        except Exception as e:
            raise IDPProcessingError(f"Failed to get geometry: {e}") from e

    def get_metrics(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        document_class: Optional[str] = None,
        batch_id: Optional[str] = None,
        stack_name: Optional[str] = None,
        **kwargs,
    ) -> Dict:
        """
        Get aggregated quality metrics across multiple documents.

        Business Context:
            Aggregate metrics help you monitor extraction quality at scale.
            Use this for:
            - Quality dashboards and reporting
            - SLA monitoring (% of documents meeting confidence thresholds)
            - Identifying problematic document types or batches
            - Tracking quality trends over time
            - Capacity planning (high-confidence docs need less review)

        Args:
            start_date: Filter documents processed after this date.
                       ISO 8601 format: "2024-01-15" or "2024-01-15T10:30:00Z"
            end_date: Filter documents processed before this date.
                     ISO 8601 format: "2024-01-31" or "2024-01-31T23:59:59Z"
            document_class: Filter by document type (e.g., "invoice", "purchase_order").
                           Use the classification names from your pipeline config.
            batch_id: Filter by specific batch identifier.
                     Example: "batch-20240115-143022"
            stack_name: Override the default stack name from client initialization.
            **kwargs: Reserved for future parameters.

        Returns:
            Dictionary containing aggregated metrics:
            - total_documents: Total number of documents analyzed
            - average_confidence: Mean confidence across all fields
            - by_document_class: Metrics broken down by document type
            - by_field: Metrics broken down by field name
            - threshold_compliance: % of fields meeting confidence thresholds
            - low_confidence_count: Number of fields below threshold

        Raises:
            IDPProcessingError: Failed to retrieve or calculate metrics
            IDPConfigurationError: Stack name not provided

        Examples:
            Monitor daily quality:
            >>> metrics = client.assessment.get_metrics(
            ...     start_date="2024-01-15",
            ...     end_date="2024-01-15"
            ... )
            >>> print(f"Processed: {metrics['total_documents']} documents")
            >>> print(f"Avg confidence: {metrics['average_confidence']:.2%}")
            >>> print(f"SLA compliance: {metrics['threshold_compliance']:.2%}")

            Compare quality across document types:
            >>> for doc_class in ["invoice", "receipt", "purchase_order"]:
            ...     metrics = client.assessment.get_metrics(document_class=doc_class)
            ...     print(f"{doc_class}: {metrics['average_confidence']:.2%}")

            Analyze specific batch quality:
            >>> metrics = client.assessment.get_metrics(batch_id="batch-001")
            >>> if metrics['threshold_compliance'] < 0.90:
            ...     alert("Batch quality below 90% threshold")

            Track quality trends:
            >>> import datetime
            >>> for i in range(7):  # Last 7 days
            ...     date = (datetime.date.today() - datetime.timedelta(days=i)).isoformat()
            ...     metrics = client.assessment.get_metrics(
            ...         start_date=date,
            ...         end_date=date
            ...     )
            ...     print(f"{date}: {metrics['average_confidence']:.2%}")

        Business Value:
            - Proactive quality monitoring prevents downstream errors
            - Identify training data needs (low-confidence patterns)
            - Optimize review workflows (focus on low-confidence batches)
            - Demonstrate ROI (track automation rate improvements)
        """
        from idp_sdk.core.assessment_analyzer import AssessmentAnalyzer

        name = self._client._require_stack(stack_name)

        try:
            analyzer = AssessmentAnalyzer(stack_name=name, region=self._client._region)
            return analyzer.get_metrics(
                start_date=start_date,
                end_date=end_date,
                document_class=document_class,
                batch_id=batch_id,
            )
        except Exception as e:
            raise IDPProcessingError(f"Failed to get assessment metrics: {e}") from e
