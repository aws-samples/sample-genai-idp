"""
OCR Service for document processing with AWS Textract.

This module provides a service for extracting text from PDF documents
using AWS Textract, with support for concurrent processing of multiple pages.
"""

import boto3
import concurrent.futures
import io
import json
import logging
import os
import time
from typing import Dict, List, Tuple, Any, Optional, BinaryIO, Union
from botocore.config import Config

import fitz  # PyMuPDF

from idp_common import s3, utils
from idp_common.models import Document, Page, Status

logger = logging.getLogger(__name__)


class OcrService:
    """Service for OCR processing of documents using AWS Textract."""

    def __init__(
        self,
        region: Optional[str] = None,
        max_workers: int = 20,
        enhanced_features: Union[bool, List[str]] = False,
    ):
        """
        Initialize the OCR service.

        Args:
            region: AWS region for Textract service
            max_workers: Maximum number of concurrent workers for page processing
            enhanced_features: Controls Textract FeatureTypes for analyze_document API:
                           - If False: Uses basic detect_document_text (faster, no features)
                           - If List[str]: Uses analyze_document with specified features
                              Valid features: TABLES, FORMS, SIGNATURES, LAYOUT
        """
        self.region = region or os.environ.get('AWS_REGION', 'us-east-1')
        self.max_workers = max_workers
        self.enhanced_features = enhanced_features
        
        # Initialize Textract client with adaptive retries
        adaptive_config = Config(
            retries={'max_attempts': 100, 'mode': 'adaptive'},
            max_pool_connections=max_workers*3
        )
        self.textract_client = boto3.client(
            'textract', 
            region_name=self.region, 
            config=adaptive_config
        )
        
        # Initialize S3 client
        self.s3_client = boto3.client('s3')

    def process_document(self, document: Document) -> Document:
        """
        Process a PDF document with OCR and update the Document model.
        
        Args:
            document: Document model object to update with OCR results
            
        Returns:
            Updated Document object with OCR results
        """
        t0 = time.time()
        
        # Get the PDF from S3
        try:
            response = self.s3_client.get_object(
                Bucket=document.input_bucket, 
                Key=document.input_key
            )
            pdf_content = response['Body'].read()
            t1 = time.time()
            logger.info(f"Time taken for S3 GetObject: {t1-t0:.6f} seconds")
        except Exception as e:
            error_msg = f"Error retrieving document from S3: {str(e)}"
            logger.error(error_msg)
            document.errors.append(error_msg)
            document.status = Status.FAILED
            return document
        
        # Process the PDF content
        try:
            pdf_document = fitz.open(stream=pdf_content, filetype="pdf")
            num_pages = len(pdf_document)
            document.num_pages = num_pages
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_page = {
                    executor.submit(
                        self._process_single_page, 
                        i, 
                        pdf_document, 
                        document.output_bucket, 
                        document.input_key
                    ): i 
                    for i in range(num_pages)
                }
                
                for future in concurrent.futures.as_completed(future_to_page):
                    page_index = future_to_page[future]
                    page_id = str(page_index + 1)
                    try:
                        ocr_result, page_metering = future.result()
                        
                        # Create Page object and add to document
                        document.pages[page_id] = Page(
                            page_id=page_id,
                            image_uri=ocr_result["image_uri"],
                            raw_text_uri=ocr_result["raw_text_uri"],
                            parsed_text_uri=ocr_result["parsed_text_uri"]
                        )
                        
                        # Merge metering data
                        document.metering = utils.merge_metering_data(document.metering, page_metering)
                        
                    except Exception as e:
                        error_msg = f"Error processing page {page_index + 1}: {str(e)}"
                        logger.error(error_msg)
                        document.errors.append(error_msg)
            
            pdf_document.close()
            
            # If no errors occurred, mark as completed
            if not document.errors:
                document.status = Status.OCR_COMPLETED
            else:
                document.status = Status.FAILED
                
        except Exception as e:
            error_msg = f"Error processing document: {str(e)}"
            logger.error(error_msg)
            document.errors.append(error_msg)
            document.status = Status.FAILED
        
        t2 = time.time()
        logger.info(f"Total time for OCR processing: {t2-t0:.2f} seconds")
        return document

    def _feature_combo(self):
        """Return the pricing feature combination string based on enhanced_features.
        
        Returns one of: "Tables", "Forms", "Tables+Forms", "Signatures", "Layout", or ""
        
        Note:
        - Layout feature is included free with any combination of Forms, Tables
        - Signatures feature is included free with Forms, Tables, and Layout
        """
        if not isinstance(self.enhanced_features, list) or not self.enhanced_features:
            return ""
            
        features = set(self.enhanced_features)
        
        # Check for feature combinations
        has_tables = "TABLES" in features
        has_forms = "FORMS" in features
        has_layout = "LAYOUT" in features
        has_signatures = "SIGNATURES" in features
        
        # Tables + Forms
        if has_tables and has_forms:
            return "-Tables+Forms"
        # Tables only
        elif has_tables:
            return "-Tables"
        # Forms only
        elif has_forms:
            return "-Forms"
        # Layout (only charged if not with Forms/Tables)
        elif has_layout:
            return "-Layout"
        # Signatures (only charged if used alone)
        elif has_signatures:
            return "-Signatures"        
        return ""
    def _process_single_page(
        self, 
        page_index: int, 
        pdf_document: fitz.Document, 
        output_bucket: str, 
        prefix: str
    ) -> Tuple[Dict[str, str], Dict[str, Any]]:
        """
        Process a single page of a PDF document.

        Args:
            page_index: Zero-based index of the page
            pdf_document: PyMuPDF document object
            output_bucket: S3 bucket to store results
            prefix: S3 prefix for storing results

        Returns:
            Tuple of (page_result_dict, metering_data)
        """
        t0 = time.time()
        page_id = page_index + 1
        
        # Extract page image
        page = pdf_document.load_page(page_index)
        pix = page.get_pixmap()
        img_bytes = pix.tobytes("jpeg")
        
        # Upload image to S3
        image_key = f"{prefix}/pages/{page_id}/image.jpg"
        s3.write_content(
            img_bytes, 
            output_bucket, 
            image_key, 
            content_type='image/jpeg'
        )
        
        t1 = time.time()
        logger.info(f"Time for image conversion (page {page_id}): {t1-t0:.6f} seconds")
        
        # Process with Textract
        if isinstance(self.enhanced_features, list) and self.enhanced_features:
            textract_result = self._analyze_document(img_bytes)
        else:
            textract_result = self.textract_client.detect_document_text(
                Document={"Bytes": img_bytes}
            )
        
        
        # Extract metering data
        feature_combo = self._feature_combo()
        metering = {
            f"textract/{self._get_api_name()}{feature_combo}": {
                "pages": textract_result["DocumentMetadata"]["Pages"]
            }
        }
        
        # Store raw Textract response
        raw_text_key = f"{prefix}/pages/{page_id}/rawText.json"
        s3.write_content(
            textract_result, 
            output_bucket, 
            raw_text_key, 
            content_type='application/json'
        )
        
        # Parse and store text content with markdown
        parsed_result = self._parse_textract_response(textract_result)
        parsed_text_key = f"{prefix}/pages/{page_id}/result.json"
        s3.write_content(
            parsed_result, 
            output_bucket, 
            parsed_text_key, 
            content_type='application/json'
        )
        
        t2 = time.time()
        logger.info(f"Time for Textract (page {page_id}): {t2-t1:.6f} seconds")
        
        # Create and return page result
        result = {
            "raw_text_uri": f"s3://{output_bucket}/{raw_text_key}",
            "parsed_text_uri": f"s3://{output_bucket}/{parsed_text_key}",
            "image_uri": f"s3://{output_bucket}/{image_key}"
        }
        
        return result, metering
    
    def _analyze_document(self, document_bytes: bytes) -> Dict[str, Any]:
        """
        Analyze document using enhanced Textract features.

        Args:
            document_bytes: Binary content of the document image

        Returns:
            Textract API response
        """
        # Use specified feature types
        # Valid types are TABLES, FORMS, SIGNATURES, and LAYOUT
        # Note: QUERIES is not supported as it requires additional parameters
        response = self.textract_client.analyze_document(
            Document={"Bytes": document_bytes},
            FeatureTypes=self.enhanced_features
        )
        return response
    
    def _get_api_name(self) -> str:
        """Get the name of the Textract API being used."""
        # If enhanced_features is a non-empty list, we're using analyze_document
        # Otherwise, we're using detect_document_text
        return "analyze_document" if isinstance(self.enhanced_features, list) and self.enhanced_features else "detect_document_text"
    
    def _parse_textract_response(self, response: Dict[str, Any]) -> Dict[str, str]:
        """
        Parse Textract response into text and markdown.

        Uses textractor to extract both plain text and rich markdown format.
        The markdown format preserves tables, forms, and layout information.
        
        Args:
            response: Raw Textract API response

        Returns:
            Dictionary with 'text' (plain text) and 'markdown' (formatted text) keys
        """
        # Use textractor for parsing
        from textractor.parsers import response_parser
        parsed_response = response_parser.parse(response)
        
        # Extract markdown representation if available
        try:
            text = parsed_response.to_markdown()
        except (AttributeError, Exception) as e:
            # If markdown extraction fails, use plain text instead
            plain_text = parsed_response.text
            text = plain_text
            logger.warning(f"Failed to generate markdown - using plain text: {str(e)}")
        
        return {
            "text": text,
        }