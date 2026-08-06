import json
import logging
import os
import re
from datetime import datetime

import boto3
from botocore.config import Config
from idp_common.dynamodb import DynamoDBClient  # type: ignore
from idp_common.s3 import find_matching_files  # type: ignore

# Constants
MAX_ZIP_SIZE_BYTES = 1073741824  # 1 GB

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def validate_test_set_name(name):
    """Validate test set name: alphanumeric, spaces, hyphens, underscores only, max 50 chars"""
    if not name or not isinstance(name, str):
        return False
    return re.match(r'^[a-zA-Z0-9\s_-]+$', name) and len(name) <= 50


def validate_description(description):
    """Validate description: max 500 chars only"""
    if description is None or description == "":
        return True  # Optional field
    if not isinstance(description, str):
        return False
    return len(description) <= 500

# Configure S3 client with S3v4 signature.
# When S3_ENDPOINT_URL is set (private VPC mode), use virtual-host addressing
# so the SigV4 host header matches the VPC endpoint DNS.
_s3_endpoint_url = os.environ.get("S3_ENDPOINT_URL") or None
_s3_addressing = "virtual" if _s3_endpoint_url else "path"
s3_config = Config(
    signature_version="s3v4",
    s3={"addressing_style": _s3_addressing},
)
s3_client = boto3.client("s3", endpoint_url=_s3_endpoint_url, config=s3_config)
db_client = DynamoDBClient(table_name=os.environ['TRACKING_TABLE'])

def _caller_in_groups(event, allowed):
    """Defense-in-depth RBAC check against the caller's Cognito groups.

    The schema restricts these fields via @aws_cognito_user_pools(cognito_groups),
    but we also enforce the group server-side so the operation is never reachable
    by an unauthorized caller even if the schema directive is missing or
    misconfigured (e.g. the prior @aws_auth directive, which AppSync silently
    ignores on a multi-auth API).
    """
    groups = (event.get("identity") or {}).get("claims", {}).get("cognito:groups") or []
    if isinstance(groups, str):
        groups = [groups]
    return bool(set(allowed).intersection(groups))


def handler(event, context):
    field_name = event['info']['fieldName']
    logger.info(f"Test set resolver invoked with field_name: {field_name}")

    # Defense-in-depth: all Test Studio test-set operations are Admin+Author.
    # Allow direct Lambda invocations (no 'identity' field or identity=None) for CI/automation.
    # AppSync invocations always have 'identity' with non-None value, so RBAC is still enforced for UI users.
    # Security: Direct invocation path is gated by IAM (lambda:InvokeFunction permission on this ARN),
    # not Cognito groups. CI/automation uses IAM credentials; UI users go through AppSync + Cognito.
    is_appsync_invoke = event.get('identity') is not None
    if is_appsync_invoke and not _caller_in_groups(event, ("Admin", "Author")):
        logger.warning(
            f"Forbidden: caller attempted '{field_name}' without Admin/Author group"
        )
        raise Exception(f"Unauthorized: '{field_name}' requires Admin or Author group")

    if field_name == 'addTestSet':
        return add_test_set(event['arguments'])
    elif field_name == 'addTestSetFromUpload':
        return add_test_set_from_upload(event['arguments'])
    elif field_name == 'addDocumentsToTestSet':
        return add_documents_to_test_set(event['arguments'])
    elif field_name == 'addDocumentsToTestSetFromUpload':
        return add_documents_to_test_set_from_upload(event['arguments'])
    elif field_name == 'updateTestSet':
        return update_test_set(event['arguments'])
    elif field_name == 'deleteTestSets':
        return delete_test_sets(event['arguments'])
    elif field_name == 'getTestSets':
        return get_test_sets()
    elif field_name == 'getTestSetDocuments':
        return get_test_set_documents(event['arguments'])
    elif field_name == 'listBucketFiles':
        return list_bucket_files(event['arguments'])
    elif field_name == 'validateTestFileName':
        return validate_test_file_name(event['arguments'])
    else:
        raise Exception(f'Unknown field: {field_name}')

