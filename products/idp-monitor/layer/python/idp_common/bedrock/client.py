# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Bedrock client module for interacting with Amazon Bedrock models.

This module provides a class-based interface for invoking Bedrock models
with built-in retry logic, metrics tracking, and configuration options.
"""

import copy
import json
import logging
import os
import random
import time
from typing import Any, Dict, List, Optional, Union

import boto3
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)
from urllib3.exceptions import ReadTimeoutError as Urllib3ReadTimeoutError

from .model_utils import parse_model_id

# Sentinel value for LambdaHook model selection
LAMBDA_HOOK_MODEL_ID = "LambdaHook"


# Dummy exception classes for requests timeouts if requests is not available
class _RequestsReadTimeout(Exception):
    """Fallback exception class when requests library is not available."""

    pass


class _RequestsConnectTimeout(Exception):
    """Fallback exception class when requests library is not available."""

    pass


try:
    from requests.exceptions import (
        ConnectTimeout as RequestsConnectTimeout,
    )
    from requests.exceptions import (
        ReadTimeout as RequestsReadTimeout,
    )
except ImportError:
    # Fallback if requests is not available - use dummy exception classes
    RequestsReadTimeout = _RequestsReadTimeout  # type: ignore[misc,assignment]
    RequestsConnectTimeout = _RequestsConnectTimeout  # type: ignore[misc,assignment]


logger = logging.getLogger(__name__)

# Default retry settings
DEFAULT_MAX_RETRIES = 7
DEFAULT_INITIAL_BACKOFF = 2  # seconds
DEFAULT_MAX_BACKOFF = 300  # 5 minutes


# Claude 4.7+ model base names that don't support temperature/top_k/top_p parameters.
# These parameters are deprecated for these models and cause runtime errors.
# Add new model base names here as needed (e.g., sonnet-4-7, haiku-4-7).
_CLAUDE_4_7_BASE_NAMES = {
    "anthropic.claude-opus-4-7",
}


def _is_claude_4_7_model(model_id: str) -> bool:
    """Check if a model is a Claude 4.7+ variant that doesn't support temperature/top_k/top_p.

    Handles region prefixes (us., eu., global.) and :1m suffix automatically.

    Args:
        model_id: Bedrock model ID (e.g., 'us.anthropic.claude-opus-4-7:1m')

    Returns:
        True if the model is a Claude 4.7+ variant
    """
    # Strip region prefix (us., eu., global.)
    parts = model_id.split(".", 1)
    if len(parts) == 2 and parts[0] in ("us", "eu", "global"):
        base = parts[1]
    else:
        base = model_id
    # Strip :1m suffix
    if base.endswith(":1m"):
        base = base[:-3]
    return base in _CLAUDE_4_7_BASE_NAMES


# Base model names that support cachePoint (without region prefix)
# Used to check inference profiles by resolving their underlying foundation model
_CACHEPOINT_BASE_MODELS = set()

# Models that support cachePoint functionality
CACHEPOINT_SUPPORTED_MODELS = [
    "us.anthropic.claude-3-5-haiku-20241022-v1:0",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    "us.anthropic.claude-opus-4-5-20251101-v1:0",
    "us.anthropic.claude-opus-4-6-v1",
    "us.anthropic.claude-opus-4-6-v1:1m",
    "us.anthropic.claude-opus-4-7",
    "us.anthropic.claude-opus-4-7:1m",
    "us.anthropic.claude-opus-4-1-20250805-v1:0",
    "us.anthropic.claude-opus-4-20250514-v1:0",
    "us.anthropic.claude-sonnet-4-20250514-v1:0",
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "us.anthropic.claude-sonnet-4-6",
    "us.anthropic.claude-sonnet-4-6:1m",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "us.amazon.nova-lite-v1:0",
    "us.amazon.nova-pro-v1:0",
    "us.amazon.nova-2-lite-v1:0",
    "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
    "eu.anthropic.claude-3-7-sonnet-20250219-v1:0",
    "eu.anthropic.claude-sonnet-4-20250514-v1:0",
    "eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "eu.anthropic.claude-sonnet-4-6",
    "eu.anthropic.claude-sonnet-4-6:1m",
    "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
    "eu.anthropic.claude-opus-4-5-20251101-v1:0",
    "eu.anthropic.claude-opus-4-6-v1",
    "eu.anthropic.claude-opus-4-6-v1:1m",
    "eu.anthropic.claude-opus-4-7",
    "eu.anthropic.claude-opus-4-7:1m",
    "eu.amazon.nova-lite-v1:0",
    "eu.amazon.nova-pro-v1:0",
    "eu.amazon.nova-2-lite-v1:0",
    "eu.amazon.nova-2-lite-v1:0:priority",
    "eu.amazon.nova-2-lite-v1:0:flex",
    "global.amazon.nova-2-lite-v1:0",
    "global.amazon.nova-2-lite-v1:0:priority",
    "global.amazon.nova-2-lite-v1:0:flex",
    "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "global.anthropic.claude-sonnet-4-6",
    "global.anthropic.claude-sonnet-4-6:1m",
    "global.anthropic.claude-opus-4-5-20251101-v1:0",
    "global.anthropic.claude-opus-4-6-v1",
    "global.anthropic.claude-opus-4-6-v1:1m",
    "global.anthropic.claude-opus-4-7",
    "global.anthropic.claude-opus-4-7:1m",
]

# Build set of base model names (without region/tier prefixes) for inference profile resolution.
# e.g., "us.anthropic.claude-sonnet-4-6" -> "anthropic.claude-sonnet-4-6"
# and "eu.amazon.nova-2-lite-v1:0:priority" -> "amazon.nova-2-lite-v1:0"
for _model_id in CACHEPOINT_SUPPORTED_MODELS:
    _parts = _model_id.split(".", 1)
    if len(_parts) == 2 and _parts[0] in ("us", "eu", "global"):
        _base = _parts[1]
        # Strip tier suffixes (:priority, :flex) but keep version suffixes (:0, :1m)
        if _base.endswith(":priority") or _base.endswith(":flex"):
            _base = _base.rsplit(":", 1)[0]
        _CACHEPOINT_BASE_MODELS.add(_base)

# Module-level cache for inference profile -> cachepoint support resolution
_inference_profile_cachepoint_cache: Dict[str, bool] = {}


class BedrockClient:
    """Client for interacting with Amazon Bedrock models and custom Lambda hooks."""

    def __init__(
        self,
        region: Optional[str] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        initial_backoff: float = DEFAULT_INITIAL_BACKOFF,
        max_backoff: float = DEFAULT_MAX_BACKOFF,
        metrics_enabled: bool = True,
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
        self.region = region or os.environ.get("AWS_REGION")
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self.metrics_enabled = metrics_enabled
        self._client = None
        self._bedrock_control_client = None
        self._lambda_client = None
        self._s3_client = None

    @property
    def client(self):
        """Lazy-loaded Bedrock client."""
        config = Config(
            connect_timeout=10,
            read_timeout=300,  # allow plenty of time for large extraction or assessment inferences
        )
        if self._client is None:
            self._client = boto3.client(
                "bedrock-runtime", region_name=self.region, config=config
            )
        return self._client

    @property
    def lambda_client(self):
        """Lazy-loaded Lambda client for LambdaHook invocations."""
        if self._lambda_client is None:
            self._lambda_client = boto3.client(
                "lambda", region_name=self.region
            )
        return self._lambda_client

    @property
    def bedrock_control_client(self):
        """Lazy-loaded Bedrock control plane client for GetInferenceProfile etc."""
        if self._bedrock_control_client is None:
            self._bedrock_control_client = boto3.client(
                "bedrock", region_name=self.region
            )
        return self._bedrock_control_client

    @property
    def s3_client(self):
        """Lazy-loaded S3 client for LambdaHook image uploads."""
        if self._s3_client is None:
            self._s3_client = boto3.client(
                "s3", region_name=self.region
            )
        return self._s3_client

    def _is_model_cachepoint_supported(self, model_id: str) -> bool:
        """
        Check if a model supports cachePoint, including inference profile resolution.

        For standard model IDs (e.g., "us.anthropic.claude-sonnet-4-6"), checks
        the CACHEPOINT_SUPPORTED_MODELS list directly.

        For inference profile ARNs (containing "inference-profile" or
        "application-inference-profile"), resolves the underlying foundation
        model via the GetInferenceProfile API and checks if that base model
        supports cachePoint. Results are cached to avoid repeated API calls.

        Args:
            model_id: Bedrock model ID or inference profile ARN

        Returns:
            True if the model (or underlying model for inference profiles) supports cachePoint
        """
        # Fast path: direct match against the known list
        if model_id in CACHEPOINT_SUPPORTED_MODELS:
            return True

        # Check if this is an inference profile ARN
        if "inference-profile" not in model_id:
            return False

        # Check module-level cache
        if model_id in _inference_profile_cachepoint_cache:
            cached = _inference_profile_cachepoint_cache[model_id]
            logger.debug(
                f"Inference profile cachepoint support (cached): {model_id} -> {cached}"
            )
            return cached

        # Resolve the inference profile to its underlying foundation model
        try:
            response = self.bedrock_control_client.get_inference_profile(
                inferenceProfileIdentifier=model_id
            )
            models = response.get("models", [])
            if not models:
                logger.warning(
                    f"Inference profile {model_id} has no models listed. "
                    "Cannot determine cachePoint support."
                )
                _inference_profile_cachepoint_cache[model_id] = False
                return False

            # Extract the base model name from the first model's ARN.
            # Model ARN format: arn:aws:bedrock:<region>::foundation-model/<base-model-name>
            # e.g., "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-6"
            first_model_arn = models[0].get("modelArn", "")
            if "foundation-model/" in first_model_arn:
                base_model_name = first_model_arn.split("foundation-model/")[-1]
            else:
                logger.warning(
                    f"Cannot parse foundation model from ARN: {first_model_arn}"
                )
                _inference_profile_cachepoint_cache[model_id] = False
                return False

            supported = base_model_name in _CACHEPOINT_BASE_MODELS
            _inference_profile_cachepoint_cache[model_id] = supported

            logger.info(
                f"Resolved inference profile {model_id} -> "
                f"foundation model '{base_model_name}' -> "
                f"cachePoint {'supported' if supported else 'not supported'}"
            )
            return supported

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            logger.warning(
                f"Failed to resolve inference profile {model_id} for cachePoint check "
                f"({error_code}): {e}. Disabling cachePoint for this model."
            )
            _inference_profile_cachepoint_cache[model_id] = False
            return False
        except Exception as e:
            logger.warning(
                f"Unexpected error resolving inference profile {model_id} "
                f"for cachePoint check: {e}. Disabling cachePoint for this model."
            )
            _inference_profile_cachepoint_cache[model_id] = False
            return False

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
        context: str = "Unspecified",
        service_tier: Optional[str] = None,
        model_lambda_hook_arn: Optional[str] = None,
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
            service_tier: Optional service tier (priority, standard, flex)

        Returns:
            Bedrock response object with metering information
        """
        # Use instance max_retries if not overridden
        effective_max_retries = (
            max_retries if max_retries is not None else self.max_retries
        )

        return self.invoke_model(
            model_id=model_id,
            system_prompt=system_prompt,
            content=content,
            temperature=temperature,
            top_k=top_k,
            top_p=top_p,
            max_tokens=max_tokens,
            max_retries=effective_max_retries,
            context=context,
            service_tier=service_tier,
            model_lambda_hook_arn=model_lambda_hook_arn,
        )

    def _preprocess_content_for_cachepoint(
        self, content: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
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
            if (
                "text" in item
                and isinstance(item["text"], str)
                and "<<CACHEPOINT>>" in item["text"]
            ):
                # Log that we found a cachepoint tag
                logger.debug(
                    f"Found <<CACHEPOINT>> tags in text content: {item['text'][:50]}..."
                )

                # Split the text by the tag
                text_parts = item["text"].split("<<CACHEPOINT>>")
                logger.debug(
                    f"Split text into {len(text_parts)} parts at cachepoint tags"
                )

                # Add each text part interspersed with cachePoint elements
                for i, text_part in enumerate(text_parts):
                    # Only add non-empty text parts
                    if text_part:
                        # Count words in this part
                        word_count = len(text_part.split())
                        logger.debug(f"Text part {i + 1}: {word_count} words")
                        processed_content.append({"text": text_part})
                    else:
                        logger.debug(f"Text part {i + 1}: Empty, skipping")

                    # Add cachePoint after each text part except the last one
                    if i < len(text_parts) - 1:
                        cachepoint_count += 1
                        logger.debug(
                            f"Inserting cachePoint #{cachepoint_count} after text part {i + 1}"
                        )
                        processed_content.append({"cachePoint": {"type": "default"}})
            else:
                # If not a text element or no tags, add it as is
                content_type = (
                    "text"
                    if "text" in item
                    else "image" if "image" in item else "other"
                )
                logger.debug(
                    f"No cachepoint tags in {content_type} content, passing through unchanged"
                )
                processed_content.append(item)

        if cachepoint_count > 0:
            logger.info(
                f"Processed content with {cachepoint_count} cachepoint insertions"
            )

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
        context: str = "Unspecified",
        service_tier: Optional[str] = None,
        model_lambda_hook_arn: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Invoke a Bedrock model or custom Lambda hook with retry logic.

        When model_id is 'LambdaHook', the request is routed to the specified
        Lambda function instead of Bedrock. The Lambda receives a Converse API-compatible
        payload and must return a Converse API-compatible response.

        Args:
            model_id: The Bedrock model ID (e.g., 'anthropic.claude-3-sonnet-20240229-v1:0')
                      Use 'LambdaHook' to invoke a custom Lambda function instead.
            system_prompt: The system prompt as string or list of content objects
            content: The content for the user message (can include text and images)
            temperature: The temperature parameter for model inference (float or string)
            top_k: Optional top_k parameter (float or string)
            top_p: Optional top_p parameter (float or string)
            max_tokens: Optional max_tokens parameter (int or string)
            max_retries: Optional override for the instance's max_retries setting
            service_tier: Optional service tier (priority, standard, flex)
            model_lambda_hook_arn: Lambda function ARN (required when model_id is 'LambdaHook')

        Returns:
            Response object with metering information (same format for both Bedrock and Lambda)
        """
        # Route to Lambda hook if model_id is LambdaHook
        if model_id == LAMBDA_HOOK_MODEL_ID:
            return self._invoke_lambda_hook(
                lambda_arn=model_lambda_hook_arn,
                system_prompt=system_prompt,
                content=content,
                temperature=temperature,
                top_k=top_k,
                top_p=top_p,
                max_tokens=max_tokens,
                max_retries=max_retries,
                context=context,
            )

        # Track total requests
        self._put_metric("BedrockRequestsTotal", 1)

        # Use instance max_retries if not overridden
        effective_max_retries = (
            max_retries if max_retries is not None else self.max_retries
        )

        # Format system prompt if needed
        if isinstance(system_prompt, str):
            formatted_system_prompt = [{"text": system_prompt}]
        else:
            formatted_system_prompt = system_prompt

        # Check for cachePoint tags in content
        has_cachepoint_tags = any(
            "text" in item
            and isinstance(item["text"], str)
            and "<<CACHEPOINT>>" in item["text"]
            for item in content
        )

        if has_cachepoint_tags:
            if self._is_model_cachepoint_supported(model_id):
                # Process content for cachePoint tags with supported model
                processed_content = self._preprocess_content_for_cachepoint(content)
                logger.info(
                    f"Applied cachePoint processing for supported model: {model_id}"
                )
            else:
                # For unsupported models, just remove the <<CACHEPOINT>> tags but keep content intact
                processed_content = []
                for item in content:
                    if (
                        "text" in item
                        and isinstance(item["text"], str)
                        and "<<CACHEPOINT>>" in item["text"]
                    ):
                        # Remove the cachepoint tags but keep the text
                        clean_text = item["text"].replace("<<CACHEPOINT>>", "")
                        processed_content.append({"text": clean_text})
                        logger.warning(
                            f"Removed <<CACHEPOINT>> tags for unsupported model: {model_id}. "
                            "CachePoint is supported for standard cross-region inference profiles "
                            "and application inference profiles that wrap supported foundation models."
                        )
                    else:
                        # Pass through unchanged
                        processed_content.append(item)
        else:
            # No cachepoint tags, use content as is
            processed_content = content

        # Build message
        message = {"role": "user", "content": processed_content}
        messages = [message]

        # Convert temperature to float if it's a string
        if isinstance(temperature, str):
            try:
                temperature = float(temperature)
            except ValueError:
                logger.warning(
                    f"Failed to convert temperature value '{temperature}' to float. Using default 0.0"
                )
                temperature = 0.0

        # Claude 4.7+ models don't support temperature, top_k, or top_p parameters
        is_claude_4_7 = _is_claude_4_7_model(model_id)
        if is_claude_4_7:
            inference_config = {}
            logger.info(
                f"Skipping temperature/top_p for Claude 4.7+ model: {model_id} "
                "(these parameters are deprecated for this model)"
            )
        else:
            # Initialize inference config with temperature
            inference_config = {"temperature": temperature}

            # Handle top_p parameter - use top_p if it's positive, otherwise use temperature
            # Some models don't allow both temperature and top_p to be specified
            # This allows temperature=0.0 for deterministic output (recommended by Anthropic)
            if top_p is not None:
                # Convert top_p to float if it's a string
                if isinstance(top_p, str):
                    try:
                        top_p = float(top_p)
                    except ValueError:
                        logger.warning(
                            f"Failed to convert top_p value '{top_p}' to float. Not using top_p."
                        )
                        top_p = None

                # Only use top_p if it's positive (greater than 0)
                if top_p is not None and top_p > 0:
                    inference_config["topP"] = top_p
                    # Remove temperature when using top_p to avoid conflicts
                    del inference_config["temperature"]
                    logger.debug(f"Using top_p={top_p} for inference (temperature ignored)")
                else:
                    logger.debug(
                        f"Using temperature={temperature} for inference (top_p is 0 or None)"
                    )

        # Handle max_tokens parameter
        if max_tokens is not None:
            # Convert max_tokens to int if it's a string
            if isinstance(max_tokens, str):
                try:
                    max_tokens = int(max_tokens)
                except ValueError:
                    logger.warning(
                        f"Failed to convert max_tokens value '{max_tokens}' to int. Not using max_tokens."
                    )
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
                    logger.warning(
                        f"Failed to convert top_k value '{top_k}' to float. Not using top_k."
                    )
                    top_k = None

        # Handle model-specific parameters
        if "anthropic" in model_id.lower():
            # Add parameters to additionalModelRequestFields for Claude (snake_case)
            # Skip top_k for Claude 4.7+ models (deprecated parameter)
            if top_k is not None and not is_claude_4_7:
                additional_model_fields["top_k"] = int(top_k)
            elif top_k is not None and is_claude_4_7:
                logger.info(
                    f"Skipping top_k for Claude 4.7+ model: {model_id} "
                    "(this parameter is deprecated for this model)"
                )

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

        # Add 1M context headers if needed
        use_model_id = model_id
        if model_id and model_id.endswith(":1m"):
            use_model_id = model_id[:-3]  # Remove ':1m'
            if additional_model_fields is None:
                additional_model_fields = {}
            additional_model_fields["anthropic_beta"] = ["context-1m-2025-08-07"]

        # Parse model ID to extract service tier from suffix
        base_model_id, tier_from_suffix = parse_model_id(use_model_id)

        # Use tier from model ID suffix if present, otherwise use service_tier parameter
        effective_service_tier = tier_from_suffix or service_tier

        # Update use_model_id to base model ID (without tier suffix)
        if tier_from_suffix:
            use_model_id = base_model_id
            logger.info(
                f"Extracted service tier '{tier_from_suffix}' from model ID. Using base model ID: {base_model_id}"
            )

        # If no additional model fields were added, set to None
        if not additional_model_fields:
            additional_model_fields = None

        # Normalize and validate service tier
        normalized_service_tier = None
        if effective_service_tier:
            tier_lower = effective_service_tier.lower().strip()
            if tier_lower in ["priority", "flex"]:
                normalized_service_tier = tier_lower
            elif tier_lower in ["standard", "default"]:
                normalized_service_tier = "default"
            else:
                logger.warning(
                    f"Invalid service_tier value '{effective_service_tier}'. "
                    f"Valid values are: priority, standard, flex. Using default tier."
                )

        # Get guardrail configuration if available
        guardrail_config = self.get_guardrail_config()

        # Build converse parameters
        converse_params: Dict[str, Any] = {
            "modelId": use_model_id,
            "messages": messages,
            "system": formatted_system_prompt,
            "inferenceConfig": inference_config,
            "additionalModelRequestFields": additional_model_fields,
        }

        # Add service tier if specified
        if normalized_service_tier:
            converse_params["serviceTier"] = {"type": normalized_service_tier}
            logger.info(f"Using service tier: {normalized_service_tier}")

        # Add guardrail config if available
        if guardrail_config:
            converse_params["guardrailConfig"] = guardrail_config

        # Start timing the entire request
        request_start_time = time.time()

        # Call the recursive retry function
        result = self._invoke_with_retry(
            model_id=model_id,
            converse_params=converse_params,
            retry_count=0,
            max_retries=effective_max_retries,
            request_start_time=request_start_time,
            context=context,
        )

        return result

    def _invoke_with_retry(
        self,
        model_id: str,
        converse_params: Dict[str, Any],
        retry_count: int,
        max_retries: int,
        request_start_time: float,
        last_exception: Optional[Exception] = None,
        context: str = "Unspecified",
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
                sanitized_params["messages"] = self._sanitize_messages_for_logging(
                    sanitized_params["messages"]
                )

            # Log detailed request parameters
            logger.info(f"Bedrock request attempt {retry_count + 1}/{max_retries}:")
            logger.info(f"  - model: {converse_params['modelId']}")
            logger.info(f"  - inferenceConfig: {converse_params['inferenceConfig']}")
            logger.info(f"  - system: {converse_params['system']}")
            logger.info(f"  - messages: {sanitized_params['messages']}")
            logger.info(
                f"  - additionalModelRequestFields: {converse_params['additionalModelRequestFields']}"
            )

            # Log guardrail usage if configured
            if "guardrailConfig" in converse_params:
                logger.debug(
                    f"  - guardrailConfig: {converse_params['guardrailConfig']}"
                )

            # Start timing this attempt
            attempt_start_time = time.time()

            # Make the API call
            response = self.client.converse(**converse_params)

            # Calculate duration
            duration = time.time() - attempt_start_time

            # Log response details, but sanitize large content
            sanitized_response = self._sanitize_response_for_logging(response)
            logger.info(
                f"Bedrock request successful after {retry_count + 1} attempts. Duration: {duration:.2f}s"
            )
            logger.debug(f"Response: {sanitized_response}")
            logger.info(f"Token Usage: {response.get('usage')}")
            # Track successful requests and latency
            self._put_metric("BedrockRequestsSucceeded", 1)
            self._put_metric("BedrockRequestLatency", duration * 1000, "Milliseconds")
            if retry_count > 0:
                self._put_metric("BedrockRetrySuccess", 1)

            # Track token usage
            if "usage" in response:
                inputTokens = response["usage"].get("inputTokens", 0)
                outputTokens = response["usage"].get("outputTokens", 0)
                total_tokens = response["usage"].get("totalTokens", 0)
                cacheReadInputTokens = response["usage"].get("cacheReadInputTokens", 0)
                cacheWriteInputTokens = response["usage"].get(
                    "cacheWriteInputTokens", 0
                )
                self._put_metric("InputTokens", inputTokens)
                self._put_metric("OutputTokens", outputTokens)
                self._put_metric("TotalTokens", total_tokens)
                self._put_metric("CacheReadInputTokens", cacheReadInputTokens)
                self._put_metric("CacheWriteInputTokens", cacheWriteInputTokens)

            # Calculate total duration
            total_duration = time.time() - request_start_time
            self._put_metric(
                "BedrockTotalLatency", total_duration * 1000, "Milliseconds"
            )

            # Create metering data
            usage = response.get("usage", {})
            response_with_metering = {
                "response": response,
                "metering": {f"{context}/bedrock/{model_id}": {**usage, "requests": 1}},
            }

            return response_with_metering

        except ClientError as e:
            # Handle boto3/botocore client errors (have response structure)
            error_code = e.response["Error"]["Code"]
            error_message = e.response["Error"]["Message"]

            retryable_errors = [
                "ThrottlingException",
                "ServiceQuotaExceededException",
                "RequestLimitExceeded",
                "TooManyRequestsException",
                "ServiceUnavailableException",
                "ModelErrorException",
                "InternalServerException",
                "InternalServerError",
                "RequestTimeout",
                "RequestTimeoutException",
            ]

            if error_code in retryable_errors:
                self._put_metric("BedrockThrottles", 1)

                # Check if we've reached max retries
                if retry_count >= max_retries:
                    logger.error(
                        f"Max retries ({max_retries}) exceeded. Last error: {error_message}"
                    )
                    self._put_metric("BedrockRequestsFailed", 1)
                    self._put_metric("BedrockMaxRetriesExceeded", 1)
                    raise

                # Calculate backoff time
                backoff = self._calculate_backoff(retry_count)
                logger.warning(
                    f"Bedrock throttling occurred (attempt {retry_count + 1}/{max_retries}). "
                    f"Error: {error_message}. "
                    f"Backing off for {backoff:.2f}s"
                )

                # Sleep for backoff period
                time.sleep(backoff)

                # Recursive call with incremented retry count
                return self._invoke_with_retry(
                    model_id=model_id,
                    converse_params=converse_params,
                    retry_count=retry_count + 1,
                    max_retries=max_retries,
                    request_start_time=request_start_time,
                    last_exception=e,
                    context=context,
                )
            else:
                logger.error(
                    f"Non-retryable Bedrock error: {error_code} - {error_message}"
                )
                self._put_metric("BedrockRequestsFailed", 1)
                self._put_metric("BedrockNonRetryableErrors", 1)
                raise

        except (
            ReadTimeoutError,
            ConnectTimeoutError,
            EndpointConnectionError,
            Urllib3ReadTimeoutError,
            RequestsReadTimeout,
            RequestsConnectTimeout,
        ) as e:
            # Handle timeout and connection errors (these are retryable)
            error_message = str(e)

            self._put_metric("BedrockTimeouts", 1)

            # Check if we've reached max retries
            if retry_count >= max_retries:
                logger.error(
                    f"Max retries ({max_retries}) exceeded. Last timeout error: {error_message}"
                )
                self._put_metric("BedrockRequestsFailed", 1)
                self._put_metric("BedrockMaxRetriesExceeded", 1)
                raise

            # Calculate backoff time
            backoff = self._calculate_backoff(retry_count)
            logger.warning(
                f"Bedrock timeout occurred (attempt {retry_count + 1}/{max_retries}). "
                f"Error: {error_message}. "
                f"Backing off for {backoff:.2f}s"
            )

            # Sleep for backoff period
            time.sleep(backoff)

            # Recursive call with incremented retry count
            return self._invoke_with_retry(
                model_id=model_id,
                converse_params=converse_params,
                retry_count=retry_count + 1,
                max_retries=max_retries,
                request_start_time=request_start_time,
                last_exception=e,
                context=context,
            )

        except Exception as e:
            # Handle unexpected errors (not retryable)
            error_message = str(e)
            logger.error(f"Unexpected Bedrock error: {error_message}", exc_info=True)
            self._put_metric("BedrockRequestsFailed", 1)
            self._put_metric("BedrockUnexpectedErrors", 1)
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
                logger.debug(
                    f"Using Bedrock Guardrail ID: {guardrail_id}, Version: {guardrail_version}"
                )
                return {
                    "guardrailIdentifier": guardrail_id,
                    "guardrailVersion": guardrail_version,
                    "trace": "enabled",  # Enable tracing for guardrail violations
                }
        except ValueError:
            logger.warning(
                f"Invalid GUARDRAIL_ID_AND_VERSION format: {guardrail_env}. Expected format: 'id:version'"
            )

        return None

    def generate_embedding(
        self,
        text: Optional[str] = None,
        model_id: str = "amazon.titan-embed-text-v1",
        max_retries: Optional[int] = None,
        image_bytes: Optional[bytes] = None,
        input_type: Optional[str] = "search_document",
    ) -> List[float]:
        """
        Generate an embedding vector for text and/or image using Amazon Bedrock.

        Supports multiple embedding models:
        - Amazon Titan Embed Text (text only)
        - Amazon Titan Multimodal Embedding (text + image)
        - Cohere Embed v3/v4 (text + image, multimodal)

        Args:
            text: The text to generate embeddings for (optional if image_bytes provided)
            model_id: The embedding model ID to use (default: amazon.titan-embed-text-v1)
            max_retries: Optional override for the instance's max_retries setting
            image_bytes: Optional image bytes for multimodal embedding models
            input_type: Input type for Cohere models (search_document, search_query,
                       classification, clustering). Defaults to search_document.

        Returns:
            List of floats representing the embedding vector
        """
        if not text and image_bytes is None:
            # Return an empty vector for empty input
            return []

        # Use instance max_retries if not overridden
        effective_max_retries = (
            max_retries if max_retries is not None else self.max_retries
        )

        # Track total embedding requests
        self._put_metric("BedrockEmbeddingRequestsTotal", 1)

        # Normalize whitespace if text provided
        normalized_text = " ".join(text.split()) if text else None

        # Prepare the request body based on the model
        request_body = self._build_embedding_request_body(
            model_id=model_id,
            text=normalized_text,
            image_bytes=image_bytes,
            input_type=input_type,
        )

        # Call the recursive embedding function
        return self._generate_embedding_with_retry(
            model_id=model_id,
            request_body=request_body,
            normalized_text=normalized_text or "(image-only)",
            retry_count=0,
            max_retries=effective_max_retries,
        )

    def generate_embeddings_batch(
        self,
        items: List[Dict[str, Any]],
        model_id: str = "amazon.titan-embed-text-v1",
        max_retries: Optional[int] = None,
        max_concurrent: int = 5,
        input_type: Optional[str] = "search_document",
        progress_callback: Optional[Any] = None,
    ) -> List[Optional[List[float]]]:
        """
        Generate embeddings for a batch of items with concurrency control.

        Each item in the batch can contain text, image_bytes, or both.

        Args:
            items: List of dicts with optional 'text' and 'image_bytes' keys
            model_id: The embedding model ID to use
            max_retries: Optional override for retry count
            max_concurrent: Maximum concurrent embedding requests
            input_type: Input type for Cohere models
            progress_callback: Optional callable(completed, total) for progress updates

        Returns:
            List of embedding vectors (None for failed items)
        """
        import concurrent.futures

        total = len(items)
        results: List[Optional[List[float]]] = [None] * total
        completed = 0

        def _embed_single(index: int, item: Dict[str, Any]) -> tuple:
            """Embed a single item and return (index, embedding)."""
            try:
                embedding = self.generate_embedding(
                    text=item.get("text"),
                    model_id=model_id,
                    max_retries=max_retries,
                    image_bytes=item.get("image_bytes"),
                    input_type=input_type,
                )
                return (index, embedding)
            except Exception as e:
                logger.warning(f"Failed to generate embedding for item {index}: {e}")
                return (index, None)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            futures = {
                executor.submit(_embed_single, i, item): i
                for i, item in enumerate(items)
            }
            for future in concurrent.futures.as_completed(futures):
                idx, embedding = future.result()
                results[idx] = embedding
                completed += 1
                if progress_callback:
                    try:
                        progress_callback(completed, total)
                    except Exception:
                        pass

        return results

    def _build_embedding_request_body(
        self,
        model_id: str,
        text: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        input_type: Optional[str] = "search_document",
    ) -> str:
        """
        Build the JSON request body for an embedding model.

        Supports:
        - Amazon Titan Embed Text v1/v2: text-only via inputText
        - Amazon Titan Multimodal Embedding: text + image via inputText/inputImage
        - Cohere Embed v3/v4: text + image via texts/images arrays

        Args:
            model_id: The embedding model ID
            text: Optional text input
            image_bytes: Optional image bytes
            input_type: Input type for Cohere models

        Returns:
            JSON string for the request body
        """
        import base64

        model_lower = model_id.lower()

        if "cohere" in model_lower:
            # Cohere Embed v3/v4 format
            body: Dict[str, Any] = {
                "input_type": input_type or "search_document",
            }
            # Detect v4 models (embed-v4) vs v3 (embed-english-v3, embed-multilingual-v3)
            is_v4 = "embed-v4" in model_lower
            if is_v4:
                # Cohere v4 requires explicit embedding type and supports output_dimension
                body["embedding_types"] = ["float"]
                body["output_dimension"] = 1024
            if text:
                body["texts"] = [text]
            if image_bytes is not None:
                img_b64 = base64.b64encode(image_bytes).decode("utf-8")
                if is_v4:
                    # Cohere v4 requires data URI format for images
                    body["images"] = [f"data:image/png;base64,{img_b64}"]
                else:
                    # Cohere v3 uses raw base64
                    body["images"] = [img_b64]
            return json.dumps(body)

        elif "titan-embed-image" in model_lower or (
            "titan-embed" in model_lower and image_bytes is not None
        ):
            # Amazon Titan Multimodal Embedding G1 format
            body = {}
            if text:
                body["inputText"] = text
            if image_bytes is not None:
                img_b64 = base64.b64encode(image_bytes).decode("utf-8")
                body["inputImage"] = img_b64
            return json.dumps(body)

        elif "titan-embed" in model_lower:
            # Amazon Titan Embed Text v1/v2 (text-only)
            return json.dumps({"inputText": text or ""})

        else:
            # Default format
            body = {}
            if text:
                body["text"] = text
            return json.dumps(body)

    def _generate_embedding_with_retry(
        self,
        model_id: str,
        request_body: str,
        normalized_text: str,
        retry_count: int,
        max_retries: int,
        last_exception: Optional[Exception] = None,
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
            logger.info(
                f"Bedrock embedding request attempt {retry_count + 1}/{max_retries}:"
            )
            logger.debug(f"  - model: {model_id}")
            logger.debug(f"  - input text length: {len(normalized_text)} characters")

            attempt_start_time = time.time()
            response = self.client.invoke_model(
                modelId=model_id,
                contentType="application/json",
                accept="application/json",
                body=request_body,
            )
            duration = time.time() - attempt_start_time

            # Extract the embedding vector from response
            response_body = json.loads(response["body"].read())

            # Handle different response formats based on the model
            if "amazon.titan-embed" in model_id:
                embedding = response_body.get("embedding", [])
            elif "cohere" in model_id.lower() and "embed-v4" in model_id.lower():
                # Cohere Embed v4 returns {"embeddings": {"float": [[...]]}}
                embeddings_obj = response_body.get("embeddings", {})
                if isinstance(embeddings_obj, dict):
                    float_embeddings = embeddings_obj.get("float", [])
                    embedding = float_embeddings[0] if float_embeddings else []
                else:
                    # Fallback for unexpected format
                    embedding = embeddings_obj[0] if embeddings_obj else []
            else:
                # Default extraction format (Cohere v3 and others)
                embedding = response_body.get("embedding", [])

            # Track successful requests and latency
            self._put_metric("BedrockEmbeddingRequestsSucceeded", 1)
            self._put_metric(
                "BedrockEmbeddingRequestLatency", duration * 1000, "Milliseconds"
            )

            logger.debug(f"Generated embedding with {len(embedding)} dimensions")
            return embedding

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_message = e.response["Error"]["Message"]

            retryable_errors = [
                "ThrottlingException",
                "ServiceQuotaExceededException",
                "RequestLimitExceeded",
                "TooManyRequestsException",
                "ServiceUnavailableException",
                "InternalServerException",
                "InternalServerError",
                "RequestTimeout",
                "ReadTimeout",
                "TimeoutError",
                "RequestTimeoutException",
            ]

            if error_code in retryable_errors:
                self._put_metric("BedrockEmbeddingThrottles", 1)

                # Check if we've reached max retries
                if retry_count >= max_retries:
                    logger.error(
                        f"Max retries ({max_retries}) exceeded for embedding. Last error: {error_message}"
                    )
                    self._put_metric("BedrockEmbeddingRequestsFailed", 1)
                    self._put_metric("BedrockEmbeddingMaxRetriesExceeded", 1)
                    raise

                # Calculate backoff time
                backoff = self._calculate_backoff(retry_count)
                logger.warning(
                    f"Bedrock throttling occurred (attempt {retry_count + 1}/{max_retries}). "
                    f"Error: {error_message}. "
                    f"Backing off for {backoff:.2f}s"
                )

                # Sleep for backoff period
                time.sleep(backoff)

                # Recursive call with incremented retry count
                return self._generate_embedding_with_retry(
                    model_id=model_id,
                    request_body=request_body,
                    normalized_text=normalized_text,
                    retry_count=retry_count + 1,
                    max_retries=max_retries,
                    last_exception=e,
                )
            else:
                logger.error(
                    f"Non-retryable Bedrock error for embedding: {error_code} - {error_message}"
                )
                self._put_metric("BedrockEmbeddingRequestsFailed", 1)
                self._put_metric("BedrockEmbeddingNonRetryableErrors", 1)
                raise

        except Exception as e:
            logger.error(
                f"Unexpected error generating embedding: {str(e)}", exc_info=True
            )
            self._put_metric("BedrockEmbeddingRequestsFailed", 1)
            self._put_metric("BedrockEmbeddingUnexpectedErrors", 1)
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
        return response_obj["output"]["message"]["content"][0].get("text", "")

    def format_prompt(
        self,
        prompt_template: str,
        substitutions: dict[str, str],
        required_placeholders: list[str] | None = None,
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
            missing_placeholders = [
                p for p in required_placeholders if f"{{{p}}}" not in prompt_template
            ]
            if missing_placeholders:
                raise ValueError(
                    f"Prompt template must contain the following placeholders: {', '.join([f'{{{p}}}' for p in missing_placeholders])}"
                )

        # Check if template uses {PLACEHOLDER} format and convert to %(PLACEHOLDER)s for secure replacement
        if any(f"{{{key}}}" in prompt_template for key in substitutions):
            for key in substitutions:
                placeholder = f"{{{key}}}"
                if placeholder in prompt_template:
                    prompt_template = prompt_template.replace(placeholder, f"%({key})s")

        # Apply substitutions using % operator which is safer than .format()
        return prompt_template % substitutions

    def _invoke_lambda_hook(
        self,
        lambda_arn: Optional[str],
        system_prompt: Union[str, List[Dict[str, str]]],
        content: List[Dict[str, Any]],
        temperature: Union[float, str] = 0.0,
        top_k: Optional[Union[float, str]] = None,
        top_p: Optional[Union[float, str]] = None,
        max_tokens: Optional[Union[int, str]] = None,
        max_retries: Optional[int] = None,
        context: str = "Unspecified",
    ) -> Dict[str, Any]:
        """
        Invoke a custom Lambda function instead of Bedrock for LLM inference.

        The Lambda receives a Converse API-compatible payload with images converted
        to S3 references (to avoid Lambda's 6MB payload limit). The Lambda must
        return a Converse API-compatible response.

        Args:
            lambda_arn: ARN of the Lambda function to invoke
            system_prompt: The system prompt as string or list of content objects
            content: The content for the user message (can include text and images)
            temperature: The temperature parameter for model inference
            top_k: Optional top_k parameter
            top_p: Optional top_p parameter
            max_tokens: Optional max_tokens parameter
            max_retries: Optional override for retry count
            context: Context prefix for metering key

        Returns:
            Response object with metering information (same format as Bedrock responses)

        Raises:
            ValueError: If lambda_arn is not provided or invalid
            Exception: If Lambda invocation fails after retries
        """
        if not lambda_arn:
            raise ValueError(
                "model_lambda_hook_arn is required when model is 'LambdaHook'. "
                "Configure the Lambda function ARN in the configuration."
            )

        # Validate Lambda function name starts with GENAIIDP-
        # Extract function name from ARN (last segment after ':function:')
        if ":function:" in lambda_arn:
            func_name_part = lambda_arn.split(":function:")[-1]
            # Handle alias/version suffix (function:name:alias)
            func_name = func_name_part.split(":")[0]
            if not func_name.startswith("GENAIIDP-"):
                raise ValueError(
                    f"Lambda function name must start with 'GENAIIDP-'. "
                    f"Got function name: '{func_name}' from ARN: '{lambda_arn}'"
                )

        self._put_metric("LambdaHookRequestsTotal", 1)

        # Format system prompt
        if isinstance(system_prompt, str):
            formatted_system_prompt = [{"text": system_prompt}]
        else:
            formatted_system_prompt = system_prompt

        # Strip <<CACHEPOINT>> tags from content (not applicable to custom Lambda)
        processed_content = []
        for item in content:
            if (
                "text" in item
                and isinstance(item["text"], str)
                and "<<CACHEPOINT>>" in item["text"]
            ):
                clean_text = item["text"].replace("<<CACHEPOINT>>", "")
                processed_content.append({"text": clean_text})
            else:
                processed_content.append(item)

        # Convert inline image bytes to S3 references to avoid 6MB Lambda payload limit
        processed_content = self._convert_images_to_s3_refs(processed_content)

        # Convert temperature to float
        if isinstance(temperature, str):
            try:
                temperature = float(temperature)
            except ValueError:
                temperature = 0.0

        # Build inference config
        inference_config: Dict[str, Any] = {"temperature": temperature}

        if top_p is not None:
            if isinstance(top_p, str):
                try:
                    top_p = float(top_p)
                except ValueError:
                    top_p = None
            if top_p is not None and top_p > 0:
                inference_config["topP"] = top_p

        if top_k is not None:
            if isinstance(top_k, str):
                try:
                    top_k = float(top_k)
                except ValueError:
                    top_k = None
            if top_k is not None:
                inference_config["topK"] = int(top_k)

        if max_tokens is not None:
            if isinstance(max_tokens, str):
                try:
                    max_tokens = int(max_tokens)
                except ValueError:
                    max_tokens = None
            if max_tokens is not None:
                inference_config["maxTokens"] = max_tokens

        # Build the Converse API-compatible payload for the Lambda
        message = {"role": "user", "content": processed_content}
        lambda_payload = {
            "modelId": LAMBDA_HOOK_MODEL_ID,
            "messages": [message],
            "system": formatted_system_prompt,
            "inferenceConfig": inference_config,
            "context": context,
        }

        # Invoke Lambda with retry logic
        effective_max_retries = max_retries if max_retries is not None else self.max_retries
        request_start_time = time.time()

        return self._invoke_lambda_hook_with_retry(
            lambda_arn=lambda_arn,
            lambda_payload=lambda_payload,
            retry_count=0,
            max_retries=effective_max_retries,
            request_start_time=request_start_time,
            context=context,
        )

    def _convert_images_to_s3_refs(
        self, content: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Convert inline image bytes in content to S3 references.

        This prevents hitting the Lambda 6MB payload limit when documents
        contain multiple page images. Images are uploaded to the working
        bucket under a temp/lambdahook/ prefix.

        Images that already use s3Location references are passed through unchanged.

        Args:
            content: Content list with potential inline image bytes

        Returns:
            Content list with images converted to S3 references
        """
        import base64
        import uuid

        working_bucket = os.environ.get("WORKING_BUCKET")
        if not working_bucket:
            logger.warning(
                "WORKING_BUCKET not set - cannot convert images to S3 refs for LambdaHook. "
                "Images will be sent inline (may hit 6MB Lambda payload limit)."
            )
            return content

        converted_content = []
        image_count = 0

        for item in content:
            if "image" not in item:
                converted_content.append(item)
                continue

            image_data = item["image"]
            source = image_data.get("source", {})
            img_format = image_data.get("format", "jpeg")

            # Skip if already an S3 reference
            if "s3Location" in source:
                converted_content.append(item)
                continue

            # Get the inline bytes
            img_bytes = source.get("bytes")
            if img_bytes is None:
                converted_content.append(item)
                continue

            # Handle base64-encoded strings (from serialized payloads)
            if isinstance(img_bytes, str):
                try:
                    img_bytes = base64.b64decode(img_bytes)
                except Exception:
                    logger.warning("Failed to decode base64 image data, passing through")
                    converted_content.append(item)
                    continue

            # Upload to S3
            image_key = f"temp/lambdahook/{uuid.uuid4().hex}.{img_format}"
            try:
                content_type_map = {
                    "jpeg": "image/jpeg",
                    "png": "image/png",
                    "gif": "image/gif",
                    "webp": "image/webp",
                }
                content_type = content_type_map.get(img_format, "application/octet-stream")

                self.s3_client.put_object(
                    Bucket=working_bucket,
                    Key=image_key,
                    Body=img_bytes,
                    ContentType=content_type,
                )

                s3_uri = f"s3://{working_bucket}/{image_key}"
                image_count += 1

                # Replace inline bytes with S3 reference
                s3_location = {"uri": s3_uri}
                # Only include bucketOwner if AWS_ACCOUNT_ID is set (Bedrock requires valid 12-digit ID or omit)
                account_id = os.environ.get("AWS_ACCOUNT_ID", "")
                if account_id and len(account_id) == 12:
                    s3_location["bucketOwner"] = account_id

                converted_content.append({
                    "image": {
                        "format": img_format,
                        "source": {
                            "s3Location": s3_location,
                        },
                    }
                })

                logger.debug(f"Uploaded image to S3: {s3_uri} ({len(img_bytes)} bytes)")

            except Exception as e:
                logger.warning(
                    f"Failed to upload image to S3 for LambdaHook: {str(e)}. "
                    "Falling back to inline bytes (may hit payload limit)."
                )
                converted_content.append(item)

        if image_count > 0:
            logger.info(
                f"Converted {image_count} inline image(s) to S3 references for LambdaHook"
            )

        return converted_content

    def _invoke_lambda_hook_with_retry(
        self,
        lambda_arn: str,
        lambda_payload: Dict[str, Any],
        retry_count: int,
        max_retries: int,
        request_start_time: float,
        last_exception: Optional[Exception] = None,
        context: str = "Unspecified",
    ) -> Dict[str, Any]:
        """
        Invoke Lambda hook with retry logic for transient failures.

        Args:
            lambda_arn: ARN of the Lambda function
            lambda_payload: Converse API-compatible payload
            retry_count: Current retry attempt
            max_retries: Maximum retry attempts
            request_start_time: When the original request started
            last_exception: Last exception for error reporting
            context: Context for metering

        Returns:
            Response with metering information

        Raises:
            Exception: If invocation fails after all retries
        """
        try:
            logger.info(
                f"LambdaHook request attempt {retry_count + 1}/{max_retries}: "
                f"ARN={lambda_arn}, context={context}"
            )

            attempt_start_time = time.time()

            # Serialize payload - handle bytes by converting to base64
            payload_json = json.dumps(lambda_payload, default=str)

            # Invoke Lambda synchronously
            response = self.lambda_client.invoke(
                FunctionName=lambda_arn,
                InvocationType="RequestResponse",
                Payload=payload_json.encode("utf-8"),
            )

            duration = time.time() - attempt_start_time

            # Check for Lambda-level errors
            function_error = response.get("FunctionError")

            if function_error:
                error_payload = json.loads(response["Payload"].read().decode("utf-8"))
                error_message = error_payload.get("errorMessage", str(error_payload))
                logger.error(
                    f"LambdaHook function error ({function_error}): {error_message}"
                )

                # Retry on unhandled errors (transient issues)
                if function_error == "Unhandled" and retry_count < max_retries:
                    backoff = self._calculate_backoff(retry_count)
                    logger.warning(
                        f"LambdaHook transient error, retrying in {backoff:.2f}s"
                    )
                    time.sleep(backoff)
                    return self._invoke_lambda_hook_with_retry(
                        lambda_arn=lambda_arn,
                        lambda_payload=lambda_payload,
                        retry_count=retry_count + 1,
                        max_retries=max_retries,
                        request_start_time=request_start_time,
                        context=context,
                    )

                self._put_metric("LambdaHookRequestsFailed", 1)
                raise RuntimeError(
                    f"LambdaHook function error: {error_message}"
                )

            # Parse response payload
            response_payload = json.loads(response["Payload"].read().decode("utf-8"))

            logger.info(
                f"LambdaHook request successful after {retry_count + 1} attempts. "
                f"Duration: {duration:.2f}s"
            )

            # Extract usage/metering from the Lambda response
            usage = response_payload.get("usage", {})
            if not usage:
                # Provide default metering if Lambda doesn't return usage
                usage = {
                    "inputTokens": 0,
                    "outputTokens": 0,
                    "totalTokens": 0,
                }

            # Track metrics
            self._put_metric("LambdaHookRequestsSucceeded", 1)
            self._put_metric("LambdaHookRequestLatency", duration * 1000, "Milliseconds")

            total_duration = time.time() - request_start_time
            self._put_metric("LambdaHookTotalLatency", total_duration * 1000, "Milliseconds")

            # Build response in the same format as Bedrock responses
            response_with_metering = {
                "response": response_payload,
                "metering": {
                    f"{context}/lambda_hook/{lambda_arn}": {
                        **usage,
                        "requests": 1,
                    }
                },
            }

            return response_with_metering

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_message = e.response["Error"]["Message"]

            retryable_errors = [
                "TooManyRequestsException",
                "ServiceException",
                "EC2ThrottledException",
                "ResourceConflictException",
            ]

            if error_code in retryable_errors and retry_count < max_retries:
                self._put_metric("LambdaHookThrottles", 1)
                backoff = self._calculate_backoff(retry_count)
                logger.warning(
                    f"LambdaHook throttled ({error_code}), retrying in {backoff:.2f}s"
                )
                time.sleep(backoff)
                return self._invoke_lambda_hook_with_retry(
                    lambda_arn=lambda_arn,
                    lambda_payload=lambda_payload,
                    retry_count=retry_count + 1,
                    max_retries=max_retries,
                    request_start_time=request_start_time,
                    last_exception=e,
                    context=context,
                )
            else:
                logger.error(
                    f"LambdaHook error: {error_code} - {error_message}"
                )
                self._put_metric("LambdaHookRequestsFailed", 1)
                raise

        except Exception as e:
            error_message = str(e)
            if "RuntimeError" not in type(e).__name__ and retry_count < max_retries:
                backoff = self._calculate_backoff(retry_count)
                logger.warning(
                    f"LambdaHook unexpected error, retrying in {backoff:.2f}s: {error_message}"
                )
                time.sleep(backoff)
                return self._invoke_lambda_hook_with_retry(
                    lambda_arn=lambda_arn,
                    lambda_payload=lambda_payload,
                    retry_count=retry_count + 1,
                    max_retries=max_retries,
                    request_start_time=request_start_time,
                    last_exception=e,
                    context=context,
                )

            logger.error(f"LambdaHook failed: {error_message}", exc_info=True)
            self._put_metric("LambdaHookRequestsFailed", 1)
            raise

    def _calculate_backoff(self, retry_count: int) -> float:
        """
        Calculate exponential backoff time with jitter.

        Args:
            retry_count: Current retry attempt (0-based)

        Returns:
            Backoff time in seconds
        """
        # Exponential backoff with base of 2
        backoff_seconds = min(self.max_backoff, self.initial_backoff * (2**retry_count))

        # Add jitter (random value between 0 and 1 second)
        jitter = random.random()  # nosec B311 - retry jitter

        return backoff_seconds + jitter

    def _put_metric(
        self, metric_name: str, value: Union[int, float], unit: str = "Count"
    ):
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

    def _sanitize_messages_for_logging(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Create a copy of messages with image content replaced for logging.

        Args:
            messages: List of message objects for Bedrock API

        Returns:
            Sanitized message objects suitable for logging
        """
        sanitized = copy.deepcopy(messages)

        for message in sanitized:
            if "content" in message and isinstance(message["content"], list):
                for content_item in message["content"]:
                    # Check for image type content
                    if (
                        isinstance(content_item, dict)
                        and content_item.get("type") == "image"
                    ):
                        # Replace actual image data with placeholder
                        if "source" in content_item:
                            content_item["source"] = {"data": "[image_data]"}
                    elif isinstance(content_item, dict) and "image" in content_item:
                        # Handle different image format used by some models
                        content_item["image"] = "[image_data]"
                    elif isinstance(content_item, dict) and "bytes" in content_item:
                        # Handle raw binary format
                        content_item["bytes"] = "[binary_data]"
                    elif isinstance(content_item, dict) and "document" in content_item:
                        # Handle different image format used by some models
                        content_item["document"] = "[document_data]"

        return sanitized

    def _sanitize_response_for_logging(
        self, response: Dict[str, Any]
    ) -> Dict[str, Any]:
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
        if "output" in sanitized and "message" in sanitized["output"]:
            message = sanitized["output"]["message"]
            if "content" in message:
                content = message["content"]

                # Handle list of content items (multimodal responses)
                if isinstance(content, list):
                    for i, item in enumerate(content):
                        if isinstance(item, dict):
                            # Truncate text content if too long
                            if (
                                "text" in item
                                and isinstance(item["text"], str)
                                and len(item["text"]) > 500
                            ):
                                item["text"] = item["text"][:500] + "... [truncated]"
                            # Replace image data with placeholder
                            if "image" in item:
                                item["image"] = "[image_data]"
                # Handle string content
                elif isinstance(content, str) and len(content) > 500:
                    message["content"] = content[:500] + "... [truncated]"

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
