# Copyright © Amazon.com and Affiliates: This deliverable is considered Developed Content as defined in the AWS Service Terms and the SOW between the parties.

import boto3
import os
import time
import json
import logging
import random
import io
from botocore.exceptions import ClientError
from PIL import Image
from get_config import get_config

CONFIG = get_config()

print("Boto3 version: ", boto3.__version__)

# TODO - consider minimizing retries in lambda / maximize in Step Functions for cost efficiency.
MAX_RETRIES = 8 # avoid 900sec Lambda time out. 
INITIAL_BACKOFF = 2  # seconds
MAX_BACKOFF = 300   # 5 minutes

METRIC_NAMESPACE = os.environ['METRIC_NAMESPACE']
OCR_TEXT_ONLY = os.environ.get('OCR_TEXT_ONLY', 'false').lower() == 'true'

# Initialize clients without adaptive retry
bedrock_client = boto3.client(service_name="bedrock-runtime")
cloudwatch_client = boto3.client('cloudwatch')
s3_client = boto3.client('s3')

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def calculate_backoff(attempt):
    """Calculate exponential backoff with jitter"""
    backoff = min(MAX_BACKOFF, INITIAL_BACKOFF * (2 ** attempt))
    jitter = random.uniform(0, 0.1 * backoff)  # 10% jitter # nosec B311
    return backoff + jitter

def put_metric(name, value, unit='Count', dimensions=None):
    dimensions = dimensions or []
    logger.info(f"Publishing metric {name}: {value}")
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

def invoke_llm(page_images, class_label, document_text):
    extraction_config = CONFIG["extraction"]
    model_id = extraction_config["model"]
    temperature = float(extraction_config["temperature"])
    top_k = float(extraction_config["top_k"])
    system_prompt = [{"text": extraction_config["system_prompt"]}]
    prompt_template = extraction_config["task_prompt"].replace("{DOCUMENT_TEXT}", "%(DOCUMENT_TEXT)s").replace("{DOCUMENT_CLASS}", "%(DOCUMENT_CLASS)s")
    task_prompt = prompt_template % {
        "DOCUMENT_TEXT": document_text,
        "DOCUMENT_CLASS": class_label
    }
    content = [{"text": task_prompt}]

    inference_config = {"temperature": temperature}
    if "anthropic" in model_id.lower():
        additional_model_fields = {"top_k": top_k}
    else:
        additional_model_fields = None

    # Bedrock currently supports max 20 image attachments
    # Per science team recommendation, we limit image attachments to 1st 20 pages.
    # TODO: Assess potential accuracy impact for longer documents, and if necessary consider alternate approaches 
    if len(page_images) > 20:
        page_images = page_images[:20] 
        logger.error(f"Number of pages in the document is greater than 20. Processing with only the first 20 pages")
    
    if page_images:
        logger.info(f"Attaching images to prompt, for {len(page_images)} pages.")
        for image in page_images:
            message = {"image": {
                "format": 'jpeg',
                "source": {"bytes": image}}}
            content.append(message)
    
    message = {
        "role": "user",
        "content": content
    }
    messages = [message]

    retry_count = 0
    last_exception = None
    request_start_time = time.time()

    # Track total requests
    put_metric('BedrockRequestsTotal', 1)

    while retry_count < MAX_RETRIES:
        try:
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
            
            logger.info(f"Bedrock request successful after {retry_count + 1} attempts. "
                       f"Duration: {duration:.2f}s")

            # Track successful requests and latency
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

            total_duration = time.time() - request_start_time
            put_metric('BedrockTotalLatency', total_duration * 1000, 'Milliseconds')

            entities = response['output']['message']['content'][0].get("text")
            return entities

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            if error_code in ['ThrottlingException', 'ServiceQuotaExceededException', 
                            'RequestLimitExceeded', 'TooManyRequestsException']:
                retry_count += 1
                put_metric('BedrockThrottles', 1)
                
                if retry_count == MAX_RETRIES:
                    logger.error(f"Max retries ({MAX_RETRIES}) exceeded. Last error: {error_message}")
                    put_metric('BedrockRequestsFailed', 1)
                    put_metric('BedrockMaxRetriesExceeded', 1)
                    raise
                
                backoff = calculate_backoff(retry_count)
                logger.warning(f"Bedrock throttling occurred (attempt {retry_count}/{MAX_RETRIES}). "
                             f"Error: {error_message}. "
                             f"Backing off for {backoff:.2f}s")
                
                time.sleep(backoff) # semgrep-ignore: arbitrary-sleep - Intentional delay backoff/retry. Duration is algorithmic and not user-controlled.
                last_exception = e
            else:
                logger.error(f"Non-retryable Bedrock error: {error_code} - {error_message}")
                put_metric('BedrockRequestsFailed', 1)
                put_metric('BedrockNonRetryableErrors', 1)
                raise

        except Exception as e:
            logger.error(f"Unexpected error invoking Bedrock: {str(e)}", exc_info=True)
            put_metric('BedrockRequestsFailed', 1)
            put_metric('BedrockUnexpectedErrors', 1)
            raise

    if last_exception:
        raise last_exception


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