def add_test_set_from_upload(args):
    logger.info(f"Adding test set from zip upload: {args}")

    input_data = args['input']
    zip_filename = input_data['fileName']
    description = input_data.get('description', '')  # Optional field
    document_class_type = input_data.get('documentClassType')  # Optional field

    # Validate zip file extension
    if not zip_filename.lower().endswith('.zip'):
        raise Exception("File must be a zip file")

    # Extract test set name from filename (remove .zip extension)
    test_set_name = zip_filename.replace('.zip', '').replace('.ZIP', '')

    # Validate test set name
    if not validate_test_set_name(test_set_name):
        raise Exception("Test set name can only contain letters, numbers, spaces, hyphens, and underscores (max 50 characters)")

    # Validate description
    if description and not validate_description(description):
        raise Exception("Description cannot exceed 500 characters")

    test_set_id = f"{test_set_name.replace(' ', '-').lower()}"

    test_set_bucket = os.environ['TEST_SET_BUCKET']

    # Upload with .zip extension in the test set folder
    key = f"{test_set_id}/{zip_filename}"

    # Generate presigned URL for zip file
    presigned_post = s3_client.generate_presigned_post(
        Bucket=test_set_bucket,
        Key=key,
        Fields={
            'Content-Type': 'application/zip'
        },
        Conditions=[
            ['content-length-range', 1, MAX_ZIP_SIZE_BYTES],
            {'Content-Type': 'application/zip'}
        ],
        ExpiresIn=900  # 15 minutes
    )

    logger.info(f"Generated presigned POST for zip file {key}")

    # Add test set entry to tracking table
    now = datetime.utcnow().isoformat() + 'Z'

    item = {
        'PK': f'testset#{test_set_id}',
        'SK': 'metadata',
        'ItemType': 'testset',
        'InitialEventTime': now,
        'id': test_set_id,
        'name': test_set_name,
        'description': description,
        'filePattern': '',  # Empty for uploaded test sets
        'status': 'QUEUED',
        'createdAt': now
    }

    # Add documentClassType if provided
    if document_class_type:
        item['documentClassType'] = document_class_type

    # Don't set fileCount for uploads - will be added after zip processing

    db_client.put_item(item)
    logger.info(f"Created test set {test_set_id} in tracking table with QUEUED status")

    logger.info(f"Test set {test_set_id} ready for zip upload - will be processed automatically on upload")

    return {
        'testSetId': test_set_id,
        'presignedUrl': json.dumps(presigned_post),
        'objectKey': key
    }

def add_test_set(args):
    logger.info(f"Adding test set: {args}")

    test_set_name = args['name']
    description = args.get('description', '')  # Optional field
    file_count = args['fileCount']
    document_class_type = args.get('documentClassType')  # Optional field

    # Validate test set name
    if not validate_test_set_name(test_set_name):
        raise Exception("Test set name can only contain letters, numbers, spaces, hyphens, and underscores (max 50 characters)")

    # Validate description
    if description and not validate_description(description):
        raise Exception("Description cannot exceed 500 characters")

    # Generate test set ID with name format, replace spaces with dashes
    test_set_id = f"{test_set_name.replace(' ', '-').lower()}"

    # Create initial test set record
    now = datetime.utcnow().isoformat() + 'Z'

    item = {
        'PK': f'testset#{test_set_id}',
        'SK': 'metadata',
        'ItemType': 'testset',
        'InitialEventTime': now,
        'id': test_set_id,
        'name': test_set_name,
        'description': description,
        'filePattern': args['filePattern'],
        'fileCount': file_count,
        'status': 'QUEUED',
        'createdAt': now
    }

    # Add documentClassType if provided
    if document_class_type:
        item['documentClassType'] = document_class_type

    db_client.put_item(item)
    logger.info(f"Created test set {test_set_id} in tracking table")

    # Send file copying job to SQS queue
    import boto3
    sqs = boto3.client('sqs')
    queue_url = os.environ['TEST_SET_COPY_QUEUE_URL']

    message_body = {
        'testSetId': test_set_id,
        'filePattern': args['filePattern'],
        'bucketType': args['bucketType'],
        'trackingTable': os.environ['TRACKING_TABLE']
    }
    if args.get('modifiedAfter'):
        message_body['modifiedAfter'] = args['modifiedAfter']

    sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(message_body)
    )

    logger.info(f"Queued test set creation job for {test_set_id} with pattern '{args['filePattern']}'")

    result = {
        'id': test_set_id,
        'name': test_set_name,
        'description': description,
        'filePattern': args['filePattern'],
        'fileCount': file_count,
        'status': 'QUEUED',
        'createdAt': now
    }

    # Add documentClassType to response if provided
    if document_class_type:
        result['documentClassType'] = document_class_type

    return result

