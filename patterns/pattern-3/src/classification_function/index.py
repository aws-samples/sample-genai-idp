import boto3
import os
import json
import time
import random
import logging
from botocore.exceptions import ClientError
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

print("Boto3 version: ", boto3.__version__)

# Retry configuration
MAX_RETRIES = 8 
INITIAL_BACKOFF = 2  # seconds
MAX_BACKOFF = 300   # 5 minutes
MAX_WORKERS = 20     # Adjust based on your needs and endpoint capacity

region = os.environ['AWS_REGION']
METRIC_NAMESPACE = os.environ['METRIC_NAMESPACE']

# Initialize clients
sm_client = boto3.client('sagemaker-runtime', region_name=region)
cloudwatch_client = boto3.client('cloudwatch', region_name=region)
s3_client = boto3.client('s3', region_name=region)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Add thread-safe metric publishing
metric_lock = Lock()

def calculate_backoff(attempt):
    """Calculate exponential backoff with jitter"""
    backoff = min(MAX_BACKOFF, INITIAL_BACKOFF * (2 ** attempt))
    jitter = random.uniform(0, 0.1 * backoff)  # 10% jitter # nosec B311
    return backoff + jitter

def put_metric(name, value, unit='Count', dimensions=None):
    dimensions = dimensions or []
    logger.info(f"Publishing metric {name}: {value}")
    with metric_lock:  # Ensure thread-safe metric publishing
        try:
            cloudwatch_client.put_metric_data(
                Namespace=f'{METRIC_NAMESPACE}',
                MetricData=[{
                    'MetricName': name,
                    'Value': value,
                    'Unit': unit,
                    'Dimensions': dimensions
                }]
            )
        except Exception as e:
            logger.error(f"Error publishing metric {name}: {e}")

def classify_single_page(page_id, page_data):
    """Classify a single page using the UDOP model"""
    retry_count = 0
    last_exception = None
    
    while retry_count < MAX_RETRIES:
        try:
            logger.info(f"Classifying page {page_id}")
            
            # Prepare inference payload
            payload = {
                "input_image": page_data['imageUri'],
                "input_textract": page_data['rawTextUri'],
                "prompt": '',
                "debug": 0
            }
            logger.info(f"Payload: {payload}")
            
            # Invoke endpoint
            attempt_start_time = time.time()
            response = sm_client.invoke_endpoint(
                EndpointName=os.environ['SAGEMAKER_ENDPOINT_NAME'],
                ContentType='application/json',
                Body=json.dumps(payload)
            )
            duration = time.time() - attempt_start_time
            
            # Parse response
            response_body = json.loads(response['Body'].read().decode())
            logger.info(f"Response body: {response_body}")
            
            # Log success metrics
            logger.info(f"Page {page_id} classification successful after {retry_count + 1} attempts. "
                       f"Duration: {duration:.2f}s")
            put_metric('ClassificationRequestsSucceeded', 1)
            put_metric('ClassificationLatency', duration * 1000, 'Milliseconds')
            if retry_count > 0:
                put_metric('ClassificationRetrySuccess', 1)
            
            # Return classification results along with page data
            return {
                'page_id': page_id,
                'class': response_body['prediction'],
                **page_data
            }     
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            if error_code in ['ThrottlingException', 'ServiceQuotaExceededException',
                            'RequestLimitExceeded', 'TooManyRequestsException']:
                retry_count += 1
                put_metric('ClassificationThrottles', 1)
                
                if retry_count == MAX_RETRIES:
                    logger.error(f"Max retries ({MAX_RETRIES}) exceeded for page {page_id}. "
                               f"Last error: {error_message}")
                    put_metric('ClassificationRequestsFailed', 1)
                    put_metric('ClassificationMaxRetriesExceeded', 1)
                    raise
                
                backoff = calculate_backoff(retry_count)
                logger.warning(f"Classification throttling occurred for page {page_id} "
                             f"(attempt {retry_count}/{MAX_RETRIES}). "
                             f"Error: {error_message}. "
                             f"Backing off for {backoff:.2f}s")
                
                time.sleep(backoff)  # semgrep-ignore: arbitrary-sleep - Intentional delay backoff/retry. Duration is algorithmic and not user-controlled.
                last_exception = e
            else:
                logger.error(f"Non-retryable classification error for page {page_id}: "
                           f"{error_code} - {error_message}")
                put_metric('ClassificationRequestsFailed', 1)
                put_metric('ClassificationNonRetryableErrors', 1)
                raise
                
        except Exception as e:
            logger.error(f"Unexpected error classifying page {page_id}: {str(e)}", 
                       exc_info=True)
            put_metric('ClassificationRequestsFailed', 1)
            put_metric('ClassificationUnexpectedErrors', 1)
            raise
            
    if last_exception:
        raise last_exception

