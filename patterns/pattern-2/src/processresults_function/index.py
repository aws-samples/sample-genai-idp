# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import logging
import datetime
import os
import boto3
import random
import string
from urllib.parse import urlparse
from decimal import Decimal

from idp_common import s3, utils
from idp_common.models import Document, Page, Section, Status, HitlMetadata
from idp_common.docs_service import create_document_service
from idp_common.config import get_config

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logging.getLogger('idp_common.bedrock.client').setLevel(os.environ.get("BEDROCK_LOG_LEVEL", "INFO"))
# Get LOG_LEVEL from environment variable with INFO as default

# Initialize AWS clients
s3_client = boto3.client('s3')
ssm_client = boto3.client('ssm')
enable_hitl = os.environ.get('ENABLE_HITL', 'false').lower()
SAGEMAKER_A2I_REVIEW_PORTAL_URL = os.environ.get('SAGEMAKER_A2I_REVIEW_PORTAL_URL', '')

def get_confidence_threshold_from_config(document: Document) -> float:
    """
    Get the HITL confidence threshold from configuration.
    
    Args:
        document (Document): The document object containing configuration
        
    Returns:
        float: The confidence threshold as a decimal (0.0-1.0)
    """
    try:
        config = get_config()
        threshold_value = float(config['assessment']['default_confidence_threshold'])
        
        # Validate that the threshold is in the expected 0.0-1.0 range
        if threshold_value < 0.0 or threshold_value > 1.0:
            logger.warning(f"Invalid confidence threshold value {threshold_value}. Must be between 0.0 and 1.0. Using default: 0.70")
            return 0.70
            
        logger.info(f"Retrieved confidence threshold from configuration: {threshold_value}")
        return threshold_value
    except Exception as e:
        logger.warning(f"Failed to retrieve confidence threshold from configuration: {e}")
        # Return default value of 70% (0.70) if configuration is not available
        logger.info("Using default confidence threshold: 0.70")
        return 0.70

def generate_random_string(length: int) -> str:
    """Generate a random alphanumeric string of specified length."""
    characters = string.ascii_letters + string.digits
    return ''.join(random.choices(characters, k=length))

def start_human_loop(
    execution_id: str,
    kv_pairs: list,
    source_image_uri: str,
    bounding_boxes: list,
    section_id: str,
    section_classification: str,
    confidence_threshold: float,
    page_ids: list,
    section_page_number: int,
    output_bucket: str,
    document_id: str
) -> dict:
    """
    Start a SageMaker A2I human review loop for fields on a specific page.
    """
    a2i_runtime_client = boto3.client('sagemaker-a2i-runtime')
    
    logger.info(f"Starting A2I for section {section_id}, page {page_ids[0] if page_ids else 'unknown'}")
    
    human_loop_input = {
        "sourceDocument": source_image_uri,
        "keyValuePairs": kv_pairs,
        "boundingBoxes": bounding_boxes,
        "confidenceThreshold": confidence_threshold,
        "record_id": section_id,
        "blueprintName": section_classification,
        "page_ids": page_ids,
        "execution_id": execution_id,
        "page_number": section_page_number,
        # S3 metadata for EventBridge processing
        "s3Bucket": output_bucket,
        "documentId": document_id,
        "sectionId": section_id
    }
    
    logger.info(f"Human loop input structure: {json.dumps(human_loop_input, indent=2, default=str)}")
    
    try:
        FlowDefinitionArn = ssm_client.get_parameter(
            Name=f"/{os.environ.get('METRIC_NAMESPACE', 'IDP')}/FlowDefinitionArn"
        )['Parameter']['Value']
        
        # Generate 2-digit unique value
        unique_value = generate_random_string(2)
        response = a2i_runtime_client.start_human_loop(
            HumanLoopName=f"review-section-{unique_value}-{execution_id}-{section_id}-{section_page_number}",
            FlowDefinitionArn=FlowDefinitionArn,
            HumanLoopInput={"InputContent": json.dumps(human_loop_input)}
        )
        logger.info(f"Started human loop: {response['HumanLoopArn']}")
        return response
    except Exception as e:
        logger.error(f"Error starting human loop: {str(e)}")
        raise