def add_documents_to_test_set(args):
    logger.info(f"Adding documents to existing test set: {args}")

    test_set_id = args['testSetId']
    file_pattern = args['filePattern']
    bucket_type = args['bucketType']
    file_count = args['fileCount']

    # Look up existing test set
    item = db_client.get_item({
        'PK': f'testset#{test_set_id}',
        'SK': 'metadata'
    })

    if not item:
        raise Exception(f"Test set '{test_set_id}' not found")

    if item.get('status') != 'COMPLETED':
        raise Exception(f"Test set '{test_set_id}' is not in COMPLETED status (current: {item.get('status')})")

    # Update status to UPDATING
    tracking_table = os.environ['TRACKING_TABLE']
    table = boto3.resource('dynamodb').Table(tracking_table)
    table.update_item(
        Key={'PK': f'testset#{test_set_id}', 'SK': 'metadata'},
        UpdateExpression='SET #status = :status REMOVE lastAddResult',
        ExpressionAttributeNames={'#status': 'status'},
        ExpressionAttributeValues={':status': 'UPDATING'}
    )

    # Send file copying job to SQS queue
    sqs = boto3.client('sqs')
    queue_url = os.environ['TEST_SET_COPY_QUEUE_URL']

    message_body = {
        'testSetId': test_set_id,
        'filePattern': file_pattern,
        'bucketType': bucket_type,
        'trackingTable': tracking_table,
        'mode': 'append'
    }
    if args.get('modifiedAfter'):
        message_body['modifiedAfter'] = args['modifiedAfter']

    sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(message_body)
    )

    logger.info(f"Queued append job for test set {test_set_id} with pattern '{file_pattern}'")

    return {
        'id': test_set_id,
        'name': item['name'],
        'description': item.get('description', ''),
        'filePattern': item.get('filePattern', ''),
        'fileCount': item.get('fileCount'),
        'status': 'UPDATING',
        'createdAt': item['createdAt']
    }


def add_documents_to_test_set_from_upload(args):
    logger.info(f"Adding documents to test set from zip upload: {args}")

    input_data = args['input']
    test_set_id = input_data['testSetId']
    zip_filename = input_data['fileName']

    # Validate zip file extension
    if not zip_filename.lower().endswith('.zip'):
        raise Exception("File must be a zip file")

    # Look up existing test set
    item = db_client.get_item({
        'PK': f'testset#{test_set_id}',
        'SK': 'metadata'
    })

    if not item:
        raise Exception(f"Test set '{test_set_id}' not found")

    if item.get('status') != 'COMPLETED':
        raise Exception(f"Test set '{test_set_id}' is not in COMPLETED status (current: {item.get('status')})")

    # Update status to UPDATING
    tracking_table = os.environ['TRACKING_TABLE']
    table = boto3.resource('dynamodb').Table(tracking_table)
    table.update_item(
        Key={'PK': f'testset#{test_set_id}', 'SK': 'metadata'},
        UpdateExpression='SET #status = :status REMOVE lastAddResult',
        ExpressionAttributeNames={'#status': 'status'},
        ExpressionAttributeValues={':status': 'UPDATING'}
    )

    test_set_bucket = os.environ['TEST_SET_BUCKET']

    # Upload with .zip extension in the test set folder
    key = f"{test_set_id}/{zip_filename}"

    # Generate presigned URL for zip file
    presigned_post = s3_client.generate_presigned_post(
        Bucket=test_set_bucket,
        Key=key,
        Fields={
            'Content-Type': 'application/zip'
        },
        Conditions=[
            ['content-length-range', 1, MAX_ZIP_SIZE_BYTES],
            {'Content-Type': 'application/zip'}
        ],
        ExpiresIn=900  # 15 minutes
    )

    logger.info(f"Generated presigned POST for append zip file {key}")

    return {
        'testSetId': test_set_id,
        'presignedUrl': json.dumps(presigned_post),
        'objectKey': key
    }


