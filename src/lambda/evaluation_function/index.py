import json
import os
import boto3
import logging
import time
from appsync_helper import AppSyncClient, UPDATE_DOCUMENT
from typing import Dict, List, Any
from botocore.exceptions import ClientError


# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Get bucket names from environment variables
METRIC_NAMESPACE = os.environ['METRIC_NAMESPACE']
BASELINE_BUCKET = os.environ['BASELINE_BUCKET']
PROCESSING_OUTPUT_BUCKET = os.environ['PROCESSING_OUTPUT_BUCKET']
EVALUATION_OUTPUT_BUCKET = os.environ['EVALUATION_OUTPUT_BUCKET']

# Model
EVALUATION_MODEL_ID = os.environ['EVALUATION_MODEL_ID']

# Retry config
MAX_RETRIES = 8 # avoid 900sec Lambda time out. 
INITIAL_BACKOFF = 2  # seconds
MAX_BACKOFF = 300   # 5 minutes

bedrock_client = boto3.client(service_name="bedrock-runtime")
cloudwatch_client = boto3.client('cloudwatch')
s3_client = boto3.client('s3')
appsync = AppSyncClient()

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

def load_json_from_s3(s3_client, bucket: str, key: str) -> Dict:
    """Load JSON file from S3"""
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        return json.loads(response['Body'].read().decode('utf-8'))
    except Exception as e:
        logger.error(f"Error loading {key} from {bucket}: {str(e)}")
        return None

def get_section_files(s3_client, bucket: str, prefix: str) -> List[str]:
    """Get list of section result files under given prefix"""
    try:
        # Append sections subfolder to the prefix
        sections_prefix = f"{prefix}/sections"
        response = s3_client.list_objects_v2(Bucket=bucket, Prefix=sections_prefix)
        files = []
        for obj in response.get('Contents', []):
            if obj['Key'].endswith('result.json'):
                files.append(obj['Key'])
        return sorted(files)
    except Exception as e:
        logger.error(f"Error listing files in {bucket}/{prefix}: {str(e)}")
        return []

def compare_sections(baseline: Dict, processing: Dict) -> Dict:
    """Compare section classification and page numbers"""
    comparison = {
        "section_type_match": baseline["document_class"]["type"] == processing["document_class"]["type"],
        "baseline_type": baseline["document_class"]["type"],
        "processing_type": processing["document_class"]["type"],
        "page_numbers_match": baseline["split_document"]["page_indices"] == processing["split_document"]["page_indices"],
        "baseline_pages": baseline["split_document"]["page_indices"],
        "processing_pages": processing["split_document"]["page_indices"]
    }
    
    logger.debug(f"Section comparison results: {json.dumps(comparison, indent=2)}")
    return comparison

def compare_inference_results(baseline: Dict, processing: Dict) -> List[Dict]:
    """Compare extracted information fields"""
    differences = []
    baseline_inf = baseline["inference_result"]
    processing_inf = processing["inference_result"]
    
    # Compare all fields
    all_keys = set(baseline_inf.keys()) | set(processing_inf.keys())
    
    for key in all_keys:
        baseline_value = baseline_inf.get(key)
        processing_value = processing_inf.get(key)
        
        if baseline_value != processing_value:
            difference = {
                "field": key,
                "baseline": baseline_value,
                "processing": processing_value
            }
            differences.append(difference)
            logger.debug(f"Found difference in field {key}: {json.dumps(difference, indent=2)}")
    
    logger.info(f"Found {len(differences)} differences in inference results")
    return differences

