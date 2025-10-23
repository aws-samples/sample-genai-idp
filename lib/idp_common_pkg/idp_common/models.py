# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Simplified document data model for IDP processing.

This module defines the Document class that represents the state of a document
as it moves through the processing pipeline.
"""

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Status(Enum):
    """Document processing status."""

    QUEUED = "QUEUED"  # Initial state when document is added to queue
    RUNNING = "RUNNING"  # Step function workflow has started
    OCR = "OCR"  # OCR processing
    CLASSIFYING = "CLASSIFYING"  # Document classification
    EXTRACTING = "EXTRACTING"  # Information extraction
    ASSESSING = "ASSESSING"  # Document assessment
    POSTPROCESSING = "POSTPROCESSING"  # Document summarization
    HITL_IN_PROGRESS = "HITL_IN_PROGRESS"  # Human-in-the-loop review in progress
    SUMMARIZING = "SUMMARIZING"  # Document summarization
    COMPLETED = "COMPLETED"  # All processing completed
    FAILED = "FAILED"  # Processing failed


@dataclass
class Page:
    """Represents a single page in a document."""

    page_id: str
    image_uri: Optional[str] = None
    raw_text_uri: Optional[str] = None
    parsed_text_uri: Optional[str] = None
    text_confidence_uri: Optional[str] = None
    classification: Optional[str] = None
    confidence: float = 0.0
    tables: List[Dict[str, Any]] = field(default_factory=list)
    forms: Dict[str, str] = field(default_factory=dict)


@dataclass
class Section:
    """Represents a section of pages with the same classification."""

    section_id: str
    classification: str
    confidence: float = 1.0
    page_ids: List[str] = field(default_factory=list)
    extraction_result_uri: Optional[str] = None
    attributes: Optional[Dict[str, Any]] = None
    confidence_threshold_alerts: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Section":
        """Create a Section from a dictionary representation."""
        if not data:
            raise ValueError("Cannot create Section from empty data")

        return cls(
            section_id=data.get("section_id", ""),
            classification=data.get("classification", ""),
            confidence=data.get("confidence", 1.0),
            page_ids=data.get("page_ids", []),
            extraction_result_uri=data.get("extraction_result_uri"),
            attributes=data.get("attributes"),
            confidence_threshold_alerts=data.get("confidence_threshold_alerts", []),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert section to dictionary representation."""
        return {
            "section_id": self.section_id,
            "classification": self.classification,
            "confidence": self.confidence,
            "page_ids": self.page_ids,
            "extraction_result_uri": self.extraction_result_uri,
            "attributes": self.attributes,
            "confidence_threshold_alerts": self.confidence_threshold_alerts,
        }