def update_test_set(args):
    logger.info(f"Updating test set: {args}")

    input_data = args['input']
    test_set_id = input_data['id']
    description = input_data.get('description')
    document_class_type = input_data.get('documentClassType')

    # Validate description if provided
    if description is not None and not validate_description(description):
        raise Exception("Description cannot exceed 500 characters")

    # Look up existing test set
    item = db_client.get_item({
        'PK': f'testset#{test_set_id}',
        'SK': 'metadata'
    })

    if not item:
        raise Exception(f"Test set '{test_set_id}' not found")

    # Build update expression dynamically
    update_parts = []
    expression_values = {}
    expression_names = {}

    if description is not None:
        update_parts.append('#desc = :desc')
        expression_values[':desc'] = description
        expression_names['#desc'] = 'description'

    # Check if we need to remove documentClassType
    remove_expression = False
    if 'documentClassType' in input_data and document_class_type is None:
        # Explicitly remove documentClassType if set to None
        remove_expression = True
    elif document_class_type is not None:
        # Set documentClassType to the new value
        update_parts.append('documentClassType = :docType')
        expression_values[':docType'] = document_class_type

    if not update_parts and not remove_expression:
        # No updates requested, just return current item
        return {
            'id': item['id'],
            'name': item['name'],
            'description': item.get('description', ''),
            'filePattern': item.get('filePattern', ''),
            'fileCount': item.get('fileCount'),
            'status': item.get('status'),
            'createdAt': item['createdAt'],
            'documentClassType': item.get('documentClassType')
        }

    # Perform the update
    tracking_table = os.environ['TRACKING_TABLE']
    table = boto3.resource('dynamodb').Table(tracking_table)

    # Build update expression
    update_expression = ""
    if update_parts:
        update_expression = f"SET {', '.join(update_parts)}"
    if remove_expression:
        if update_expression:
            update_expression += " REMOVE documentClassType"
        else:
            update_expression = "REMOVE documentClassType"

    update_kwargs = {
        'Key': {'PK': f'testset#{test_set_id}', 'SK': 'metadata'},
        'UpdateExpression': update_expression,
        'ReturnValues': 'ALL_NEW'
    }

    if expression_names:
        update_kwargs['ExpressionAttributeNames'] = expression_names
    if expression_values:
        update_kwargs['ExpressionAttributeValues'] = expression_values

    response = table.update_item(**update_kwargs)
    updated_item = response['Attributes']

    logger.info(f"Updated test set {test_set_id}")

    return {
        'id': updated_item['id'],
        'name': updated_item['name'],
        'description': updated_item.get('description', ''),
        'filePattern': updated_item.get('filePattern', ''),
        'fileCount': updated_item.get('fileCount'),
        'status': updated_item.get('status'),
        'createdAt': updated_item['createdAt'],
        'documentClassType': updated_item.get('documentClassType')
    }


def delete_test_sets(args):
    logger.info(f"Deleting test sets: {args['testSetIds']}")

    test_set_ids = args['testSetIds']
    test_set_bucket = os.environ['TEST_SET_BUCKET']
    
    for test_set_id in test_set_ids:
        # Delete files from test set bucket.
        #
        # Both APIs used here are page-limited, so both must be looped:
        #   * list_objects_v2 returns at most 1000 keys per call
        #   * delete_objects accepts at most 1000 keys per call
        # A single unpaginated pass silently orphaned every object past the
        # first 1000 — the DynamoDB record disappeared from the UI while the
        # files stayed in the bucket, invisible and still billed. Real test sets
        # exceed this easily: Fake-W2-Tax-Forms is 2000 documents (~4000 objects
        # counting baselines).
        try:
            deleted_count = 0
            continuation_token = None
            while True:
                list_kwargs = {
                    'Bucket': test_set_bucket,
                    'Prefix': f"{test_set_id}/",
                }
                if continuation_token:
                    list_kwargs['ContinuationToken'] = continuation_token
                response = s3_client.list_objects_v2(**list_kwargs)

                objects_to_delete = [
                    {'Key': key}
                    for key in (
                        obj.get('Key') for obj in response.get('Contents', [])
                    )
                    if key
                ]
                # One list page is at most 1000 keys, which is also the
                # delete_objects maximum, so this is a single batch in practice —
                # the slice keeps it correct regardless.
                for i in range(0, len(objects_to_delete), 1000):
                    batch = objects_to_delete[i:i + 1000]
                    s3_client.delete_objects(
                        Bucket=test_set_bucket,
                        Delete={'Objects': batch}
                    )
                    deleted_count += len(batch)

                if not response.get('IsTruncated'):
                    break
                continuation_token = response.get('NextContinuationToken')
                if not continuation_token:
                    # Defensive: a truncated response without a token would
                    # otherwise loop forever.
                    logger.warning(
                        f"Truncated listing without a continuation token for "
                        f"test set {test_set_id}; stopping after {deleted_count} objects"
                    )
                    break

            if deleted_count:
                logger.info(f"Deleted {deleted_count} files for test set {test_set_id}")

        except Exception as e:
            logger.error(f"Failed to delete files for test set {test_set_id}: {str(e)}")
        
        # Delete tracking table record
        db_client.delete_item({
            'PK': f'testset#{test_set_id}',
            'SK': 'metadata'
        })
    
    logger.info(f"Deleted {len(test_set_ids)} test sets")
    return True

