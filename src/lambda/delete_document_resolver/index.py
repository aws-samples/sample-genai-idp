# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import os
import boto3
import json
import logging
from typing import List
from robust_list_deletion import delete_list_entries_robust

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logging.getLogger('idp_common.bedrock.client').setLevel(os.environ.get("BEDROCK_LOG_LEVEL", "INFO"))
# Get LOG_LEVEL from environment variable with INFO as default

dynamodb = boto3.resource('dynamodb')
s3 = boto3.client('s3')

def handler(event, context):
    logger.info(f"Delete document resolver invoked with event: {json.dumps(event)}")
    
    try:
        object_keys: List[str] = event['arguments']['objectKeys']
        
        # Validate input
        if not object_keys or not isinstance(object_keys, list):
            raise ValueError("objectKeys must be a non-empty list")
        
        tracking_table = dynamodb.Table(os.environ['TRACKING_TABLE_NAME'])
        input_bucket = os.environ['INPUT_BUCKET']
        output_bucket = os.environ['OUTPUT_BUCKET']
        
        logger.info(f"Preparing to delete {len(object_keys)} documents: {object_keys}")
        logger.debug(f"Using tracking table: {os.environ['TRACKING_TABLE_NAME']}")
        logger.debug(f"Input bucket: {input_bucket}, Output bucket: {output_bucket}")

        deleted_count = 0
        # Delete each document and its associated data
        for object_key in object_keys:
            logger.info(f"Processing deletion for document: {object_key}")
            
            # First get the document metadata to extract the queued time
            doc_pk = f"doc#{object_key}"
            logger.info(f"Getting document metadata with PK={doc_pk}, SK=none from tracking table")
            document_metadata = None
            try:
                response = tracking_table.get_item(
                    Key={
                        'PK': doc_pk,
                        'SK': 'none'
                    }
                )
                if 'Item' in response:
                    document_metadata = response['Item']
                    logger.info(f"Successfully got document metadata: {document_metadata}")
                else:
                    logger.warning(f"Document metadata not found for {object_key}")
            except Exception as e:
                logger.error(f"Error getting document metadata: {str(e)}")
                # Continue with deletion process even if this part fails
            
            # Delete from input bucket
            try:
                logger.info(f"Deleting document from input bucket: {input_bucket}/{object_key}")
                s3.delete_object(
                    Bucket=input_bucket,
                    Key=object_key
                )
                logger.info("Successfully deleted document from input bucket")
            except Exception as e:
                logger.error(f"Error deleting from input bucket: {str(e)}")

            # Delete from output bucket
            try:
                # List and delete all objects with the prefix
                logger.info(f"Deleting document outputs from output bucket with prefix: {object_key}")
                paginator = s3.get_paginator('list_objects_v2')
                deleted_output_count = 0
                
                for page in paginator.paginate(Bucket=output_bucket, Prefix=object_key):
                    if 'Contents' in page:
                        for obj in page['Contents']:
                            logger.debug(f"Deleting output file: {obj['Key']}")
                            s3.delete_object(
                                Bucket=output_bucket,
                                Key=obj['Key']
                            )
                            deleted_output_count += 1
                
                logger.info(f"Successfully deleted {deleted_output_count} output files from output bucket")
            except Exception as e:
                logger.error(f"Error deleting from output bucket: {str(e)}")

            # Delete from list entries using robust deletion strategy
            try:
                logger.info(f"Attempting robust list entry deletion for {object_key}")
                deletion_success = delete_list_entries_robust(tracking_table, object_key, document_metadata)
                
                if deletion_success:
                    logger.info(f"Successfully deleted list entries for {object_key}")
                else:
                    logger.warning(f"No list entries were found/deleted for {object_key}")
            except Exception as e:
                logger.error(f"Error in robust list entry deletion: {str(e)}")
            
            # Finally, delete the document record from tracking table
            if document_metadata:
                logger.info(f"Deleting document record with PK={doc_pk}, SK=none from tracking table")
                try:
                    tracking_table.delete_item(
                        Key={
                            'PK': doc_pk,
                            'SK': 'none'
                        }
                    )
                    logger.info("Successfully deleted document record from tracking table")
                except Exception as e:
                    logger.error(f"Error deleting document record from tracking table: {str(e)}")
            
            deleted_count += 1
            logger.info(f"Completed deletion process for document: {object_key}")

        logger.info(f"Successfully deleted {deleted_count} of {len(object_keys)} documents")
        return True
    except Exception as e:
        logger.error(f"Error in delete_document resolver: {str(e)}", exc_info=True)
        raise e
