# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import os
import boto3
import logging
from datetime import datetime, timezone

# Import IDP Common modules
from idp_common.models import Document, Section, Status
from idp_common.docs_service import create_document_service

logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

# Initialize AWS clients
s3_client = boto3.client('s3')
sqs_client = boto3.client('sqs')

# Environment variables
QUEUE_URL = os.environ.get('QUEUE_URL')

def handler(event, context):
    logger.info(f"ProcessChanges resolver invoked with event: {json.dumps(event)}")
    
    # Add comprehensive error handling
    try:
        # Extract arguments from the GraphQL event
        args = event.get('arguments', {})
        logger.info(f"Arguments received: {json.dumps(args)}")
        
        object_key = args.get('objectKey')
        modified_sections = args.get('modifiedSections', [])
        
        if not object_key:
            logger.error("objectKey is required but not provided")
            return {
                'success': False,
                'message': 'objectKey is required',
                'processingJobId': None
            }
        
        if not modified_sections:
            logger.error("modifiedSections is required but not provided")
            return {
                'success': False,
                'message': 'modifiedSections is required',
                'processingJobId': None
            }

        logger.info(f"Processing changes for document: {object_key}")
        logger.info(f"Modified sections: {json.dumps(modified_sections)}")

        # Use DynamoDB service to get the document (only service that supports get_document)
        try:
            dynamodb_service = create_document_service(mode='dynamodb')
            document = dynamodb_service.get_document(object_key)  # Returns Document object directly
            
            if not document:
                raise ValueError(f"Document {object_key} not found")
            
            # Set bucket names from environment variables (fix for null bucket issue)
            input_bucket = os.environ.get('INPUT_BUCKET')
            output_bucket = os.environ.get('OUTPUT_BUCKET')
            document.input_bucket = input_bucket
            document.output_bucket = output_bucket
            logger.info(f"Set document buckets - input_bucket: {input_bucket}, output_bucket: {output_bucket}")
            
            logger.info(f"Found document: {document.id}")
            
        except Exception as e:
            logger.error(f"Error retrieving document {object_key}: {str(e)}")
            raise ValueError(f"Document {object_key} not found or error retrieving: {str(e)}")

        # Track modified section IDs for selective processing
        modified_section_ids = []
        
        # Process each modification
        for modified_section in modified_sections:
            section_id = modified_section['sectionId']
            classification = modified_section['classification']
            page_ids = [int(pid) for pid in modified_section['pageIds']]  # Ensure integer page IDs
            is_new = modified_section.get('isNew', False)
            is_deleted = modified_section.get('isDeleted', False)
            
            if is_deleted:
                # Find section to delete BEFORE removing it
                section_to_delete = None
                for s in document.sections:
                    if s.section_id == section_id:
                        section_to_delete = s
                        break
                
                if section_to_delete:
                    # Clear S3 extraction data before removing section
                    if section_to_delete.extraction_result_uri:
                        clear_extraction_data(section_to_delete.extraction_result_uri)
                        logger.info(f"Cleared extraction data for deleted section: {section_id}")
                    
                    # Remove section from document
                    document.sections = [s for s in document.sections if s.section_id != section_id]
                    logger.info(f"Deleted section: {section_id}")
                else:
                    logger.warning(f"Section {section_id} marked for deletion but not found")
                        
                continue
            
            elif is_new:
                # Create new section (don't search for existing)
                logger.info(f"Creating new section: {section_id}")
                new_section = Section(
                    section_id=section_id,
                    classification=classification,
                    confidence=1.0,
                    page_ids=[str(pid) for pid in page_ids],
                    extraction_result_uri=None,
                    attributes=None,
                    confidence_threshold_alerts=[]
                )
                document.sections.append(new_section)
                
            else:
                # Update existing section
                existing_section = None
                for section in document.sections:
                    if section.section_id == section_id:
                        existing_section = section
                        break
                
                if existing_section:
                    logger.info(f"Updating existing section: {section_id}")
                    existing_section.classification = classification
                    existing_section.page_ids = [str(pid) for pid in page_ids]
                    
                    # Clear extraction data for reprocessing
                    if existing_section.extraction_result_uri:
                        clear_extraction_data(existing_section.extraction_result_uri)
                        existing_section.extraction_result_uri = None
                        existing_section.attributes = None
                    
                    # Clear confidence threshold alerts for modified sections
                    existing_section.confidence_threshold_alerts = []
                    logger.info(f"Cleared confidence alerts for modified section: {section_id}")
                else:
                    logger.warning(f"Section {section_id} marked as update but not found - treating as new")
                    # Treat as new section if not found
                    new_section = Section(
                        section_id=section_id,
                        classification=classification,
                        confidence=1.0,
                        page_ids=[str(pid) for pid in page_ids],
                        extraction_result_uri=None,
                        attributes=None,
                        confidence_threshold_alerts=[]
                    )
                    document.sections.append(new_section)
            
            # Only add to modified list if not deleted
            modified_section_ids.append(section_id)
            
            # Update page classifications to match section classification (only if not deleted)
            for page_id in page_ids:
                page_id_str = str(page_id)
                if page_id_str in document.pages:
                    document.pages[page_id_str].classification = classification
                    logger.info(f"Updated page {page_id} classification to {classification}")

        # Update document status and timing - reset for reprocessing
        current_time = datetime.now(timezone.utc).isoformat()
        document.status = Status.QUEUED
        document.initial_event_time = document.queued_time or current_time
        document.start_time = None
        document.completion_time = None
        document.workflow_execution_arn = None

        # Sort sections by starting page ID
        document.sections.sort(key=lambda s: min([int(pid) for pid in s.page_ids] + [float('inf')]))

        logger.info(f"Document updated with {len(document.sections)} sections and {len(document.pages)} pages")

        # Log uncompressed document for troubleshooting
        uncompressed_document_json = json.dumps(document.to_dict(), default=str)
        logger.info(f"Uncompressed document (size: {len(uncompressed_document_json)} chars): {uncompressed_document_json}")

        # NOTE: We intentionally do NOT write the document back to the database here.
        # The processing pipeline will handle document updates via AppSync as it processes.
        # This avoids race conditions and ensures consistent state management.

        # Compress document before sending to SQS for large document optimization
        working_bucket = os.environ.get('WORKING_BUCKET')
        if working_bucket:
            # Use document compression (always compress with 0KB threshold)
            sqs_message_content = document.serialize_document(working_bucket, "process_changes", logger)
            logger.info(f"Document compressed for SQS (always compress)")
        else:
            # Fallback to direct document dict if no working bucket
            sqs_message_content = document.to_dict()
            logger.warning("No WORKING_BUCKET configured, sending uncompressed document")

        # Log the SQS message for debugging
        message_body = json.dumps(sqs_message_content, default=str)
        logger.info(f"SQS message prepared (size: {len(message_body)} chars)")
        logger.info(f"SQS message content: {message_body}")
        logger.info(f"Modified sections will be reprocessed: {modified_section_ids}")

        if QUEUE_URL:
            response = sqs_client.send_message(
                QueueUrl=QUEUE_URL,
                MessageBody=message_body
            )
            
            logger.info(f"Sent document to SQS queue. MessageId: {response.get('MessageId')}")
            processing_job_id = response.get('MessageId')
        else:
            logger.warning("QUEUE_URL not configured, skipping SQS message")
            processing_job_id = None

        # Use AppSync service for immediate UI status update
        try:
            appsync_service = create_document_service(mode='appsync')
            document.status = Status.QUEUED  # Ensure status is QUEUED for UI
            updated_document = appsync_service.update_document(document)
            logger.info(f"Updated document status to QUEUED in AppSync for immediate UI feedback")
        except Exception as e:
            logger.warning(f"Failed to update document status in AppSync: {str(e)}")
            # Don't fail the entire operation if AppSync update fails

        # Log successful completion
        logger.info(f"Successfully processed changes for {len(modified_sections)} sections")
        
        response = {
            'success': True,
            'message': f'Successfully processed changes for {len(modified_sections)} sections',
            'processingJobId': processing_job_id
        }
        
        logger.info(f"Returning response: {json.dumps(response)}")
        return response

    except Exception as e:
        logger.error(f"Error processing changes: {str(e)}", exc_info=True)
        
        error_response = {
            'success': False,
            'message': f'Error processing changes: {str(e)}',
            'processingJobId': None
        }
        
        logger.error(f"Returning error response: {json.dumps(error_response)}")
        return error_response

def clear_extraction_data(s3_uri):
    """Clear extraction data from S3"""
    try:
        if not s3_uri or not s3_uri.startswith('s3://'):
            return
            
        # Parse S3 URI
        parts = s3_uri.replace('s3://', '').split('/', 1)
        if len(parts) != 2:
            return
            
        bucket, key = parts
        
        # Delete the object
        s3_client.delete_object(Bucket=bucket, Key=key)
        logger.info(f"Cleared extraction data: {s3_uri}")
        
    except Exception as e:
        logger.warning(f"Failed to clear extraction data {s3_uri}: {str(e)}")
