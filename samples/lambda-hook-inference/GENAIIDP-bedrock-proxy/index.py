# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
GENAIIDP-bedrock-proxy: Sample Lambda Hook that proxies to Amazon Bedrock.

This Lambda function receives a Converse API-compatible payload from the
GenAI IDP Accelerator's LambdaHook feature and forwards it to Amazon Bedrock.

Use this as:
- A starting template for custom Lambda hooks
- A passthrough with optional pre/post processing
- A way to route to different models based on context

The function reads images from S3 (since the accelerator converts inline
images to S3 references to avoid the 6MB Lambda payload limit), converts
them back to inline bytes for Bedrock, and returns the response in
Converse API-compatible format.
"""

import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

# Initialize clients
bedrock_client = boto3.client("bedrock-runtime")
s3_client = boto3.client("s3")

# Configuration - override the model to use via environment variable
TARGET_MODEL_ID = os.environ.get("TARGET_MODEL_ID", "us.amazon.nova-pro-v1:0")


def download_image_from_s3(s3_uri: str) -> bytes:
    """Download image bytes from an S3 URI."""
    # Parse s3://bucket/key format
    parts = s3_uri.replace("s3://", "").split("/", 1)
    bucket = parts[0]
    key = parts[1]
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def convert_s3_images_to_inline(content: list) -> list:
    """
    Convert S3 image references back to inline bytes for Bedrock.

    The IDP accelerator uploads images to S3 to avoid Lambda's 6MB payload limit.
    Bedrock Converse API accepts both inline bytes and S3 references, but this
    function demonstrates how to read S3 images if your target API needs inline bytes.
    """
    converted = []
    for item in content:
        if "image" in item:
            source = item["image"].get("source", {})
            if "s3Location" in source:
                # Download from S3 and convert to inline bytes
                s3_uri = source["s3Location"]["uri"]
                try:
                    img_bytes = download_image_from_s3(s3_uri)
                    converted.append(
                        {
                            "image": {
                                "format": item["image"]["format"],
                                "source": {"bytes": img_bytes},
                            }
                        }
                    )
                    logger.info(
                        f"Downloaded image from S3: {s3_uri} ({len(img_bytes)} bytes)"
                    )
                except Exception as e:
                    logger.error(f"Failed to download image from {s3_uri}: {e}")
                    # Pass through the S3 reference as-is (Bedrock supports s3Location too)
                    converted.append(item)
            else:
                converted.append(item)
        else:
            converted.append(item)
    return converted


def lambda_handler(event, context):
    """
    Lambda handler that proxies the LambdaHook payload to Amazon Bedrock.

    Expected event format (Converse API-compatible):
    {
        "modelId": "LambdaHook",
        "messages": [{"role": "user", "content": [...]}],
        "system": [{"text": "..."}],
        "inferenceConfig": {"temperature": 0.0, ...},
        "context": "Extraction"  # Which IDP step is calling
    }

    Returns Converse API-compatible response:
    {
        "output": {"message": {"role": "assistant", "content": [{"text": "..."}]}},
        "usage": {"inputTokens": N, "outputTokens": N, "totalTokens": N}
    }
    """
    logger.info(
        f"Received LambdaHook request. Context: {event.get('context', 'unknown')}"
    )
    logger.info(f"Proxying to Bedrock model: {TARGET_MODEL_ID}")

    # Extract payload components
    messages = event.get("messages", [])
    system = event.get("system", [])
    inference_config = event.get("inferenceConfig", {})

    # Convert S3 image references to inline bytes for Bedrock
    # (Bedrock also supports s3Location directly, but this demonstrates the conversion)
    for message in messages:
        if "content" in message:
            message["content"] = convert_s3_images_to_inline(message["content"])

    # Build Bedrock Converse API parameters
    converse_params = {
        "modelId": TARGET_MODEL_ID,
        "messages": messages,
        "system": system,
        "inferenceConfig": {},
    }

    # Map inference config
    if "temperature" in inference_config:
        converse_params["inferenceConfig"]["temperature"] = inference_config[
            "temperature"
        ]
    if "maxTokens" in inference_config:
        converse_params["inferenceConfig"]["maxTokens"] = inference_config["maxTokens"]
    if "topP" in inference_config:
        converse_params["inferenceConfig"]["topP"] = inference_config["topP"]

    # === CUSTOMIZATION POINT ===
    # Add your custom pre-processing logic here:
    # - Modify prompts based on context (Extraction vs Classification etc.)
    # - Add custom system instructions
    # - Filter or transform content
    # - Route to different models based on document type

    logger.info(f"Calling Bedrock Converse API with model {TARGET_MODEL_ID}")

    try:
        # Call Bedrock Converse API
        response = bedrock_client.converse(**converse_params)

        # Extract usage data
        usage = response.get("usage", {})

        logger.info(
            f"Bedrock response received. "
            f"Input tokens: {usage.get('inputTokens', 0)}, "
            f"Output tokens: {usage.get('outputTokens', 0)}"
        )

        # === CUSTOMIZATION POINT ===
        # Add your custom post-processing logic here:
        # - Transform the response
        # - Add metadata
        # - Log or audit the results

        # Return Converse API-compatible response
        return {
            "output": response.get("output", {}),
            "usage": {
                "inputTokens": usage.get("inputTokens", 0),
                "outputTokens": usage.get("outputTokens", 0),
                "totalTokens": usage.get("totalTokens", 0),
            },
        }

    except Exception as e:
        logger.error(f"Bedrock invocation failed: {str(e)}")
        raise