def get_test_sets():
    logger.info("Retrieving all test sets and scanning for direct uploads")
    
    # Use GSI to find testset PK/SK keys efficiently, then BatchGetItem for full records.
    # This avoids scanning the entire TrackingTable (which includes all documents).
    tracking_table = boto3.resource('dynamodb').Table(os.environ['TRACKING_TABLE'])
    items = []
    try:
        from boto3.dynamodb.conditions import Key as DDBKey
        # Step 1: GSI query to get testset keys (lightweight - only projected attrs)
        gsi_items = []
        query_kwargs = {
            'IndexName': 'TypeDateIndex',
            'KeyConditionExpression': DDBKey('ItemType').eq('testset'),
            'ProjectionExpression': 'PK, SK',
        }
        while True:
            response = tracking_table.query(**query_kwargs)
            gsi_items.extend(response.get('Items', []))
            if 'LastEvaluatedKey' not in response:
                break
            query_kwargs['ExclusiveStartKey'] = response['LastEvaluatedKey']
        
        logger.info(f"GSI query found {len(gsi_items)} testset keys")
        
        if gsi_items:
            # Step 2: BatchGetItem to fetch full records from base table
            keys = [{'PK': item['PK'], 'SK': item['SK']} for item in gsi_items]
            # DynamoDB BatchGetItem supports max 100 keys per call
            for i in range(0, len(keys), 100):
                batch_keys = keys[i:i+100]
                batch_response = boto3.resource('dynamodb').batch_get_item(
                    RequestItems={
                        os.environ['TRACKING_TABLE']: {'Keys': batch_keys}
                    }
                )
                items.extend(batch_response.get('Responses', {}).get(os.environ['TRACKING_TABLE'], []))
            logger.info(f"BatchGetItem returned {len(items)} full testset records")
    except Exception as e:
        logger.warning(f"GSI+BatchGet failed, falling back to scan: {e}")
        items = []
    
    # Fallback to scan only if GSI approach failed
    if not items:
        items = db_client.scan_all(
            filter_expression='begins_with(PK, :pk) AND SK = :sk',
            expression_attribute_values={
                ':pk': 'testset#',
                ':sk': 'metadata'
            }
        )
    
    existing_test_sets = {}
    result = []
    
    for item in items:
        # GSI projection may not include 'id' - derive from PK if needed
        test_set_id = item.get('id') or item.get('PK', '').replace('testset#', '')
        existing_test_sets[test_set_id] = item
        result.append({
            'id': test_set_id,
            'name': item['name'],
            'description': item.get('description', ''),
            'filePattern': item.get('filePattern', ''),
            'fileCount': item.get('fileCount'),  # Returns None if attribute doesn't exist
            'status': item.get('status'),
            'createdAt': item['createdAt'],
            'error': item.get('error'),  # Include error message for failed test sets
            'lastAddResult': item.get('lastAddResult'),
            'documentClassType': item.get('documentClassType'),
            # Optional: a test set may declare which configuration version Test
            # Studio should preselect for it. Absent for the stack-managed
            # benchmark sets, which rely on the id==version-name convention.
            'configVersion': item.get('configVersion')
        })
    
    # Scan TestSetBucket for direct uploads
    try:
        test_set_bucket = os.environ['TEST_SET_BUCKET']
        s3_client = boto3.client('s3')
        
        # Track which test sets still exist in S3
        s3_test_sets = set()
        
        # List all top-level prefixes (potential test sets)
        paginator = s3_client.get_paginator('list_objects_v2')
        page_iterator = paginator.paginate(
            Bucket=test_set_bucket,
            Delimiter='/'
        )
        
        for page in page_iterator:
            # Check common prefixes (folders)
            for prefix_info in page.get('CommonPrefixes', []):
                prefix = prefix_info['Prefix'].rstrip('/')
                s3_test_sets.add(prefix)
                
                # Skip if already exists in DynamoDB
                if prefix in existing_test_sets:
                    continue
                
                # Check if this looks like a test set (has input/ and baseline/ folders)
                if _is_valid_test_set_structure(s3_client, test_set_bucket, prefix):
                    logger.info(f"Found direct upload test set: {prefix}")
                    
                    # Get creation timestamp from first file in the test set
                    created_at = _get_test_set_creation_time(s3_client, test_set_bucket, prefix)
                    
                    # Validate file matching and get counts
                    validation_result = _validate_test_set_files(s3_client, test_set_bucket, prefix)
                    
                    # Create tracking entry
                    status = 'COMPLETED' if validation_result['valid'] else 'FAILED'
                    error_message = validation_result.get('error')
                    
                    _create_test_set_tracking_entry(
                        prefix, 
                        prefix,  # Use prefix as name
                        validation_result['input_count'],
                        status,
                        error_message,
                        created_at
                    )
                    
                    # Add to results
                    result.append({
                        'id': prefix,
                        'name': prefix,
                        'description': '',  # Direct uploads don't have descriptions
                        'filePattern': '',
                        'fileCount': validation_result['input_count'],
                        'status': status,
                        'createdAt': created_at,
                        'documentClassType': None
                    })
                    
                    logger.info(f"Registered direct upload test set {prefix} with status {status}")
        
        # Check for deleted test sets (exist in DynamoDB but not in S3)
        # Only delete old FAILED test sets or any COMPLETED test sets
        from datetime import datetime, timedelta
        
        deleted_test_sets = []
        cutoff_time = datetime.utcnow() - timedelta(hours=1)  # Only delete FAILED if older than 1 hour
        
        for test_set_id in existing_test_sets:
            test_set_item = existing_test_sets[test_set_id]
            test_set_status = test_set_item.get('status')
            created_at_str = test_set_item.get('createdAt', '')
            
            # Parse creation time
            try:
                created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
            except:
                continue  # Skip if can't parse date
            
            # Only delete if S3 folder missing AND:
            # - Status is COMPLETED (any time), OR
            # - Status is FAILED and older than cutoff time
            if (test_set_id not in s3_test_sets and 
                (test_set_status == 'COMPLETED' or 
                 (test_set_status == 'FAILED' and created_at < cutoff_time))):
                deleted_test_sets.append(test_set_id)
        
        # Delete orphaned test sets from DynamoDB
        for test_set_id in deleted_test_sets:
            try:
                db_client.delete_item({
                    'PK': f'testset#{test_set_id}',
                    'SK': 'metadata'
                })
                logger.info(f"Deleted orphaned test set from DynamoDB: {test_set_id}")
                
                # Remove from result list
                result = [item for item in result if item['id'] != test_set_id]
                
            except Exception as e:
                logger.error(f"Failed to delete orphaned test set {test_set_id}: {str(e)}")
    
    except Exception as e:
        logger.error(f"Error scanning for direct uploads: {str(e)}")
    
    logger.info(f"Returning {len(result)} test sets")
    return result

