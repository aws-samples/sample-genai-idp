# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import os
import boto3
import json
import logging
import re
from decimal import Decimal
from robust_list_deletion import delete_list_entries_robust, calculate_shard

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
logging.getLogger('idp_common.bedrock.client').setLevel(os.environ.get("BEDROCK_LOG_LEVEL", "INFO"))

dynamodb = boto3.resource('dynamodb')

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

def extract_user_id(event):
    """
    Extract Cognito user ID (UUID) from AppSync event context.
    Prioritizes 'sub' field which contains the actual Cognito UUID.
    Falls back to 'username' only if 'sub' is not available.
    """
    identity = event.get('identity', {})
    
    # PRIORITY 1: Extract from 'sub' field (this is the actual Cognito UUID)
    user_id = identity.get('sub')
    if user_id:
        logger.info(f"Extracted user_id from sub: {user_id}")
        return user_id
    
    # PRIORITY 2: Fallback to 'username' if 'sub' is not available
    user_id = identity.get('username')
    if user_id:
        logger.info(f"Extracted user_id from username: {user_id}")
        return user_id
    
    logger.error("No user ID found in identity context")
    logger.error(f"Identity context: {json.dumps(identity)}")
    raise ValueError("User not authenticated - missing user ID")

def validate_user_id(user_id):
    """
    Validate user ID format (should be UUID-like from Cognito).
    """
    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    if not re.match(uuid_pattern, user_id, re.IGNORECASE):
        logger.warning(f"User ID doesn't match UUID pattern: {user_id}")
    return user_id

def handler(event, context):
    logger.info(f"Create document resolver invoked with event: {json.dumps(event)}")
    
    try:
        # Extract input data from full AppSync context
        input_data = event['arguments']['input']
        
        # Get user ID: prefer input data (from Lambda), fallback to identity context (from UI)
        if input_data.get('UserId'):
            user_id = input_data.get('UserId')
            logger.info(f"Using UserId from input: {user_id}")
        else:
            user_id = extract_user_id(event)
            logger.info(f"Using UserId from identity context: {user_id}")
            
        user_id = validate_user_id(user_id)
        logger.info(f"Processing request for user: {user_id}")
        
        # Validate required input fields
        if not input_data:
            raise ValueError("Input data is required")
        
        object_key = input_data.get('ObjectKey')
        queued_time = input_data.get('QueuedTime')
        
        if not object_key or not isinstance(object_key, str):
            raise ValueError("ObjectKey must be a non-empty string")
        if not queued_time or not isinstance(queued_time, str):
            raise ValueError("QueuedTime must be a non-empty string")
        
        logger.info(f"Processing document: {object_key}, QueuedTime: {queued_time}, User: {user_id}")
        
        tracking_table = dynamodb.Table(os.environ['TRACKING_TABLE_NAME'])
        logger.info(f"Using tracking table: {os.environ['TRACKING_TABLE_NAME']}")
        
        # Define USER-SCOPED document key format
        # IMPORTANT: Use the FULL object_key (including users/<user_id>/ prefix) to match GetDocumentResolver expectations
        # GetDocumentResolver constructs: user#<userId>#doc#<ObjectKey> where ObjectKey is the full S3 path
        doc_pk = f"user#{user_id}#doc#{object_key}"
        doc_sk = "none"
        
        logger.info(f"Creating user-scoped document record: PK={doc_pk}, SK={doc_sk}")
        
        # First check if document already exists
        logger.info(f"Checking if document {object_key} already exists for user {user_id}")
        existing_doc = None
        try:
            response = tracking_table.get_item(
                Key={
                    'PK': doc_pk,
                    'SK': doc_sk
                }
            )
            if 'Item' in response:
                existing_doc = response['Item']
                logger.info(f"Found existing document metadata: {json.dumps(existing_doc, cls=DecimalEncoder)}")
        except Exception as e:
            logger.error(f"Error checking for existing document: {str(e)}")
            # Continue with creation process even if this check fails
        
        # If existing document found, delete its list entry using robust deletion
        if existing_doc:
            try:
                logger.info(f"Attempting robust deletion of list entries for existing document: {object_key}")
                deletion_success = delete_list_entries_robust(tracking_table, object_key, existing_doc)
                
                if deletion_success:
                    logger.info(f"Successfully deleted existing list entries for {object_key}")
                else:
                    logger.warning(f"No existing list entries found/deleted for {object_key}")
            except Exception as e:
                logger.error(f"Error in robust list entry deletion: {str(e)}")
                # Continue with creation process even if deletion fails
        
        # Calculate shard ID for new list entry using shared utility
        date_part, shard_str = calculate_shard(queued_time)
        list_pk = f"list#{date_part}#s#{shard_str}"
        list_sk = f"ts#{queued_time}#id#{object_key}"
        
        logger.info(f"Creating document entries with doc_pk={doc_pk}, list_pk={list_pk}")
        
        # Create both items directly using the resource interface
        try:
            # Add UserId to input_data for the document record
            input_data_with_user = {**input_data, 'UserId': user_id}
            
            # Create the document record with user-scoped PK
            logger.info(f"Creating user-scoped document record: PK={doc_pk}, SK={doc_sk}")
            tracking_table.put_item(
                Item={
                    'PK': doc_pk,
                    'SK': doc_sk,
                    **input_data_with_user
                }
            )
            
            # Create the list item with UserId for filtering
            logger.info(f"Creating list item: PK={list_pk}, SK={list_sk}")
            tracking_table.put_item(
                Item={
                    'PK': list_pk,
                    'SK': list_sk,
                    'ObjectKey': object_key,
                    'QueuedTime': queued_time,
                    'UserId': user_id,  # Add UserId to enable filtering
                    'ExpiresAfter': input_data.get('ExpiresAfter')
                }
            )
            
            logger.info(f"Successfully created document and list entries for user {user_id}, object {object_key}")
        except Exception as e:
            logger.error(f"Error creating document entries: {str(e)}")
            raise e
        
        return {"ObjectKey": object_key, "UserId": user_id}
    except Exception as e:
        logger.error(f"Error in create_document resolver: {str(e)}", exc_info=True)
        raise e