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

    Input event:
    {
        "class_label": "<class_label e.g. invoice>",
        "document_text": "<document_text e.g. plain text or markdown from section 1 (pages 1-3)...>",
        "image_content": ["<base64_image_content_1>", "<base64_image_content_2>", ...]
    }

    Return format:
    [
        {
            "attributes_prompt": "expected attributes are: ...",
            "class_prompt": "This is an example of the class 'invoice'",
            "distance": 0.122344521145,
            "image_content": ["<base64_image_content_1>", "<base64_image_content_2>", ...]
        }
    ]
    """

    try:
        logger.info("=== DYNAMIC FEW-SHOT LAMBDA INVOKED ===")
        logger.debug(f"Complete input event: {json.dumps(event, indent=2)}")

        # Validate input
        class_label = event.get("class_label")
        document_text = event.get("document_text")
        image_content = event.get("image_content", [])

        logger.info(f"=== INPUT VALUES ===")
        logger.info(f"Class label: {class_label if class_label else 'Not specified'}")
        logger.info(
            f"Document text: {len(document_text) if document_text else '0'} bytes"
        )
        logger.info(f"Image content: {len(image_content)} images")

        # Decode input data
        image_data = _decode_images(image_content)

        logger.info(f"=== FIND SIMILAR ITEMS ===")

        # Find similar items using S3 vectors lookup from image similarity
        result = _s3vectors_find_similar_items(image_data)

        # Log complete output structure
        logger.info(f"=== OUTPUT ANALYSIS ===")
        logger.debug(f"Complete result: {json.dumps(result, indent=2)}")
        logger.info(f"Output items: {len(result)}")

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


def _decode_images(image_content):
    """Base64 decode image content to bytes"""
    result = []
    for image_base64 in image_content:
        image_data = base64.b64decode(image_base64)
        result.append(image_data)
    return result


def _encode_images(image_content):
    """Base64 encode image content to JSON-serializable string"""
    result = []
    for image_bytes in image_content:
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        result.append(image_base64)
    return result


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
        "attributes_prompt": metadata.get("attributesPrompt"),
        "class_prompt": metadata.get("classPrompt"),
        "distance": distance,
    }

    image_path = metadata.get("imagePath")
    if image_path:
        image_data = _get_image_data_from_s3_path(image_path)
        encoded_images = _encode_images(image_data)
        attributes["image_content"] = encoded_images

    return attributes


def _get_image_data_from_s3_path(image_path):
    """
    Load images from image path

    Args:
        image_path: Path to image file, directory, or S3 prefix

    Returns:
        List of images (bytes)
    """
    # Get list of image files from the path (supports directories/prefixes)
    image_files = _get_image_files_from_s3_path(image_path)
    image_content = []

    # Process each image file
    for image_file_path in image_files:
        try:
            # Load image content
            if image_file_path.startswith("s3://"):
                # Direct S3 URI
                image_bytes = s3.get_binary_content(image_file_path)
            else:
                raise ValueError(f"Invalid file path {image_path} - expecting S3 path")

            image_content.append(image_bytes)
        except Exception as e:
            logger.warning(f"Failed to load image {image_file_path}: {e}")
            continue

    return image_content


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