def get_test_set_documents(args):
    """List the documents in a test set with their baseline (ground truth) sections.

    Paginated over the set's `input/` prefix; the S3 continuation token is
    passed through opaquely as `nextToken`. For each page of input files, the
    whole `baseline/` prefix is listed once (bulk) and section result.json
    keys are matched to their document in memory — one extra LIST per page
    regardless of page size, and it handles nested input file names.
    """
    test_set_id = args['testSetId']
    limit = args.get('limit') or 100
    next_token = args.get('nextToken')
    # Optional exact-match filter: return just this document (used by the UI's
    # document detail page when deep-linked, so it doesn't page through the
    # whole set to find one doc).
    object_key = args.get('objectKey')

    # The id is derived from a validated name (validate_test_set_name), so it
    # must match the same charset (with '-' for spaces). Rejects '/' and '..'
    # so it can't traverse outside the test set's S3 prefix.
    if not validate_test_set_name(test_set_id):
        raise Exception("Invalid test set id")
    if object_key and '..' in object_key:
        raise Exception("Invalid object key")
    limit = max(1, min(int(limit), 1000))

    item = db_client.get_item({
        'PK': f'testset#{test_set_id}',
        'SK': 'metadata'
    })
    if not item:
        raise Exception(f"Test set '{test_set_id}' not found")

    test_set_bucket = os.environ['TEST_SET_BUCKET']
    input_prefix = f"{test_set_id}/input/"

    list_kwargs = {
        'Bucket': test_set_bucket,
        # Exact-name prefix narrows the listing to (at most) the one document;
        # the objectKey equality check below drops same-prefix siblings.
        'Prefix': f"{input_prefix}{object_key}" if object_key else input_prefix,
        'MaxKeys': limit,
    }
    if next_token:
        list_kwargs['ContinuationToken'] = next_token
    response = s3_client.list_objects_v2(**list_kwargs)

    documents = []
    for obj in response.get('Contents', []):
        key = obj['Key']
        if key.endswith('/'):
            continue  # skip folder placeholder objects
        relative_name = key[len(input_prefix):]
        if object_key and relative_name != object_key:
            continue
        documents.append({
            'objectKey': relative_name,
            'inputKey': key,
            'size': obj.get('Size'),
            'lastModified': obj['LastModified'].isoformat(),
            'sections': [],
        })

    if documents:
        # Bulk-list baseline section files once and match to this page's docs.
        # Baseline layout: <id>/baseline/<relative_name>/sections/<n>/result.json
        baseline_prefix = f"{test_set_id}/baseline/"
        sections_by_doc = {d['objectKey']: d['sections'] for d in documents}
        section_re = re.compile(r'^(.+)/sections/([^/]+)/result\.json$')
        paginator = s3_client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=test_set_bucket, Prefix=baseline_prefix):
            for obj in page.get('Contents', []):
                rel = obj['Key'][len(baseline_prefix):]
                match = section_re.match(rel)
                if not match:
                    continue
                doc_name, section_id = match.groups()
                sections = sections_by_doc.get(doc_name)
                if sections is not None:
                    sections.append({
                        'sectionId': section_id,
                        'baselineKey': obj['Key'],
                    })

        # Sort sections numerically where possible so "10" doesn't precede "2"
        for doc in documents:
            doc['sections'].sort(
                key=lambda s: (0, int(s['sectionId']))
                if s['sectionId'].isdigit()
                else (1, s['sectionId'])
            )

    result = {
        'documents': documents,
        'nextToken': response.get('NextContinuationToken'),
    }
    logger.info(
        f"getTestSetDocuments({test_set_id}): {len(documents)} documents"
        f"{' (more available)' if result['nextToken'] else ''}"
    )
    return result