def write_json_to_s3(json_string, bucket_name, object_key):
    s3_client.put_object(
        Bucket=bucket_name,
        Key=object_key,
        Body=json_string,
        ContentType='application/json'
    )
    logger.info(f"JSON file successfully written to s3://{bucket_name}/{object_key}")

def handler(event, context):
    """
    Input event for single document / section of given type:
    {
        "output_bucket": <BUCKET>,
        "metadata": {
            "input_bucket": <BUCKET>,
            "object_key": <KEY>,
            "output_bucket": <BUCKET>,
            "output_prefix": <PREFIX>,
            "num_pages": <NUMBER OF PAGES IN ORIGINAL INPUT DOC>
        },
        "execution_arn": <ARN>,
        "section": {
            "id": <ID>,
            "class": <TYPE or CLASS>,
            "pages": [
                {
                    "page_id": <NUM>,
                    "class": <TYPE or CLASS>,
                    "rawTextUri": <S3_URI>,
                    "parsedTextUri": <S3_URI>,
                    "imageUri": <S3_URI>
                }
            ]
        }
    }
    """
    logger.info(f"Event: {json.dumps(event)}")
    logger.info(f"Config: {json.dumps(CONFIG)}")  
    
    # Get parameters from event
    metadata = event.get("metadata")
    section = event.get("section")
    output_bucket = event.get("output_bucket")   
    object_key = metadata.get("object_key")
    class_label = section.get("class")
    pages = section.get("pages")
    page_ids = [page['page_id'] for page in pages]
    output_prefix = object_key


    # Sort pages by page number
    sorted_page_ids = sorted([page['page_id'] for page in section['pages']], key=int)
    start_page = int(sorted_page_ids[0])
    end_page = int(sorted_page_ids[-1])
    logger.info(f"Processing {len(sorted_page_ids)} pages from {object_key} {section}, class {class_label}: {start_page}-{end_page}")

    # Read document text from all pages in order
    t0 = time.time()
    document_texts = []
    for page in sorted(section['pages'], key=lambda x: int(x['page_id'])):
        text_path = page['parsedTextUri']
        page_text = get_text_content(text_path)
        document_texts.append(page_text)
    
    document_text = '\n'.join(document_texts)
    t1 = time.time()
    logger.info(f"Time taken to read text content: {t1-t0:.2f} seconds")

    # Read page images
    page_images = []
    for page in sorted(section['pages'], key=lambda x: int(x['page_id'])):
        imageUri = page['imageUri']
        image_content = get_image_content(imageUri)
        page_images.append(image_content)
    
    t2 = time.time()
    logger.info(f"Time taken to read images: {t2-t1:.2f} seconds")

    # Process with LLM
    extracted_entities_str = invoke_llm(
        page_images,
        class_label,
        document_text
        )
    t3 = time.time()
    logger.info(f"Time taken by bedrock: {t3-t2:.2f} seconds")

    try:
        extracted_entities = json.loads(extracted_entities_str)
    except Exception as e:
        logger.error(f"Error parsing LLM output - invalid JSON?: {extracted_entities_str} - {e}")
        logger.info(f"UsIng unparsed LLM output.")
        extracted_entities = extracted_entities_str

    # Write results - emulate BDA for pattern consistency
    output = {
        "document_class": {
            "type": class_label
        },
        "split_document": {
            "page_indices": page_ids
        },
        "inference_result": extracted_entities
    }
    output_key = f"{output_prefix}/sections/{section['id']}/result.json"
    write_json_to_s3(json.dumps(output), output_bucket, output_key)
    
    # Track metrics
    put_metric('InputDocuments', 1)
    put_metric('InputDocumentPages', len(pages))
    

    result = {
        "section": {
            "id": section['id'],
            "class": section['class'],
            "page_ids": page_ids,
            "outputJSONUri": f"s3://{output_bucket}/{output_key}",
        },
        "pages": pages
    }
    
    return result