"""
Classification service for documents using LLMs.

This module provides a service for classifying documents using various backends:
1. Bedrock LLMs with text support
2. Bedrock LLMs with multimodal support
"""

import json
import logging
import os
import time
from typing import Dict, List, Any, Optional, Tuple

from idp_common import bedrock, s3, image, utils
from idp_common.models import Document, Section, Status

logger = logging.getLogger(__name__)


class ClassificationService:
    """Service for classifying documents using various backends."""
    
    def __init__(
        self,
        region: str = None,
        config: Dict[str, Any] = None
    ):
        """
        Initialize the classification service.
        
        Args:
            region: AWS region for backend services
            config: Configuration dictionary
        """
        self.config = config or {}
        self.region = region or self.config.get("region") or os.environ.get("AWS_REGION")
        
        # Get model_id from config for logging
        model_id = self.config.get("model_id") or self.config.get("classification", {}).get("model")
        logger.info(f"Initialized classification service with model {model_id}")

    def _get_classification_config(self) -> Dict[str, Any]:
        """
        Get and validate the classification configuration.
                    
        Returns:
            Dict with validated classification configuration parameters
            
        Raises:
            ValueError: If required configuration values are missing
        """
        classification_config = self.config.get("classification", {})
        config = {
            "model_id": self.config.get("model_id") or classification_config.get("model"),
            "temperature": float(classification_config.get("temperature", 0)),
            "top_k": float(classification_config.get("top_k", 0.5)),
            "classification_method": classification_config.get("classificationMethod", "textbasedHolisticClassification")
        }
        
        # Validate system prompt
        system_prompt = classification_config.get("system_prompt")
        if not system_prompt:
            raise ValueError("No system_prompt found in classification configuration")
        
        config["system_prompt"] = system_prompt
        
        # Validate task prompt
        task_prompt = classification_config.get("task_prompt")
        if not task_prompt:
            raise ValueError("No task_prompt found in classification configuration")
        
        config["task_prompt"] = task_prompt
        
        return config

    def _format_class_descriptions(self, classes_config: List[Dict[str, Any]]) -> str:
        """
        Format class descriptions for the prompt.
        
        Args:
            classes_config: List of class configurations
            
        Returns:
            Formatted class descriptions as a markdown table
        """
        if not classes_config:
            return "| Class | Description |\n| --- | --- |\n| generic | A general document type |"
        
        # Create markdown table
        table = "| Class | Description |\n| --- | --- |\n"
        for class_obj in classes_config:
            name = class_obj.get("name", "")
            description = class_obj.get("description", "")
            table += f"| {name} | {description} |\n"
        
        return table

    def _extract_json(self, text: str) -> str:
        """Extract JSON string from text."""
        # Check for code block format
        if "```json" in text:
            start_idx = text.find("```json") + len("```json")
            end_idx = text.find("```", start_idx)
            if end_idx > start_idx:
                return text[start_idx:end_idx].strip()
        elif "```" in text:
            start_idx = text.find("```") + len("```")
            end_idx = text.find("```", start_idx)
            if end_idx > start_idx:
                return text[start_idx:end_idx].strip()
        
        # Check for simple JSON
        if "{" in text and "}" in text:
            start_idx = text.find("{")
            # Find matching closing brace
            open_braces = 0
            for i in range(start_idx, len(text)):
                if text[i] == "{":
                    open_braces += 1
                elif text[i] == "}":
                    open_braces -= 1
                    if open_braces == 0:
                        return text[start_idx:i+1].strip()
        
        # If we can't find JSON, return the text as-is
        return text

    def process_document(self, document: Document) -> Document:
        """
        Classify a document and update the Document object with classification results.
        
        Args:
            document: Document object to classify
            
        Returns:
            Document: Updated Document object with classification results
        """
        if not document.pages:
            logger.warning("Document has no pages to classify")
            return self._update_document_status(
                document, 
                success=False, 
                error_message="Document has no pages to classify"
            )
        
        try:
            # Start timing
            start_time = time.time()
            
            # Get classification configuration
            config = self._get_classification_config()
            classification_method = config["classification_method"]
            
            # Get class descriptions
            classes_config = self.config.get("classes", [])
            class_descriptions = self._format_class_descriptions(classes_config)
            
            # Combine text from all pages
            all_text = ""
            for page_id, page in sorted(document.pages.items()):
                if page.parsed_text_uri:
                    try:
                        page_text = s3.get_text_content(page.parsed_text_uri)
                        all_text += f"<page-number>{page_id}</page-number>\n{page_text}\n\n"
                    except Exception as e:
                        logger.warning(f"Failed to load text content from {page.parsed_text_uri}: {e}")
                        # Continue with other pages
            
            if not all_text:
                logger.warning("No text content found in document pages")
                return self._update_document_status(
                    document, 
                    success=False, 
                    error_message="No text content found in document pages"
                )
            
            # Use common function to prepare prompt with required placeholder validation
            task_prompt = bedrock.format_prompt(
                config["task_prompt"], 
                {
                    "DOCUMENT_TEXT": all_text,
                    "CLASS_NAMES_AND_DESCRIPTIONS": class_descriptions
                },
                required_placeholders=["DOCUMENT_TEXT", "CLASS_NAMES_AND_DESCRIPTIONS"]
            )
            
            content = [{"text": task_prompt}]
            
            logger.info(f"Classifying document with method: {classification_method}")
            
            # Invoke Bedrock model
            response_with_metering = bedrock.invoke_model(
                model_id=config["model_id"],
                system_prompt=config["system_prompt"],
                content=content,
                temperature=config["temperature"],
                top_k=config["top_k"]
            )
            
            response = response_with_metering["response"]
            metering = response_with_metering["metering"]
            
            # Extract classification result
            result_text = response['output']['message']['content'][0].get("text", "")
            
            # Try to extract JSON from the response
            try:
                result_json = self._extract_json(result_text)
                result_data = json.loads(result_json)
                
                # Process segments into sections
                segments = result_data.get("segments", [])
                
                # Create sections from segments
                for i, segment in enumerate(segments):
                    start_page = segment.get("ordinal_start_page")
                    end_page = segment.get("ordinal_end_page")
                    doc_type = segment.get("type")
                    
                    if not all([start_page, end_page, doc_type]):
                        logger.warning(f"Incomplete segment data: {segment}")
                        continue
                    
                    # Create page IDs list
                    page_ids = [str(p) for p in range(start_page, end_page + 1)]
                    
                    # Create section
                    section = Section(
                        section_id=f"section-{i+1}",
                        classification=doc_type,
                        confidence=1.0,  # Default confidence
                        page_ids=page_ids
                    )
                    
                    # Add section to document
                    document.sections.append(section)
                    
                    # Update page classifications
                    for page_id in page_ids:
                        if page_id in document.pages:
                            document.pages[page_id].classification = doc_type
                
                # Calculate execution time
                execution_time = time.time() - start_time
                
                # Update document metering
                document.metering = utils.merge_metering_data(document.metering, metering)
                
                # Update document status
                document = self._update_document_status(document)
                
                logger.info(f"Document classified successfully with {len(document.sections)} sections")
                
            except Exception as e:
                error_msg = f"Error parsing classification result: {str(e)}"
                logger.error(error_msg)
                document = self._update_document_status(document, success=False, error_message=error_msg)
            
        except Exception as e:
            error_msg = f"Error classifying document: {str(e)}"
            logger.error(error_msg)
            document = self._update_document_status(document, success=False, error_message=error_msg)
        
        return document
    
    def _update_document_status(self, document: Document, success: bool = True, error_message: Optional[str] = None) -> Document:
        """
        Update document status based on processing results.
        
        Args:
            document: Document to update
            success: Whether processing was successful
            error_message: Optional error message to add
            
        Returns:
            Updated document with appropriate status
        """
        if error_message and error_message not in document.errors:
            document.errors.append(error_message)
            
        if not success:
            document.status = Status.FAILED
            if error_message:
                logger.error(error_message)
        else:
            # Set status to CLASSIFIED even with non-fatal errors
            document.status = Status.CLASSIFIED
            if document.errors:
                logger.warning(f"Document classified with {len(document.errors)} errors")
                
        return document