def extract_all_fields_from_explainability(explainability_info: list, page_id: str) -> list:
    """
    Extract all fields from explainability_info for a specific page.
    
    Args:
        explainability_info: List of explainability data from section
        page_id: Page ID to filter fields for
        
    Returns:
        List of field dictionaries with name, confidence, geometry, etc.
    """
    fields = []
    
    def extract_fields_recursive(data: dict, current_path: str = '', page_filter: str = None):
        for key, value in data.items():
            new_path = f"{current_path}.{key}" if current_path else key
            
            if isinstance(value, dict):
                # Check if this is a field with confidence (leaf node)
                if 'confidence' in value:
                    # Check if this field belongs to the specified page
                    field_page = None
                    geometry = value.get('geometry', [])
                    if geometry and len(geometry) > 0:
                        field_page = str(geometry[0].get('page', ''))
                    
                    # Include field if no page filter or if it matches the page (handle both string and int comparison)
                    if page_filter is None or field_page == page_filter or field_page == str(page_filter):
                        fields.append({
                            'name': new_path,
                            'confidence': value.get('confidence', 0.0),
                            'confidence_threshold': value.get('confidence_threshold'),  # Can be None
                            'geometry': geometry,
                            'page': field_page
                        })
                else:
                    # Recurse into nested structure
                    extract_fields_recursive(value, new_path, page_filter)
            elif isinstance(value, list):
                # Handle arrays (like FederalTaxes, StateTaxes, etc.)
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        extract_fields_recursive(item, f"{new_path}[{i}]", page_filter)
    
    # Handle both list of dicts and single dict structures
    if explainability_info:
        if isinstance(explainability_info[0], dict):
            extract_fields_recursive(explainability_info[0], '', page_id)
        else:
            for item in explainability_info:
                if isinstance(item, dict):
                    extract_fields_recursive(item, '', page_id)
    
    return fields

def extract_field_value(inference_result: dict, field_name: str):
    """
    Extract field value from inference_result using dot notation.
    Handles nested fields like 'CompanyAddress.Line2' and array notation like 'FederalTaxes[0].YTD'
    """
    # Handle array notation
    import re
    parts = []
    current_part = ""
    i = 0
    
    while i < len(field_name):
        if field_name[i] == '.':
            if current_part:
                parts.append(current_part)
                current_part = ""
        elif field_name[i] == '[':
            if current_part:
                parts.append(current_part)
                current_part = ""
            # Find the closing bracket
            j = i + 1
            while j < len(field_name) and field_name[j] != ']':
                j += 1
            if j < len(field_name):
                array_index = field_name[i+1:j]
                parts.append(f"[{array_index}]")
                i = j
        else:
            current_part += field_name[i]
        i += 1
    
    if current_part:
        parts.append(current_part)
    
    current = inference_result
    
    for part in parts:
        if part.startswith('[') and part.endswith(']'):
            # Array index
            try:
                index = int(part[1:-1])
                if isinstance(current, list) and 0 <= index < len(current):
                    current = current[index]
                else:
                    return None
            except (ValueError, TypeError):
                return None
        else:
            # Regular key
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
    
    return current