def _is_valid_test_set_structure(s3_client, bucket, prefix):
    """Check if prefix contains input/ and baseline/ folders.
    
    Also checks for a .uploading marker file which indicates the CLI is still
    uploading files. This prevents a race condition where the resolver auto-detects
    and validates a test set before all files (especially baselines) are uploaded.
    See: https://github.com/aws-solutions-library-samples/accelerated-intelligent-document-processing-on-aws/issues/193
    """
    try:
        # Check for upload-in-progress marker
        try:
            s3_client.head_object(Bucket=bucket, Key=f"{prefix}/.uploading")
            logger.info(f"Skipping {prefix} - upload in progress (.uploading marker found)")
            return False
        except Exception:
            pass  # No marker = not uploading, proceed with validation

        # Check for input/ folder
        input_response = s3_client.list_objects_v2(
            Bucket=bucket,
            Prefix=f"{prefix}/input/",
            MaxKeys=1
        )
        
        # Check for baseline/ folder  
        baseline_response = s3_client.list_objects_v2(
            Bucket=bucket,
            Prefix=f"{prefix}/baseline/",
            MaxKeys=1
        )
        
        has_input = input_response.get('KeyCount', 0) > 0
        has_baseline = baseline_response.get('KeyCount', 0) > 0
        
        return has_input and has_baseline
        
    except Exception as e:
        logger.error(f"Error checking test set structure for {prefix}: {str(e)}")
        return False

