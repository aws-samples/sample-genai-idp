import boto3
import os
import json
import time
import random
import logging
import io
from PIL import Image
from botocore.exceptions import ClientError
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from get_config import get_config


# Configuration
CONFIG = get_config()
MAX_RETRIES = 8 
INITIAL_BACKOFF = 2  # seconds
MAX_BACKOFF = 300   # 5 minutes
MAX_WORKERS = 20     # Adjust based on your needs

region = os.environ['AWS_REGION']
METRIC_NAMESPACE = os.environ['METRIC_NAMESPACE']

# Initialize clients
bedrock_client = boto3.client('bedrock-runtime', region_name=region)
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
    with metric_lock:
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

def get_text_content(s3path):
    """Read text content from a single S3 path"""
    try:
        # Extract key from s3:// URL
        _, _, bucket, *key_parts = s3path.split('/')
        key = '/'.join(key_parts)
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = json.loads(response['Body'].read().decode('utf-8'))
        return content.get('text', '')
    except Exception as e:
        logger.error(f"Error reading text from {s3path}: {e}")
        raise

def get_image_content(s3path, target_width=951, target_height=1268):
    """Read and process a single image from S3"""
    try:
        _, _, bucket, *key_parts = s3path.split('/')
        key = '/'.join(key_parts)
        response = s3_client.get_object(Bucket=bucket, Key=key)
        image_data = response['Body'].read()
        
        image = Image.open(io.BytesIO(image_data))
        current_width, current_height = image.size
        current_resolution = current_width * current_height
        target_resolution = target_width * target_height
        
        if current_resolution > target_resolution:
            logger.info(f"Downsizing image from {current_width}x{current_height}")
            image = image.resize((target_width, target_height))
        
        img_byte_array = io.BytesIO()
        image.save(img_byte_array, format="JPEG")
        return img_byte_array.getvalue()
        
    except Exception as e:
        logger.error(f"Error reading image from {s3path}: {e}")
        raise


