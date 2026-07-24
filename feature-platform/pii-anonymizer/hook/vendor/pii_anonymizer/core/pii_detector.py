# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""
PII Detector Module

This module handles the detection of PII in images using a vision-capable LLM.
It provides functions to:
1. Invoke the LLM with images
2. Parse the LLM responses
3. Extract PII information with bounding boxes
4. Visualize detected PII
"""

import io
import time
import logging
import traceback

from PIL import Image, ImageDraw

from core.prompts import VISION_SYSTEM_PROMPT, VISION_TASK_PROMPT
from helpers.model_config_helper import (
    get_precise_config_from_yaml,
    get_additional_model_fields,
)
from helpers.model_router import converse_or_responses, MantleNonRetryableError

import os


def _aws_region():
    """Region the pipeline runs in (for routing OpenAI mantle calls)."""
    return os.environ.get(
        "AWS_DEFAULT_REGION", os.environ.get("AWS_REGION", "us-east-1")
    )


# Configure logging
logger = logging.getLogger(__name__)


def invoke_model(
    image,
    model_id,
    model_provider,
    bedrock_runtime,
    system_prompt=None,
    task_prompt=None,
    token_tracker=None,
    additional_model_fields=None,
    config=None,
):
    """
    Invoke a vision-capable LLM with an image.

    Supports {DOCUMENT_IMAGE} placeholder in task_prompt. When present, the prompt
    is split at the placeholder and the image is inserted between the text parts,
    following the AWS IDP pattern for multimodal content.

    Args:
        image: PIL Image to process
        model_id: ID of the model to use
        model_provider: Provider of the model ("amazon" or "anthropic")
        bedrock_runtime: Bedrock runtime client
        system_prompt: System prompt for the LLM (optional, defaults to VISION_SYSTEM_PROMPT)
        task_prompt: Task prompt for the LLM (optional, defaults to VISION_TASK_PROMPT)
        token_tracker: Optional TokenTracker instance for usage tracking

    Returns:
        Model response dict from Bedrock converse API
    """
    # Convert image to JPEG bytes
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG")
    image_bytes = buffered.getvalue()
    image_block = {"image": {"format": "jpeg", "source": {"bytes": image_bytes}}}

    if system_prompt is None:
        system_prompt = VISION_SYSTEM_PROMPT
    if task_prompt is None:
        task_prompt = VISION_TASK_PROMPT

    # Build content array — split at PAGE_IMAGE tags if present
    if "<PAGE_IMAGE>" in task_prompt:
        before, rest = task_prompt.split("<PAGE_IMAGE>", 1)
        after = rest.split("</PAGE_IMAGE>", 1)[1] if "</PAGE_IMAGE>" in rest else ""
        content = []
        if before.strip():
            content.append({"text": before})
        content.append(image_block)
        if after.strip():
            content.append({"text": after})
    else:
        content = [image_block, {"text": task_prompt}]

    # Invoke model with retry logic
    max_retries = 5
    for attempt in range(max_retries):
        try:
            messages = [{"role": "user", "content": content}]

            from validation.model_schemas import validate_image_input

            system = [{"text": system_prompt}]
            validate_image_input(model_id, messages, system)
            # Fall back to the loaded config (not {}) so model capabilities and
            # detection tuning are respected even when the caller passes none.
            if config:
                cfg = config
            else:
                from helpers.config_loader import load_config

                cfg = load_config()
            # Build a plain base request. converse_or_responses applies the
            # per-model shaping (thinking/effort format, sampling strip, maxTokens
            # clamp) from the capability registry + config — no per-model logic here.
            kwargs = {
                "modelId": model_id,
                "messages": messages,
                "system": system,
                "inferenceConfig": get_precise_config_from_yaml(cfg),
            }
            extra = get_additional_model_fields(cfg, model_id)
            if extra:
                kwargs["additionalModelRequestFields"] = extra
            response = converse_or_responses(
                bedrock_runtime,
                kwargs,
                region=_aws_region(),
                token_tracker=token_tracker,
                config=cfg,
                step="detection",
            )
            return response

        except MantleNonRetryableError:
            # Deterministic failure (e.g. unsupported reasoning_effort). Do not
            # retry, do not swallow — propagate so the job fails loud instead of
            # silently producing 0 detections (which would leak PII).
            raise
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Retry {attempt + 1}/{max_retries}: {str(e)}")
                time.sleep(2**attempt)
            else:
                # Retries exhausted — raise instead of returning an error dict,
                # so the failure is surfaced rather than swallowed into [].
                raise RuntimeError(
                    f"Model invocation failed after {max_retries} attempts: {e}"
                ) from e


def invoke_model_for_text(
    prompt,
    system_prompt,
    model_id,
    model_provider,
    bedrock_runtime,
    inference_params=None,
    token_tracker=None,
    additional_model_fields=None,
    reasoning_effort=None,
    thinking_config=None,
    config=None,
    step="detection",
):
    """
    Invoke an LLM for text-only processing.

    Args:
        prompt: Text prompt for the LLM
        system_prompt: System prompt for the LLM
        model_id: ID of the model to use
        model_provider: Provider of the model ("amazon" or "anthropic")
        bedrock_runtime: Bedrock runtime client
        inference_params: Optional custom inference parameters
        additional_model_fields: Optional additionalModelRequestFields (e.g. topK)

    Returns:
        Model response
    """
    # Default inference parameters for detection
    default_inf_params = get_precise_config_from_yaml({})

    # Use custom parameters if provided
    inf_params = inference_params if inference_params else default_inf_params

    # Validate input before sending
    from validation.model_schemas import validate_text_input

    validate_text_input(model_id, prompt, system_prompt)

    # Resolve config once so converse_or_responses can apply per-model shaping
    # (thinking/effort format, sampling strip, maxTokens clamp) from the registry.
    if config is None:
        from helpers.config_loader import load_config

        config = load_config()

    # Invoke model with retry logic
    max_retries = 5
    for attempt in range(max_retries):
        try:
            system = [{"text": system_prompt}]
            messages = [{"role": "user", "content": [{"text": prompt}]}]
            kwargs = {
                "modelId": model_id,
                "messages": messages,
                "system": system,
                "inferenceConfig": inf_params,
            }
            if additional_model_fields:
                kwargs["additionalModelRequestFields"] = additional_model_fields
            response = converse_or_responses(
                bedrock_runtime,
                kwargs,
                region=_aws_region(),
                token_tracker=token_tracker,
                config=config,
                step=step,
            )
            return response

        except MantleNonRetryableError:
            # Deterministic failure — do not retry, do not swallow (see above).
            raise
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Retry {attempt + 1}/{max_retries}: {str(e)}")
                time.sleep(2**attempt)  # Exponential backoff
            else:
                raise RuntimeError(
                    f"Model invocation failed after {max_retries} attempts: {e}"
                ) from e


def parse_llm_response(response):
    """
    Parse the LLM response to extract PII detections.

    Args:
        response: Response from the LLM

    Returns:
        List of PII detections with bounding boxes
    """
    # Truncation = the model hit its output limit mid-response, so the PII list
    # is cut off. Fail loud (before the try below, which would swallow it into
    # []) — a partial detection silently leaks the undetected tail. The chunk is
    # counted as failed and the job fails. Use a larger-output model (Claude/GPT)
    # or a smaller input for very dense documents.
    from validation.model_schemas import is_truncated_response

    if is_truncated_response(response):
        raise RuntimeError(
            "Detection response truncated (model output-token limit hit) — PII "
            "would be incomplete. Use a model with a larger output limit "
            "(Claude/GPT) or reduce the input size."
        )
    try:
        from validation.model_schemas import (
            safe_get_response_content,
            extract_json_dict,
            ImageBasedOutput,
        )

        # Safely extract content
        content = safe_get_response_content(response)

        # Robustly extract JSON (handles control chars, code fences, preamble,
        # and truncation). Returns None only if truly unrecoverable.
        pii_data = extract_json_dict(content)
        if pii_data is None:
            logger.warning("No parseable JSON found in the response")
            return []

        # Validate and return detections
        validated_output = ImageBasedOutput.from_dict(pii_data)
        return validated_output.pii_detections

    except ValueError as e:
        logger.error(f"Validation error: {str(e)}")
        return []
    except Exception as e:
        logger.error(f"Error parsing LLM response: {str(e)}")
        traceback.print_exc()
        return []


def parse_text_response(response):
    """
    Parse a text-only response from the LLM.
    Handles both standard and extended thinking responses.

    Args:
        response: Response from the LLM

    Returns:
        Extracted text
    """
    try:
        content_blocks = response["output"]["message"]["content"]
        # With thinking enabled, find the text block (skip thinking blocks)
        for block in content_blocks:
            if block.get("type") == "text" or (
                "text" in block and "thinking" not in block
            ):
                return block["text"].strip()
        # Fallback to first block
        return content_blocks[0]["text"].strip()

    except Exception as e:
        logger.error(f"Error parsing text response: {str(e)}")
        traceback.print_exc()
        return ""


def detect_pii_in_image(
    image,
    metadata,
    model_id,
    model_provider,
    bedrock_runtime,
    token_tracker=None,
    ocr_text="",
    config=None,
):
    """
    Detect PII in an image using a vision-capable LLM with OCR text context.

    Sends both the document image and OCR-extracted text to the LLM. The LLM uses
    exact OCR words in its response, eliminating mismatches between LLM output and
    Textract bounding boxes. OCR text should be obtained from Textract before calling.

    Args:
        image: PIL Image to process
        metadata: Metadata dictionary with page_number and optional dimensions
        model_id: ID of the Bedrock model to use
        model_provider: Provider of the model ("amazon" or "anthropic")
        bedrock_runtime: Bedrock runtime client
        token_tracker: Optional TokenTracker instance for usage tracking
        ocr_text: OCR-extracted text (from Textract) to include in the prompt.
                  LLM is instructed to use exact OCR words for PII content.

    Returns:
        List of PII detection dicts with type, content, confidence, and page_num
    """
    try:
        from core.prompts import VISION_TASK_PROMPT

        task_prompt = VISION_TASK_PROMPT.replace("{ocr_text}", ocr_text or "")

        response = invoke_model(
            image,
            model_id,
            model_provider,
            bedrock_runtime,
            task_prompt=task_prompt,
            token_tracker=token_tracker,
            config=config,
        )

        pii_detections = parse_llm_response(response)

        for detection in pii_detections:
            detection["page_num"] = metadata["page_number"]

        return pii_detections

    except Exception as e:
        # Do NOT swallow into [] — a silently-dropped page means undetected PII
        # (a leak). Propagate so the page is counted as failed and the job fails.
        logger.error(f"Error detecting PII in image: {str(e)}")
        traceback.print_exc()
        raise


def detect_pii_in_embedded_image(
    image, metadata, model_id, model_provider, bedrock_runtime, token_tracker=None
):
    """
    Detect PII in an embedded image using a vision-capable LLM.
    Then enhance with accurate bounding boxes from AWS Textract.

    Args:
        image: PIL Image to process
        metadata: Metadata dictionary with image information
        model_id: ID of the model to use
        model_provider: Provider of the model
        bedrock_runtime: Bedrock runtime client

    Returns:
        List of PII detections with image metadata and accurate bounding boxes
    """
    try:
        # Invoke the model to detect PII (no OCR text for embedded images)
        from core.prompts import VISION_TASK_PROMPT

        task_prompt = VISION_TASK_PROMPT.replace("{ocr_text}", "")
        response = invoke_model(
            image,
            model_id,
            model_provider,
            bedrock_runtime,
            task_prompt=task_prompt,
            token_tracker=token_tracker,
        )

        # Parse the response
        pii_detections = parse_llm_response(response)

        # Enhance with accurate Textract bounding boxes
        from helpers.textract_helper import enhance_pii_detections_with_textract

        pii_detections = enhance_pii_detections_with_textract(
            image, pii_detections, bedrock_runtime
        )

        # Add metadata to each detection
        for detection in pii_detections:
            detection["page_num"] = metadata["page_number"]
            detection["img_index"] = metadata["image_index"]
            detection["xref"] = metadata["xref"]

        return pii_detections

    except Exception as e:
        logger.error(f"Error detecting PII in embedded image: {str(e)}")
        traceback.print_exc()
        raise


def visualize_pii_detections(image, pii_detections):
    """
    Visualize PII detections on an image.

    Args:
        image: PIL Image to visualize on
        pii_detections: List of PII detections

    Returns:
        PIL Image with PII information overlaid
    """
    # Create a copy of the image
    img_with_info = image.copy()
    draw = ImageDraw.Draw(img_with_info)

    # Define colors for different PII types
    colors = {
        "name": (255, 0, 0),  # Red
        "ssn": (0, 255, 0),  # Green
        "dob": (0, 0, 255),  # Blue
        "address": (255, 255, 0),  # Yellow
        "phone": (255, 0, 255),  # Magenta
        "email": (0, 255, 255),  # Cyan
        "patient_id": (128, 0, 0),  # Dark Red
        "institution_name": (128, 128, 0),  # Olive
        "default": (255, 165, 0),  # Orange
    }

    # Add a semi-transparent overlay at the top of the image
    overlay_height = min(30 * len(pii_detections) + 40, image.height // 2)
    overlay = Image.new("RGBA", (image.width, overlay_height), (0, 0, 0, 180))
    img_with_info.paste(overlay, (0, 0), overlay)

    # Draw PII information as text
    y_pos = 20
    draw.text((10, y_pos - 15), "Detected PII:", fill=(255, 255, 255))
    y_pos += 15

    for i, detection in enumerate(pii_detections):
        pii_type = detection["type"].lower()
        color = colors.get(pii_type, colors["default"])

        # Draw label
        label = f"{detection['type']}: {detection['content']}"
        draw.text((20, y_pos), label, fill=color)
        y_pos += 25

    return img_with_info
