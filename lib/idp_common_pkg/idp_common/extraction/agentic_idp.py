"""
Agentic IDP implementation using Strands agents with tool-based structured output.

This module implements structured data extraction using Strands agents and tools,
recreating the structured_output_async functionality from ai-tools-registry using
tool-based approach with dynamic tool creation based on Pydantic models.
"""

import asyncio
import io
import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import (
    Any,
    TypedDict,
    TypeVar,
)

import jsonpatch
from aws_lambda_powertools import Logger
from botocore.config import Config
from PIL import Image
from pydantic import BaseModel, Field
from strands import Agent, tool
from strands.agent.conversation_manager import SummarizingConversationManager
from strands.models import BedrockModel
from strands.types.agent import AgentInput
from strands.types.content import CachePoint, ContentBlock, Message
from strands.types.media import (
    DocumentContent,
    ImageContent,
    ImageSource,
)

from idp_common.bedrock.client import CACHEPOINT_SUPPORTED_MODELS
from idp_common.config.models import IDPConfig
from idp_common.utils.bedrock_utils import (
    async_exponential_backoff_retry,
)
from idp_common.utils.strands_agent_tools.todo_list import (
    create_todo_list,
    update_todo,
    view_todo_list,
)

# Supported image formats for Bedrock API
SUPPORTED_IMAGE_FORMATS = {"jpeg", "png", "gif", "webp"}


def detect_image_format(image_bytes: bytes) -> str:
    """
    Detect the image format from raw bytes.

    Args:
        image_bytes: Raw image bytes

    Returns:
        Image format string suitable for Bedrock API ('jpeg', 'png', 'gif', 'webp')

    Raises:
        ValueError: If the image format is unsupported or cannot be detected
    """
    img = Image.open(io.BytesIO(image_bytes))

    if not img.format or img.format.lower() not in SUPPORTED_IMAGE_FORMATS:
        raise ValueError(
            f"Unsupported image format: {img.format}. "
            f"Supported formats: {', '.join(SUPPORTED_IMAGE_FORMATS)}"
        )
    return img.format.lower()


# Use AWS Lambda Powertools Logger for structured logging
# Automatically logs as JSON with Lambda context, request_id, timestamp, etc.
# In Lambda: Full JSON structured logs
# Outside Lambda: Human-readable format for local development
logger = Logger(service="agentic_idp", level=os.getenv("LOG_LEVEL", "INFO"))
# Configure strands bedrock logger based on environment variable
logging.getLogger("strands.models.bedrock").setLevel(
    os.getenv("STRANDS_LOG_LEVEL", os.getenv("LOG_LEVEL", "INFO"))
)
TargetModel = TypeVar("TargetModel", bound=BaseModel)


def supports_tool_caching(model_id: str) -> bool:
    """
    Check if a model supports tool caching (cachePoint in toolConfig).

    Note: Only Claude models support tool caching. Nova models support
    prompt caching but NOT tool caching.

    Args:
        model_id: The Bedrock model identifier

    Returns:
        True if the model supports tool caching, False otherwise
    """
    return "anthropic.claude" in model_id or "us.anthropic.claude" in model_id


def supports_prompt_caching(model_id: str) -> bool:
    """
    Check if a model supports prompt caching (cachePoint in system prompt).

    Args:
        model_id: The Bedrock model identifier

    Returns:
        True if the model supports prompt caching, False otherwise
    """
    return model_id in CACHEPOINT_SUPPORTED_MODELS


class BedrockUsage(TypedDict, total=False):
    """Token usage information from Bedrock response."""

    inputTokens: int
    outputTokens: int
    totalTokens: int
    cacheReadInputTokens: int
    cacheWriteInputTokens: int


class BedrockMessageContent(TypedDict):
    """Content item in a Bedrock message."""

    text: str | None


class BedrockMessage(TypedDict):
    """Message structure in Bedrock response."""

    role: str
    content: list[BedrockMessageContent]


class BedrockOutput(TypedDict):
    """Output structure in Bedrock response."""

    message: BedrockMessage


class BedrockResponse(TypedDict, total=False):
    """Raw response from Bedrock converse API."""

    output: BedrockOutput
    usage: BedrockUsage
    stopReason: str | None
    metrics: dict[str, Any] | None


class BedrockInvokeModelResponse(TypedDict):
    """
    Complete response structure from bedrock.invoke_model method.

    This represents the structure returned by:
    response_with_metering = bedrock.invoke_model(...)

    The response contains both the raw Bedrock API response and
    metering information with usage statistics.
    """

    response: BedrockResponse
    metering: dict[str, BedrockUsage]  # Key format: "{context}/bedrock/{model_id}"


class JsonPatchModel(BaseModel):
    """Model for JSON patch operations."""

    patches: list[dict[str, Any]] = Field(
        ...,
        description="JSON patch operations to apply. Each patch should follow RFC 6902 format with 'op', 'path', and optionally 'value' keys.",
    )
    reasoning: str = Field(
        ...,
        description="Explanation of what these patches are intended to fix or update",
    )


