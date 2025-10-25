# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0


import os
import json
import time
import logging
import boto3
import uuid
from datetime import datetime
from decimal import Decimal

from idp_common import metrics, get_config, extraction
from idp_common.models import Document, Status
from idp_common.docs_service import create_document_service
from idp_common.utils import calculate_lambda_metering, merge_metering_data

# Configuration will be loaded in handler function

OCR_TEXT_ONLY = os.environ.get("OCR_TEXT_ONLY", "false").lower() == "true"
EXTRACTION_RESULTS_TABLE = os.environ.get("EXTRACTION_RESULTS_TABLE")

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logging.getLogger("idp_common.bedrock.client").setLevel(
    os.environ.get("BEDROCK_LOG_LEVEL", "INFO")
)

# Initialize DynamoDB client (lazy initialization to avoid issues in non-Lambda environments)
dynamodb = None
extraction_table = None


def get_dynamodb_table():
    """Lazy initialization of DynamoDB table"""
    global dynamodb, extraction_table
    if extraction_table is None and EXTRACTION_RESULTS_TABLE:
        dynamodb = boto3.resource('dynamodb')
        extraction_table = dynamodb.Table(EXTRACTION_RESULTS_TABLE)
    return extraction_table


def convert_floats_to_decimals(obj):
    """Recursively convert float values to Decimal for DynamoDB compatibility"""
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: convert_floats_to_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_floats_to_decimals(item) for item in obj]
    return obj


def write_extraction_to_dynamodb(section_document, section_id, extraction_result_uri):
    """
    Write generic extraction results to DynamoDB for querying.

    This provides a fallback for non-invoice documents, storing structured
    extraction data in DynamoDB for consistent querying across all document types.
    """
    table = get_dynamodb_table()
    if not table:
        logger.warning("EXTRACTION_RESULTS_TABLE not configured - skipping DynamoDB write")
        return 0

    try:
        # Extract section from document
        section = section_document.sections[0] if section_document.sections else None
        if not section:
            logger.warning(f"No section found in document for section_id {section_id}")
            return 0

        # Download extraction result from S3 to get inference_result
        inference_result = {}
        if extraction_result_uri:
            try:
                from urllib.parse import urlparse
                import boto3

                s3_client = boto3.client('s3')
                parsed_uri = urlparse(extraction_result_uri)
                bucket = parsed_uri.netloc
                key = parsed_uri.path.lstrip('/')

                s3_obj = s3_client.get_object(Bucket=bucket, Key=key)
                extraction_data = json.loads(s3_obj['Body'].read().decode('utf-8'))
                inference_result = extraction_data.get('inference_result', {})

                logger.info(f"Retrieved inference_result with {len(inference_result)} fields from S3")
            except Exception as e:
                logger.warning(f"Failed to retrieve extraction data from S3: {str(e)}")

        if not inference_result:
            logger.info("No inference_result found - skipping DynamoDB write")
            return 0

        # Extract metadata from document
        user_id = section_document.user_id or "unknown"
        client_id = section_document.client_id or "unknown"
        document_id = section_document.id
        document_type = section.classification or "UNKNOWN"

        # Generate unique extraction ID
        extraction_id = str(uuid.uuid4())
        timestamp = int(datetime.now().timestamp())

        # Build partition and sort keys (user-scoped schema)
        pk = f"user#{user_id}#doc#{document_id}"
        sk = f"type#{document_type}#section#{section_id}"

        # Build GSI keys
        gsi1_pk = f"user#{user_id}#type#{document_type}"
        gsi3_pk = f"company#{client_id}#type#{document_type}"
        gsi6_pk = f"client#{client_id}#type#{document_type}"

        # Convert floats to Decimals for DynamoDB
        inference_result_converted = convert_floats_to_decimals(inference_result)

        # Build DynamoDB item
        item = {
            # Primary key
            'PK': pk,
            'SK': sk,

            # Core identifiers
            'ExtractionId': extraction_id,
            'UserId': user_id,
            'ClientId': client_id,
            'DocumentId': document_id,
            'SectionId': section_id,
            'DocumentType': document_type,

            # Extraction data (flattened inference_result)
            'ExtractionData': inference_result_converted,

            # Metadata
            'ExtractionResultUri': extraction_result_uri,
            'ProcessedAt': timestamp,
            'ExtractionStatus': 'COMPLETED',
            'SectionPages': section.page_ids if section.page_ids else [],
            'PageCount': len(section.page_ids) if section.page_ids else 0,

            # GSI keys for querying
            'GSI1PK': gsi1_pk,  # User + Type queries
            'GSI3PK': gsi3_pk,  # Company + Type queries
            'GSI4PK': f"doc#{document_id}",  # Document-centric queries
            'GSI5PK': 'COMPLETED',  # Status monitoring
            'GSI6PK': gsi6_pk,  # Client reporting

            # Timestamps
            'CreatedAt': timestamp,
            'UpdatedAt': timestamp
        }

        # Write to DynamoDB
        table.put_item(Item=item)

        logger.info(f"✅ Wrote extraction result to DynamoDB: {pk} / {sk}")
        logger.info(f"   Document Type: {document_type}, Fields: {len(inference_result)}")

        return 1

    except Exception as e:
        logger.error(f"❌ Failed to write extraction to DynamoDB: {str(e)}")
        logger.error(f"   Error details: {type(e).__name__}")
        return 0