def process_section_for_hitl(section: Section, section_data: dict, confidence_threshold: float, execution_id: str, document_id: str) -> bool:
    """
    Process a section to determine if A2I should be triggered and start human loops for each page.
    Creates separate A2I tasks for each page in the section.
    
    Args:
        section: Section object
        section_data: Section extraction result data from S3
        confidence_threshold: Confidence threshold to check against
        execution_id: Execution ID for tracking
        document_id: Document ID from the event
        
    Returns:
        bool: True if any A2I was triggered, False otherwise
    """
    if not section.confidence_threshold_alerts:
        logger.info(f"No confidence threshold alerts for section {section.section_id}")
        return False
        
    logger.info(f"Section {section.section_id} has {len(section.confidence_threshold_alerts)} confidence threshold alerts")
    
    # Extract explainability_info
    explainability_info = section_data.get('explainability_info', [])
    if not explainability_info:
        logger.warning(f"No explainability_info found for section {section.section_id}")
        return False
    
    inference_result = section_data.get('inference_result', {})
    any_hitl_triggered = False
    
    # Extract output bucket from section extraction_result_uri, use document_id from event
    uri_parts = section.extraction_result_uri.split('/')
    output_bucket = uri_parts[2] if len(uri_parts) >= 3 else os.environ.get('OUTPUT_BUCKET', '')
    
    # Process each page in the section separately with reset page numbering
    section_page_number = 1
    for page_id in section.page_ids:
        logger.info(f"Processing page {page_id} for section {section.section_id} (section page number: {section_page_number})")
        
        # Extract all fields for this specific page using section-relative page number
        page_fields = extract_all_fields_from_explainability(explainability_info, str(section_page_number))
        
        # Build key-value pairs and bounding boxes for all fields on this page
        kv_pairs = []
        bounding_boxes = []
        
        if page_fields:
            logger.info(f"Found {len(page_fields)} fields for page {page_id}")
            
            # Count fields with and without specific thresholds for logging
            fields_with_threshold = sum(1 for f in page_fields if f.get('confidence_threshold') is not None and f.get('confidence_threshold') != 0)
            fields_without_threshold = len(page_fields) - fields_with_threshold
            logger.info(f"Page {page_id}: {fields_with_threshold} fields with specific thresholds, {fields_without_threshold} using config threshold ({confidence_threshold})")
            
            for field in page_fields:
                field_name = field['name']
                confidence = field['confidence']
                # Use field-specific confidence threshold if available, otherwise use config threshold
                field_confidence_threshold = field.get('confidence_threshold')
                if field_confidence_threshold is None or field_confidence_threshold == 0:
                    confidence_threshold_val = confidence_threshold  # Use config threshold
                    logger.debug(f"Field {field_name} using config threshold: {confidence_threshold}")
                else:
                    confidence_threshold_val = field_confidence_threshold
                    logger.debug(f"Field {field_name} using field-specific threshold: {confidence_threshold_val}")
                
                geometry = field['geometry']
                
                # Extract field value from inference_result
                field_value = extract_field_value(inference_result, field_name)
                
                kv_pairs.append({
                    'key': field_name,
                    'value': str(field_value) if field_value is not None else '',
                    'confidence': confidence,
                    'confidence_threshold': confidence_threshold_val
                })
                
                # Extract bounding box if available
                if geometry and len(geometry) > 0:
                    bbox = geometry[0].get('boundingBox', {})
                    bounding_boxes.append({
                        'key': field_name,
                        'bounding_box': {
                            'top': bbox.get('top', 0),
                            'left': bbox.get('left', 0),
                            'width': bbox.get('width', 0),
                            'height': bbox.get('height', 0)
                        }
                    })
                else:
                    # Add empty bounding box to maintain index alignment
                    bounding_boxes.append({
                        'key': field_name,
                        'bounding_box': {
                            'top': 0,
                            'left': 0,
                            'width': 0,
                            'height': 0
                        }
                    })
        else:
            logger.warning(f"No fields found for page {page_id} in section {section.section_id}")
            # Create a placeholder entry to ensure A2I is still triggered for this page
            kv_pairs.append({
                'key': 'page_review_required',
                'value': f'No fields found for page {page_id} in section {section.section_id}',
                'confidence': 0.0,
                'confidence_threshold': confidence_threshold
            })
            bounding_boxes.append({
                'key': 'page_review_required',
                'bounding_box': {
                    'top': 0,
                    'left': 0,
                    'width': 1.0,
                    'height': 1.0
                }
            })
        
        logger.info(f"Prepared {len(kv_pairs)} key-value pairs for page {page_id}")
        
        # Create source image URI for this specific page
        source_image_uri = f"s3://{output_bucket}/{document_id}/pages/{page_id}/image.jpg"
        
        try:
            response = start_human_loop(
                execution_id=execution_id,
                kv_pairs=kv_pairs,
                source_image_uri=source_image_uri,
                bounding_boxes=bounding_boxes,
                section_id=section.section_id,
                section_classification=section.classification,
                confidence_threshold=confidence_threshold,
                page_ids=[page_id],  # Single page for this A2I task
                section_page_number=section_page_number,  # Use section-relative page number
                output_bucket=output_bucket,
                document_id=document_id
            )
            logger.info(f"Successfully triggered A2I for section {section.section_id}, page {page_id} (section page {section_page_number})")
            any_hitl_triggered = True
        except Exception as e:
            logger.error(f"Failed to trigger A2I for section {section.section_id}, page {page_id}: {str(e)}")
        
        # Increment section page number for next iteration
        section_page_number += 1
    
    return any_hitl_triggered

