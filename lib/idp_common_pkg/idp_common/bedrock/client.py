# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Bedrock client module for interacting with Amazon Bedrock models.

This module provides a class-based interface for invoking Bedrock models
with built-in retry logic, metrics tracking, and configuration options.
"""

import boto3
import json
import os
import time
import logging
import copy
import random
import socket
from typing import Dict, Any, List, Optional, Union, Tuple
from botocore.config import Config
from botocore.exceptions import ClientError, ReadTimeoutError, ConnectTimeoutError, EndpointConnectionError
from urllib3.exceptions import ReadTimeoutError as Urllib3ReadTimeoutError
try:
    from requests.exceptions import ReadTimeout as RequestsReadTimeout, ConnectTimeout as RequestsConnectTimeout
except ImportError:
    # Fallback if requests is not available
    RequestsReadTimeout = Exception
    RequestsConnectTimeout = Exception

logger = logging.getLogger(__name__)

# Default retry settings
DEFAULT_MAX_RETRIES = 7
DEFAULT_INITIAL_BACKOFF = 2  # seconds
DEFAULT_MAX_BACKOFF = 300    # 5 minutes


# Models that support cachePoint functionality
CACHEPOINT_SUPPORTED_MODELS = [
    "us.anthropic.claude-3-5-haiku-20241022-v1:0",
    "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    "us.amazon.nova-lite-v1:0",
    "us.amazon.nova-pro-v1:0"
]

class BedrockClient:
    """Client for interacting with Amazon Bedrock models."""
    
    def __init__(
        self, 
        region: Optional[str] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        initial_backoff: float = DEFAULT_INITIAL_BACKOFF,
        max_backoff: float = DEFAULT_MAX_BACKOFF,
        metrics_enabled: bool = True
    ):
        """
        Initialize a Bedrock client.
        
        Args:
            region: AWS region (defaults to AWS_REGION env var or us-west-2)
            max_retries: Maximum number of retry attempts
            initial_backoff: Initial backoff time in seconds
            max_backoff: Maximum backoff time in seconds
            metrics_enabled: Whether to publish metrics
        """
        self.region = region or os.environ.get('AWS_REGION', 'us-west-2')
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self.metrics_enabled = metrics_enabled
        self._client = None
        
    @property
    def client(self):
        """Lazy-loaded Bedrock client."""
        config = Config(
            connect_timeout=10,
            read_timeout=120
            )
        if self._client is None:
            self._client = boto3.client('bedrock-runtime', region_name=self.region, config=config)
        return self._client
    
    def __call__(
        self,
        model_id: str,
        system_prompt: Union[str, List[Dict[str, str]]],
        content: List[Dict[str, Any]],
        temperature: Union[float, str] = 0.0,
        top_k: Optional[Union[float, str]] = None,
        top_p: Optional[Union[float, str]] = None,
        max_tokens: Optional[Union[int, str]] = None,
        max_retries: Optional[int] = None,
        context: str = "Unspecified"
    ) -> Dict[str, Any]:
        """
        Make the instance callable with the same signature as the original function.
        
        This allows instances to be used as drop-in replacements for the function.
        
        Args:
            model_id: The Bedrock model ID (e.g., 'anthropic.claude-3-sonnet-20240229-v1:0')
            system_prompt: The system prompt as string or list of content objects
            content: The content for the user message (can include text and images)
            temperature: The temperature parameter for model inference (float or string)
            top_k: Optional top_k parameter (float or string)
            top_p: Optional top_p parameter (float or string)
            max_tokens: Optional max_tokens parameter (int or string)
            max_retries: Optional override for the instance's max_retries setting
            
        Returns:
            Bedrock response object with metering information
        """
        # Use instance max_retries if not overridden
        effective_max_retries = max_retries if max_retries is not None else self.max_retries
            
        return self.invoke_model(
            model_id=model_id,
            system_prompt=system_prompt,
            content=content,
            temperature=temperature,
            top_k=top_k,
            top_p=top_p,
            max_tokens=max_tokens,
            max_retries=effective_max_retries,
            context=context
        )
    
    def _preprocess_content_for_cachepoint(self, content: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process content list to handle <<CACHEPOINT>> tags in text elements.
        
        For text elements containing <<CACHEPOINT>> tags, this function will split the text
        and insert cachePoint elements at the tag positions.
        
        Args:
            content: The content list for the user message (can include text and images)
            
        Returns:
            Processed content list with cachePoint elements inserted
        """
        if not content:
            return content
            
        processed_content = []
        cachepoint_count = 0
        
        for item in content:
            # If it's a text element, check for <<CACHEPOINT>> tags
            if "text" in item and isinstance(item["text"], str) and "<<CACHEPOINT>>" in item["text"]:
                # Log that we found a cachepoint tag
                logger.debug(f"Found <<CACHEPOINT>> tags in text content: {item['text'][:50]}...")
                
                # Split the text by the tag
                text_parts = item["text"].split("<<CACHEPOINT>>")
                logger.debug(f"Split text into {len(text_parts)} parts at cachepoint tags")
                
                # Add each text part interspersed with cachePoint elements
                for i, text_part in enumerate(text_parts):
                    # Only add non-empty text parts
                    if text_part:
                        # Count words in this part
                        word_count = len(text_part.split())
                        logger.debug(f"Text part {i+1}: {word_count} words")
                        processed_content.append({"text": text_part})
                    else:
                        logger.debug(f"Text part {i+1}: Empty, skipping")
                    
                    # Add cachePoint after each text part except the last one
                    if i < len(text_parts) - 1:
                        cachepoint_count += 1
                        logger.debug(f"Inserting cachePoint #{cachepoint_count} after text part {i+1}")
                        processed_content.append({"cachePoint": {"type": "default"}})
            else:
                # If not a text element or no tags, add it as is
                content_type = "text" if "text" in item else "image" if "image" in item else "other"
                logger.debug(f"No cachepoint tags in {content_type} content, passing through unchanged")
                processed_content.append(item)
        
        if cachepoint_count > 0:
            logger.info(f"Processed content with {cachepoint_count} cachepoint insertions")
        
        return processed_content
    
    def invoke_model(
        self,
        model_id: str,
        system_prompt: Union[str, List[Dict[str, str]]],
        content: List[Dict[str, Any]],
        temperature: Union[float, str] = 0.0,
        top_k: Optional[Union[float, str]] = 5,
        top_p: Optional[Union[float, str]] = 0.1,
        max_tokens: Optional[Union[int, str]] = None,
        max_retries: Optional[int] = None,
        context: str = "Unspecified"
    ) -> Dict[str, Any]:
        """
        Invoke a Bedrock model with retry logic.
        
        Args:
            model_id: The Bedrock model ID (e.g., 'anthropic.claude-3-sonnet-20240229-v1:0')
            system_prompt: The system prompt as string or list of content objects
            content: The content for the user message (can include text and images)
            temperature: The temperature parameter for model inference (float or string)
            top_k: Optional top_k parameter (float or string)
            top_p: Optional top_p parameter (float or string)
            max_tokens: Optional max_tokens parameter (int or string)
            max_retries: Optional override for the instance's max_retries setting
            
        Returns:
            Bedrock response object with metering information
        """
        # Track total requests
        self._put_metric('BedrockRequestsTotal', 1)
        
        # Use instance max_retries if not overridden
        effective_max_retries = max_retries if max_retries is not None else self.max_retries
        
        # Format system prompt if needed
        if isinstance(system_prompt, str):
            formatted_system_prompt = [{"text": system_prompt}]
        else:
            formatted_system_prompt = system_prompt
        
        # Check for cachePoint tags in content
        has_cachepoint_tags = any("text" in item and isinstance(item["text"], str) and "<<CACHEPOINT>>" in item["text"] for item in content)
        
        if has_cachepoint_tags:
            if model_id in CACHEPOINT_SUPPORTED_MODELS:
                # Process content for cachePoint tags with supported model
                processed_content = self._preprocess_content_for_cachepoint(content)
                logger.info(f"Applied cachePoint processing for supported model: {model_id}")
            else:
                # For unsupported models, just remove the <<CACHEPOINT>> tags but keep content intact
                processed_content = []
                for item in content:
                    if "text" in item and isinstance(item["text"], str) and "<<CACHEPOINT>>" in item["text"]:
                        # Remove the cachepoint tags but keep the text
                        clean_text = item["text"].replace("<<CACHEPOINT>>", "")
                        processed_content.append({"text": clean_text})
                        logger.warning(f"Removed <<CACHEPOINT>> tags for unsupported model: {model_id}. CachePoint is only supported for: {', '.join(CACHEPOINT_SUPPORTED_MODELS)}")
                    else:
                        # Pass through unchanged
                        processed_content.append(item)
        else:
            # No cachepoint tags, use content as is
            processed_content = content
            
        # Build message
        message = {
            "role": "user",
            "content": processed_content
        }
        messages = [message]
        
        # Convert temperature to float if it's a string
        if isinstance(temperature, str):
            try:
                temperature = float(temperature)
            except ValueError:
                logger.warning(f"Failed to convert temperature value '{temperature}' to float. Using default 0.0")
                temperature = 0.0
        
        # Initialize inference config with temperature
        inference_config = {"temperature": temperature}
        
        # Handle top_p parameter
        if top_p is not None:
            # Convert top_p to float if it's a string
            if isinstance(top_p, str):
                try:
                    top_p = float(top_p)
                except ValueError:
                    logger.warning(f"Failed to convert top_p value '{top_p}' to float. Not using top_p.")
                    top_p = None
            
            inference_config["topP"] = top_p
        
        # Handle max_tokens parameter
        if max_tokens is not None:
            # Convert max_tokens to int if it's a string
            if isinstance(max_tokens, str):
                try:
                    max_tokens = int(max_tokens)
                except ValueError:
                    logger.warning(f"Failed to convert max_tokens value '{max_tokens}' to int. Not using max_tokens.")
                    max_tokens = None
            
            # Add to inferenceConfig as maxTokens for Nova models
            if max_tokens is not None and "amazon" in model_id.lower():
                inference_config["maxTokens"] = max_tokens
        
        # Add additional model fields if needed
        additional_model_fields = {}
        
        # Handle top_k parameter
        if top_k is not None:
            # Convert top_k to float if it's a string
            if isinstance(top_k, str):
                try:
                    top_k = float(top_k)
                except ValueError:
                    logger.warning(f"Failed to convert top_k value '{top_k}' to float. Not using top_k.")
                    top_k = None
        
        # Handle model-specific parameters
        if "anthropic" in model_id.lower():
            # Add parameters to additionalModelRequestFields for Claude (snake_case)
            if top_k is not None:
                additional_model_fields["top_k"] = top_k
            
            if max_tokens is not None:
                additional_model_fields["max_tokens"] = max_tokens
        
        # Handle Nova-specific parameters
        elif "amazon" in model_id.lower():
            # For Nova models, topK should be in additionalModelRequestFields.inferenceConfig
            if top_k is not None:
                if additional_model_fields is None:
                    additional_model_fields = {}
                if "inferenceConfig" not in additional_model_fields:
                    additional_model_fields["inferenceConfig"] = {}
                additional_model_fields["inferenceConfig"]["topK"] = int(top_k)
        
        # If no additional model fields were added, set to None
        if not additional_model_fields:
            additional_model_fields = None
        
        # Get guardrail configuration if available
        guardrail_config = self.get_guardrail_config()
        
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
        
        # Start timing the entire request
        request_start_time = time.time()
        
        # Call the recursive retry function
        result = self._invoke_with_retry(
            converse_params=converse_params,
            retry_count=0,
            max_retries=effective_max_retries,
            request_start_time=request_start_time,
            context=context
        )
        
        return result
    
    def _invoke_with_retry(
        self,
        converse_params: Dict[str, Any],
        retry_count: int,
        max_retries: int,
        request_start_time: float,
        last_exception: Exception = None,
        context: str = "Unspecified"
    ) -> Dict[str, Any]:
        """
        Recursive helper method to handle retries for Bedrock invocation.
        
        Args:
            converse_params: Parameters for the Bedrock converse API call
            retry_count: Current retry attempt (0-based)
            max_retries: Maximum number of retry attempts
            request_start_time: Time when the original request started
            last_exception: The last exception encountered (for final error reporting)
            
        Returns:
            Bedrock response object with metering information
            
        Raises:
            Exception: The last exception encountered if max retries are exceeded
        """
        try:
            # Create a copy of the messages to sanitize for logging
            sanitized_params = copy.deepcopy(converse_params)
            if "messages" in sanitized_params:
                sanitized_params["messages"] = self._sanitize_messages_for_logging(sanitized_params["messages"])
            
            # Log detailed request parameters
            logger.info(f"Bedrock request attempt {retry_count + 1}/{max_retries}:")
            logger.info(f"  - model: {converse_params['modelId']}")
            logger.info(f"  - inferenceConfig: {converse_params['inferenceConfig']}")
            logger.info(f"  - system: {converse_params['system']}")
            logger.info(f"  - messages: {sanitized_params['messages']}")
            logger.info(f"  - additionalModelRequestFields: {converse_params['additionalModelRequestFields']}")
            
            # Log guardrail usage if configured
            if "guardrailConfig" in converse_params:
                logger.debug(f"  - guardrailConfig: {converse_params['guardrailConfig']}")
            
            # Start timing this attempt
            attempt_start_time = time.time()
            
            # Make the API call
            response = self.client.converse(**converse_params)
            
            # Calculate duration
            duration = time.time() - attempt_start_time
            
            # Log response details, but sanitize large content
            sanitized_response = self._sanitize_response_for_logging(response)
            logger.info(f"Bedrock request successful after {retry_count + 1} attempts. Duration: {duration:.2f}s")
            logger.debug(f"Response: {sanitized_response}")
            logger.info(f"Token Usage: {response.get('usage')}")
            # Track successful requests and latency
            self._put_metric('BedrockRequestsSucceeded', 1)
            self._put_metric('BedrockRequestLatency', duration * 1000, 'Milliseconds')
            if retry_count > 0:
                self._put_metric('BedrockRetrySuccess', 1)
            
            # Track token usage
            if 'usage' in response:
                inputTokens = response['usage'].get('inputTokens', 0)
                outputTokens = response['usage'].get('outputTokens', 0)
                total_tokens = response['usage'].get('totalTokens', 0)
                cacheReadInputTokens = response['usage'].get('cacheReadInputTokens', 0)
                cacheWriteInputTokens = response['usage'].get('cacheWriteInputTokens', 0)
                self._put_metric('InputTokens', inputTokens)
                self._put_metric('OutputTokens', outputTokens)
                self._put_metric('TotalTokens', total_tokens)
                self._put_metric('CacheReadInputTokens', cacheReadInputTokens)
                self._put_metric('CacheWriteInputTokens', cacheWriteInputTokens)
            
            # Calculate total duration
            total_duration = time.time() - request_start_time
            self._put_metric('BedrockTotalLatency', total_duration * 1000, 'Milliseconds')
            
            # Create metering data
            usage = response.get('usage', {})
            response_with_metering = {
                "response": response,
                "metering": {
                    f"{context}/bedrock/{converse_params['modelId']}": {
                        **usage
                    }
                }
            }
            
            return response_with_metering
            
        except Exception as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            
            retryable_errors = [
                'ThrottlingException', 
                'ServiceQuotaExceededException', 
                'RequestLimitExceeded', 
                'TooManyRequestsException', 
                'ServiceUnavailableException',
                'ModelErrorException',
                'RequestTimeout',
                'ReadTimeout',
                'TimeoutError',
                'RequestTimeoutException'
            ]
            
            if error_code in retryable_errors:
                self._put_metric('BedrockThrottles', 1)
                
                # Check if we've reached max retries
                if retry_count >= max_retries:
                    logger.error(f"Max retries ({max_retries}) exceeded. Last error: {error_message}")
                    self._put_metric('BedrockRequestsFailed', 1)
                    self._put_metric('BedrockMaxRetriesExceeded', 1)
                    raise
                
                # Calculate backoff time
                backoff = self._calculate_backoff(retry_count)
                logger.warning(f"Bedrock throttling occurred (attempt {retry_count + 1}/{max_retries}). "
                             f"Error: {error_message}. "
                             f"Backing off for {backoff:.2f}s")
                
                # Sleep for backoff period
                time.sleep(backoff)
                
                # Recursive call with incremented retry count
                return self._invoke_with_retry(
                    converse_params=converse_params,
                    retry_count=retry_count + 1,
                    max_retries=max_retries,
                    request_start_time=request_start_time,
                    last_exception=e,
                    context=context
                )
            else:
                logger.error(f"Non-retryable Bedrock error: {error_code} - {error_message}")
                self._put_metric('BedrockRequestsFailed', 1)
                self._put_metric('BedrockNonRetryableErrors', 1)
                raise

    
    def get_guardrail_config(self) -> Optional[Dict[str, str]]:
        """
        Get guardrail configuration from environment if available.
        
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
    
    def generate_embedding(
        self, 
        text: str, 
        model_id: str = "amazon.titan-embed-text-v1",
        max_retries: Optional[int] = None
    ) -> List[float]:
        """
        Generate an embedding vector for the given text using Amazon Bedrock.
        
        Args:
            text: The text to generate embeddings for
            model_id: The embedding model ID to use (default: amazon.titan-embed-text-v1)
            max_retries: Optional override for the instance's max_retries setting
            
        Returns:
            List of floats representing the embedding vector
        """
        if not text or not isinstance(text, str):
            # Return an empty vector for empty input
            return []
        
        # Use instance max_retries if not overridden
        effective_max_retries = max_retries if max_retries is not None else self.max_retries
            
        # Track total embedding requests
        self._put_metric('BedrockEmbeddingRequestsTotal', 1)
        
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
        
        # Call the recursive embedding function
        return self._generate_embedding_with_retry(
            model_id=model_id,
            request_body=request_body,
            normalized_text=normalized_text,
            retry_count=0,
            max_retries=effective_max_retries
        )
    
    def _generate_embedding_with_retry(
        self,
        model_id: str,
        request_body: str,
        normalized_text: str,
        retry_count: int,
        max_retries: int,
        last_exception: Exception = None
    ) -> List[float]:
        """
        Recursive helper method to handle retries for embedding generation.
        
        Args:
            model_id: The embedding model ID
            request_body: JSON request body for the API call
            normalized_text: Normalized input text (for logging)
            retry_count: Current retry attempt (0-based)
            max_retries: Maximum number of retry attempts
            last_exception: The last exception encountered (for final error reporting)
            
        Returns:
            List of floats representing the embedding vector
            
        Raises:
            Exception: The last exception encountered if max retries are exceeded
        """
        try:
            logger.info(f"Bedrock embedding request attempt {retry_count + 1}/{max_retries}:")
            logger.debug(f"  - model: {model_id}")
            logger.debug(f"  - input text length: {len(normalized_text)} characters")
            
            attempt_start_time = time.time()
            response = self.client.invoke_model(
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
            self._put_metric('BedrockEmbeddingRequestsSucceeded', 1)
            self._put_metric('BedrockEmbeddingRequestLatency', duration * 1000, 'Milliseconds')
            
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
                'ServiceUnavailableException',
                'RequestTimeout',
                'ReadTimeout',
                'TimeoutError',
                'RequestTimeoutException'
            ]
            
            if error_code in retryable_errors:
                self._put_metric('BedrockEmbeddingThrottles', 1)
                
                # Check if we've reached max retries
                if retry_count >= max_retries:
                    logger.error(f"Max retries ({max_retries}) exceeded for embedding. Last error: {error_message}")
                    self._put_metric('BedrockEmbeddingRequestsFailed', 1)
                    self._put_metric('BedrockEmbeddingMaxRetriesExceeded', 1)
                    raise
                
                # Calculate backoff time
                backoff = self._calculate_backoff(retry_count)
                logger.warning(f"Bedrock throttling occurred (attempt {retry_count + 1}/{max_retries}). "
                            f"Error: {error_message}. "
                            f"Backing off for {backoff:.2f}s")
                
                # Sleep for backoff period
                time.sleep(backoff)
                
                # Recursive call with incremented retry count
                return self._generate_embedding_with_retry(
                    model_id=model_id,
                    request_body=request_body,
                    normalized_text=normalized_text,
                    retry_count=retry_count + 1,
                    max_retries=max_retries,
                    last_exception=e
                )
            else:
                logger.error(f"Non-retryable Bedrock error for embedding: {error_code} - {error_message}")
                self._put_metric('BedrockEmbeddingRequestsFailed', 1)
                self._put_metric('BedrockEmbeddingNonRetryableErrors', 1)
                raise
        
        except Exception as e:
            logger.error(f"Unexpected error generating embedding: {str(e)}", exc_info=True)
            self._put_metric('BedrockEmbeddingRequestsFailed', 1)
            self._put_metric('BedrockEmbeddingUnexpectedErrors', 1)
            raise
    
    def extract_text_from_response(self, response: Dict[str, Any]) -> str:
        """
        Extract text from a Bedrock response.
        
        Args:
            response: Bedrock response object
            
        Returns:
            Extracted text content
        """
        response_obj = response.get("response", response)
        return response_obj['output']['message']['content'][0].get("text", "")
    
    def format_prompt(
        self, 
        prompt_template: str, 
        substitutions: Dict[str, str], 
        required_placeholders: List[str] = None
    ) -> str:
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
    
    def _calculate_backoff(self, retry_count: int) -> float:
        """
        Calculate exponential backoff time with jitter.
        
        Args:
            retry_count: Current retry attempt (0-based)
            
        Returns:
            Backoff time in seconds
        """
        # Exponential backoff with base of 2
        backoff_seconds = min(
            self.max_backoff,
            self.initial_backoff * (2 ** retry_count)
        )
        
        # Add jitter (random value between 0 and 1 second)
        jitter = random.random()
        
        return backoff_seconds + jitter
    
    def _put_metric(self, metric_name: str, value: Union[int, float], unit: str = 'Count'):
        """
        Publish a metric if metrics are enabled.
        
        Args:
            metric_name: Name of the metric
            value: Metric value
            unit: Metric unit (default: Count)
        """
        if self.metrics_enabled:
            try:
                from ..metrics import put_metric
                put_metric(metric_name, value, unit)
            except Exception as e:
                logger.warning(f"Failed to publish metric {metric_name}: {str(e)}")
    
    def _sanitize_messages_for_logging(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Create a copy of messages with image content replaced for logging.
        
        Args:
            messages: List of message objects for Bedrock API
            
        Returns:
            Sanitized message objects suitable for logging
        """
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
    
    def _sanitize_response_for_logging(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a sanitized copy of the response suitable for logging.
        
        Args:
            response: Response from Bedrock API
            
        Returns:
            Sanitized response suitable for logging
        """
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
        
        return sanitized


# Create a default client instance
default_client = BedrockClient()

# Export the default client as invoke_model for backward compatibility
invoke_model = default_client

# Add docstring to the exported function for better IDE support
invoke_model.__doc__ = """
Invoke a Bedrock model with retry logic.

Args:
    model_id: The Bedrock model ID (e.g., 'anthropic.claude-3-sonnet-20240229-v1:0')
    system_prompt: The system prompt as string or list of content objects
    content: The content for the user message (can include text and images)
    temperature: The temperature parameter for model inference (float or string)
    top_k: Optional top_k parameter (float or string)
    top_p: Optional top_p parameter (float or string)
    max_tokens: Optional max_tokens parameter (int or string)
    max_retries: Optional override for the instance's max_retries setting
    context: Context prefix for metering key (default: "Unspecified")
    
Returns:
    Bedrock response object with metering information
"""