def apply_patches_to_data(
    existing_data: dict[str, Any],
    patches: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Apply JSON patches to existing data and validate the result.

    Args:
        existing_data: The current structured data to patch
        patches: List of JSON patch operations

    Returns:
        Patched and validated data
    """
    if not patches:
        return existing_data

    patch = jsonpatch.JsonPatch(patches)
    patched_dict = patch.apply(existing_data)

    return patched_dict


def create_view_image_tool(page_images: list[bytes]) -> Any:
    """
    Create a view_image tool that has access to page images.

    Args:
        page_images: List of page image bytes (with grid overlay already applied)
        sorted_page_ids: List of page IDs in sorted order

    Returns:
        A Strands tool function for viewing images
    """

    @tool
    def view_image(image_index: int, agent: Agent) -> dict:
        """
        View a specific page image. Use this tool when the doc has more images than what you already see.
        """

        # Validate image index exists
        if not page_images:
            raise ValueError("No images available to view.")
        if image_index >= len(page_images):
            raise ValueError(
                f"Invalid image_index {image_index}. "
                f"Valid range: 0-{len(page_images) - 1}"
            )

        # Get the base image (already has grid overlay)
        img_bytes = page_images[image_index]

        # Detect actual image format from bytes
        img_format = detect_image_format(img_bytes)

        logger.info(
            "Returning image to agent",
            extra={
                "image_index": image_index,
                "image_size_bytes": len(img_bytes),
                "image_format": img_format,
            },
        )

        return {
            "status": "success",
            "content": [
                {
                    "image": {
                        "format": img_format,
                        "source": {
                            "bytes": img_bytes,
                        },
                    }
                }
            ],
        }

    return view_image


def create_dynamic_extraction_tool_and_patch_tool(model_class: type[TargetModel]):
    """
    Create a dynamic tool function that extracts data according to a Pydantic model.

    This follows the pattern from ai-tools-registry where the tool's input schema
    is dynamically generated from the Pydantic model, ensuring the LLM knows exactly
    what structure to provide.

    Args:
        model_class: The Pydantic model class to use for extraction

    Returns:
        A tool-decorated function that validates against the model
    """

    @tool
    def extraction_tool(
        extraction: model_class,  # pyright: ignore[reportInvalidTypeForm]
        agent: Agent,  # pyright: ignore[reportInvalidTypeForm]
    ) -> str:  # pyright: ignore[reportInvalidTypeForm]
        """Use this tool to return the requested data extraction.
        When you call this tool it overwrites the previous extraction, if you want to expand the extraction use jsonpatch.
        This tool needs to be Successfully invoked before the patch tool can be used."""

        # Note: The @tool decorator passes data as a dict, not as a model instance
        # We need to validate it manually using the Pydantic model
        extraction_model = model_class.model_validate(extraction)  # pyright: ignore[reportAssignmentType]
        extraction_dict = extraction_model.model_dump(mode="json")
        logger.info(
            "extraction_tool called", extra={"models_extraction": extraction_dict}
        )
        agent.state.set(key="current_extraction", value=extraction_dict)
        logger.debug(
            "Successfully stored extraction in state",
            extra={"extraction": extraction_dict},
        )
        return "Extraction succeeded, the data format is correct"

    @tool
    def apply_json_patches(
        patches: list[dict[str, Any]],
        agent: Agent,
    ) -> dict[str, Any]:
        """
        Apply JSON patches to fix or update the extracted data.

        Args:
            patches: List of JSON patch operations (RFC 6902 format)
            reasoning: Explanation of what the patches fix
        """
        current_data: dict[str, Any] | None = agent.state.get("current_extraction")

        logger.info("Patch tool called", extra={"patch_request": patches})
        if not current_data:
            return {"error": "No current extraction to patch"}

        patched_data = apply_patches_to_data(current_data, patches)
        validated_patched_data = model_class(**patched_data)
        agent.state.set(
            key="current_extraction",
            value=validated_patched_data.model_dump(mode="json"),
        )

        return {
            "status": "success",
            "patches_applied": len(patches),
        }

    @tool
    def make_buffer_data_final_extraction(agent: Agent) -> str:
        valid_extraction = model_class(**agent.state.get("intermediate_extraction"))

        agent.state.set("current_extraction", valid_extraction.model_dump(mode="json"))

        return f"Successfully made the existing extraction the same as the buffer data {str(valid_extraction.model_dump(mode='json'))[:100]}..."

    return extraction_tool, apply_json_patches, make_buffer_data_final_extraction


@tool
def view_existing_extraction(agent: Agent) -> str:
    """Use this tool to view data is currently stored as extracted."""
    logger.info(
        "Current extraction state",
        extra={"current_extraction": agent.state.get("current_extraction")},
    )
    return agent.state.get("current_extraction")


@tool
def write_buffer_date(data: dict[str, Any], agent: Agent) -> str:
    """
    Use this tool when the extraction is too large to do in a single step, this is a buffer where you can save intermediate data that wouldn't pass validation yet.

    IMPORTANT: The data you save here must eventually match the extraction schema structure. Plan your buffer data structure to align with the required schema fields and types.
    Review the extraction schema before using this tool to ensure compatibility.
    """
    agent.state.set("intermediate_extraction", data)
    logger.info("Saving intermediate data", extra={"intermediate_extraction": data})
    return f"Saved data: {str(data)[:100]}.... "


@tool
def view_buffer_data(agent: Agent) -> str:
    """View the intermediate buffer data with this tool, this data is not a validated extraction, but intermediate state for you to work with.

    WARNING: This returns the ENTIRE buffer which can be very large. For large extractions, prefer using view_buffer_data_section or view_buffer_data_stats."""

    return agent.state.get("intermediate_extraction")


@tool
def view_buffer_data_section(path: str, agent: Agent) -> Any:
    """View a specific section of the intermediate buffer data by JSON Pointer path (RFC 6901). Token-efficient way to inspect parts of large data.

    Args:
        path: JSON Pointer path (same format as JSON Patch). Must start with "/" for nested paths, or use "" for root.

    Examples:
        - path="/table_rows" -> returns the entire table_rows array
        - path="/table_rows/0" -> returns first item in table_rows array
        - path="/table_rows/0/fund_name" -> returns fund_name field of first row
        - path="/document_name" -> returns just the document_name field
        - path="" -> returns entire buffer (same as view_buffer_data)

    Note: Uses same path format as JSON Patch operations for consistency.
    """
    data = agent.state.get("intermediate_extraction")

    if not data:
        return {"error": "No intermediate data in buffer"}

    # Handle empty path (root)
    if path == "":
        return data

    # Remove leading slash and parse path
    if not path.startswith("/"):
        return {
            "error": "Path must start with '/' (e.g., '/table_rows/0') or be empty string for root"
        }

    parts = path[1:].split("/") if path != "/" else []
    current = data

    try:
        for part in parts:
            if not part:  # Skip empty parts from double slashes
                continue

            if isinstance(current, list):
                # Try to convert to int for list indexing
                current = current[int(part)]
            elif isinstance(current, dict):
                current = current[part]
            else:
                return {
                    "error": f"Cannot navigate path '{path}' - reached non-dict/list at '{part}'"
                }

        return current
    except (KeyError, IndexError, ValueError) as e:
        return {"error": f"Path '{path}' not found: {str(e)}"}


@tool
def get_extraction_schema_reminder(agent: Agent) -> str:
    """Use this tool during long extractions to review the expected data schema and field requirements. Helps ensure you stay aligned with the required structure.

    RECOMMENDED: Call this tool every 100-200 rows in large extractions to verify you're maintaining the correct structure."""

    schema = agent.state.get("extraction_schema_json")
    if not schema:
        return "Schema not available"

    return f"Remember: Your extraction must match this schema:\n\n{schema}\n\nEnsure all field names, types, and required fields are correct."


@tool
def view_buffer_data_stats(agent: Agent) -> dict[str, Any]:
    """View overview statistics of intermediate buffer data. Token-efficient alternative to viewing full data. Use this for progress checks during large extractions.

    TIP: For large extractions (500+ items), consider calling get_extraction_schema_reminder every 100-200 items to stay aligned with requirements."""

    data = agent.state.get("intermediate_extraction")

    if not data:
        return {"status": "empty", "message": "No intermediate data in buffer"}

    # Build statistics
    stats = {}

    if isinstance(data, dict):
        stats["keys"] = list(data.keys())
        stats["field_count"] = len(data)
        # Sample nested structure for arrays
        for key, value in data.items():
            if isinstance(value, list):
                stats[f"{key}_length"] = len(value)
                if value:
                    stats[f"{key}_sample_type"] = type(value[0]).__name__
    # Add estimated token count (rough approximation)
    data_str = str(data)

    return {
        "status": "contains_data",
        "structure": stats,
        "estimated_size_chars": len(data_str),
        "tip": "Use patch_buffer_data to update specific fields, Use make_buffer_data_final_extraction to complete or get detailed guidance on missing requirements.",
    }


@tool
def patch_buffer_data(patches: list[dict[str, Any]], agent: Agent) -> str:
    """Update the intermediate_extraction data inside the buffer, this is not validated yet

    Apply JSON patches to fix or update the extracted data.

    Args:
        patches: List of JSON patch operations (RFC 6902 format)
        reasoning: Explanation of what the patches fix

    """

    logger.info("Buffer Patch tool called", extra={"patch_request": patches})
    patched_data = apply_patches_to_data(
        existing_data=agent.state.get("intermediate_extraction"), patches=patches
    )

    agent.state.set("intermediate_extraction", patched_data)

    logger.info(f"Current length of buffer data {len(patched_data)} ")

    return f"Successfully patched {str(patched_data)[100:]}...."


SYSTEM_PROMPT = """
You are a useful assistant that helps turn unstructured data into structured data using the provided tools.

EXTRACTION APPROACH:
1. Use the extraction_tool for fresh data extraction - this validates data against the schema immediately
2. When updating existing data or fixing validation errors, use JSON patch operations via the apply_json_patches tool
3. JSON patches allow precise, targeted updates without losing correct data
4. If the document is large and the extraction request can't be done in one go, create a valid extraction object and iterate with jsonpatches until you completed the entire extraction!
5. Use intermediate data buffer if you can't extract a valid data object in a single step

IMPORTANT:
YOU MUST perform a batched extraction if there are more than 50 fields to extract.
batched extraction is when you create a viable format with extraction tool and then you expand it with jsonpatches. 
You can pass up to 100 records in a single patch operation.
When using batched extraction plan it out and make a todo list with target size based on the document and other key tasks.

NEVER STOP early on large documents, always extract all the data.

JSON PATCH FORMAT (RFC 6902):
- {"op": "replace", "path": "/field_name", "value": "new_value"} - Update a field
- {"op": "add", "path": "/new_field", "value": "value"} - Add a field
- {"op": "remove", "path": "/field_name"} - Remove a field

CRITICAL EXTRACTION RULES:
1. Extract text EXACTLY as it appears in the source document - character for character
2. NEVER interpret, expand, or modify any text formatting, special characters, or punctuation
3. Preserve ALL original formatting including brackets, parentheses, hyphens, underscores, etc.
4. Maintain exact capitalization, spacing, and line structure as shown in the source
5. Do not treat any text as markdown, code, or special formatting - everything is literal text

VALIDATION AND CORRECTION:
1. Review each field in your extracted data
2. Double-check each value against the source
3. Pay special attention to dates, amounts, and similar-looking data
4. Verify that all characters and formatting are preserved exactly as they appear
5. When fixing errors, use JSON patches to target specific problems


FINAL REVIEW (CRITICAL):
After successfully using the extraction tool, you MUST:
1. Review the complete extracted data one more time
2. Compare each field against the source document character by character
3. Verify all punctuation, special characters, and formatting match exactly
4. Look for any missing fields, incorrect values, or formatting issues
5. If any discrepancies are found, use the apply_json_patches tool to fix them
6. Only finish when you are confident all data is accurate and complete
"""


@async_exponential_backoff_retry(
    max_retries=50,
    initial_delay=5,
    max_delay=1800,
    jitter=0.5,
)
async def invoke_agent_with_retry(input: AgentInput, agent: Agent):
    return await agent.invoke_async(input)


def _initialize_token_usage() -> dict[str, int]:
    """Initialize token usage tracking dictionary."""
    return {
        "inputTokens": 0,
        "outputTokens": 0,
        "totalTokens": 0,
        "cacheReadInputTokens": 0,
        "cacheWriteInputTokens": 0,
    }


def _accumulate_token_usage(response: Any, token_usage: dict[str, int]) -> None:
    """
    Accumulate token usage from response into usage dict.

    Args:
        response: Agent response object with metrics
        token_usage: Dictionary to accumulate usage into (modified in place)
    """
    if response and response.metrics and response.metrics.accumulated_usage:
        for key in token_usage.keys():
            token_usage[key] += response.metrics.accumulated_usage.get(key, 0)


def _build_system_prompt(
    base_prompt: str, custom_instruction: str | None, data_format: type[BaseModel]
) -> tuple[str, str]:
    """
    Build complete system prompt with custom instructions and schema.

    Args:
        base_prompt: The base system prompt (typically SYSTEM_PROMPT constant)
        custom_instruction: Optional custom instructions to append
        data_format: Pydantic model class to extract schema from

    Returns:
        Tuple of (complete system prompt with schema, schema_json for state storage)
    """
    # Generate and clean schema
    schema_json = json.dumps(data_format.model_json_schema(), indent=2)

    # Build final prompt
    final_prompt = base_prompt
    if custom_instruction:
        final_prompt = f"{final_prompt}\n\nCustom Instructions for this specific task: {custom_instruction}"

    complete_prompt = f"{final_prompt}\n\nExpected Schema:\n{schema_json}"

    return complete_prompt, schema_json


def _build_model_config(
    model_id: str,
    max_tokens: int | None,
    max_retries: int,
    connect_timeout: float,
    read_timeout: float,
) -> dict[str, Any]:
    """
    Build model configuration with token limits and caching settings.

    This function:
    1. Creates boto3 Config with retry and timeout settings
    2. Determines model-specific max token limits
    3. Validates and caps max_tokens if needed
    4. Auto-detects and enables caching support (prompt and tool caching)

    Args:
        model_id: Bedrock model identifier (supports us.*, eu.*, and global.anthropic.*)
        max_tokens: Optional max tokens override (will be capped at model max)
        max_retries: Maximum retry attempts for API calls
        connect_timeout: Connection timeout in seconds
        read_timeout: Read timeout in seconds

    Returns:
        Dictionary of model configuration parameters for create_strands_bedrock_model.
        Automatically uses BedrockModel for regional models (us.*, eu.*) and
        AnthropicModel with AnthropicBedrock for cross-region models (global.anthropic.*).
    """
    # Configure retry behavior and timeouts using boto3 Config
    boto_config = Config(
        retries={
            "max_attempts": max_retries,
            "mode": "adaptive",  # Uses exponential backoff with adaptive retry mode
        },
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
    )

    # Determine model-specific maximum token limits
    model_max = 4_096  # Default fallback
    model_id_lower = model_id.lower()

    # Check Claude 4 patterns first (more specific)
    if re.search(r"claude-(opus|sonnet|haiku)-4", model_id_lower):
        model_max = 64_000
    # Check Nova models
    elif any(
        nova in model_id_lower
        for nova in ["nova-premier", "nova-pro", "nova-lite", "nova-micro"]
    ):
        model_max = 10_000
    # Check Claude 3 models
    elif "claude-3" in model_id_lower:
        model_max = 8_192

    # Use config value if provided, but cap at model's maximum
    if max_tokens is not None:
        if max_tokens > model_max:
            logger.warning(
                "Config max_tokens exceeds model limit, capping at model maximum",
                extra={
                    "config_max_tokens": max_tokens,
                    "model_max_tokens": model_max,
                    "model_id": model_id,
                },
            )
            max_output_tokens = model_max
        else:
            max_output_tokens = max_tokens
    else:
        # No config value - use model maximum for agentic extraction
        max_output_tokens = model_max

    # Build base model config
    model_config = dict(
        model_id=model_id, boto_client_config=boto_config, max_tokens=max_output_tokens
    )

    logger.info(
        "Setting max_tokens for model",
        extra={
            "max_tokens": max_output_tokens,
            "model_id": model_id,
            "model_max_tokens": model_max,
        },
    )

    # Auto-detect caching support based on model capabilities
    if supports_prompt_caching(model_id):
        model_config["cache_prompt"] = "default"
        logger.info(
            "Prompt caching enabled for model",
            extra={"model_id": model_id, "auto_detected": True},
        )

        # Only enable tool caching if the model supports it (Claude only, not Nova)
        if supports_tool_caching(model_id):
            model_config["cache_tools"] = "default"
            logger.info(
                "Tool caching enabled for model",
                extra={"model_id": model_id, "auto_detected": True},
            )
        else:
            logger.info(
                "Tool caching not supported for model",
                extra={"model_id": model_id, "reason": "prompt_caching_only"},
            )
    else:
        logger.debug("Caching not supported for model", extra={"model_id": model_id})

    return model_config


def _get_inference_params(temperature: float, top_p: float | None) -> dict[str, float]:
    """
    Get inference parameters ensuring temperature and top_p are mutually exclusive.

    Some Bedrock models don't allow both temperature and top_p to be specified.
    This follows the same logic as bedrock/client.py lines 348-364.

    Args:
        temperature: Temperature value from config
        top_p: Top_p value from config (may be None)

    Returns:
        Dict with only one of temperature or top_p
    """
    params = {}

    # Only use top_p if it's positive (greater than 0)
    # This allows temperature=0.0 for deterministic output (recommended by Anthropic)
    if top_p is not None and top_p > 0:
        params["top_p"] = top_p
        logger.debug(
            "Using top_p for inference (temperature ignored)", extra={"top_p": top_p}
        )
    else:
        params["temperature"] = temperature
        logger.debug(
            "Using temperature for inference (top_p is 0 or None)",
            extra={"temperature": temperature},
        )

    return params


def _prepare_prompt_content(
    prompt: str | Message | Image.Image,
    page_images: list[bytes] | None,
    existing_data: BaseModel | None,
) -> list[ContentBlock]:
    """
    Prepare prompt content from various input types.

    Converts different prompt types (text, PIL Image, Message dict) into
    a list of ContentBlocks, adds page images, and appends existing data context.

    Args:
        prompt: Input content (text string, PIL Image, or Message dict)
        page_images: Optional list of page image bytes to include
        existing_data: Optional existing extraction data to update

    Returns:
        List of ContentBlock objects ready for agent invocation
    """
    prompt_content: list[ContentBlock] = []

    # Process prompt based on type
    if isinstance(prompt, Image.Image):
        # Convert PIL Image to binary string
        img_buffer = io.BytesIO()
        prompt.save(img_buffer, format="PNG")
        img_bytes = img_buffer.getvalue()

        logger.debug(
            "Processing PIL Image",
            extra={"size": prompt.size, "mode": prompt.mode},
        )

        prompt_content = [
            ContentBlock(text="Extract structured data from this image:"),
            ContentBlock(
                image=ImageContent(format="png", source=ImageSource(bytes=img_bytes))
            ),
        ]
    elif isinstance(prompt, dict) and "content" in prompt:
        prompt_content = prompt["content"]  # type: ignore
    else:
        prompt_content = [ContentBlock(text=str(prompt))]

    # Add page images if provided - no limit with latest Bedrock API
    if page_images:
        logger.info(
            "Attaching images to agentic extraction prompt",
            extra={"image_count": len(page_images)},
        )

        for img_bytes in page_images:
            # Detect actual image format from bytes
            img_format = detect_image_format(img_bytes)
            prompt_content.append(
                ContentBlock(
                    image=ImageContent(
                        format=img_format,  # pyright: ignore[reportArgumentType]
                        source=ImageSource(bytes=img_bytes),
                    )
                )
            )

    # Add existing data context if provided
    if existing_data:
        prompt_content.append(
            ContentBlock(
                text=f"Please update the existing data using the extraction tool or patches. Existing data: {existing_data.model_dump(mode='json')}"
            )
        )

    prompt_content += [
        ContentBlock(text="end of your main task description"),
        ContentBlock(cachePoint=CachePoint(type="default")),
    ]
    return prompt_content


async def _invoke_agent_for_extraction(
    agent: Agent,
    prompt_content: list[ContentBlock],
    data_format: type[TargetModel],
    max_extraction_retries: int = 3,
) -> tuple[Any, TargetModel | None]:
    """
    Invoke agent and retry if extraction fails.

    Unlike network retries (handled by invoke_agent_with_retry), this retries when
    the agent completes successfully but fails to produce a valid extraction.

    Args:
        agent: The Strands agent to invoke
        prompt_content: List of ContentBlocks to send to the agent
        data_format: Pydantic model class for validation
        max_extraction_retries: Maximum retry attempts for failed extractions (default: 3)

    Returns:
        Tuple of (response, validated_result or None)
    """
    response = None

    for attempt in range(max_extraction_retries):
        # invoke_agent_with_retry already handles network errors and throttling
        response = await invoke_agent_with_retry(agent=agent, input=prompt_content)
        logger.debug("Agent response received")

        # Try to get extraction from state
        current_extraction = agent.state.get("current_extraction")

        if current_extraction:
            try:
                result = data_format(**current_extraction)
                logger.debug(
                    "Successfully validated extraction",
                    extra={"data_format": data_format.__name__, "attempt": attempt + 1},
                )
                return response, result
            except Exception as e:
                logger.warning(
                    "Extraction validation failed, retrying",
                    extra={
                        "attempt": attempt + 1,
                        "max_retries": max_extraction_retries,
                        "error": str(e),
                        "data_format": data_format.__name__,
                    },
                )
                if attempt < max_extraction_retries - 1:
                    # Ask agent to fix the extraction
                    prompt_content = [
                        ContentBlock(
                            text=f"The extraction failed validation with error: {str(e)}. Please fix the extraction using the tools."
                        )
                    ]
                    continue
                else:
                    # Last attempt failed
                    logger.error(
                        "Failed to validate extraction after all retries",
                        extra={
                            "data_format": data_format.__name__,
                            "error": str(e),
                            "extraction_data": current_extraction,
                        },
                    )
                    return response, None
        else:
            logger.warning(
                "No extraction found in agent state",
                extra={"attempt": attempt + 1, "max_retries": max_extraction_retries},
            )
            if attempt < max_extraction_retries - 1:
                # Ask agent to provide extraction
                prompt_content = [
                    ContentBlock(
                        text="No extraction was found. Please use the extraction_tool to provide the extracted data."
                    )
                ]
                continue

    # Should never reach here, but handle it gracefully
    if response is None:
        raise ValueError("No response from agent after retries")

    return response, None


async def structured_output_async(
    model_id: str,
    data_format: type[TargetModel],
    prompt: str | Message | Image.Image,
    existing_data: BaseModel | None = None,
    system_prompt: str | None = None,
    custom_instruction: str | None = None,
    config: IDPConfig = IDPConfig(),
    page_images: list[bytes] | None = None,
    context: str = "Extraction",
    max_retries: int = 7,
    connect_timeout: float = 10.0,
    read_timeout: float = 300.0,
    max_tokens: int | None = None,
) -> tuple[TargetModel, BedrockInvokeModelResponse]:
    """
    Extract structured data using Strands agents with tool-based validation.

    This recreates the structured_output_async functionality from ai-tools-registry
    using dynamically created tools that validate against the Pydantic model.

    USAGE GUIDELINES:
    - **STRONGLY DISCOURAGED**: Do not modify the system_prompt parameter unless absolutely necessary.
      The default SYSTEM_PROMPT is carefully crafted for optimal extraction accuracy and consistency.
    - **RECOMMENDED**: Use custom_instruction parameter to add task-specific guidance without
      disrupting the core extraction logic and validation rules.
    - Custom instructions are appended to the system prompt, preserving the original behavior
      while allowing for domain-specific customizations.

    DATA FORMAT GUIDELINES:
    - **IMPORTANT**: Neither custom_instruction nor system_prompt should contain data format
      specifications, field definitions, or schema requirements. All data structure requirements
      should be expressed through the Pydantic data model.
    - Use Pydantic field descriptions (Field(..., description="...")) and model docstrings
      to clarify field meanings, formats, and extraction requirements.
    - The extraction system automatically incorporates the complete model schema and field
      descriptions into the agent's understanding.

    Args:
        model_id: Model identifier (e.g., "us.anthropic.claude-sonnet-4-20250514-v1:0")
        data_format: Pydantic model class defining the expected structure
        prompt: Input content (text, image, or content blocks)
        enable_image_tools: Whether to enable image enhancement tools (default: True)
        existing_data: Optional existing data to update via patches
        system_prompt: **DISCOURAGED** - Custom system prompt. Only use if the default
                      SYSTEM_PROMPT is completely unsuitable for your use case.
        custom_instruction: **RECOMMENDED** - Additional task-specific instructions
                           appended to the system prompt. Use this for domain-specific
                           guidance, field clarifications, or extraction rules.
        max_retries: Maximum number of retry attempts for Bedrock API calls (default: 5).
                    Increase this value if your AWS account has low throttling limits.
        connect_timeout: Connection timeout in seconds (default: 60.0).
                        Increase if experiencing connection timeout errors.
        read_timeout: Read timeout in seconds (default: 300.0 = 5 minutes).
                     Increase for large documents or slow model responses.

    Returns:
        Tuple of (extracted data, bedrock response with token usage)

    Examples:
        # Define data structure with field descriptions (RECOMMENDED):
        # - Use Field(..., description="...") for field-specific requirements
        # - Use model docstrings for overall structure documentation
        # - All data format details belong in the Pydantic model, not instructions

        # Recommended usage with custom instructions for extraction guidance
        result, response = await structured_output_async(
            model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
            data_format=InvoiceModel,
            prompt=image_content,
            custom_instruction="Focus on line items in the main table. Ignore header/footer text."
        )

        # WRONG - Don't define data format in custom instructions:
        # custom_instruction="Extract: invoice_number, total_amount, line_items array..."

        # Discouraged - only use if default system prompt is completely unsuitable
        result, response = await structured_output_async(
            model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
            data_format=CustomModel,
            prompt=content,
            system_prompt="Your completely custom system prompt here..."
        )
    """
    if not system_prompt:
        system_prompt = SYSTEM_PROMPT
    logger.debug(
        "Starting agentic extraction",
        extra={"data_format": data_format.__name__, "model_id": model_id},
    )

    # Create the dynamic extraction tool for this specific model
    dynamic_extraction_tools = create_dynamic_extraction_tool_and_patch_tool(
        data_format
    )
    image_tools = []
    if page_images:
        image_tools.append(create_view_image_tool(page_images))

    # Prepare tools list
    tools = [
        *dynamic_extraction_tools,
        *image_tools,
        view_existing_extraction,
        patch_buffer_data,
        view_buffer_data,
        view_buffer_data_section,
        view_buffer_data_stats,
        write_buffer_date,
        get_extraction_schema_reminder,
        create_todo_list,
        update_todo,
        view_todo_list,
    ]

    # Build system prompt with schema
    final_system_prompt, schema_json = _build_system_prompt(
        base_prompt=system_prompt or SYSTEM_PROMPT,
        custom_instruction=custom_instruction,
        data_format=data_format,
    )

    tool_names = [getattr(tool, "__name__", str(tool)) for tool in tools]
    logger.debug(
        "Created agent with tools",
        extra={
            "tool_count": len(tools),
            "data_format": data_format.__name__,
            "tool_names": tool_names,
        },
    )

    # Build model configuration with token limits and caching
    model_config = _build_model_config(
        model_id=model_id,
        max_tokens=max_tokens,
        max_retries=max_retries,
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
    )

    # Prepare prompt content
    prompt_content = _prepare_prompt_content(
        prompt=prompt, page_images=page_images, existing_data=existing_data
    )

    # Track token usage
    token_usage = _initialize_token_usage()

    # Get inference params ensuring temperature and top_p are mutually exclusive
    inference_params = _get_inference_params(
        temperature=config.extraction.temperature, top_p=config.extraction.top_p
    )

    agent = Agent(
        model=BedrockModel(
            **model_config,
            **inference_params,
        ),  # pyright: ignore[reportArgumentType]
        tools=tools,
        system_prompt=final_system_prompt,
        state={
            "current_extraction": None,
            "images": {},
            "existing_data": existing_data.model_dump(mode="json")
            if existing_data
            else None,
            "extraction_schema_json": schema_json,  # Store for schema reminder tool
        },
        conversation_manager=SummarizingConversationManager(
            summary_ratio=0.8, preserve_recent_messages=2
        ),
    )
    if existing_data:
        agent.state.set("current_extraction", existing_data.model_dump(mode="json"))

    response, result = await _invoke_agent_for_extraction(
        agent=agent,
        prompt_content=prompt_content,
        data_format=data_format,
        max_extraction_retries=3,
    )

    # Accumulate token usage
    _accumulate_token_usage(response, token_usage)

    # Add explicit review step (Option 2)
    if (
        config.extraction.agentic.enabled
        and config.extraction.agentic.review_agent
        and config.extraction.agentic.review_agent_model
    ):
        # result is guaranteed to be non-None here (we raised an error earlier if it was None)
        assert result is not None

        logger.debug(
            "Initiating final review of extracted data",
            extra={"review_enabled": True},
        )
        review_prompt = Message(
            role="user",
            content=[
                *prompt_content,
                ContentBlock(
                    text=f"""
                You have successfully extracted the following data:
                {json.dumps(result.model_dump(mode="json"), indent=2)}

                Please take one final careful look at this extraction:
                1. Check each field against the source document
                2. Verify all values are accurate (pay special attention to numbers, dates, names)
                3. Ensure no required fields are missing
                4. Look for any formatting issues or typos
                5. Make sure no data locations didn't change compared to the document unless to adhere to the data format required.

                If everything is correct, respond with "Data verified and accurate."
                If corrections are needed, use the apply_json_patches tool to fix any issues you find.
                """
                ),
                ContentBlock(cachePoint=CachePoint(type="default")),
            ],
        )
        # Build config for review agent
        review_model_config = _build_model_config(
            model_id=config.extraction.agentic.review_agent_model,
            max_tokens=max_tokens,
            max_retries=max_retries,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
        )

        # Get inference params for review agent ensuring temperature and top_p are mutually exclusive
        review_inference_params = _get_inference_params(
            temperature=config.extraction.temperature, top_p=config.extraction.top_p
        )

        agent = Agent(
            model=BedrockModel(
                **review_model_config,
                **review_inference_params,
            ),  # pyright: ignore[reportArgumentType]
            tools=tools,
            system_prompt=f"{final_system_prompt}",
            state={
                "current_extraction": result.model_dump(mode="json"),
                "images": {},
                "existing_data": existing_data.model_dump(mode="json")
                if existing_data
                else None,
                "extraction_schema_json": schema_json,  # Store for schema reminder tool
            },
            conversation_manager=SummarizingConversationManager(
                summary_ratio=0.8, preserve_recent_messages=2
            ),
        )

        review_response = await invoke_agent_with_retry(
            agent=agent, input=[review_prompt]
        )
        logger.debug("Review response received", extra={"review_completed": True})

        # Accumulate token usage from review
        _accumulate_token_usage(review_response, token_usage)

        # Check if patches were applied during review
        updated_extraction = agent.state.get("current_extraction")
        if updated_extraction != result.model_dump(mode="json"):
            # Patches were applied, validate the new extraction
            try:
                result = data_format(**updated_extraction)
                logger.debug(
                    "Applied corrections after final review",
                    extra={"corrections_applied": True},
                )
            except Exception as e:
                logger.debug(
                    "Post-review validation failed",
                    extra={"error": str(e)},
                )

    # Return best effort result
    if result and response:
        return result, BedrockInvokeModelResponse(
            response=BedrockResponse(
                output=BedrockOutput(
                    message=BedrockMessage(
                        role="assistant",
                        content=[BedrockMessageContent(text=str(response))],
                    )
                )
            ),
            metering={f"{context}/bedrock/{model_id}": BedrockUsage(**token_usage)},
        )

    logger.error(
        "Failed to extract structured data",
        extra={"data_format": data_format.__name__},
    )
    raise ValueError("Failed to generate valid structured output.")


def structured_output(
    model_id: str,
    data_format: type[BaseModel],
    prompt: str | Message | Image.Image,
    existing_data: BaseModel | None = None,
    system_prompt: str | None = None,
    custom_instruction: str | None = None,
    page_images: list[bytes] | None = None,
    context: str = "Extraction",
    config: IDPConfig = IDPConfig(),
    max_retries: int = 7,
    connect_timeout: float = 10.0,
    read_timeout: float = 300.0,
) -> tuple[BaseModel, BedrockInvokeModelResponse]:
    """
    Synchronous version of structured_output_async.

    Extract structured data using Strands agents with tool-based validation.
    This is a wrapper that runs the async version in a sync event loop.

    USAGE GUIDELINES:
    - **STRONGLY DISCOURAGED**: Do not modify the system_prompt parameter unless absolutely necessary.
      The default SYSTEM_PROMPT is carefully crafted for optimal extraction accuracy and consistency.
    - **RECOMMENDED**: Use custom_instruction parameter to add task-specific guidance without
      disrupting the core extraction logic and validation rules.
    - Custom instructions are appended to the system prompt, preserving the original behavior
      while allowing for domain-specific customizations.

    Args:
        model_id: Model identifier (e.g., "us.anthropic.claude-sonnet-4-20250514-v1:0")
        data_format: Pydantic model class defining the expected structure
        prompt: Input content (text, image, or content blocks)
        existing_data: Optional existing data to update via patches
        system_prompt: **DISCOURAGED** - Custom system prompt. Only use if the default
                      SYSTEM_PROMPT is completely unsuitable for your use case.
        custom_instruction: **RECOMMENDED** - Additional task-specific instructions
                           appended to the system prompt. Use this for domain-specific
                           guidance, field clarifications, or extraction rules.

    Returns:
        Tuple of (extracted data, bedrock response with token usage)

    Examples:
        # Define data structure with field descriptions (RECOMMENDED):
        # - Use Field(..., description="...") for field-specific requirements
        # - Use model docstrings for overall structure documentation
        # - All data format details belong in the Pydantic model, not instructions

        # Recommended usage with custom instructions for extraction guidance
        result, response = structured_output(
            model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
            data_format=InvoiceModel,
            prompt=image_content,
            custom_instruction="Focus on line items in the main table. Ignore header/footer text."
        )

        # WRONG - Don't define data format in custom instructions:
        # custom_instruction="Extract: invoice_number, total_amount, line_items array..."

        # Discouraged - only use if default system prompt is completely unsuitable
        result, response = structured_output(
            model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
            data_format=CustomModel,
            prompt=content,
            system_prompt="Your completely custom system prompt here..."
        )
    """
    logger.debug(
        "Starting sync agentic extraction",
        extra={"data_format": data_format.__name__},
    )

    # Check if we're already in an event loop (e.g., Jupyter notebook)
    try:
        asyncio.get_running_loop()
        # We're in an existing event loop, use run_until_complete with a new task

        result = None
        exception = None

        def run_in_new_loop():
            nonlocal result, exception
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                result = new_loop.run_until_complete(
                    structured_output_async(
                        model_id=model_id,
                        data_format=data_format,
                        prompt=prompt,
                        existing_data=existing_data,
                        system_prompt=system_prompt,
                        custom_instruction=custom_instruction,
                        config=config,
                        context=context,
                        max_retries=max_retries,
                        connect_timeout=connect_timeout,
                        read_timeout=read_timeout,
                        page_images=page_images,
                    )
                )
            except Exception as e:
                exception = e
            finally:
                new_loop.close()

        thread = threading.Thread(target=run_in_new_loop)
        thread.start()
        thread.join()

        if exception:
            raise exception
        assert result is not None  # For type checker
        return result

    except RuntimeError:
        # No event loop running, safe to use asyncio.run()
        return asyncio.run(
            structured_output_async(
                model_id=model_id,
                data_format=data_format,
                prompt=prompt,
                existing_data=existing_data,
                system_prompt=system_prompt,
                custom_instruction=custom_instruction,
                config=config,
                context=context,
                max_retries=max_retries,
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
                page_images=page_images,
            )
        )


if __name__ == "__main__":

    class Persona(BaseModel):
        age: int
        name: str

    base_dir = Path(__file__).parent.parent.parent.parent.parent
    file_path = base_dir / "samples" / "Nuveen.pdf"

    # Multipage document testcase
    class DocumentRow(BaseModel):
        fund_name: str
        ticker: str
        record_date: str
        ex_dividend_date: str
        payment_date: str
        estimated_short_term_capital_gains: str
        estimated_long_term_capital_gains: str
        nav_as_of_10_31_2024: float
        total_cap_gain_distribution_prc_of_nav: float

    class DocumentFormat(BaseModel):
        document_name: str
        document_text: str
        table_rows: list[DocumentRow] = Field(min_length=500)

    with open(file_path, "rb") as f:
        data = f.read()

    async def async_main():
        result, _ = await structured_output_async(
            model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
            data_format=DocumentFormat,
            prompt=Message(
                role="user",
                content=[
                    ContentBlock(text="please extract the following document"),
                    ContentBlock(
                        document=DocumentContent(
                            format="pdf",
                            source={"bytes": data},
                            name="document to extract",
                        )
                    ),
                ],
            ),
        )
        print(result)
        print("\n\n")
        print(len(result.table_rows))

    asyncio.run(async_main())