def generate_evaluation_prompt(section_comparisons: List[Dict], inference_differences: List[Dict]) -> str:
    """Generate prompt for LLM to analyze differences"""
    logger.info("Generating evaluation prompt")
    
    prompt = """Please analyze the following document processing accuracy results and generate a detailed evaluation report.
    Focus on:
    1. Section classification and page number accuracy
    2. Extracted information accuracy, specifically:
       - Most commonly different fields
       - Whether differences are substantial (affecting meaning/operations) or cosmetic (formatting)
       - Patterns in the differences
       - Potential data quality issues or concerns
    
    Section Comparisons:
    """
    
    # Add section comparison details
    for idx, comp in enumerate(section_comparisons):
        prompt += f"\nSection {idx}:\n"
        prompt += f"Type Match: {comp['section_type_match']}\n"
        prompt += f"Baseline Type: {comp['baseline_type']}, Processing Type: {comp['processing_type']}\n"
        prompt += f"Page Numbers Match: {comp['page_numbers_match']}\n"
        prompt += f"Baseline Pages: {comp['baseline_pages']}, Processing Pages: {comp['processing_pages']}\n"
    
    prompt += "\nField Differences:\n"
    
    # Add inference differences details
    for diff in inference_differences:
        prompt += f"\nField: {diff['field']}\n"
        prompt += f"Baseline: {diff['baseline']}\n"
        prompt += f"Processing: {diff['processing']}\n"
    
    prompt += "\nPlease provide the analysis in markdown format suitable for web display."
    
    logger.debug(f"Generated prompt: {prompt}")
    return prompt

def invoke_llm(bedrock_client, prompt: str) -> str:
    """Invoke Claude via Amazon Bedrock"""
    retry_count = 0
    last_exception = None
    
    while retry_count < MAX_RETRIES:
        try:            
            # Prepare inference payload
            inference_config = {"temperature": 0}
            if EVALUATION_MODEL_ID.startswith("us.anthropic"):
                additional_model_fields = {"top_k": 200}
            else:
                additional_model_fields = None
            content = [{"text": prompt}]
            message = {
                "role": "user",
                "content": content
            }
            messages = [message]
            
            # Invoke Bedrock
            logger.info(f"Bedrock request attempt {retry_count + 1}/{MAX_RETRIES} - "
                       f"model: {EVALUATION_MODEL_ID}, "
                       f"inferenceConfig: {inference_config}, "
                       f"additionalFields: {additional_model_fields}")
            attempt_start_time = time.time()
            response = bedrock_client.converse(
                modelId=EVALUATION_MODEL_ID,
                messages=messages,
                inferenceConfig=inference_config,
                additionalModelRequestFields=additional_model_fields
            )
            duration = time.time() - attempt_start_time
            
            # Log success metrics
            logger.info(f"Evaluation inference successful after {retry_count + 1} attempts. "
                       f"Duration: {duration:.2f}s")
            put_metric('EvaluationRequestsSucceeded', 1)
            put_metric('EvaluationLatency', duration * 1000, 'Milliseconds')
            if retry_count > 0:
                put_metric('EvaluationRetrySuccess', 1)

            # Track token usage
            if 'usage' in response:
                input_tokens = response['usage'].get('inputTokens', 0)
                output_tokens = response['usage'].get('outputTokens', 0)
                total_tokens = response['usage'].get('totalTokens', 0)
                put_metric('InputTokens', input_tokens)
                put_metric('OutputTokens', output_tokens)
                put_metric('TotalTokens', total_tokens)
            
            # Return evaluation results
            evaluation_response = response['output']['message']['content'][0].get("text")
            logger.info("Successfully received evaluation from Claude")
            return evaluation_response
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            if error_code in ['ThrottlingException', 'ServiceQuotaExceededException',
                            'RequestLimitExceeded', 'TooManyRequestsException']:
                retry_count += 1
                put_metric('EvaluationThrottles', 1)
                
                if retry_count == MAX_RETRIES:
                    logger.error(f"Max retries ({MAX_RETRIES}) exceeded. "
                               f"Last error: {error_message}")
                    put_metric('EvaluationRequestsFailed', 1)
                    put_metric('EvaluationMaxRetriesExceeded', 1)
                    raise
                
                backoff = calculate_backoff(retry_count)
                logger.warning(f"Evaluation throttling occurred: "
                             f"(attempt {retry_count}/{MAX_RETRIES}). "
                             f"Error: {error_message}. "
                             f"Backing off for {backoff:.2f}s")
                
                time.sleep(backoff) # semgrep-ignore: arbitrary-sleep - Intentional delay backoff/retry. Duration is algorithmic and not user-controlled.
                last_exception = e
            else:
                logger.error(f"Non-retryable evaluation error: "
                           f"{error_code} - {error_message}")
                put_metric('EvaluationRequestsFailed', 1)
                put_metric('EvaluationNonRetryableErrors', 1)
                raise
                
        except Exception as e:
            logger.error(f"Unexpected error evaluating results: {e}", 
                       exc_info=True)
            put_metric('EvaluationRequestsFailed', 1)
            put_metric('EvaluationUnexpectedErrors', 1)
            raise
            
    if last_exception:
        raise last_exception