def _validate_test_set_files(s3_client, bucket, prefix):
    """Validate that input and baseline files match.
    
    Each input file must have a corresponding baseline folder with the exact same name
    (including extension). For example, input file 'doc.png' requires baseline folder 'doc.png/'.
    Any file extension is supported, and mixed extensions within a test set are allowed.
    """
    try:
        input_files = set()
        baseline_files = set()
        
        # Get input files
        paginator = s3_client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix}/input/"):
            for obj in page.get('Contents', []):
                key = obj['Key']
                if not key.endswith('/'):  # Skip directories
                    filename = key.split('/')[-1]
                    input_files.add(filename)
        
        # Get baseline folder names (first folder after /baseline/)
        for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix}/baseline/"):
            for obj in page.get('Contents', []):
                key = obj['Key']
                if not key.endswith('/'):  # Skip directories
                    # Extract folder name after /baseline/
                    parts = key.split(f"{prefix}/baseline/", 1)
                    if len(parts) == 2 and '/' in parts[1]:
                        # First path component is the baseline folder name
                        folder_name = parts[1].split('/')[0]
                        if folder_name:
                            baseline_files.add(folder_name)
        
        # Validate matching
        if len(input_files) == 0:
            return {'valid': False, 'error': 'No input files found', 'input_count': 0}
        
        if len(baseline_files) == 0:
            return {'valid': False, 'error': 'No baseline files found', 'input_count': len(input_files)}
        
        missing_baselines = input_files - baseline_files
        if missing_baselines:
            return {
                'valid': False, 
                'error': f'Missing baseline files for: {", ".join(list(missing_baselines)[:3])}{"..." if len(missing_baselines) > 3 else ""}',
                'input_count': len(input_files)
            }
        
        extra_baselines = baseline_files - input_files
        if extra_baselines:
            return {
                'valid': False,
                'error': f'Extra baseline files: {", ".join(list(extra_baselines)[:3])}{"..." if len(extra_baselines) > 3 else ""}',
                'input_count': len(input_files)
            }
        
        return {'valid': True, 'input_count': len(input_files)}
        
    except Exception as e:
        logger.error(f"Error validating test set files for {prefix}: {str(e)}")
        return {'valid': False, 'error': f'Validation error: {str(e)}', 'input_count': 0}

def _get_test_set_creation_time(s3_client, bucket, prefix):
    """Get the earliest creation time from files in the test set"""
    earliest_time = None
    
    # Check input folder for earliest file
    paginator = s3_client.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix}/input/", MaxKeys=10):
        for obj in page.get('Contents', []):
            if not obj['Key'].endswith('/'):  # Skip directories
                if earliest_time is None or obj['LastModified'] < earliest_time:
                    earliest_time = obj['LastModified']
    
    if earliest_time is None:
        raise Exception(f"No files found in {prefix}/input/ to determine creation time")
    
    return earliest_time.isoformat()

def _create_test_set_tracking_entry(test_set_id, name, file_count, status, error=None, created_at=None):
    """Create tracking table entry for direct upload test set"""
    try:
        now = datetime.utcnow().isoformat() + 'Z'
        item = {
            'PK': f'testset#{test_set_id}',
            'SK': 'metadata',
            'ItemType': 'testset',
            'InitialEventTime': now,
            'id': test_set_id,
            'name': name,
            'description': '',  # Direct uploads don't have descriptions
            'filePattern': '',
            'fileCount': file_count,
            'status': status,
            'createdAt': now
        }
        
        if error:
            item['error'] = error
        
        db_client.put_item(item)
        logger.info(f"Created tracking entry for direct upload test set {test_set_id}")
        
    except Exception as e:
        logger.error(f"Error creating tracking entry for {test_set_id}: {str(e)}")


def list_bucket_files(args):
    logger.info(f"Listing files with pattern: {args['filePattern']} from bucket type: {args['bucketType']}")

    file_pattern = args['filePattern']
    bucket_type = args['bucketType']
    modified_after = args.get('modifiedAfter')

    # Determine which bucket to use based on bucket type
    if bucket_type == 'input':
        bucket = os.environ['INPUT_BUCKET']
    elif bucket_type == 'testset':
        bucket = os.environ['TEST_SET_BUCKET']
    else:
        raise Exception(f"Invalid bucket type: {bucket_type}")

    files = find_matching_files(bucket, file_pattern, modified_after=modified_after)
    logger.info(f"Found {len(files)} matching files in {bucket_type} bucket")

    return files

def validate_test_file_name(args):
    logger.info(f"Validating test file name: {args['fileName']}")
    
    test_set_name = args['fileName']
    test_set_id = f"{test_set_name.replace(' ', '-').lower()}"
    
    # Check if test set already exists in tracking table
    try:
        item = db_client.get_item({
            'PK': f'testset#{test_set_id}',
            'SK': 'metadata'
        })
        
        if item:
            logger.info(f"Test set {test_set_id} already exists")
            return {
                'exists': True,
                'testSetId': test_set_id
            }
        else:
            logger.info(f"Test set {test_set_id} does not exist")
            return {
                'exists': False,
                'testSetId': None
            }
    except Exception as e:
        logger.error(f"Error checking test set existence: {str(e)}")
        return {
            'exists': False,
            'testSetId': None
        }
