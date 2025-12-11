# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Lambda function to provide examples with ground truth data based on S3 Vectors lookup.

Key Features Demonstrated:
- Dynamically retrieve similar examples based on document content using vector similarity search
- Provide few-shot examples to improve extraction accuracy through example-based prompting
- Leverage S3 Vectors for efficient similarity search across large example datasets
- Integrate multimodal embeddings using Amazon Nova models for image-based similarity
- Customize example selection based on document characteristics and business rules
"""

import json
import logging
import base64
import boto3
import os

from idp_common import bedrock, s3
from idp_common.bedrock import format_prompt

from typing import Any

logger = logging.getLogger(__name__)
level = logging.getLevelName(os.environ.get("LOG_LEVEL", "INFO"))
logger.setLevel(level)

# Parse environment variables with error handling
try:
    S3VECTOR_BUCKET = os.environ["S3VECTOR_BUCKET"]
    S3VECTOR_INDEX = os.environ["S3VECTOR_INDEX"]
    S3VECTOR_DIMENSIONS = int(os.environ["S3VECTOR_DIMENSIONS"])
    MODEL_ID = os.environ["MODEL_ID"]
    TOP_K = int(os.environ["TOP_K"])
    THRESHOLD = float(os.environ["THRESHOLD"])
except (KeyError, ValueError, IndexError) as e:
    logger.error(f"Failed to parse environment variables: {e}")
    raise

# Initialize clients
s3vectors = boto3.client("s3vectors")
bedrock_client = bedrock.BedrockClient()


def lambda_handler(event, context):
    """
    Process a document to find similar examples using S3 Vectors similarity search.
    This function will expand {FEW_SHOT_EXAMPLES} in the extraction prompt to examples
    found in S3 Vectors lookup.
    """

    try:
        logger.info("=== DYNAMIC FEW-SHOT LAMBDA INVOKED ===")
        logger.debug(f"Complete input event: {json.dumps(event, indent=2)}")

        # Extract key information from the payload
        config = event.get("config", {})
        placeholders = event.get("prompt_placeholders", {})
        default_content = event.get("default_task_prompt_content", [])
        document = event.get("serialized_document", {})
               
        document_class = placeholders.get("DOCUMENT_CLASS", "")
        document_text = placeholders.get("DOCUMENT_TEXT", "")
        document_image_uris = placeholders.get("DOCUMENT_IMAGE", [])
        document_id = document.get("id", "unknown")

        # Log extraction config details
        extraction_config = config.get("extraction", {})
        logger.info(f"=== EXTRACTION CONFIG ===")
        logger.info(f"Model: {extraction_config.get('model', 'Not specified')}")
        logger.info(f"Temperature: {extraction_config.get('temperature', 'Not specified')}")
        logger.info(f"Max tokens: {extraction_config.get('max_tokens', 'Not specified')}")
        logger.info(f"Custom Lambda ARN: {extraction_config.get('custom_prompt_lambda_arn', 'Not specified')}")
        
        # Default system prompt from config
        default_system_prompt = config.get("extraction", {}).get("system_prompt", "")
        logger.info(f"Default system prompt length: {len(default_system_prompt)} characters")
        default_task_prompt = config.get("extraction", {}).get("task_prompt", "")
        logger.info(f"Default task prompt length: {len(default_task_prompt)} characters")

        logger.info(f"=== HANDLE INPUT DOCUMENT ===")

        # Handle input document
        result = _handle_input_document(placeholders, default_system_prompt, default_task_prompt)

        # Log complete output structure
        logger.info(f"=== OUTPUT ANALYSIS ===")
        logger.info(f"Output keys: {list(result.keys())}")
        logger.info(f"System prompt length: {len(result.get('system_prompt', ''))}")
        logger.info(f"System prompt (first 200 chars): {result.get('system_prompt', '')[:200]}...")
        
        task_content = result.get('task_prompt_content', [])
        logger.info(f"Task prompt content items: {len(task_content)}")
        for i, item in enumerate(task_content[:3]):  # Log first 3 items
            logger.info(f"Content item {i}: keys={list(item.keys())}")
            if 'text' in item:
                logger.info(f"  Text length: {len(item['text'])} characters")
                logger.info(f"  Text sample (first 150 chars): {item['text'][:150]}...")
            if 'image_uri' in item:
                logger.info(f"  Image URI: {item['image_uri']}")
        
        if len(task_content) > 3:
            logger.info(f"  ... and {len(task_content) - 3} more content items")

        logger.debug(f"Complete result output: {json.dumps(result, indent=2)}")
        logger.info("=== DYNAMIC FEW-SHOT LAMBDA COMPLETED ===")
        return result

    except Exception as e:
        logger.error(f"=== DYNAMIC FEW-SHOT LAMBDA ERROR ===")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error message: {str(e)}")
        logger.error(
            f"Input event keys: {list(event.keys()) if 'event' in locals() else 'Unknown'}"
        )
        # In demo, we'll fail gracefully with detailed error info
        raise Exception(f"Dynamic few-shot Lambda failed: {str(e)}")

def _handle_input_document(placeholders, default_system_prompt, default_task_prompt):
    """
    Handle input request and return custom system_prompt and task_prompt_content
    """
    substitutions = {
        "DOCUMENT_TEXT": placeholders.get("DOCUMENT_TEXT"),
        "DOCUMENT_CLASS": placeholders.get("DOCUMENT_CLASS"),
        "ATTRIBUTE_NAMES_AND_DESCRIPTIONS": placeholders.get("ATTRIBUTE_NAMES_AND_DESCRIPTIONS")
    }
    task_prompt_content = _build_prompt_content(
        default_task_prompt, substitutions, placeholders.get("DOCUMENT_IMAGE")
    )

    return {
        "system_prompt": default_system_prompt,
        "task_prompt_content": task_prompt_content
    }


def _build_prompt_content(
    prompt_template: str,
    substitutions: dict[str, Any],
    image_content: Any = None,
) -> list[dict[str, Any]]:
    """
    Build prompt content array handling FEW_SHOT_EXAMPLES and DOCUMENT_IMAGE placeholders.

    This consolidated method handles all placeholder types and combinations:
    - {FEW_SHOT_EXAMPLES}: Inserts few-shot examples from config
    - {DOCUMENT_IMAGE}: Inserts images at specific location
    - Regular text placeholders: DOCUMENT_TEXT, DOCUMENT_CLASS, etc.

    Args:
        prompt_template: The prompt template with optional placeholders
        substitutions: Dictionary of placeholder values
        image_content: Optional image content to insert (only used with {DOCUMENT_IMAGE})

    Returns:
        List of content items with text and image content properly ordered
    """
    content: list[dict[str, Any]] = []

    # Handle FEW_SHOT_EXAMPLES placeholder first
    if "{FEW_SHOT_EXAMPLES}" in prompt_template:
        parts = prompt_template.split("{FEW_SHOT_EXAMPLES}")
        if len(parts) == 2:
            # Process before examples
            content.extend(
                _build_text_and_image_content(parts[0], substitutions, image_content)
            )

            # Add few-shot examples
            content.extend(_build_few_shot_examples_content(image_content))

            # Process after examples (only pass images if not already used)
            image_for_after = (
                None if "{DOCUMENT_IMAGE}" in parts[0] else image_content
            )
            content.extend(
                _build_text_and_image_content(parts[1], substitutions, image_for_after)
            )

            return content

    # No FEW_SHOT_EXAMPLES, just handle text and images
    logger.warn("Missing {FEW_SHOT_EXAMPLES} placeholder in prompt template")
    return _build_text_and_image_content(prompt_template, substitutions, image_content)


def _build_text_and_image_content(
    prompt_template: str,
    substitutions: dict[str, Any],
    image_content: Any = None,
) -> list[dict[str, Any]]:
    """
    Build content array with text and optionally images based on DOCUMENT_IMAGE placeholder.

    Args:
        prompt_template: Template that may contain {DOCUMENT_IMAGE}
        substitutions: Dictionary of placeholder values
        image_content: Optional image content

    Returns:
        List of content items
    """
    content: list[dict[str, Any]] = []

    if "{DOCUMENT_IMAGE}" in prompt_template:
        parts = prompt_template.split("{DOCUMENT_IMAGE}")
        if len(parts) == 2:
            # Add text before image
            before_text = _prepare_prompt_from_template(
                parts[0], substitutions, required_placeholders=[]
            )
            if before_text.strip():
                content.append({"text": before_text})

            # Add images
            if image_content:
                for image_uri in image_content:
                    content.append({"image_uri": image_uri})

            # Add text after image
            after_text = _prepare_prompt_from_template(
                parts[1], substitutions, required_placeholders=[]
            )
            if after_text.strip():
                content.append({"text": after_text})

            return content
        else:
            logger.warning("Invalid DOCUMENT_IMAGE placeholder usage")

    # No image placeholder, just text
    task_prompt = _prepare_prompt_from_template(
        prompt_template, substitutions, required_placeholders=[]
    )
    content.append({"text": task_prompt})

    return content


def _build_few_shot_examples_content(image_content: Any = None) -> list[dict[str, Any]]:
    """
    Build content items for few-shot examples from the configuration for a specific class.

    Args:
        image_content: Optional document image content

    Returns:
        List of content items containing text and image content for examples
    """
    content: list[dict[str, Any]] = []

    image_data = []
    if image_content:
        for image_uri in image_content:
            # Load image content
            if image_uri.startswith("s3://"):
                # Direct S3 URI
                image_bytes = s3.get_binary_content(image_uri)
            else:
                raise ValueError(f"Invalid file path {image_path} - expecting S3 path")

            image_data.append(image_bytes)

    examples = _s3vectors_find_similar_items(image_data)
    for example in examples:
        content.append({"text": example.get("attributesPrompt")})

        for image_uri in example.get("imageFiles", []):
            content.append({"image_uri": image_uri})

    return content


def _prepare_prompt_from_template(prompt_template, substitutions, required_placeholders):
    """
    Prepare prompt from template by replacing placeholders with values.

    Args:
        prompt_template: The prompt template with placeholders
        substitutions: Dictionary of placeholder values
        required_placeholders: List of placeholder names that must be present in the template

    Returns:
        String with placeholders replaced by values

    Raises:
        ValueError: If a required placeholder is missing from the template
    """

    return format_prompt(prompt_template, substitutions, required_placeholders)


def _s3vectors_find_similar_items(image_data):
    """Find similar items for input"""
    # find similar items based on image similarity only
    similar_items = {}
    for page_image in image_data:
        result = _s3vectors_find_similar_items_from_image(page_image)
        _merge_examples(similar_items, result)

    # create result set
    result = []
    for key, example in similar_items.items():
        metadata = example.get("metadata", {})
        distance = example.get("distance")
        attributes_prompt = metadata.get("attributesPrompt")

        # Only process this example if it has a non-empty attributesPrompt
        if not attributes_prompt or not attributes_prompt.strip():
            logger.info(f"Skipping example with empty attributesPrompt: {key}")
            continue

        attributes = _extract_metadata(metadata, distance)
        result.append(attributes)

    # sort results by distance score (lowest to highest - lower is more similar)
    sorted_result = sorted(
        result, key=lambda example: example["distance"], reverse=False
    )

    # filter result by distance score
    filtered_result = []
    for example in sorted_result:
        if example["distance"] > THRESHOLD:
            logger.info(
                f"Skipping example with distance {example['distance']} above threshold {THRESHOLD}: {key}"
            )
        else:
            filtered_result.append(example)

    return filtered_result


def _s3vectors_find_similar_items_from_image(page_image):
    """Search for similar items using image query"""
    embedding = bedrock_client.generate_embedding(
        image_source=page_image,
        model_id=MODEL_ID,
        dimensions=S3VECTOR_DIMENSIONS,
    )
    response = s3vectors.query_vectors(
        vectorBucketName=S3VECTOR_BUCKET,
        indexName=S3VECTOR_INDEX,
        queryVector={"float32": embedding},
        topK=TOP_K,
        returnDistance=True,
        returnMetadata=True,
    )
    logger.debug(f"S3 vectors lookup result: {response['vectors']}")
    return response["vectors"]


def _merge_examples(examples, new_examples):
    """
    Merge in-place new examples into the result list, avoiding duplicates.

    Args:
        examples: Dict of existing examples
        new_examples: List of new examples to be merged
    """
    for new_example in new_examples:
        key = new_example["key"]
        new_distance = new_example.get("distance", 1.0)

        # update example
        if examples.get(key):
            existing_distance = examples[key].get("distance", 1.0)
            examples[key]["distance"] = min(new_distance, existing_distance)
            examples[key]["metadata"] = new_example.get("metadata")
        # insert example
        else:
            examples[key] = {
                "distance": new_distance,
                "metadata": new_example.get("metadata"),
            }


def _extract_metadata(metadata, distance):
    """Create result object from S3 vectors metadata"""
    # Result object attributes
    attributes = {
        "attributesPrompt": metadata.get("attributesPrompt"),
        "classPrompt": metadata.get("classPrompt"),
        "imageFiles": _get_image_files_from_s3_path(metadata.get("imagePath")),
        "distance": distance,
    }

    return attributes


def _get_image_files_from_s3_path(image_path):
    """
    Get list of image files from an S3 path.

    Args:
        image_path: Path to image file, directory, or S3 prefix

    Returns:
        List of image file paths/URIs sorted by filename
    """
    # Handle S3 URIs
    if not image_path.startswith("s3://"):
        raise ValueError(f"Invalid file path {image_path} - expecting S3 URI")

    # Check if it's a direct file or a prefix
    if image_path.endswith(
        (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp")
    ):
        # Direct S3 file
        return [image_path]
    else:
        # S3 prefix - list all images
        return s3.list_images_from_path(image_path)
