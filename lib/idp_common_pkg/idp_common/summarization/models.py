"""
Models for document summarization.

This module provides data models for document summarization results.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List


@dataclass
class DocumentSummary:
    """Flexible model for document summary results that can handle any JSON structure."""
    
    content: Dict[str, Any]
    """The raw content from the summarization result, containing any fields the LLM returned."""
    
    metadata: Dict[str, Any] = field(default_factory=dict)
    """Optional metadata about the summarization process."""
    
    def __getitem__(self, key: str) -> Any:
        """Allow dictionary-like access to summary fields."""
        return self.content.get(key)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a summary field with an optional default value."""
        return self.content.get(key, default)
    
    def keys(self) -> List[str]:
        """Get a list of available keys in the summary."""
        return list(self.content.keys())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        result = self.content.copy()
        result['metadata'] = self.metadata
        return result


@dataclass
class DocumentSummarizationResult:
    """Comprehensive summarization result for a document."""
    document_id: str
    summary: DocumentSummary
    execution_time: float = 0.0
    output_uri: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        result = {
            "document_id": self.document_id,
            "execution_time": self.execution_time,
            "output_uri": self.output_uri
        }
        
        # Include all content fields from the summary
        result.update(self.summary.content)
        result["metadata"] = self.summary.metadata
            
        return result
    
    def to_markdown(self) -> str:
        """Convert summarization results to markdown format."""
        sections = []
        
        # Add document header
        sections.append(f"# Document Summary: {self.document_id}")
        sections.append("")
        
        # Process each key in the summary as a section
        for key, value in self.summary.content.items():
            # Format the section title from the key
            section_title = key.replace('_', ' ').title()
            sections.append(f"## {section_title}")
            
            # Handle different value types appropriately
            if isinstance(value, list):
                # Format list items
                for item in value:
                    sections.append(f"- {item}")
            elif isinstance(value, dict):
                # Format dictionary items as subsections
                for sub_key, sub_value in value.items():
                    sections.append(f"### {sub_key.replace('_', ' ').title()}")
                    sections.append(f"{sub_value}")
                    sections.append("")
            else:
                # Format simple string/value
                sections.append(str(value))
            
            sections.append("")
        
        # Add metadata if available
        if self.summary.metadata:
            metadata = self.summary.metadata
            sections.append("## Metadata")
            
            # Format metadata as a table
            metadata_table = "| Key | Value |\n| --- | --- |\n"
            
            # Filter out metering data for cleaner display
            display_metadata = {k: v for k, v in metadata.items() if k != "metering"}
            
            for key, value in display_metadata.items():
                # Format value for table display
                if isinstance(value, dict):
                    value_str = "Complex data - see below"
                else:
                    value_str = str(value)
                
                metadata_table += f"| {key} | {value_str} |\n"
            
            sections.append(metadata_table)
            
            # Add detailed metadata as nested sections if needed
            for key, value in display_metadata.items():
                if isinstance(value, dict):
                    sections.append(f"### {key}")
                    # Format the nested dict
                    for sub_key, sub_value in value.items():
                        sections.append(f"- **{sub_key}**: {sub_value}")
            
            sections.append("")
        
        # Add execution time
        sections.append(f"Execution time: {self.execution_time:.2f} seconds")
        
        return "\n".join(sections)
