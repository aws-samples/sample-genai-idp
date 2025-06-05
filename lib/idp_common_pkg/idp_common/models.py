# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Simplified document data model for IDP processing.

This module defines the Document class that represents the state of a document
as it moves through the processing pipeline.
"""

import json
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
    POSTPROCESSING = "POSTPROCESSING"  # Document summarization
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
        }


@dataclass
class Document:
    """
    Core document type that is passed through the processing pipeline.
    Each processing step enriches this object.
    """

    # Core identifiers
    id: Optional[str] = None  # Generated document ID
    input_bucket: Optional[str] = None  # S3 bucket containing the input document
    input_key: Optional[str] = None  # S3 key of the input document
    output_bucket: Optional[str] = None  # S3 bucket for processing outputs

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
    evaluation_result: Any = None  # Holds the DocumentEvaluationResult object
    summarization_result: Any = None  # Holds the DocumentSummarizationResult object
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert document to dictionary representation."""
        # First convert basic attributes
        result = {
            "id": self.id,
            "input_bucket": self.input_bucket,
            "input_key": self.input_key,
            "output_bucket": self.output_bucket,
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
            }
            if section.attributes:
                section_dict["attributes"] = section.attributes
            result["sections"].append(section_dict)

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Document":
        """Create a Document from a dictionary representation."""
        document = cls(
            id=data.get("id", data.get("input_key")),
            input_bucket=data.get("input_bucket"),
            input_key=data.get("input_key"),
            output_bucket=data.get("output_bucket"),
            num_pages=data.get("num_pages", 0),
            initial_event_time=data.get("initial_event_time"),
            queued_time=data.get("queued_time"),
            start_time=data.get("start_time"),
            completion_time=data.get("completion_time"),
            workflow_execution_arn=data.get("workflow_execution_arn"),
            evaluation_status=data.get("evaluation_status"),
            evaluation_report_uri=data.get("evaluation_report_uri"),
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
                )
            )

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
        return json.dumps(self.to_dict())

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