def handler(event, context):
    """
    Consolidates the results from multiple extraction steps into a single output.
    
    Args:
        event: Contains the document metadata and extraction results array
        context: Lambda context
        
    Returns:
        Dict containing the fully processed document
    """
    logger.info(f"Processing event: {json.dumps(event)}")
    
    # Get the base document from the original classification result - handle both compressed and uncompressed
    working_bucket = os.environ.get('WORKING_BUCKET')
    classification_document_data = event.get("ClassificationResult", {}).get("document", {})
    document = Document.load_document(classification_document_data, working_bucket, logger)
    
    extraction_results = event.get("ExtractionResults", [])
    execution_arn = event.get("execution_arn", "")
    execution_id = execution_arn.split(':')[-1] if execution_arn else "unknown"
    
    # Get confidence threshold from configuration
    confidence_threshold = get_confidence_threshold_from_config(document)
    logger.info(f"Using confidence threshold: {confidence_threshold}")
    
    # Update document status to POSTPROCESSING
    document.status = Status.POSTPROCESSING
    document_service = create_document_service()
    logger.info(f"Updating document status to {document.status}")
    document_service.update_document(document)
    
    # Clear sections list to rebuild from extraction results
    document.sections = []
    validation_errors = []
    validation_errors = []
    hitl_triggered = False
    
    # Combine all section results
    for i, result in enumerate(extraction_results):
        # New optimized format - document is at the top level
        document_data = result.get("document", {})
        section_document = Document.load_document(document_data, working_bucket, logger)
        logger.info(f"section_document: {section_document}")
        if section_document:       
            # Add section to document if present
            if section_document.sections:
                section = section_document.sections[0]
                logger.info(f"section: {section}")
                document.sections.append(section)
                
                # Check if A2I should be triggered for this section
                if enable_hitl == 'true' and section.confidence_threshold_alerts:
                    logger.info(f"Checking A2I trigger for section {section.section_id} with {len(section.confidence_threshold_alerts)} alerts")
                    logger.info(f"Processing section {section.section_id} for HITL with confidence threshold {confidence_threshold}")
                    logger.info(f"Section confidence threshold alerts: {section.confidence_threshold_alerts}")
                    
                    # Download section data to get explainability_info
                    try:
                        # Parse S3 URI to get bucket and key
                        from urllib.parse import urlparse
                        parsed_uri = urlparse(section.extraction_result_uri)
                        section_bucket = parsed_uri.netloc
                        section_key = parsed_uri.path.lstrip('/')
                        
                        # Download section data
                        section_obj = s3_client.get_object(Bucket=section_bucket, Key=section_key)
                        section_data = json.loads(section_obj['Body'].read().decode('utf-8'))
                        
                        # Process section for HITL (creates A2I tasks for each page)
                        section_hitl_triggered = process_section_for_hitl(
                            section, section_data, confidence_threshold, execution_id, document.id
                        )
                        
                        if section_hitl_triggered:
                            hitl_triggered = True
                            logger.info(f"A2I triggered for section {section.section_id}")
                            
                            # Create ONE HITL metadata entry per section (like Pattern-1)
                            # Include all pages in the section that triggered HITL
                            section_page_numbers = list(range(1, len(section.page_ids) + 1))
                            hitl_metadata = HitlMetadata(
                                execution_id=execution_id,
                                record_number=int(section.section_id),  # Use actual section ID
                                bp_match=True,
                                extraction_bp_name=section.classification,
                                hitl_triggered=True,
                                page_array=section_page_numbers,  # All pages in this section
                                review_portal_url=SAGEMAKER_A2I_REVIEW_PORTAL_URL
                            )
                            document.hitl_metadata.append(hitl_metadata)
                        
                    except Exception as e:
                        logger.error(f"Error processing A2I for section {section.section_id}: {str(e)}")
                
                # Create metadata file for section output
                if section.extraction_result_uri:
                    create_metadata_file(section.extraction_result_uri, section.classification, 'section')

                if section_document.status == Status.FAILED:
                    error_message = (f"Processing failed for section {i + 1}: "
                                     f"{'; '.join(section_document.errors)}")
                    validation_errors.append(error_message)
                    logger.error(f"Error: {error_message}")
            
            # Add metering from section processing
            document.metering = utils.merge_metering_data(document.metering, section_document.metering)
    
    # Create metadata files for pages
    for page_id, page in document.pages.items():
        if page.raw_text_uri:
            create_metadata_file(page.raw_text_uri, page.classification, 'page')
    
    # Update document status based on HITL requirement
    if hitl_triggered:
        # Set status to HITL_IN_PROGRESS when HITL is triggered
        document.status = Status.HITL_IN_PROGRESS
        logger.info(f"Document requires human review, setting status to {document.status}")
    # else:
    #     # Only mark as POSTPROCESSING if no human review is needed
    #     document.status = Status.POSTPROCESSING
    #     document.completion_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
    #     logger.info(f"Document processing complete, setting status to {document.status}")
    
    # Update final status in AppSync / Document Service
    logger.info(f"Updating document status to {document.status}")
    document_service.update_document(document)
    
    # Return the completed document with compression
    response = {
        "document": document.serialize_document(working_bucket, "processresults", logger),
        "hitl_triggered": hitl_triggered
    }
    
    logger.info(f"Response: {json.dumps(response, default=str)}")

    if document.errors:
        validation_errors.extend(document.errors)

    # Raise exception if there were validation errors
    if validation_errors:
        document.status = Status.FAILED
        # Create comprehensive error message
        error_summary = f"Processing failed for {len(validation_errors)} out of {len(extraction_results)} sections"
        combined_errors = '; '.join(validation_errors)
        full_error_message = f"{error_summary}: {combined_errors}"
        logger.error(f"Error: {full_error_message}")
        raise Exception(full_error_message)

    return response

def create_metadata_file(file_uri, class_type, file_type=None):
    """
    Creates a metadata file alongside the given URI file with the same name plus '.metadata.json'
    """
    try:
        # Parse the S3 URI to get bucket and key
        parsed_uri = urlparse(file_uri)
        bucket = parsed_uri.netloc
        key = parsed_uri.path.lstrip('/')
        
        # Create the metadata key by adding '.metadata.json' to the original key
        metadata_key = f"{key}.metadata.json"
        
        # Determine the file type if not provided
        if file_type is None:
            if key.endswith('.json'):
                file_type = 'section'
            else:
                file_type = 'page'
        
        # Create metadata content
        metadata_content = {
            "metadataAttributes": {
                "DateTime": datetime.datetime.now().isoformat(),
                "Class": class_type,
                "FileType": file_type
            }
        }
        
        # Upload metadata file to S3 using common library
        s3.write_content(metadata_content, bucket, metadata_key, content_type='application/json')
        
        logger.info(f"Created metadata file at s3://{bucket}/{metadata_key}")
    except Exception as e:
        logger.error(f"Error creating metadata file for {file_uri}: {str(e)}")