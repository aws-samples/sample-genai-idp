import os
import boto3
import json
import logging
from typing import List

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
# Get LOG_LEVEL from environment variable with INFO as default

dynamodb = boto3.resource('dynamodb')
s3 = boto3.client('s3')

def handler(event, context):
    logger.info(f"Delete document resolver invoked with event: {json.dumps(event)}")
    
    try:
        object_keys: List[str] = event['arguments']['objectKeys']
        tracking_table = dynamodb.Table(os.environ['TRACKING_TABLE_NAME'])
        input_bucket = os.environ['INPUT_BUCKET']
        output_bucket = os.environ['OUTPUT_BUCKET']
        
        logger.info(f"Preparing to delete {len(object_keys)} documents: {object_keys}")
        logger.info(f"Using tracking table: {os.environ['TRACKING_TABLE_NAME']}")
        logger.info(f"Input bucket: {input_bucket}, Output bucket: {output_bucket}")

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
            
            # Delete the document record
            if document_metadata:
                logger.info(f"Deleting document record with PK={doc_pk}, SK=none from tracking table")
                try:
                    tracking_table.delete_item(
                        Key={
                            'PK': doc_pk,
                            'SK': 'none'
                        }
                    )
                    logger.info(f"Successfully deleted document record from tracking table")
                except Exception as e:
                    logger.error(f"Error deleting document record from tracking table: {str(e)}")
            
            # Delete from input bucket
            try:
                logger.info(f"Deleting document from input bucket: {input_bucket}/{object_key}")
                s3.delete_object(
                    Bucket=input_bucket,
                    Key=object_key
                )
                logger.info(f"Successfully deleted document from input bucket")
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

            # Delete from list entries
            try:
                # If we have the document metadata, extract the times needed to construct the list PK
                # Prefer QueuedTime, but fallback to InitialEventTime if needed
                event_time = None
                if document_metadata:
                    if 'QueuedTime' in document_metadata and document_metadata['QueuedTime']:
                        event_time = document_metadata['QueuedTime']
                        logger.info(f"Using QueuedTime for list key construction: {event_time}")
                    elif 'InitialEventTime' in document_metadata and document_metadata['InitialEventTime']:
                        event_time = document_metadata['InitialEventTime']
                        logger.info(f"QueuedTime not found, using InitialEventTime instead: {event_time}")
                    
                if event_time:
                    # Format is typically ISO: 2023-01-01T12:34:56Z
                    date_part = event_time.split('T')[0]  # e.g., 2023-01-01
                    hour_part = event_time.split('T')[1].split(':')[0]  # e.g., 12
                    
                    # Construct list entry format based on date shard - 6 shards per day
                    hours_in_shard = 24 / 6  # 4 hours per shard
                    shard = int(int(hour_part) / hours_in_shard)
                    shard_str = f"{shard:02d}"  # Format with leading zero for single digits
                    
                    # Use the actual format from the database
                    list_pk = f"list#{date_part}#s#{shard_str}"
                    list_sk = f"ts#{event_time}#id#{object_key}"
                    
                    logger.info(f"Constructed list entry key: PK={list_pk}, SK={list_sk}")
                    
                    logger.info(f"Attempting to delete list entry")
                    
                    try:
                        logger.info(f"Deleting list entry with PK={list_pk}, SK={list_sk}")
                        result = tracking_table.delete_item(
                            Key={
                                'PK': list_pk,
                                'SK': list_sk
                            },
                            ReturnValues='ALL_OLD'
                        )
                        if 'Attributes' in result:
                            logger.info(f"Successfully deleted list entry: {result['Attributes']}")
                        else:
                            logger.warning(f"No list entry found with PK={list_pk}, SK={list_sk}")
                    except Exception as e:
                        logger.error(f"Error deleting list entry: {str(e)}")
                else:
                    logger.warning(f"Cannot delete list entries - no time information available for {object_key}")
                    if document_metadata:
                        logger.debug(f"Available metadata fields: {list(document_metadata.keys())}")
            except Exception as e:
                logger.error(f"Error deleting list entry: {str(e)}")
            
            deleted_count += 1
            logger.info(f"Completed deletion process for document: {object_key}")

        logger.info(f"Successfully deleted {deleted_count} of {len(object_keys)} documents")
        return True
    except Exception as e:
        logger.error(f"Error in delete_document resolver: {str(e)}", exc_info=True)
        raise e