def write_json_to_s3(json_string, bucket_name, object_key):
    s3_client.put_object(
        Bucket=bucket_name,
        Key=object_key,
        Body=json_string,
        ContentType='application/json'
    )
    logger.info(f"JSON file successfully written to s3://{bucket_name}/{object_key}")

def group_consecutive_pages(results):
    """
    Group consecutive pages with the same classification into sections.
    Returns a list of sections, each containing an id, class, and pages.
    """
    # Sort results by page number to ensure proper consecutive grouping
    sorted_results = sorted(results, key=lambda x: x['page_id'])
    
    sections = []
    current_group = 1
    
    if not sorted_results:
        return sections
        
    # Initialize with first result
    current_class = sorted_results[0]['class']
    current_pages = [sorted_results[0]]
    
    # Process remaining results
    for result in sorted_results[1:]:
        if result['class'] == current_class:
            # Add to current group if same class
            current_pages.append(result)
        else:
            # Store current group and start new one
            sections.append({
                'id': f"{current_group}",
                'class': current_class,
                'pages': current_pages
            })
            current_group += 1
            current_class = result['class']
            current_pages = [result]
    
    # Store final group
    sections.append({
        'id': f"{current_group}",
        'class': current_class,
        'pages': current_pages
    })
    
    return sections

def classify_pages_concurrently(pages):
    """Classify multiple pages concurrently using a thread pool"""
    all_results = []
    futures = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all classification tasks
        for page_num, page_data in pages.items():
            future = executor.submit(classify_single_page, page_num, page_data)
            futures.append(future)
        
        # Collect results as they complete
        for future in as_completed(futures):
            try:
                result = future.result()
                all_results.append(result)
            except Exception as e:
                logger.error(f"Error in concurrent classification: {str(e)}")
                raise
    
    return all_results

def handler(event, context):
    """
    Input event containing page level OCR and image data from OCR step:
    {
        "execution_arn": <ARN>,
        "output_bucket": <BUCKET>,
        "OCRResult": {
            "metadata": {
                "input_bucket": <BUCKET>,
                "object_key": <KEY>,
                "output_bucket": <BUCKET>,
                "output_prefix": <PREFIX>,
                "num_pages": <NUMBER OF PAGES IN ORIGINAL INPUT DOC>,
                "metering: {"<service_api>": {"<unit>": <value>}}
            }
        },
        "pages": {
            <ID>: {
                        "rawTextUri": <S3_URI>,
                        "parsedTextUri": <S3_URI>,
                        "imageUri": <S3_URI>
            }
        }
    }
    """
    logger.info(f"Event: {json.dumps(event)}")
    
    # Get parameters from event
    metadata = event.get("OCRResult", {}).get("metadata")
    pages = event.get("OCRResult", {}).get("pages")

    if not all([metadata, pages]):
        raise ValueError("Missing required parameters in event")

    t0 = time.time()
    
    # Track total classification requests
    total_pages = len(pages)
    put_metric('ClassificationRequestsTotal', total_pages)
    
    # Classify pages concurrently
    all_results = classify_pages_concurrently(pages)
    
    t1 = time.time()
    logger.info(f"Time taken for classification: {t1-t0:.2f} seconds")

    # Group consecutive pages with same classification
    sections = group_consecutive_pages(all_results)
    
    response = {
        "metadata": metadata,
        "sections": sections
    }

    return response