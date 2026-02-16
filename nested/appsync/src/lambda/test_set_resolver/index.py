import uuid
import json
import logging
from datetime import datetime
import os
import boto3
import re
from botocore.config import Config
from idp_common.s3 import find_matching_files  # type: ignore
from idp_common.dynamodb import DynamoDBClient  # type: ignore

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
    """Validate description: max 200 chars only"""
    if description is None or description == "":
        return True  # Optional field
    if not isinstance(description, str):
        return False
    return len(description) <= 200

# Configure S3 client with S3v4 signature
s3_config = Config(
    signature_version='s3v4',
    s3={'addressing_style': 'path'}
)
s3_client = boto3.client('s3', config=s3_config)
db_client = DynamoDBClient(table_name=os.environ['TRACKING_TABLE'])

def handler(event, context):
    field_name = event['info']['fieldName']
    logger.info(f"Test set resolver invoked with field_name: {field_name}")
    
    if field_name == 'addTestSet':
        return add_test_set(event['arguments'])
    elif field_name == 'addTestSetFromUpload':
        return add_test_set_from_upload(event['arguments'])
    elif field_name == 'deleteTestSets':
        return delete_test_sets(event['arguments'])
    elif field_name == 'getTestSets':
        return get_test_sets()
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
        raise Exception("Description cannot exceed 200 characters")
    
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
        'id': test_set_id,
        'name': test_set_name,
        'description': description,
        'filePattern': '',  # Empty for uploaded test sets
        'status': 'QUEUED',
        'createdAt': now
    }
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
    
    # Validate test set name
    if not validate_test_set_name(test_set_name):
        raise Exception("Test set name can only contain letters, numbers, spaces, hyphens, and underscores (max 50 characters)")
    
    # Validate description
    if description and not validate_description(description):
        raise Exception("Description cannot exceed 200 characters")
    
    # Generate test set ID with name format, replace spaces with dashes
    test_set_id = f"{test_set_name.replace(' ', '-').lower()}"
    
    # Create initial test set record
    now = datetime.utcnow().isoformat() + 'Z'
    
    item = {
        'PK': f'testset#{test_set_id}',
        'SK': 'metadata',
        'id': test_set_id,
        'name': test_set_name,
        'description': description,
        'filePattern': args['filePattern'],
        'fileCount': file_count,
        'status': 'QUEUED',
        'createdAt': now
    }
    
    db_client.put_item(item)
    logger.info(f"Created test set {test_set_id} in tracking table")
    
    # Send file copying job to SQS queue
    import boto3
    sqs = boto3.client('sqs')
    queue_url = os.environ['TEST_SET_COPY_QUEUE_URL']
    
    sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps({
            'testSetId': test_set_id,
            'filePattern': args['filePattern'],
            'bucketType': args['bucketType'],
            'trackingTable': os.environ['TRACKING_TABLE']
        })
    )
    
    logger.info(f"Queued test set creation job for {test_set_id} with pattern '{args['filePattern']}'")
    
    return {
        'id': test_set_id,
        'name': test_set_name,
        'description': description,
        'filePattern': args['filePattern'],
        'fileCount': file_count,
        'status': 'QUEUED',
        'createdAt': now
    }

def delete_test_sets(args):
    logger.info(f"Deleting test sets: {args['testSetIds']}")
    
    test_set_ids = args['testSetIds']
    test_set_bucket = os.environ['TEST_SET_BUCKET']
    
    for test_set_id in test_set_ids:
        # Delete files from test set bucket
        try:
            # List all objects with test_set_id prefix
            response = s3_client.list_objects_v2(
                Bucket=test_set_bucket,
                Prefix=f"{test_set_id}/"
            )
            
            if 'Contents' in response:
                # Delete all objects in the test set folder
                objects_to_delete = [{'Key': obj['Key']} for obj in response['Contents']]
                
                if objects_to_delete:
                    s3_client.delete_objects(
                        Bucket=test_set_bucket,
                        Delete={'Objects': objects_to_delete}
                    )
                    logger.info(f"Deleted {len(objects_to_delete)} files for test set {test_set_id}")
            
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
    
    # Get existing test sets from DynamoDB
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
        test_set_id = item['id']
        existing_test_sets[test_set_id] = item
        result.append({
            'id': test_set_id,
            'name': item['name'],
            'description': item.get('description', ''),
            'filePattern': item.get('filePattern', ''),
            'fileCount': item.get('fileCount'),  # Returns None if attribute doesn't exist
            'status': item.get('status'),
            'createdAt': item['createdAt'],
            'error': item.get('error')  # Include error message for failed test sets
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
                        'createdAt': created_at
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

def _is_valid_test_set_structure(s3_client, bucket, prefix):
    """Check if prefix contains input/ and baseline/ folders"""
    try:
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
        item = {
            'PK': f'testset#{test_set_id}',
            'SK': 'metadata',
            'id': test_set_id,
            'name': name,
            'description': '',  # Direct uploads don't have descriptions
            'filePattern': '',
            'fileCount': file_count,
            'status': status,
            'createdAt': datetime.utcnow().isoformat() + 'Z'
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
    
    # Determine which bucket to use based on bucket type
    if bucket_type == 'input':
        bucket = os.environ['INPUT_BUCKET']
    elif bucket_type == 'testset':
        bucket = os.environ['TEST_SET_BUCKET']
    else:
        raise Exception(f"Invalid bucket type: {bucket_type}")
    
    files = find_matching_files(bucket, file_pattern)
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
