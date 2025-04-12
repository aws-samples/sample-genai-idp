"""
Simplified document data model for IDP processing.

This module defines the Document class that represents the state of a document
as it moves through the processing pipeline.
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Any, Optional


class Status(Enum):
    """Document processing status."""
    QUEUED = "QUEUED"           # Initial state when document is added to queue
    STARTED = "STARTED"         # Step function workflow has started
    OCR_COMPLETED = "OCR_COMPLETED"  # OCR processing completed
    CLASSIFIED = "CLASSIFIED"   # Document classification completed
    EXTRACTED = "EXTRACTED"     # Information extraction completed
    PROCESSED = "PROCESSED"     # All processing completed
    FAILED = "FAILED"           # Processing failed
    EVALUATED = "EVALUATED"     # Document has been evaluated against baseline


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
    def from_dict(cls, data: Dict[str, Any]) -> 'Section':
        """Create a Section from a dictionary representation."""
        if not data:
            raise ValueError("Cannot create Section from empty data")
            
        return cls(
            section_id=data.get('section_id', ''),
            classification=data.get('classification', ''),
            confidence=data.get('confidence', 1.0),
            page_ids=data.get('page_ids', []),
            extraction_result_uri=data.get('extraction_result_uri'),
            attributes=data.get('attributes')
        )
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert section to dictionary representation."""
        return {
            "section_id": self.section_id,
            "classification": self.classification,
            "confidence": self.confidence,
            "page_ids": self.page_ids,
            "extraction_result_uri": self.extraction_result_uri,
            "attributes": self.attributes
        }


@dataclass
class Document:
    """
    Core document type that is passed through the processing pipeline.
    Each processing step enriches this object.
    """
    # Core identifiers
    id: Optional[str] = None            # Generated document ID
    input_bucket: Optional[str] = None  # S3 bucket containing the input document
    input_key: Optional[str] = None     # S3 key of the input document
    output_bucket: Optional[str] = None # S3 bucket for processing outputs
    
    # Processing state and timing
    status: Status = Status.QUEUED
    queued_time: Optional[str] = None
    start_time: Optional[str] = None
    completion_time: Optional[str] = None
    workflow_execution_arn: Optional[str] = None
    
    # Document content details
    num_pages: int = 0
    pages: Dict[str, Page] = field(default_factory=dict)
    sections: List[Section] = field(default_factory=list)
    
    # Processing metadata
    metering: Dict[str, Any] = field(default_factory=dict)
    evaluation_report_uri: Optional[str] = None
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
            "queued_time": self.queued_time,
            "start_time": self.start_time,
            "completion_time": self.completion_time,
            "workflow_execution_arn": self.workflow_execution_arn,
            "num_pages": self.num_pages,
            "evaluation_report_uri": self.evaluation_report_uri,
            "errors": self.errors,
            "metering": self.metering
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
                "forms": page.forms
            }
        
        # Convert sections
        result["sections"] = []
        for section in self.sections:
            section_dict = {
                "section_id": section.section_id,
                "classification": section.classification,
                "confidence": section.confidence,
                "page_ids": section.page_ids,
                "extraction_result_uri": section.extraction_result_uri
            }
            if section.attributes:
                section_dict["attributes"] = section.attributes
            result["sections"].append(section_dict)
            
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Document':
        """Create a Document from a dictionary representation."""
        document = cls(
            id=data.get('id', data.get('input_key')),
            input_bucket=data.get('input_bucket'),
            input_key=data.get('input_key'),
            output_bucket=data.get('output_bucket'),
            num_pages=data.get('num_pages', 0),
            queued_time=data.get('queued_time'),
            start_time=data.get('start_time'),
            completion_time=data.get('completion_time'),
            workflow_execution_arn=data.get('workflow_execution_arn'),
            evaluation_report_uri=data.get('evaluation_report_uri'),
            metering=data.get('metering', {}),
            errors=data.get('errors', [])
        )
        
        # Convert status from string to enum
        if 'status' in data:
            try:
                document.status = Status(data['status'])
            except ValueError:
                # If the status isn't a valid enum value, use QUEUED as default
                document.status = Status.QUEUED
        
        # Convert pages
        pages_data = data.get('pages', {})
        for page_id, page_data in pages_data.items():
            document.pages[page_id] = Page(
                page_id=page_id,
                image_uri=page_data.get('image_uri'),
                raw_text_uri=page_data.get('raw_text_uri'),
                parsed_text_uri=page_data.get('parsed_text_uri'),
                classification=page_data.get('classification'),
                confidence=page_data.get('confidence', 0.0),
                tables=page_data.get('tables', []),
                forms=page_data.get('forms', {})
            )
        
        # Convert sections
        sections_data = data.get('sections', [])
        for section_data in sections_data:
            document.sections.append(Section(
                section_id=section_data.get('section_id'),
                classification=section_data.get('classification'),
                confidence=section_data.get('confidence', 1.0),
                page_ids=section_data.get('page_ids', []),
                extraction_result_uri=section_data.get('extraction_result_uri'),
                attributes=section_data.get('attributes')
            ))
        
        return document
    
    @classmethod
    def from_s3_event(cls, event: Dict[str, Any], output_bucket: str) -> 'Document':
        """Create a Document from an S3 event."""
        input_bucket = event.get("detail", {}).get("bucket", {}).get("name", "")
        input_key = event.get("detail", {}).get("object", {}).get("key", "")
        
        return cls(
            id=input_key,
            input_bucket=input_bucket,
            input_key=input_key,
            output_bucket=output_bucket,
            status=Status.QUEUED
        )
    
    def to_json(self) -> str:
        """Convert document to JSON string."""
        return json.dumps(self.to_dict())
    
    @classmethod
    def from_json(cls, json_str: str) -> 'Document':
        """Create a Document from a JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)