@dataclass
class HitlMetadata:
    """Represents HITL (Human-In-The-Loop) metadata for a document."""

    execution_id: Optional[str] = None
    record_number: Optional[int] = None
    bp_match: Optional[bool] = None
    extraction_bp_name: Optional[str] = None
    hitl_bp_change: Optional[str] = None
    hitl_triggered: bool = False
    page_array: List[str] = field(default_factory=list)
    review_portal_url: Optional[str] = None  # Added field for review portal URL
    hitl_completed: bool = False  # Added field to track completion status

    def to_dict(self) -> Dict[str, Any]:
        """Convert HITL metadata to dictionary representation."""
        return {
            "execution_id": self.execution_id,
            "record_number": self.record_number,
            "bp_match": self.bp_match,
            "extraction_bp_name": self.extraction_bp_name,
            "hitl_bp_change": self.hitl_bp_change,
            "hitl_triggered": self.hitl_triggered,
            "page_array": self.page_array,
            "review_portal_url": self.review_portal_url,  # Include review portal URL in dict
            "hitl_completed": self.hitl_completed,  # Include completion status in dict
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HitlMetadata":
        """Create a HitlMetadata from a dictionary representation."""
        if not data:
            return cls()

        return cls(
            execution_id=data.get("execution_id"),
            record_number=data.get("record_number"),
            bp_match=data.get("bp_match"),
            extraction_bp_name=data.get("extraction_bp_name"),
            hitl_bp_change=data.get("hitl_bp_change"),
            hitl_triggered=data.get("hitl_triggered", False),
            review_portal_url=data.get(
                "review_portal_url"
            ),  # Fix: Include review portal URL
            hitl_completed=data.get(
                "hitl_completed", False
            ),  # Fix: Include completion status
            page_array=data.get("page_array", []),
        )


@dataclass
class Document:
    """
    Core document type that is passed through the processing pipeline.
    Each processing step enriches this object.

    The Document class provides comprehensive support for handling large documents
    in Step Functions workflows through automatic compression and decompression.

    Key Features:
    - Automatic compression for documents exceeding size thresholds
    - Seamless handling of compressed and uncompressed document data
    - Utility methods for Lambda function input/output processing
    - Preservation of section IDs for Step Functions Map operations

    Compression Methods:
    - compress(): Store full document in S3 and return lightweight wrapper
    - decompress(): Restore full document from S3 using compressed wrapper
    - from_compressed_or_dict(): Handle both compressed and regular document data

    Utility Methods:
    - load_document(): Process document input from Lambda events
    - serialize_document(): Prepare document output with automatic compression

    Usage Examples:
        # Handle input in Lambda functions
        document = Document.load_document(event_data, working_bucket, logger)

        # Prepare output with automatic compression
        response = {"document": document.serialize_document(working_bucket, "step_name", logger)}

        # Manual compression/decompression
        compressed_data = document.compress(working_bucket, "processing")
        restored_document = Document.decompress(working_bucket, compressed_data)
    """

    # Core identifiers
    id: Optional[str] = None  # Generated document ID
    input_bucket: Optional[str] = None  # S3 bucket containing the input document
    input_key: Optional[str] = None  # S3 key of the input document
    output_bucket: Optional[str] = None  # S3 bucket for processing outputs
    user_id: Optional[str] = None  # Cognito user ID for multi-tenant isolation

    # Processing state and timing
    status: Status = Status.QUEUED
    initial_event_time: Optional[str] = None
    queued_time: Optional[str] = None
    start_time: Optional[str] = None
    completion_time: Optional[str] = None
    workflow_execution_arn: Optional[str] = None

    # Document content details
    num_pages: int = 0
    pages: Dict[str, Page] = field(default_factory=dict)
    sections: List[Section] = field(default_factory=list)
    summary_report_uri: Optional[str] = None

    # Processing metadata
    metering: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    evaluation_status: Optional[str] = None
    evaluation_report_uri: Optional[str] = None
    evaluation_results_uri: Optional[str] = None
    evaluation_result: Any = None  # Holds the DocumentEvaluationResult object
    summarization_result: Any = None  # Holds the DocumentSummarizationResult object
    errors: List[str] = field(default_factory=list)

    # HITL metadata
    hitl_metadata: List[HitlMetadata] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert document to dictionary representation."""
        # First convert basic attributes
        result = {
            "id": self.id,
            "input_bucket": self.input_bucket,
            "input_key": self.input_key,
            "output_bucket": self.output_bucket,
            "user_id": self.user_id,
            "status": self.status.value,
            "initial_event_time": self.initial_event_time,
            "queued_time": self.queued_time,
            "start_time": self.start_time,
            "completion_time": self.completion_time,
            "workflow_execution_arn": self.workflow_execution_arn,
            "num_pages": self.num_pages,
            "summary_report_uri": self.summary_report_uri,
            "evaluation_status": self.evaluation_status,
            "evaluation_report_uri": self.evaluation_report_uri,
            "evaluation_results_uri": self.evaluation_results_uri,
            "errors": self.errors,
            "metering": self.metering,
            # We don't include evaluation_result or summarization_result in the dict since they're objects
        }

        # Convert pages
        result["pages"] = {}
        for page_id, page in self.pages.items():
            result["pages"][page_id] = {
                "page_id": page.page_id,
                "image_uri": page.image_uri,
                "raw_text_uri": page.raw_text_uri,
                "parsed_text_uri": page.parsed_text_uri,
                "text_confidence_uri": page.text_confidence_uri,
                "classification": page.classification,
                "confidence": page.confidence,
                "tables": page.tables,
                "forms": page.forms,
            }

        # Convert sections
        result["sections"] = []
        for section in self.sections:
            section_dict = {
                "section_id": section.section_id,
                "classification": section.classification,
                "confidence": section.confidence,
                "page_ids": section.page_ids,
                "extraction_result_uri": section.extraction_result_uri,
                "confidence_threshold_alerts": section.confidence_threshold_alerts,
            }
            if section.attributes:
                section_dict["attributes"] = section.attributes
            result["sections"].append(section_dict)

        # Add HITL metadata if it has any values
        if self.hitl_metadata:
            result["hitl_metadata"] = [
                metadata.to_dict() for metadata in self.hitl_metadata
            ]

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Document":
        """Create a Document from a dictionary representation."""
        document = cls(
            id=data.get("id", data.get("input_key")),
            input_bucket=data.get("input_bucket"),
            input_key=data.get("input_key"),
            output_bucket=data.get("output_bucket"),
            user_id=data.get("user_id"),
            num_pages=int(data.get("num_pages", 0)),  # Ensure num_pages is integer
            initial_event_time=data.get("initial_event_time"),
            queued_time=data.get("queued_time"),
            start_time=data.get("start_time"),
            completion_time=data.get("completion_time"),
            workflow_execution_arn=data.get("workflow_execution_arn"),
            evaluation_status=data.get("evaluation_status"),
            evaluation_report_uri=data.get("evaluation_report_uri"),
            evaluation_results_uri=data.get("evaluation_results_uri"),
            summary_report_uri=data.get("summary_report_uri"),
            metering=data.get("metering", {}),
            errors=data.get("errors", []),
        )

        # Convert status from string to enum
        if "status" in data:
            try:
                document.status = Status(data["status"])
            except ValueError:
                # If the status isn't a valid enum value, use QUEUED as default
                document.status = Status.QUEUED

        # Convert pages
        pages_data = data.get("pages", {})
        for page_id, page_data in pages_data.items():
            document.pages[page_id] = Page(
                page_id=page_id,
                image_uri=page_data.get("image_uri"),
                raw_text_uri=page_data.get("raw_text_uri"),
                parsed_text_uri=page_data.get("parsed_text_uri"),
                text_confidence_uri=page_data.get("text_confidence_uri"),
                classification=page_data.get("classification"),
                confidence=page_data.get("confidence", 0.0),
                tables=page_data.get("tables", []),
                forms=page_data.get("forms", {}),
            )

        # Convert sections
        sections_data = data.get("sections", [])
        for section_data in sections_data:
            document.sections.append(
                Section(
                    section_id=section_data.get("section_id"),
                    classification=section_data.get("classification"),
                    confidence=section_data.get("confidence", 1.0),
                    page_ids=section_data.get("page_ids", []),
                    extraction_result_uri=section_data.get("extraction_result_uri"),
                    attributes=section_data.get("attributes"),
                    confidence_threshold_alerts=section_data.get(
                        "confidence_threshold_alerts", []
                    ),
                )
            )

        # Convert HITL metadata if present
        hitl_metadata_data = data.get("hitl_metadata", [])
        for metadata_item in hitl_metadata_data:
            document.hitl_metadata.append(HitlMetadata.from_dict(metadata_item))

        return document

    @classmethod
    def from_s3_event(cls, event: Dict[str, Any], output_bucket: str) -> "Document":
        """Create a Document from an S3 event."""
        input_bucket = event.get("detail", {}).get("bucket", {}).get("name", "")
        input_key = event.get("detail", {}).get("object", {}).get("key", "")
        initial_event_time = event.get("time", "")

        return cls(
            id=input_key,
            input_bucket=input_bucket,
            input_key=input_key,
            output_bucket=output_bucket,
            initial_event_time=initial_event_time,
            status=Status.QUEUED,
        )

    def to_json(self) -> str:
        """Convert document to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_json(cls, json_str: str) -> "Document":
        """Create a Document from a JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)

    @classmethod
    def from_s3(cls, bucket: str, input_key: str) -> "Document":
        """
        Create a Document from baseline results stored in S3.

        This method loads page and section result.json files from the specified
        S3 bucket with the given input_key prefix.

        Args:
            bucket: The S3 bucket containing baseline results
            input_key: The document key (used as prefix for finding baseline files)

        Returns:
            A Document instance populated with data from baseline files
        """
        import logging

        import boto3

        from idp_common.s3 import get_json_content
        from idp_common.utils import build_s3_uri

        logger = logging.getLogger(__name__)
        s3_client = boto3.client("s3")

        # Create a basic document structure
        document = cls(
            id=input_key,
            input_key=input_key,
            output_bucket=bucket,
            status=Status.COMPLETED,
        )

        # List all objects with the given prefix to find pages and sections
        prefix = f"{input_key}/"
        logger.info(f"Listing objects in {bucket} with prefix {prefix}")

        try:
            # List pages first
            pages_prefix = f"{prefix}pages/"
            paginator = s3_client.get_paginator("list_objects_v2")
            page_dirs = set()

            # Find all page directories
            for page in paginator.paginate(
                Bucket=bucket, Prefix=pages_prefix, Delimiter="/"
            ):
                for prefix_item in page.get("CommonPrefixes", []):
                    page_dir = prefix_item.get("Prefix")
                    page_id = page_dir.split("/")[-2]  # Extract page ID from path
                    page_dirs.add((page_id, page_dir))

            # Process each page directory
            for page_id, page_dir in page_dirs:
                result_key = f"{page_dir}result.json"

                try:
                    # Check if result.json exists
                    s3_client.head_object(Bucket=bucket, Key=result_key)

                    # Load page data from result.json
                    result_uri = build_s3_uri(bucket, result_key)
                    page_data = get_json_content(result_uri)

                    # Create image and raw text URIs
                    image_uri = build_s3_uri(bucket, f"{page_dir}image.jpg")
                    raw_text_uri = build_s3_uri(bucket, f"{page_dir}rawText.json")

                    # Add page to document
                    document.pages[page_id] = Page(
                        page_id=page_id,
                        image_uri=image_uri,
                        raw_text_uri=raw_text_uri,
                        parsed_text_uri=result_uri,
                        classification=page_data.get("classification"),
                        confidence=page_data.get("confidence", 1.0),
                        tables=page_data.get("tables", []),
                        forms=page_data.get("forms", {}),
                    )

                except Exception as e:
                    logger.warning(f"Error loading page {page_id}: {str(e)}")

            # Update document with number of pages
            document.num_pages = len(document.pages)

            # Now list sections
            sections_prefix = f"{prefix}sections/"
            section_dirs = set()

            # Find all section directories
            for section_page in paginator.paginate(
                Bucket=bucket, Prefix=sections_prefix, Delimiter="/"
            ):
                for prefix_item in section_page.get("CommonPrefixes", []):
                    section_dir = prefix_item.get("Prefix")
                    section_id = section_dir.split("/")[
                        -2
                    ]  # Extract section ID from path
                    section_dirs.add((section_id, section_dir))

            # Process each section directory
            for section_id, section_dir in section_dirs:
                result_key = f"{section_dir}result.json"

                try:
                    # Check if result.json exists
                    s3_client.head_object(Bucket=bucket, Key=result_key)

                    # Load section data from result.json
                    result_uri = build_s3_uri(bucket, result_key)
                    section_data = get_json_content(result_uri)

                    # Get section attributes if they exist in the result
                    attributes = section_data.get("attributes", section_data)

                    # Determine page IDs for this section based on classification
                    # If not available in section_data, we'll try to infer from page classifications
                    section_classification = section_data.get("classification")
                    page_ids = section_data.get("page_ids", [])

                    # If page_ids not found in section data, try to infer from pages
                    if not page_ids and section_classification:
                        for page_id, page in document.pages.items():
                            if page.classification == section_classification:
                                page_ids.append(page_id)

                    # If section_id is numeric, match it to page_id
                    if not page_ids and section_id.isdigit():
                        if section_id in document.pages:
                            page_ids = [section_id]

                    # Add section to document
                    document.sections.append(
                        Section(
                            section_id=section_id,
                            classification=section_classification,
                            confidence=section_data.get("confidence", 1.0),
                            page_ids=page_ids,
                            extraction_result_uri=result_uri,
                            attributes=attributes,
                        )
                    )

                except Exception as e:
                    logger.warning(f"Error loading section {section_id}: {str(e)}")

            return document

        except Exception as e:
            logger.error(f"Error building document from S3: {str(e)}")
            raise

    def compress(self, bucket: str, step_name: str = "processing") -> Dict[str, Any]:
        """
        Store full document in S3 and return lightweight wrapper for Step Functions.

        Args:
            bucket: S3 bucket to store the full document
            step_name: Name of the processing step (for unique S3 key)

        Returns:
            Lightweight wrapper containing essential fields and section IDs for Map step
        """
        import logging

        import boto3

        logger = logging.getLogger(__name__)
        s3_client = boto3.client("s3")

        # Generate unique S3 key with timestamp
        timestamp = str(int(time.time() * 1000))  # milliseconds for uniqueness
        s3_key = f"compressed_documents/{self.id}/{timestamp}_{step_name}_state.json"

        try:
            # Store full document in S3
            full_document_json = self.to_json()
            s3_client.put_object(
                Bucket=bucket,
                Key=s3_key,
                Body=full_document_json,
                ContentType="application/json",
            )

            s3_uri = f"s3://{bucket}/{s3_key}"
            logger.info(f"Compressed document {self.id} to {s3_uri}")

            # Create lightweight wrapper with just section IDs for Map step
            # This significantly reduces payload size for large documents
            sections_for_map = [section.section_id for section in self.sections]

            return {
                "document_id": self.id,
                "s3_uri": s3_uri,
                "timestamp": timestamp,
                "status": self.status.value,
                "num_pages": self.num_pages,
                "sections": sections_for_map,  # For Step Functions Map state
                "compressed": True,
            }

        except Exception as e:
            logger.error(f"Error compressing document {self.id}: {str(e)}")
            raise

    @classmethod
    def decompress(cls, bucket: str, compressed_data: Dict[str, Any]) -> "Document":
        """
        Restore full Document from S3 using compressed wrapper data.

        Args:
            bucket: S3 bucket containing the compressed document
            compressed_data: Lightweight wrapper from compress() method

        Returns:
            Full Document object with all content restored
        """
        import logging
        from urllib.parse import urlparse

        import boto3

        logger = logging.getLogger(__name__)
        s3_client = boto3.client("s3")

        try:
            # Extract S3 key from URI
            s3_uri = compressed_data.get("s3_uri")
            if not s3_uri:
                raise ValueError("No s3_uri found in compressed data")

            parsed_uri = urlparse(s3_uri)
            s3_key = parsed_uri.path.lstrip("/")

            # Retrieve full document from S3
            response = s3_client.get_object(Bucket=bucket, Key=s3_key)
            document_json = response["Body"].read().decode("utf-8")

            # Restore full document
            document = cls.from_json(document_json)

            logger.info(f"Decompressed document {document.id} from {s3_uri}")
            return document

        except Exception as e:
            logger.error(f"Error decompressing document: {str(e)}")
            raise

    @classmethod
    def from_compressed_or_dict(cls, data, bucket=None):
        """
        Create a Document from either compressed data or a regular dict.

        Args:
            data: Either a compressed document reference or a regular document dict
            bucket: S3 bucket name (required if data is compressed)

        Returns:
            Document: The document instance
        """
        if isinstance(data, dict) and data.get("compressed") is True:
            if not bucket:
                raise ValueError("Bucket required for decompressing document")
            return cls.decompress(bucket, data)
        else:
            return cls.from_dict(data)

    @classmethod
    def load_document(cls, event_data, working_bucket, logger=None):
        """
        Utility method to handle document input from Lambda events.
        Automatically handles both compressed and uncompressed documents.

        Args:
            event_data: The document data from the Lambda event
            working_bucket: S3 bucket for decompression
            logger: Optional logger for debug messages

        Returns:
            Document: The document instance
        """
        if isinstance(event_data, dict) and event_data.get("compressed") is True:
            if logger:
                logger.info("Decompressed document from S3")
            return cls.decompress(working_bucket, event_data)
        else:
            if logger:
                logger.info("Loaded uncompressed document")
            return cls.from_dict(event_data)

    def serialize_document(
        self, working_bucket, step_name, logger=None, size_threshold_kb=0
    ):
        """
        Utility method to prepare document output for Lambda responses.
        Automatically compresses documents and returns appropriate response format.

        Args:
            working_bucket: S3 bucket for compression
            step_name: Name of the processing step (for S3 key generation)
            logger: Optional logger for debug messages
            size_threshold_kb: Size threshold in KB for compression (default 0KB - always compress)

        Returns:
            dict: Response data with either compressed reference or document dict
        """
        document_json = json.dumps(self.to_dict(), default=str)
        document_size = len(document_json.encode("utf-8"))
        threshold_bytes = size_threshold_kb * 1024

        if logger:
            logger.info(f"Document size after {step_name}: {document_size} bytes")

        # Compress if document is larger than threshold (default 0KB means always compress)
        if working_bucket and document_size > threshold_bytes:
            if logger:
                logger.info(
                    f"Document size ({document_size} bytes) exceeds {size_threshold_kb}KB threshold, compressing to S3"
                )
            compressed_data = self.compress(working_bucket, step_name)
            return compressed_data
        else:
            if logger:
                logger.info(
                    f"Document size ({document_size} bytes) is under {size_threshold_kb}KB threshold, returning as JSON"
                )
            return self.to_dict()
