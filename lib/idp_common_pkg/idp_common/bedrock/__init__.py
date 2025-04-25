import boto3
import json
import os
import time
import logging
from typing import Dict, Any, List, Optional, Union, Tuple
from botocore.exceptions import ClientError
from ..utils import calculate_backoff
from ..metrics import put_metric

logger = logging.getLogger(__name__)

# Default retry settings
MAX_RETRIES = 8
INITIAL_BACKOFF = 2  # seconds
MAX_BACKOFF = 300    # 5 minutes

# Add version info
__version__ = "0.1.0"

# Initialize clients
_bedrock_client = None

def get_bedrock_client():
    """
    Get or initialize the Bedrock client
    
    Returns:
        boto3 Bedrock client
    """
    global _bedrock_client
    if _bedrock_client is None:
        region = os.environ.get('AWS_REGION')
        _bedrock_client = boto3.client('bedrock-runtime', region_name=region)
    return _bedrock_client

def get_guardrail_config() -> Optional[Dict[str, str]]:
    """
    Get guardrail configuration from environment if available
    
    Returns:
        Optional guardrail configuration dict with id and version
    """
    guardrail_env = os.environ.get("GUARDRAIL_ID_AND_VERSION", "")
    if not guardrail_env:
        return None
        
    try:
        guardrail_id, guardrail_version = guardrail_env.split(":")
        if guardrail_id and guardrail_version:
            logger.debug(f"Using Bedrock Guardrail ID: {guardrail_id}, Version: {guardrail_version}")
            return {
                "guardrailIdentifier": guardrail_id,
                "guardrailVersion": guardrail_version,
                "trace": "enabled"  # Enable tracing for guardrail violations
            }
    except ValueError:
        logger.warning(f"Invalid GUARDRAIL_ID_AND_VERSION format: {guardrail_env}. Expected format: 'id:version'")
        
    return None

def invoke_model(
    model_id: str,
    system_prompt: Union[str, List[Dict[str, str]]],
    content: List[Dict[str, Any]],
    temperature: Union[float, str] = 0.0,
    top_k: Optional[Union[float, str]] = None,
    max_retries: int = MAX_RETRIES
) -> Dict[str, Any]:
    """
    Invoke a Bedrock model with retry logic
    
    Args:
        model_id: The Bedrock model ID (e.g., 'anthropic.claude-3-sonnet-20240229-v1:0')
        system_prompt: The system prompt as string or list of content objects
        content: The content for the user message (can include text and images)
        temperature: The temperature parameter for model inference (float or string that can be converted to float)
        top_k: Optional top_k parameter for Anthropic models (float or string that can be converted to float)
        max_retries: Maximum number of retry attempts
        
    Returns:
        Bedrock response object
    """
    bedrock_client = get_bedrock_client()
    retry_count = 0
    last_exception = None
    request_start_time = time.time()
    
    # Track total requests
    put_metric('BedrockRequestsTotal', 1)
    
    # Format system prompt if needed
    if isinstance(system_prompt, str):
        formatted_system_prompt = [{"text": system_prompt}]
    else:
        formatted_system_prompt = system_prompt
    
    # Build message and inference config
    message = {
        "role": "user",
        "content": content
    }
    messages = [message]
    
    # Convert temperature to float if it's a string
    if isinstance(temperature, str):
        try:
            temperature = float(temperature)
        except ValueError:
            logger.warning(f"Failed to convert temperature value '{temperature}' to float. Using default 0.0")
            temperature = 0.0
    
    inference_config = {"temperature": temperature}
    
    # Add additional model fields if needed
    additional_model_fields = None
    if "anthropic" in model_id.lower() and top_k is not None:
        # Convert top_k to float if it's a string
        if isinstance(top_k, str):
            try:
                top_k = float(top_k)
            except ValueError:
                logger.warning(f"Failed to convert top_k value '{top_k}' to float. Not using top_k.")
                # Skip adding top_k if conversion fails
            else:
                additional_model_fields = {"top_k": top_k}
        else:
            additional_model_fields = {"top_k": top_k}
    
    # Get guardrail configuration if available
    guardrail_config = get_guardrail_config()
    
    while retry_count < max_retries:
        try:
            # Create a copy of the messages to sanitize for logging
            sanitized_messages = _sanitize_messages_for_logging(messages)
            
            # Log detailed request parameters
            logger.info(f"Bedrock request attempt {retry_count + 1}/{max_retries}:")
            logger.debug(f"  - model: {model_id}")
            logger.debug(f"  - inferenceConfig: {inference_config}")
            logger.debug(f"  - system: {formatted_system_prompt}")
            logger.debug(f"  - messages: {sanitized_messages}")
            logger.debug(f"  - additionalModelRequestFields: {additional_model_fields}")
            
            # Log guardrail usage if configured
            if guardrail_config:
                logger.debug(f"  - guardrailConfig: {guardrail_config}")
            
            attempt_start_time = time.time()
            
            # Build converse parameters
            converse_params = {
                "modelId": model_id,
                "messages": messages,
                "system": formatted_system_prompt,
                "inferenceConfig": inference_config,
                "additionalModelRequestFields": additional_model_fields
            }
            
            # Add guardrail config if available
            if guardrail_config:
                converse_params["guardrailConfig"] = guardrail_config
            
            response = bedrock_client.converse(**converse_params)
            duration = time.time() - attempt_start_time
            
            # Log response details, but sanitize large content
            sanitized_response = _sanitize_response_for_logging(response)
            logger.debug(f"Bedrock request successful after {retry_count + 1} attempts. Duration: {duration:.2f}s")
            logger.info(f"Response: {sanitized_response}")
            
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
            
            # Create metering data
            usage = response.get('usage', {})
            response_with_metering = {
                "response": response,
                "metering": {
                    f"bedrock/{model_id}": {
                        **usage
                    }
                }
            }
            
            return response_with_metering
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            retryable_errors = [
                'ThrottlingException', 
                'ServiceQuotaExceededException', 
                'RequestLimitExceeded', 
                'TooManyRequestsException', 
                'ServiceUnavailableException',
                'ModelErrorException'
            ]
            
            if error_code in retryable_errors:
                retry_count += 1
                put_metric('BedrockThrottles', 1)
                
                if retry_count == max_retries:
                    logger.error(f"Max retries ({max_retries}) exceeded. Last error: {error_message}")
                    put_metric('BedrockRequestsFailed', 1)
                    put_metric('BedrockMaxRetriesExceeded', 1)
                    raise
                
                backoff = calculate_backoff(retry_count)
                logger.warning(f"Bedrock throttling occurred (attempt {retry_count}/{max_retries}). "
                             f"Error: {error_message}. "
                             f"Backing off for {backoff:.2f}s")
                
                time.sleep(backoff)
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

