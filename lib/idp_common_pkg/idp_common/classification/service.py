"""
Classification service for documents using LLMs or SageMaker UDOP models.

This module provides a service for classifying documents using various backends:
1. Bedrock LLMs with text and image support
2. SageMaker UDOP models for multimodal document classification
"""

import json
import logging
import os
import boto3
from typing import List, Dict, Any, Optional, Union, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from botocore.exceptions import ClientError
import time
import threading

from idp_common import bedrock, s3, utils
from idp_common.classification.models import (
    DocumentClassification,
    DocumentType,
    PageClassification,
    DocumentSection,
    ClassificationResult
)
from idp_common.models import Document, Section, Status, Page

logger = logging.getLogger(__name__)


class ClassificationService:
    """Service for classifying documents using various backends."""

    # Configuration for the SageMaker retry mechanism
    MAX_RETRIES = 8 
    INITIAL_BACKOFF = 2  # seconds
    MAX_BACKOFF = 300    # 5 minutes

    def __init__(
        self,
        region: str = None,
        max_workers: int = 20,
        config: Dict[str, Any] = None,
        backend: str = "bedrock"
    ):
        """
        Initialize the classification service.
        
        Args:
            region: AWS region for backend services
            max_workers: Maximum number of concurrent workers
            config: Configuration dictionary
            backend: Classification backend to use ('bedrock' or 'sagemaker')
        """
        self.config = config or {}
        self.region = region or self.config.get("region") or os.environ.get("AWS_REGION")
        self.max_workers = max_workers
        self.document_types = self._load_document_types()
        self.valid_doc_types: Set[str] = {dt.type_name for dt in self.document_types}
        self.backend = backend.lower()
        
        # Validate backend choice
        if self.backend not in ["bedrock", "sagemaker"]:
            logger.warning(f"Invalid backend '{backend}', falling back to 'bedrock'")
            self.backend = "bedrock"
        
        # Initialize backend-specific clients
        if self.backend == "bedrock":
            # Get model_id from config for logging
            model_id = self.config.get("model_id") or self.config.get("classification", {}).get("model")
            if not model_id:
                logger.warning("No model ID specified in configuration, will use default from Bedrock client")
            logger.info(f"Initialized classification service with Bedrock backend using model {model_id}")
        else:  # sagemaker
            endpoint_name = self.config.get("sagemaker_endpoint_name") or os.environ.get("SAGEMAKER_ENDPOINT_NAME")
            if not endpoint_name:
                logger.warning("No SageMaker endpoint name specified in configuration or environment")
            self.sm_client = boto3.client('sagemaker-runtime', region_name=self.region)
            logger.info(f"Initialized classification service with SageMaker backend using endpoint {endpoint_name}")

    def _load_document_types(self) -> List[DocumentType]:
        """Load document types from configuration."""
        doc_types = []
        
        # Get document types from config
        classes = self.config.get("classes", [])
        for class_obj in classes:
            doc_types.append(DocumentType(
                type_name=class_obj.get("name", ""),
                description=class_obj.get("description", "")
            ))
        
        if not doc_types:
            # Add a default type if none are defined
            logger.warning("No document types defined in configuration, using default 'unclassified' type")
            doc_types.append(DocumentType(
                type_name="unclassified",
                description="A document that does not match any known type."
            ))
        
        return doc_types

    def _format_document_types(self) -> str:
        """Format document types for the prompt."""
        return "\n".join([
            f"{doc_type.type_name}  \t[ {doc_type.description} ]" 
            for doc_type in self.document_types
        ])

    def classify_page_bedrock(
        self,
        page_id: str,
        text_content: str = None,
        image_content: Optional[bytes] = None,
        text_uri: Optional[str] = None,
        image_uri: Optional[str] = None,
        raw_text_uri: Optional[str] = None
    ) -> PageClassification:
        """
        Classify a single page using Bedrock LLMs.
        
        Args:
            page_id: ID of the page
            text_content: Text content of the page
            image_content: Image content as bytes
            text_uri: URI of the text content
            image_uri: URI of the image content
            raw_text_uri: URI of the raw text content
            
        Returns:
            PageClassification: Classification result for the page
        """
        # Load text content from URI if not provided
        if text_content is None and text_uri:
            try:
                text_content = s3.get_text_content(text_uri)
            except Exception as e:
                logger.warning(f"Failed to load text content from {text_uri}: {e}")
                # Continue without text content
        
        # Load image content from URI if not provided
        if image_content is None and image_uri:
            try:
                image_content = s3.get_binary_content(image_uri)
            except Exception as e:
                logger.warning(f"Failed to load image content from {image_uri}: {e}")
                # Continue without image content
        
        # Verify we have at least some content to classify
        if not text_content and not image_content:
            logger.warning(f"No content available for page {page_id}")
            # Return unclassified result
            return PageClassification(
                page_id=page_id,
                classification=DocumentClassification(
                    doc_type="unclassified",
                    confidence=0.0,
                    metadata={"error": "No content available for classification"}
                ),
                image_uri=image_uri,
                text_uri=text_uri,
                raw_text_uri=raw_text_uri
            )
        
        # Get classification configuration
        classification_config = self.config.get("classification", {})
        model_id = self.config.get("model_id") or classification_config.get("model")
        temperature = float(classification_config.get("temperature", 0))
        top_k = float(classification_config.get("top_k", 0.5))
        system_prompt = classification_config.get("system_prompt", "")
        
        # Prepare prompt
        prompt_template = classification_config.get("task_prompt", "")
        if "{DOCUMENT_TEXT}" in prompt_template and "{CLASS_NAMES_AND_DESCRIPTIONS}" in prompt_template:
            prompt_template = prompt_template.replace("{DOCUMENT_TEXT}", "%(DOCUMENT_TEXT)s").replace("{CLASS_NAMES_AND_DESCRIPTIONS}", "%(CLASS_NAMES_AND_DESCRIPTIONS)s")
            task_prompt = prompt_template % {
                "CLASS_NAMES_AND_DESCRIPTIONS": self._format_document_types(),
                "DOCUMENT_TEXT": text_content or ""
            }
        else:
            # Default prompt if template not found
            logger.warning("No task_prompt template found in configuration, using default")
            task_prompt = f"""
            Classify the following document into one of these types:
            
            {self._format_document_types()}
            
            Document text:
            {text_content or ""}
            
            Respond with a JSON object with a single field "class" containing the document type.
            """
        
        content = [{"text": task_prompt}]
        
        # Add image if available
        if image_content:
            from idp_common import image
            content.append(image.prepare_bedrock_image_attachment(image_content))
        
        logger.info(f"Classifying page {page_id} with Bedrock")
        
        t0 = time.time()
        
        # Invoke Bedrock with the common library
        try:
            response_with_metering = bedrock.invoke_model(
                model_id=model_id,
                system_prompt=system_prompt,
                content=content,
                temperature=temperature,
                top_k=top_k
            )
            
            t1 = time.time()
            logger.info(f"Time taken for classification of page {page_id}: {t1-t0:.2f} seconds")
            
            response = response_with_metering["response"]
            metering = response_with_metering["metering"]
            
            # Extract classification result
            classification_text = response['output']['message']['content'][0].get("text", "")
            
            # Try to extract JSON from the response
            try:
                classification_json = self._extract_json(classification_text)
                classification_data = json.loads(classification_json)
                doc_type = classification_data.get("class", "")
            except Exception as e:
                logger.warning(f"Failed to parse JSON from response: {e}")
                # Try to extract classification directly from text
                doc_type = self._extract_class_from_text(classification_text)
            
            # Validate classification against known document types
            if not doc_type:
                doc_type = "unclassified"
                logger.warning(f"Empty classification for page {page_id}, using 'unclassified'")
            elif doc_type not in self.valid_doc_types:
                logger.warning(
                    f"Unknown document type '{doc_type}' for page {page_id}, "
                    f"valid types are: {', '.join(self.valid_doc_types)}"
                )
                # Still use the classification, it might be a new valid type
            
            logger.info(f"Page {page_id} classified as {doc_type}")
            
            # Create and return classification result
            return PageClassification(
                page_id=page_id,
                classification=DocumentClassification(
                    doc_type=doc_type,
                    confidence=1.0,  # Default confidence
                    metadata={"metering": metering}
                ),
                image_uri=image_uri,
                text_uri=text_uri,
                raw_text_uri=raw_text_uri
            )
        except Exception as e:
            logger.error(f"Error classifying page {page_id}: {str(e)}")
            # Return unclassified result with error
            return PageClassification(
                page_id=page_id,
                classification=DocumentClassification(
                    doc_type="unclassified",
                    confidence=0.0,
                    metadata={"error": str(e)}
                ),
                image_uri=image_uri,
                text_uri=text_uri,
                raw_text_uri=raw_text_uri
            )

    def classify_page_sagemaker(
        self,
        page_id: str,
        image_uri: Optional[str] = None,
        raw_text_uri: Optional[str] = None,
        text_uri: Optional[str] = None
    ) -> PageClassification:
        """
        Classify a single page using SageMaker UDOP model endpoint.
        
        Args:
            page_id: ID of the page
            image_uri: URI of the page image
            raw_text_uri: URI of the raw text (Textract output)
            text_uri: URI of the processed text
            
        Returns:
            PageClassification: Classification result for the page
        """
        # Verify we have the required URIs
        if not image_uri or not raw_text_uri:
            logger.warning(f"Missing required URIs for page {page_id}")
            return PageClassification(
                page_id=page_id,
                classification=DocumentClassification(
                    doc_type="unclassified",
                    confidence=0.0,
                    metadata={"error": "Missing required image_uri or raw_text_uri"}
                ),
                image_uri=image_uri,
                text_uri=text_uri,
                raw_text_uri=raw_text_uri
            )
        
        # Get endpoint name from config or environment
        endpoint_name = self.config.get("sagemaker_endpoint_name") or os.environ.get("SAGEMAKER_ENDPOINT_NAME")
        if not endpoint_name:
            logger.error("No SageMaker endpoint name specified in configuration or environment")
            return PageClassification(
                page_id=page_id,
                classification=DocumentClassification(
                    doc_type="unclassified",
                    confidence=0.0,
                    metadata={"error": "No SageMaker endpoint configured"}
                ),
                image_uri=image_uri,
                text_uri=text_uri,
                raw_text_uri=raw_text_uri
            )
        
        # Prepare payload
        payload = {
            "input_image": image_uri,
            "input_textract": raw_text_uri,
            "prompt": '',
            "debug": 0
        }
        
        # Implement retry logic
        retry_count = 0
        metering = {}
        
        while retry_count < self.MAX_RETRIES:
            try:
                logger.info(f"Classifying page {page_id} with SageMaker UDOP model")
                t0 = time.time()
                
                # Invoke endpoint
                response = self.sm_client.invoke_endpoint(
                    EndpointName=endpoint_name,
                    ContentType='application/json',
                    Body=json.dumps(payload)
                )
                
                duration = time.time() - t0
                
                # Parse response
                response_body = json.loads(response['Body'].read().decode())
                doc_type = response_body.get('prediction', 'unclassified')
                
                # Log success metrics
                logger.info(f"Page {page_id} classification successful in {duration:.2f}s")
                
                # Add some metering data for consistency with Bedrock
                metering = {
                    "sagemaker/invoke_endpoint": {
                        "invocations": 1,
                    }
                }
                
                # Create and return classification result
                return PageClassification(
                    page_id=page_id,
                    classification=DocumentClassification(
                        doc_type=doc_type,
                        confidence=1.0,  # Default confidence since SageMaker doesn't provide it
                        metadata={"metering": metering}
                    ),
                    image_uri=image_uri,
                    text_uri=text_uri,
                    raw_text_uri=raw_text_uri
                )
                
            except ClientError as e:
                error_code = e.response['Error']['Code']
                error_message = e.response['Error']['Message']
                
                retryable_errors = [
                    'ThrottlingException', 
                    'ServiceQuotaExceededException',
                    'RequestLimitExceeded', 
                    'TooManyRequestsException'
                ]
                
                if error_code in retryable_errors:
                    retry_count += 1
                    
                    if retry_count == self.MAX_RETRIES:
                        logger.error(f"Max retries ({self.MAX_RETRIES}) exceeded for page {page_id}")
                        break
                    
                    backoff = utils.calculate_backoff(retry_count, self.INITIAL_BACKOFF, self.MAX_BACKOFF)
                    logger.warning(
                        f"SageMaker throttling occurred for page {page_id} "
                        f"(attempt {retry_count}/{self.MAX_RETRIES}). "
                        f"Error: {error_message}. "
                        f"Backing off for {backoff:.2f}s"
                    )
                    
                    time.sleep(backoff)  # semgrep-ignore: arbitrary-sleep - Intentional delay backoff/retry. Duration is algorithmic and not user-controlled.
                else:
                    logger.error(
                        f"Non-retryable SageMaker error for page {page_id}: "
                        f"{error_code} - {error_message}"
                    )
                    # Return unclassified with error
                    return PageClassification(
                        page_id=page_id,
                        classification=DocumentClassification(
                            doc_type="unclassified",
                            confidence=0.0,
                            metadata={"error": f"{error_code}: {error_message}"}
                        ),
                        image_uri=image_uri,
                        text_uri=text_uri,
                        raw_text_uri=raw_text_uri
                    )
            except Exception as e:
                logger.error(f"Unexpected error classifying page {page_id}: {str(e)}")
                # Return unclassified with error
                return PageClassification(
                    page_id=page_id,
                    classification=DocumentClassification(
                        doc_type="unclassified",
                        confidence=0.0,
                        metadata={"error": str(e)}
                    ),
                    image_uri=image_uri,
                    text_uri=text_uri,
                    raw_text_uri=raw_text_uri
                )
        
        # If we've reached here after max retries, return error
        return PageClassification(
            page_id=page_id,
            classification=DocumentClassification(
                doc_type="unclassified",
                confidence=0.0,
                metadata={"error": "Max retries exceeded for SageMaker classification"}
            ),
            image_uri=image_uri,
            text_uri=text_uri,
            raw_text_uri=raw_text_uri
        )

    def classify_page(
        self,
        page_id: str,
        text_content: str = None,
        image_content: Optional[bytes] = None,
        text_uri: Optional[str] = None,
        image_uri: Optional[str] = None,
        raw_text_uri: Optional[str] = None
    ) -> PageClassification:
        """
        Classify a single page based on its text and/or image content.
        Uses the configured backend (Bedrock or SageMaker).
        
        Args:
            page_id: ID of the page
            text_content: Text content of the page
            image_content: Image content as bytes
            text_uri: URI of the text content
            image_uri: URI of the image content
            raw_text_uri: URI of the raw text content
            
        Returns:
            PageClassification: Classification result for the page
        """
        if self.backend == "bedrock":
            return self.classify_page_bedrock(
                page_id=page_id,
                text_content=text_content,
                image_content=image_content,
                text_uri=text_uri,
                image_uri=image_uri,
                raw_text_uri=raw_text_uri
            )
        else:  # sagemaker
            return self.classify_page_sagemaker(
                page_id=page_id,
                image_uri=image_uri,
                raw_text_uri=raw_text_uri,
                text_uri=text_uri
            )

    def _extract_json(self, text: str) -> str:
        """Extract JSON string from text."""
        # Check for code block format
        if "```json" in text:
            start_idx = text.find("```json") + len("```json")
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

    def _extract_class_from_text(self, text: str) -> str:
        """Extract class name from text if JSON parsing fails."""
        # Check for common patterns
        patterns = [
            "class: ", 
            "document type: ", 
            "document class: ", 
            "classification: ",
            "type: "
        ]
        
        text_lower = text.lower()
        for pattern in patterns:
            if pattern in text_lower:
                start_idx = text_lower.find(pattern) + len(pattern)
                end_idx = text_lower.find("\n", start_idx)
                if end_idx == -1:
                    end_idx = len(text_lower)
                
                return text[start_idx:end_idx].strip().strip('"\'')
        
        return ""

    def classify_document(self, document: Document) -> Document:
        """
        Classify a document's pages and update the Document object with sections.
        Uses the configured backend (Bedrock or SageMaker).
        
        Args:
            document: Document object to classify and update
            
        Returns:
            Document: Updated Document object with classifications and sections
        """
        if not document.pages:
            logger.warning("Document has no pages to classify")
            document.status = Status.FAILED
            document.errors.append("Document has no pages to classify")
            return document
            
        t0 = time.time()
        logger.info(f"Classifying document with {len(document.pages)} pages using {self.backend} backend")
        
        try:
            # Process pages concurrently
            all_page_results = []
            combined_metering = {}
            errors_lock = threading.Lock()  # Thread safety for error collection
            
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {}
                
                # Start processing all pages
                for page_id, page in document.pages.items():
                    future = executor.submit(
                        self.classify_page,
                        page_id=page_id,
                        text_uri=page.parsed_text_uri,
                        image_uri=page.image_uri,
                        raw_text_uri=page.raw_text_uri
                    )
                    futures[future] = page_id
                
                # Process results as they complete
                for future in as_completed(futures):
                    page_id = futures[future]
                    try:
                        page_result = future.result()
                        all_page_results.append(page_result)
                        
                        # Check if there was an error in the classification
                        if "error" in page_result.classification.metadata:
                            with errors_lock:
                                error_msg = f"Error classifying page {page_id}: {page_result.classification.metadata['error']}"
                                document.errors.append(error_msg)
                        
                        # Update the page in the document
                        document.pages[page_id].classification = page_result.classification.doc_type
                        document.pages[page_id].confidence = page_result.classification.confidence
                        
                        # Merge metering data
                        page_metering = page_result.classification.metadata.get("metering", {})
                        combined_metering = utils.merge_metering_data(combined_metering, page_metering)
                    except Exception as e:
                        error_msg = f"Error classifying page {page_id}: {str(e)}"
                        logger.error(error_msg)
                        with errors_lock:
                            document.errors.append(error_msg)
                        
                        # Mark page as unclassified on error
                        if page_id in document.pages:
                            document.pages[page_id].classification = "unclassified"
                            document.pages[page_id].confidence = 0.0
            
            # Group pages into sections only if we have results
            document.sections = []
            try:
                sorted_results = sorted(all_page_results, key=lambda x: int(x.page_id))
            except (ValueError, TypeError) as e:
                logger.warning(f"Unable to sort page IDs as integers, using string sort: {e}")
                sorted_results = sorted(all_page_results, key=lambda x: x.page_id)
            
            if sorted_results:
                current_group = 1
                current_type = sorted_results[0].classification.doc_type
                current_pages = [sorted_results[0]]
                
                for result in sorted_results[1:]:
                    if result.classification.doc_type == current_type:
                        current_pages.append(result)
                    else:
                        # Create a new section with the current group of pages
                        section = Section(
                            section_id=str(current_group),
                            classification=current_type,
                            confidence=1.0,
                            page_ids=[p.page_id for p in current_pages]
                        )
                        document.sections.append(section)
                        
                        # Start a new group
                        current_group += 1
                        current_type = result.classification.doc_type
                        current_pages = [result]
                
                # Add the final section
                section = Section(
                    section_id=str(current_group),
                    classification=current_type,
                    confidence=1.0,
                    page_ids=[p.page_id for p in current_pages]
                )
                document.sections.append(section)
            
            # Update document status based on errors
            if document.errors:
                logger.warning(f"Document classified with {len(document.errors)} errors")
                # We still set status to CLASSIFIED even with errors since we have some results
                document.status = Status.CLASSIFIED
            else:
                document.status = Status.CLASSIFIED
            
            document.metering = utils.merge_metering_data(document.metering, combined_metering)
            
            t1 = time.time()
            logger.info(f"Document classified with {len(document.sections)} sections in {t1-t0:.2f} seconds")
        
        except Exception as e:
            error_msg = f"Error classifying document: {str(e)}"
            logger.error(error_msg)
            document.errors.append(error_msg)
            document.status = Status.FAILED
        
        return document
        
    def classify_pages(self, pages: Dict[str, Dict[str, Any]]) -> ClassificationResult:
        """
        Classify multiple pages concurrently.
        
        Args:
            pages: Dictionary of pages with their data
            
        Returns:
            ClassificationResult: Result with classified pages grouped into sections
        """
        all_results = []
        futures = []
        metering = {}
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            for page_num, page_data in pages.items():
                future = executor.submit(
                    self.classify_page,
                    page_id=page_num,
                    text_uri=page_data.get('parsedTextUri'),
                    image_uri=page_data.get('imageUri'),
                    raw_text_uri=page_data.get('rawTextUri')
                )
                futures.append(future)
            
            for future in as_completed(futures):
                try:
                    page_result = future.result()
                    page_metering = page_result.classification.metadata.get("metering", {})
                    all_results.append(page_result)
                    
                    # Merge metering data
                    metering = utils.merge_metering_data(metering, page_metering)
                except Exception as e:
                    logger.error(f"Error in concurrent classification: {str(e)}")
                    raise
        
        # Group pages into sections
        sections = self._group_consecutive_pages(all_results)
        
        # Create and return classification result
        return ClassificationResult(
            metadata={"metering": metering},
            sections=sections
        )

    def _group_consecutive_pages(self, results: List[PageClassification]) -> List[DocumentSection]:
        """
        Group consecutive pages with the same classification into sections.
        
        Args:
            results: List of page classification results
            
        Returns:
            List of document sections
        """
        try:
            sorted_results = sorted(results, key=lambda x: int(x.page_id))
        except (ValueError, TypeError):
            logger.warning("Unable to sort page IDs as integers, using string sort")
            sorted_results = sorted(results, key=lambda x: x.page_id)
            
        sections = []
        
        if not sorted_results:
            return sections
        
        current_group = 1
        current_type = sorted_results[0].classification.doc_type
        current_pages = [sorted_results[0]]
        
        for result in sorted_results[1:]:
            if result.classification.doc_type == current_type:
                current_pages.append(result)
            else:
                sections.append(DocumentSection(
                    section_id=str(current_group),
                    classification=DocumentClassification(
                        doc_type=current_type,
                        confidence=1.0  # Default confidence
                    ),
                    pages=current_pages
                ))
                current_group += 1
                current_type = result.classification.doc_type
                current_pages = [result]
        
        # Add the last section
        sections.append(DocumentSection(
            section_id=str(current_group),
            classification=DocumentClassification(
                doc_type=current_type,
                confidence=1.0  # Default confidence
            ),
            pages=current_pages
        ))
        
        return sections