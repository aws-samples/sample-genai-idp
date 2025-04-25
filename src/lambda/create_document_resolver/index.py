import os
import boto3
import json
import logging
from decimal import Decimal
import datetime

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
# Get LOG_LEVEL from environment variable with INFO as default

dynamodb = boto3.resource('dynamodb')

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

def handler(event, context):
    logger.info(f"Create document resolver invoked with event: {json.dumps(event)}")
    
    try:
        # Extract input data from full AppSync context
        input_data = event['arguments']['input']
        object_key = input_data['ObjectKey']
        queued_time = input_data['QueuedTime']
        
        logger.info(f"Processing document: {object_key}, QueuedTime: {queued_time}")
        
        tracking_table = dynamodb.Table(os.environ['TRACKING_TABLE_NAME'])
        logger.info(f"Using tracking table: {os.environ['TRACKING_TABLE_NAME']}")
        
        # Define document key format
        doc_pk = f"doc#{object_key}"
        doc_sk = "none"
        
        # First check if document already exists
        logger.info(f"Checking if document {object_key} already exists")
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
        
        # If existing document found, delete its list entry
        if existing_doc and 'QueuedTime' in existing_doc:
            try:
                old_time = existing_doc['QueuedTime']
                logger.info(f"Deleting list entry for existing document with QueuedTime: {old_time}")
                
                # Calculate shard ID for the old list entry
                old_date = old_time.split('T')[0]  # e.g., 2023-01-01
                old_hour = int(old_time.split('T')[1].split(':')[0])  # e.g., 12
                
                # Calculate shard (6 shards per day = 4 hours each)
                shards_in_day = 6
                hours_in_shard = 24 / shards_in_day
                old_shard = int(old_hour / hours_in_shard)
                old_shard_str = f"{old_shard:02d}"  # Format with leading zero
                
                old_list_pk = f"list#{old_date}#s#{old_shard_str}"
                old_list_sk = f"ts#{old_time}#id#{object_key}"
                
                logger.info(f"Deleting list entry with PK={old_list_pk}, SK={old_list_sk}")
                result = tracking_table.delete_item(
                    Key={
                        'PK': old_list_pk,
                        'SK': old_list_sk
                    },
                    ReturnValues='ALL_OLD'
                )
                
                if 'Attributes' in result:
                    logger.info(f"Successfully deleted list entry: {json.dumps(result['Attributes'], cls=DecimalEncoder)}")
                else:
                    logger.warning(f"No list entry found to delete with PK={old_list_pk}, SK={old_list_sk}")
            except Exception as e:
                logger.error(f"Error deleting list entry: {str(e)}")
                # Continue with creation process even if deletion fails
        
        # Calculate shard ID for new list entry
        date_part = queued_time.split('T')[0]  # e.g., 2023-01-01
        hour_part = int(queued_time.split('T')[1].split(':')[0])  # e.g., 12
        
        # Calculate shard (6 shards per day = 4 hours each)
        shards_in_day = 6
        hours_in_shard = 24 / shards_in_day
        shard = int(hour_part / hours_in_shard)
        shard_str = f"{shard:02d}"  # Format with leading zero
        
        list_pk = f"list#{date_part}#s#{shard_str}"
        list_sk = f"ts#{queued_time}#id#{object_key}"
        
        logger.info(f"Creating document entries with doc_pk={doc_pk}, list_pk={list_pk}")
        
        # Create both items directly using the resource interface instead of transactions
        try:
            # Create the document record
            logger.info(f"Creating document record: PK={doc_pk}, SK={doc_sk}")
            tracking_table.put_item(
                Item={
                    'PK': doc_pk,
                    'SK': doc_sk,
                    **input_data
                }
            )
            
            # Create the list item
            logger.info(f"Creating list item: PK={list_pk}, SK={list_sk}")
            tracking_table.put_item(
                Item={
                    'PK': list_pk,
                    'SK': list_sk,
                    'ObjectKey': object_key,
                    'QueuedTime': queued_time,
                    'ExpiresAfter': input_data.get('ExpiresAfter')
                }
            )
            
            logger.info(f"Successfully created document and list entries for {object_key}")
        except Exception as e:
            logger.error(f"Error creating document entries: {str(e)}")
            raise e
        
        return {"ObjectKey": object_key}
    except Exception as e:
        logger.error(f"Error in create_document resolver: {str(e)}", exc_info=True)
        raise e