def classify_single_page(page_id, page_data):
    """Classify a single page using Bedrock"""
    retry_count = 0
    last_exception = None

    # Read text content from S3
    text_content = get_text_content(page_data['parsedTextUri'])
    image_content = get_image_content(page_data['imageUri'])

    classification_config = CONFIG["classification"]
    model_id = classification_config["model"]
    temperature = float(classification_config["temperature"])
    top_k = float(classification_config["top_k"])
    system_prompt = [{"text": classification_config["system_prompt"]}]
    prompt_template = classification_config["task_prompt"].replace("{DOCUMENT_TEXT}", "%(DOCUMENT_TEXT)s")
    task_prompt = prompt_template % {
        "DOCUMENT_TEXT": text_content
    }
    content = [{"text": task_prompt}]

    inference_config = {"temperature": temperature}
    if "anthropic" in model_id.lower():
        additional_model_fields = {"top_k": top_k}
    else:
        additional_model_fields = None
    message = {"image": {
        "format": 'jpeg',
        "source": {"bytes": image_content}}}
    content.append(message)
    message = {
        "role": "user",
        "content": content
    }
    messages = [message]
    
    while retry_count < MAX_RETRIES:
        try:
            logger.info(f"Classifying page {page_id}, {page_data}")
            
            # Invoke Bedrock
            logger.info(f"Bedrock request attempt {retry_count + 1}/{MAX_RETRIES} - "
                       f"model: {model_id}, "
                       f"inferenceConfig: {inference_config}, "
                       f"additionalFields: {additional_model_fields}")
            attempt_start_time = time.time()
            response = bedrock_client.converse(
                modelId=model_id,
                messages=messages,
                system=system_prompt,
                inferenceConfig=inference_config,
                additionalModelRequestFields=additional_model_fields
            )
            duration = time.time() - attempt_start_time
            
            # Log success metrics
            logger.info(f"Page {page_id} classification successful after {retry_count + 1} attempts. "
                       f"Duration: {duration:.2f}s")
            put_metric('BedrockRequestsSucceeded', 1)
            put_metric('BedrockRequestLatency', duration * 1000, 'Milliseconds')
            if retry_count > 0:
                put_metric('BedrockRetrySuccess', 1)

            # Track token usage
            if 'usage' in response:
                input_tokens = response['usage'].get('inputTokens', 0)
                output_tokens = response['usage'].get('outputTokens', 0)
                total_tokens = response['usage'].get('totalTokens', 0)
                put_metric('InputTokens', input_tokens)
                put_metric('OutputTokens', output_tokens)
                put_metric('TotalTokens', total_tokens)
            
            # Return classification results along with page data
            classification_json = response['output']['message']['content'][0].get("text")
            final_classification = json.loads(classification_json).get("class", "Unknown")
            logger.info(f"Page {page_id} classified as {final_classification}")
            return {
                'page_id': page_id,
                'class': final_classification,
                **page_data
            }
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            if error_code in ['ThrottlingException', 'ServiceQuotaExceededException',
                            'RequestLimitExceeded', 'TooManyRequestsException']:
                retry_count += 1
                put_metric('BedrockThrottles', 1)
                
                if retry_count == MAX_RETRIES:
                    logger.error(f"Max retries ({MAX_RETRIES}) exceeded for page {page_id}. "
                               f"Last error: {error_message}")
                    put_metric('BedrockRequestsFailed', 1)
                    put_metric('BedrockMaxRetriesExceeded', 1)
                    raise
                
                backoff = calculate_backoff(retry_count)
                logger.warning(f"Classification throttling occurred for page {page_id} "
                             f"(attempt {retry_count}/{MAX_RETRIES}). "
                             f"Error: {error_message}. "
                             f"Backing off for {backoff:.2f}s")
                
                time.sleep(backoff) # semgrep-ignore: arbitrary-sleep - Intentional delay backoff/retry. Duration is algorithmic and not user-controlled.
                last_exception = e
            else:
                logger.error(f"Non-retryable classification error for page {page_id}: "
                           f"{error_code} - {error_message}")
                put_metric('BedrockRequestsFailed', 1)
                put_metric('BedrockNonRetryableErrors', 1)
                raise
                
        except Exception as e:
            logger.error(f"Unexpected error classifying page {page_id}: {e}", 
                       exc_info=True)
            put_metric('BedrockRequestsFailed', 1)
            put_metric('BedrockUnexpectedErrors', 1)
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
    sorted_results = sorted(results, key=lambda x: x['page_id'])
    sections = []
    current_group = 1
    
    if not sorted_results:
        return sections
        
    current_class = sorted_results[0]['class']
    current_pages = [sorted_results[0]]
    
    for result in sorted_results[1:]:
        if result['class'] == current_class:
            current_pages.append(result)
        else:
            sections.append({
                'id': f"{current_group}",
                'class': current_class,
                'pages': current_pages
            })
            current_group += 1
            current_class = result['class']
            current_pages = [result]
    
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
        for page_num, page_data in pages.items():
            future = executor.submit(classify_single_page, page_num, page_data)
            futures.append(future)
        
        for future in as_completed(futures):
            try:
                result = future.result()
                all_results.append(result)
            except Exception as e:
                logger.error(f"Error in concurrent classification: {str(e)}")
                raise
    
    return all_results

def handler(event, context):
    """Lambda handler function"""
    logger.info(f"Event: {json.dumps(event)}")
    logger.info(f"Config: {json.dumps(CONFIG)}")  
    
    metadata = event.get("OCRResult", {}).get("metadata")
    pages = event.get("OCRResult", {}).get("pages")

    if not all([metadata, pages]):
        raise ValueError("Missing required parameters in event")

    t0 = time.time()
    
    total_pages = len(pages)
    put_metric('BedrockRequestsTotal', total_pages)
    
    all_results = classify_pages_concurrently(pages)
    
    t1 = time.time()
    logger.info(f"Time taken for classification: {t1-t0:.2f} seconds")

    sections = group_consecutive_pages(all_results)
    
    response = {
        "metadata": metadata,
        "sections": sections
    }

    return response