def _sanitize_messages_for_logging(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Create a copy of messages with image content replaced for logging
    
    Args:
        messages: List of message objects for Bedrock API
        
    Returns:
        Sanitized message objects suitable for logging
    """
    import copy
    sanitized = copy.deepcopy(messages)
    
    for message in sanitized:
        if 'content' in message and isinstance(message['content'], list):
            for content_item in message['content']:
                # Check for image type content
                if isinstance(content_item, dict) and content_item.get('type') == 'image':
                    # Replace actual image data with placeholder
                    if 'source' in content_item:
                        content_item['source'] = {'data': '[image_data]'}
                elif isinstance(content_item, dict) and 'image' in content_item:
                    # Handle different image format used by some models
                    content_item['image'] = '[image_data]'
                elif isinstance(content_item, dict) and 'bytes' in content_item:
                    # Handle raw binary format
                    content_item['bytes'] = '[binary_data]'
    
    return sanitized

def _sanitize_response_for_logging(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a sanitized copy of the response suitable for logging
    
    Args:
        response: Response from Bedrock API
        
    Returns:
        Sanitized response suitable for logging
    """
    import copy
    import json
    
    # Create a deep copy to avoid modifying the original
    sanitized = copy.deepcopy(response)
    
    # For very large responses, limit the content for logging
    if 'output' in sanitized and 'message' in sanitized['output']:
        message = sanitized['output']['message']
        if 'content' in message:
            content = message['content']
            
            # Handle list of content items (multimodal responses)
            if isinstance(content, list):
                for i, item in enumerate(content):
                    if isinstance(item, dict):
                        # Truncate text content if too long
                        if 'text' in item and isinstance(item['text'], str) and len(item['text']) > 500:
                            item['text'] = item['text'][:500] + '... [truncated]'
                        # Replace image data with placeholder
                        if 'image' in item:
                            item['image'] = '[image_data]'
            # Handle string content
            elif isinstance(content, str) and len(content) > 500:
                message['content'] = content[:500] + '... [truncated]'
    
    # Include usage info for token counts
    if 'usage' in sanitized:
        # Usage is already compact, no need to truncate
        pass
    
    return sanitized

def extract_text_from_response(response: Dict[str, Any]) -> str:
    """
    Extract text from a Bedrock response
    
    Args:
        response: Bedrock response object
        
    Returns:
        Extracted text content
    """
    response_obj = response.get("response", response)
    return response_obj['output']['message']['content'][0].get("text", "")

def generate_embedding(text: str, model_id: str = "amazon.titan-embed-text-v1") -> List[float]:
    """
    Generate an embedding vector for the given text using Amazon Bedrock
    
    Args:
        text: The text to generate embeddings for
        model_id: The embedding model ID to use (default: amazon.titan-embed-text-v1)
        
    Returns:
        List of floats representing the embedding vector
    """
    if not text or not isinstance(text, str):
        # Return an empty vector for empty input
        return []
        
    bedrock_client = get_bedrock_client()
    retry_count = 0
    last_exception = None
    max_retries = MAX_RETRIES
    
    # Track total embedding requests
    put_metric('BedrockEmbeddingRequestsTotal', 1)
    
    # Normalize whitespace and prepare the input text
    normalized_text = " ".join(text.split())
    
    # Prepare the request body based on the model
    if "amazon.titan-embed" in model_id:
        request_body = json.dumps({
            "inputText": normalized_text
        })
    else:
        # Default format for other models
        request_body = json.dumps({
            "text": normalized_text
        })
    
    while retry_count < max_retries:
        try:
            logger.info(f"Bedrock embedding request attempt {retry_count + 1}/{max_retries}:")
            logger.debug(f"  - model: {model_id}")
            logger.debug(f"  - input text length: {len(normalized_text)} characters")
            
            attempt_start_time = time.time()
            response = bedrock_client.invoke_model(
                modelId=model_id,
                contentType="application/json",
                accept="application/json",
                body=request_body
            )
            duration = time.time() - attempt_start_time
            
            # Extract the embedding vector from response
            response_body = json.loads(response["body"].read())
            
            # Handle different response formats based on the model
            if "amazon.titan-embed" in model_id:
                embedding = response_body.get("embedding", [])
            else:
                # Default extraction format
                embedding = response_body.get("embedding", [])
            
            # Track successful requests and latency
            put_metric('BedrockEmbeddingRequestsSucceeded', 1)
            put_metric('BedrockEmbeddingRequestLatency', duration * 1000, 'Milliseconds')
            
            logger.debug(f"Generated embedding with {len(embedding)} dimensions")
            return embedding
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            retryable_errors = [
                'ThrottlingException', 
                'ServiceQuotaExceededException', 
                'RequestLimitExceeded', 
                'TooManyRequestsException', 
                'ServiceUnavailableException'
            ]
            
            if error_code in retryable_errors:
                retry_count += 1
                put_metric('BedrockEmbeddingThrottles', 1)
                
                if retry_count == max_retries:
                    logger.error(f"Max retries ({max_retries}) exceeded for embedding. Last error: {error_message}")
                    put_metric('BedrockEmbeddingRequestsFailed', 1)
                    put_metric('BedrockEmbeddingMaxRetriesExceeded', 1)
                    raise
                
                backoff = calculate_backoff(retry_count)
                logger.warning(f"Bedrock throttling occurred (attempt {retry_count}/{max_retries}). "
                            f"Error: {error_message}. "
                            f"Backing off for {backoff:.2f}s")
                
                time.sleep(backoff)
                last_exception = e
            else:
                logger.error(f"Non-retryable Bedrock error for embedding: {error_code} - {error_message}")
                put_metric('BedrockEmbeddingRequestsFailed', 1)
                put_metric('BedrockEmbeddingNonRetryableErrors', 1)
                raise
    
        except Exception as e:
            logger.error(f"Unexpected error generating embedding: {str(e)}", exc_info=True)
            put_metric('BedrockEmbeddingRequestsFailed', 1)
            put_metric('BedrockEmbeddingUnexpectedErrors', 1)
            raise
    
    if last_exception:
        raise last_exception
    
    # Should never reach here, but return empty embedding if it does
    return []


def format_prompt(prompt_template: str, substitutions: Dict[str, str], required_placeholders: List[str] = None) -> str:
    """
    Prepare prompt from template by replacing placeholders with values.
    
    Args:
        prompt_template: The prompt template with placeholders in {PLACEHOLDER} format
        substitutions: Dictionary of placeholder values
        required_placeholders: List of placeholder names that must be present in the template
        
    Returns:
        String with placeholders replaced by values
        
    Raises:
        ValueError: If a required placeholder is missing from the template
    """
    # Validate required placeholders if specified
    if required_placeholders:
        missing_placeholders = [p for p in required_placeholders if f"{{{p}}}" not in prompt_template]
        if missing_placeholders:
            raise ValueError(f"Prompt template must contain the following placeholders: {', '.join([f'{{{p}}}' for p in missing_placeholders])}")
    
    # Check if template uses {PLACEHOLDER} format and convert to %(PLACEHOLDER)s for secure replacement
    if any(f"{{{key}}}" in prompt_template for key in substitutions):
        for key in substitutions:
            placeholder = f"{{{key}}}"
            if placeholder in prompt_template:
                prompt_template = prompt_template.replace(placeholder, f"%({key})s")
                
    # Apply substitutions using % operator which is safer than .format()
    return prompt_template % substitutions