def handler(event, context):
    """
    Process a single section of a document for information extraction
    """
    start_time = time.time()  # Capture start time for Lambda metering
    logger.info(f"Event: {json.dumps(event)}")

    # Load configuration
    config = get_config()
    logger.info(f"Config: {json.dumps(config, default=str)}")

    # For Map state, we get just one section from the document
    # Extract the document and section from the event - handle both compressed and uncompressed
    working_bucket = os.environ.get("WORKING_BUCKET")
    full_document = Document.load_document(
        event.get("document", {}), working_bucket, logger
    )

    # Log loaded document for troubleshooting
    logger.info(
        f"Loaded document - ID: {full_document.id}, input_key: {full_document.input_key}"
    )
    logger.info(
        f"Document buckets - input_bucket: {full_document.input_bucket}, output_bucket: {full_document.output_bucket}"
    )
    logger.info(
        f"Document status: {full_document.status}, num_pages: {full_document.num_pages}"
    )
    logger.info(
        f"Document pages count: {len(full_document.pages)}, sections count: {len(full_document.sections)}"
    )
    logger.info(
        f"Full document content: {json.dumps(full_document.to_dict(), default=str)}"
    )

    # Get the section ID directly from the Map state input
    # Now using the simplified array of section IDs format
    section_id = event.get("section_id")

    if not section_id:
        raise ValueError("No section_id found in event")

    # Look up the full section from the decompressed document
    section = None
    for doc_section in full_document.sections:
        if doc_section.section_id == section_id:
            section = doc_section
            break

    if not section:
        raise ValueError(f"Section {section_id} not found in document")

    logger.info(f"Processing section {section_id} with {len(section.page_ids)} pages")

    # Intelligent Extraction detection: Skip if section already has extraction data
    if section.extraction_result_uri and section.extraction_result_uri.strip():
        logger.info(
            f"Skipping extraction for section {section_id} - already has extraction data: {section.extraction_result_uri}"
        )

        # Add Lambda metering for extraction skip execution
        try:
            lambda_metering = calculate_lambda_metering(
                "Extraction", context, start_time
            )
            full_document.metering = merge_metering_data(
                full_document.metering, lambda_metering
            )
        except Exception as e:
            logger.warning(
                f"Failed to add Lambda metering for extraction skip: {str(e)}"
            )

        # Return the section without processing
        response = {
            "section_id": section_id,
            "document": full_document.serialize_document(
                working_bucket, f"extraction_skip_{section_id}", logger
            ),
        }

        logger.info(
            f"Extraction skipped - Response: {json.dumps(response, default=str)}"
        )
        return response
    else:
        logger.info(
            f"Processing section {section_id} - no extraction data found, proceeding with extraction"
        )

    # Normal extraction processing or selective processing for modified sections
    # Update document status to EXTRACTING
    full_document.status = Status.EXTRACTING
    document_service = create_document_service()
    logger.info(f"Updating document status to {full_document.status}")
    document_service.update_document(full_document)

    # Create a section-specific document by modifying the original document
    section_document = full_document
    section_document.sections = [section]
    section_document.metering = {}

    # Filter to keep only the pages needed for this section
    needed_pages = {}
    for page_id in section.page_ids:
        if page_id in full_document.pages:
            needed_pages[page_id] = full_document.pages[page_id]
    section_document.pages = needed_pages

    # Initialize the extraction service
    extraction_service = extraction.ExtractionService(config=config)

    # Track metrics
    metrics.put_metric("InputDocuments", 1)
    metrics.put_metric("InputDocumentPages", len(section.page_ids))

    # Process the section in our focused document
    t0 = time.time()
    section_document = extraction_service.process_document_section(
        document=section_document, section_id=section_id
    )
    t1 = time.time()
    logger.info(f"Total extraction time: {t1-t0:.2f} seconds")

    # Check if document processing failed
    if section_document.status == Status.FAILED:
        error_message = f"Extraction failed for document {section_document.id}, section {section_id}"
        logger.error(error_message)
        raise Exception(error_message)

    # Add Lambda metering for successful extraction execution
    try:
        lambda_metering = calculate_lambda_metering("Extraction", context, start_time)
        section_document.metering = merge_metering_data(
            section_document.metering, lambda_metering
        )
    except Exception as e:
        logger.warning(f"Failed to add Lambda metering for extraction: {str(e)}")

    # Write structured extraction results to DynamoDB (fallback for non-invoice documents)
    try:
        extraction_uri = section.extraction_result_uri if section_document.sections else None
        rows_written = write_extraction_to_dynamodb(
            section_document,
            section_id,
            extraction_uri
        )
        if rows_written > 0:
            logger.info(f"📊 Successfully wrote {rows_written} extraction record(s) to DynamoDB")
    except Exception as e:
        logger.error(f"Failed to write extraction to DynamoDB (non-fatal): {str(e)}")
        # Don't fail the extraction if DynamoDB write fails

    # Get the section classification for routing
    section_classification = section.classification if section else None

    # Prepare output with automatic compression if needed
    response = {
        "section_id": section_id,
        "section_classification": section_classification,
        "document": section_document.serialize_document(
            working_bucket, f"extraction_{section_id}", logger
        ),
    }

    logger.info(f"Response: {json.dumps(response, default=str)}")
    return response
