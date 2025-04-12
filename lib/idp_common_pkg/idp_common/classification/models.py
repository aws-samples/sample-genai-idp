"""
Data models for document classification.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional


@dataclass
class DocumentType:
    """Document type definition with name and description."""
    
    type_name: str
    """The name of the document type."""
    
    description: str
    """Description of the document type."""


@dataclass
class DocumentClassification:
    """Classification result for a document or page."""
    
    doc_type: str
    """The classified document type."""
    
    confidence: float = 1.0
    """Confidence score for the classification (0-1)."""
    
    metadata: Dict[str, Any] = field(default_factory=dict)
    """Additional metadata for the classification."""


@dataclass
class PageClassification:
    """Classification result for a single page."""
    
    page_id: str
    """The ID of the page."""
    
    classification: DocumentClassification
    """The classification result for the page."""
    
    image_uri: Optional[str] = None
    """URI of the page image, if available."""
    
    text_uri: Optional[str] = None
    """URI of the page text, if available."""
    
    raw_text_uri: Optional[str] = None
    """URI of the raw text, if available."""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'page_id': self.page_id,
            'class': self.classification.doc_type,
            'confidence': self.classification.confidence,
            'imageUri': self.image_uri,
            'parsedTextUri': self.text_uri,
            'rawTextUri': self.raw_text_uri,
            **self.classification.metadata
        }


@dataclass
class DocumentSection:
    """A section of consecutive pages with the same classification."""
    
    section_id: str
    """The ID of the section."""
    
    classification: DocumentClassification
    """The classification result for the section."""
    
    pages: List[PageClassification]
    """The pages in the section."""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'id': self.section_id,
            'class': self.classification.doc_type,
            'pages': [page.to_dict() for page in self.pages]
        }


@dataclass
class ClassificationResult:
    """Result of a document classification operation."""
    
    metadata: Dict[str, Any]
    """Metadata about the classification operation."""
    
    sections: List[DocumentSection]
    """Sections of classified pages."""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation for API responses."""
        return {
            'metadata': self.metadata,
            'sections': [section.to_dict() for section in self.sections]
        }