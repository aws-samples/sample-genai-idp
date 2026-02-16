# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
GENAIIDP-sagemaker-hook: Sample Lambda Hook that calls a SageMaker endpoint.

This Lambda function receives a Converse API-compatible payload from the
GenAI IDP Accelerator's LambdaHook feature and forwards it to a SageMaker
real-time inference endpoint.

Use this as:
- A template for integrating SageMaker-hosted models with GenAI IDP
- An example of converting Converse API format to SageMaker format
- A starting point for custom model integrations

The function:
1. Extracts system prompt and user content from the Converse API payload
2. Downloads images from S3 (since they arrive as S3 references)
3. Builds a SageMaker-compatible payload
4. Invokes the endpoint and maps the response back to Converse API format
"""

import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Initialize clients
sagemaker_runtime = boto3.client("sagemaker-runtime")
s3_client = boto3.client("s3")

# Configuration
SAGEMAKER_ENDPOINT_NAME = os.environ.get("SAGEMAKER_ENDPOINT_NAME", "")
CONTENT_TYPE = os.environ.get("CONTENT_TYPE", "application/json")
ACCEPT_TYPE = os.environ.get("ACCEPT_TYPE", "application/json")


def download_image_from_s3(s3_uri: str) -> bytes:
    """Download image bytes from an S3 URI."""
    parts = s3_uri.replace("s3://", "").split("/", 1)
    bucket = parts[0]
    key = parts[1]
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def extract_text_and_images(messages: list) -> tuple:
    """
    Extract text content and images from Converse API messages.

    Args:
        messages: List of Converse API message objects

    Returns:
        Tuple of (combined_text, list_of_image_bytes)
    """
    texts = []
    images = []

    for message in messages:
        for item in message.get("content", []):
            if "text" in item:
                texts.append(item["text"])
            elif "image" in item:
                source = item["image"].get("source", {})
                if "s3Location" in source:
                    try:
                        img_bytes = download_image_from_s3(source["s3Location"]["uri"])
                        images.append(
                            {
                                "bytes": img_bytes,
                                "format": item["image"].get("format", "jpeg"),
                            }
                        )
                        logger.info(f"Downloaded image: {source['s3Location']['uri']}")
                    except Exception as e:
                        logger.error(f"Failed to download image: {e}")
                elif "bytes" in source:
                    images.append(
                        {
                            "bytes": source["bytes"],
                            "format": item["image"].get("format", "jpeg"),
                        }
                    )

    return "\n".join(texts), images


def lambda_handler(event, context):
    """
    Lambda handler that proxies the LambdaHook payload to a SageMaker endpoint.

    Expected event format (Converse API-compatible):
    {
        "modelId": "LambdaHook",
        "messages": [{"role": "user", "content": [...]}],
        "system": [{"text": "..."}],
        "inferenceConfig": {"temperature": 0.0, ...},
        "context": "Extraction"
    }

    Returns Converse API-compatible response:
    {
        "output": {"message": {"role": "assistant", "content": [{"text": "..."}]}},
        "usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0}
    }
    """
    if not SAGEMAKER_ENDPOINT_NAME:
        raise ValueError(
            "SAGEMAKER_ENDPOINT_NAME environment variable is required. "
            "Set it to your SageMaker endpoint name."
        )

    idp_context = event.get("context", "unknown")
    logger.info(f"Received LambdaHook request. Context: {idp_context}")
    logger.info(f"Forwarding to SageMaker endpoint: {SAGEMAKER_ENDPOINT_NAME}")

    # Extract system prompt
    system_texts = [item.get("text", "") for item in event.get("system", [])]
    system_prompt = "\n".join(system_texts)

    # Extract user content (text + images)
    messages = event.get("messages", [])
    user_text, images = extract_text_and_images(messages)

    # Get inference config
    inference_config = event.get("inferenceConfig", {})

    # =========================================================================
    # BUILD SAGEMAKER PAYLOAD
    #
    # Customize this section for your specific SageMaker model's expected format.
    # The example below shows a common text-generation format.
    # =========================================================================

    # Option A: Text-only payload (most SageMaker text models)
    sagemaker_payload = {
        "inputs": f"{system_prompt}\n\n{user_text}",
        "parameters": {
            "temperature": inference_config.get("temperature", 0.0),
            "max_new_tokens": inference_config.get("maxTokens", 4096),
        },
    }

    # Option B: Multimodal payload with base64 images (uncomment if your model supports images)
    # if images:
    #     sagemaker_payload["images"] = [
    #         {
    #             "data": base64.b64encode(img["bytes"]).decode("utf-8"),
    #             "format": img["format"],
    #         }
    #         for img in images
    #     ]

    logger.info(
        f"Invoking SageMaker endpoint with "
        f"{len(user_text)} chars of text and {len(images)} images"
    )

    try:
        # Invoke SageMaker endpoint
        response = sagemaker_runtime.invoke_endpoint(
            EndpointName=SAGEMAKER_ENDPOINT_NAME,
            ContentType=CONTENT_TYPE,
            Accept=ACCEPT_TYPE,
            Body=json.dumps(sagemaker_payload),
        )

        # Parse SageMaker response
        response_body = json.loads(response["Body"].read().decode("utf-8"))

        # =====================================================================
        # PARSE SAGEMAKER RESPONSE
        #
        # Customize this section for your model's response format.
        # Common formats:
        #   - {"generated_text": "..."} (HuggingFace Text Generation)
        #   - [{"generated_text": "..."}] (HuggingFace Pipeline)
        #   - {"predictions": [{"output": "..."}]} (SageMaker built-in)
        #   - {"outputs": "..."} (Custom models)
        # =====================================================================

        # Try common response formats
        if isinstance(response_body, list) and len(response_body) > 0:
            # HuggingFace Pipeline format: [{"generated_text": "..."}]
            generated_text = response_body[0].get(
                "generated_text", str(response_body[0])
            )
        elif isinstance(response_body, dict):
            # Try common dict formats
            generated_text = (
                response_body.get("generated_text")
                or response_body.get("outputs")
                or response_body.get("output")
                or response_body.get("predictions", [{}])[0].get("output")
                or json.dumps(response_body)
            )
        else:
            generated_text = str(response_body)

        # Extract token counts if available from the SageMaker response
        input_tokens = (
            response_body.get("input_tokens", 0)
            if isinstance(response_body, dict)
            else 0
        )
        output_tokens = (
            response_body.get("output_tokens", 0)
            if isinstance(response_body, dict)
            else 0
        )

        logger.info(
            f"SageMaker response received. Generated text length: {len(str(generated_text))}"
        )

        # Return Converse API-compatible response
        return {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [{"text": str(generated_text)}],
                }
            },
            "usage": {
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
                "totalTokens": input_tokens + output_tokens,
            },
        }

    except Exception as e:
        logger.error(f"SageMaker invocation failed: {str(e)}")
        raise