def write_report_to_s3(s3_client, bucket: str, key: str, report: str):
    """Write evaluation report to S3"""
    try:
        logger.info(f"Writing evaluation report to s3://{bucket}/{key}")
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=report.encode('utf-8'),
            ContentType='text/markdown'
        )
        logger.info("Successfully wrote evaluation report")
    except Exception as e:
        logger.error(f"Error writing report to {bucket}/{key}: {str(e)}")

def extract_object_key(event: Dict) -> str:
    """Extract object key from the event structure"""
    try:
        # Parse the nested JSON string in the input field
        input_json = json.loads(event['detail']['input'])
        # Extract the object key
        object_key = input_json['detail']['object']['key']
        return object_key
    except Exception as e:
        logger.error(f"Error extracting object key from event: {str(e)}")
        raise ValueError(f"Invalid event structure: {str(e)}")

def update_document_tracker(object_key: str, evaluationReportUri: str) -> Dict[str, Any]:
    """
    Update document status via AppSync
    
    Args:
        object_key: The document key
        evaluationReportUri: S3 path to generated evaluation report
        
    Returns:
        The updated document data
        
    Raises:
        AppSyncError: If the GraphQL operation fails
    """
    update_input = {
        'input': {
            'ObjectKey': object_key,
            'EvaluationReportUri': evaluationReportUri
        }
    }
    
    logger.info(f"Updating document via AppSync: {update_input}")
    result = appsync.execute_mutation(UPDATE_DOCUMENT, update_input)
    return result['updateDocument']


def handler(event, context):
    try:
        logger.info(f"Starting evaluation process with event: {json.dumps(event, indent=2)}")
               
        # Extract object key from event
        object_key = extract_object_key(event)
        logger.info(f"Extracted object_key: {object_key}")
        
        # Get list of section files
        baseline_files = get_section_files(s3_client, BASELINE_BUCKET, object_key)
        logger.info(f"Found {len(baseline_files)} section files to process")

        isBaselineDataReady = len(baseline_files) > 0

        if not isBaselineDataReady:
            logger.info(f"No baseline data found for {object_key}. Skipping evaluation.")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': f'No baseline data for {object_key} in evaluation baseline bucket {BASELINE_BUCKET}'
                })
            }
        
        # Store comparisons
        section_comparisons = []
        inference_differences = []
        
        # Compare each section
        for baseline_file in baseline_files:
            logger.info(f"Processing section file: {baseline_file}")
            processing_file = baseline_file  # Same structure in both buckets
            
            baseline_data = load_json_from_s3(s3_client, BASELINE_BUCKET, baseline_file)
            processing_data = load_json_from_s3(s3_client, PROCESSING_OUTPUT_BUCKET, processing_file)
            
            if baseline_data and processing_data:
                # Compare section classification and pages
                section_comp = compare_sections(baseline_data, processing_data)
                section_comparisons.append(section_comp)
                
                # Compare extracted information
                differences = compare_inference_results(baseline_data, processing_data)
                inference_differences.extend(differences)
            else:
                logger.warning(f"Skipping comparison for {baseline_file} due to missing data")
        
        # Generate evaluation prompt
        prompt = generate_evaluation_prompt(section_comparisons, inference_differences)
        
        # Get evaluation report from Claude
        evaluation_report = invoke_llm(bedrock_client, prompt)
        
        # Write report to S3
        report_key = f"{object_key}/evaluation.md"
        write_report_to_s3(s3_client, EVALUATION_OUTPUT_BUCKET, report_key, evaluation_report)

        # Update document tracker
        document = update_document_tracker(object_key, f"s3://{EVALUATION_OUTPUT_BUCKET}/{report_key}")
        logger.info(f"Document updated: {document}")
        
        logger.info("Evaluation process completed successfully")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Evaluation completed successfully',
                'report_location': f"s3://{EVALUATION_OUTPUT_BUCKET}/{report_key}"
            })
        }
    
    except Exception as e:
        error_msg = f"Error in lambda_handler: {str(e)}"
        logger.error(error_msg)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'message': 'Evaluation failed',
                'error': error_msg
            })
        }