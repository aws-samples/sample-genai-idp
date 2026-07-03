# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Extraction service for documents using LLMs.

This module provides a service for extracting fields and values from documents
using LLMs, with support for text and image content.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from idp_common import bedrock, image, metrics, s3, utils
from idp_common.bedrock import format_prompt, is_openai_responses_model
from idp_common.config.models import IDPConfig
from idp_common.config.schema_constants import (
    ID_FIELD,
    SCHEMA_ITEMS,
    SCHEMA_PROPERTIES,
    SCHEMA_TYPE,
    TYPE_ARRAY,
    TYPE_OBJECT,
    X_AWS_IDP_DOCUMENT_TYPE,
    X_AWS_IDP_EXTRACTION_ESCALATION_MODEL,
    X_AWS_IDP_EXTRACTION_MODEL,
    X_AWS_IDP_EXTRACTION_SYSTEM_PROMPT,
    X_AWS_IDP_EXTRACTION_TASK_PROMPT,
    X_AWS_IDP_SOURCE_PAGE_TYPES,
)
from idp_common.extraction.page_type_resolver import (
    PageTypePresence,
    resolve_page_types,
)
from idp_common.extraction.sharding import (
    DEFAULT_MAX_PAGES_PER_SHARD,
    DEFAULT_SHARD_TOKEN_BUDGET,
    estimate_tokens,
    plan_shards,
)
from idp_common.extraction.validation import (
    ValidationReport,
    build_subset_schema,
    validate_extraction,
)
from idp_common.models import Document, Section
from idp_common.utils.few_shot_example_builder import (
    build_few_shot_extraction_examples_content,
)

# Conditional import for agentic extraction (requires Python 3.12+ dependencies)
try:
    from idp_common.extraction.agentic_idp import (
        concurrent_structured_output_async,
        set_confidence_data,
        structured_output,
    )
    from idp_common.schema import create_pydantic_model_from_json_schema

    AGENTIC_AVAILABLE = True
except ImportError:
    AGENTIC_AVAILABLE = False
from pydantic import BaseModel

from idp_common.utils import extract_json_from_text, repair_truncated_json

logger = logging.getLogger(__name__)


# Pydantic models for internal data transfer
class SectionInfo(BaseModel):
    """Metadata about a document section being processed."""

    model_config = {"arbitrary_types_allowed": True}

    class_label: str
    sorted_page_ids: list[str]
    page_indices: list[int]
    output_bucket: str
    output_key: str
    output_uri: str
    start_page: int
    end_page: int
    page_type_presence: PageTypePresence | None = None


class ExtractionConfig(BaseModel):
    """Configuration for model invocation."""

    model_id: str
    temperature: float
    top_k: float
    top_p: float
    max_tokens: int | None
    system_prompt: str


class ExtractionResult(BaseModel):
    """Result from model extraction."""

    extracted_fields: dict[str, Any]
    metering: dict[str, Any]
    parsing_succeeded: bool
    total_duration: float
    output_truncated: bool = False
    output_repaired: bool = False
    repair_method: str | None = None
    schema_analysis: dict[str, Any] | None = None
    ocr_analysis: dict[str, Any] | None = None


class ExtractionService:
    """Service for extracting fields from documents using LLMs."""

    def __init__(
        self,
        region: str | None = None,
        config: dict[str, Any] | IDPConfig | None = None,
    ):
        """
        Initialize the extraction service.

        Args:
            region: AWS region for Bedrock
            config: Configuration dictionary or IDPConfig model
        """
        # Convert dict to IDPConfig if needed
        if config is not None and isinstance(config, dict):
            config_model: IDPConfig = IDPConfig(**config)
        elif config is None:
            config_model = IDPConfig()
        else:
            config_model = config

        self.config = config_model
        self.region = region or os.environ.get("AWS_REGION")

        # Instance variables for prompt context
        # These are initialized here and populated during each process_document_section call
        # This allows methods to access context without passing multiple parameters
        self._document_text: str = ""
        self._class_label: str = ""
        self._attribute_descriptions: str = ""
        self._class_schema: dict[str, Any] = {}
        self._page_images: list[bytes] = []
        self._image_uris: list[str] = []
        # Per-page OCR text in section order, populated per section. Used to
        # shard the input by page range for concurrent agentic extraction.
        self._page_texts: list[str] = []
        # Optional checkpoint callback for incremental saves during agentic extraction.
        # When set, called after each successful extraction_tool or apply_json_patches
        # invocation with the current extraction dict, enabling resume on Lambda timeout.
        self._checkpoint_callback: Any | None = None
        # Optional per-shard persistence backend (idp_common.extraction.runtime.
        # ShardPersistence). When set (e.g. an S3ShardPersistence wired by the
        # extraction Lambda), the concurrent/sharded path persists each shard's
        # result to a deterministic key and skips shards whose complete result is
        # already present — so an SFN retry of a timed-out section re-runs ONLY
        # the incomplete shards. None => in-memory only (standalone/notebook).
        self._shard_persistence: Any | None = None
        # Validation outcome from the most recent _invoke_extraction_model call,
        # consumed by _save_results when building the metadata block. Reset per
        # section so a prior section's result can never leak into the next.
        self._pending_validation_metadata: dict[str, Any] | None = None
        # Model actually used for the most recent section's extraction (after
        # per-class override resolution), recorded in metadata for audit. Reset
        # per section.
        self._pending_extraction_model: str | None = None
        # Grounded per-field assessment staged by _attach_explainability for the
        # current section, emitted as explainability_info by _save_results.
        # Reset per section. None when in-shard assessment did not run.
        self._grounded_assessment: dict[str, Any] | None = None

        # Get model_id from config for logging (type-safe access with fallback)
        model_id = (
            self.config.extraction.model if self.config.extraction else "not configured"
        )
        logger.info(f"Initialized extraction service with model {model_id}")

    @property
    def _substitutions(self) -> dict[str, str]:
        """Get prompt placeholder substitutions from stored context."""
        return {
            "DOCUMENT_TEXT": self._document_text,
            "DOCUMENT_CLASS": self._class_label,
            "ATTRIBUTE_NAMES_AND_DESCRIPTIONS": self._attribute_descriptions,
        }

    def _get_default_prompt_content(self) -> list[dict[str, Any]]:
        """
        Build default fallback prompt content when no template is provided.

        Returns:
            List of content items with default prompt text and images
        """
        task_prompt = f"""
        Extract the following fields from this {self._class_label} document:
        
        {self._attribute_descriptions}
        
        Document text:
        {self._document_text}
        
        Respond with a JSON object containing each field name and its extracted value.
        """
        content = [{"text": task_prompt}]

        # Add image attachments to the content - no limit with latest Bedrock API
        if self._page_images:
            logger.info(
                f"Attaching {len(self._page_images)} images to default extraction prompt"
            )
            for img in self._page_images:
                content.append(image.prepare_bedrock_image_attachment(img))

        return content

    def _get_class_schema(self, class_label: str) -> dict[str, Any]:
        """
        Get JSON Schema for a specific document class from configuration.

        Args:
            class_label: The document class name

        Returns:
            JSON Schema for the class, or empty dict if not found
        """
        # Access classes through IDPConfig - returns List of dicts
        classes_config = self.config.classes

        # Find class by $id or x-aws-idp-document-type using constants
        for class_obj in classes_config:
            class_id = class_obj.get(ID_FIELD, "") or class_obj.get(
                X_AWS_IDP_DOCUMENT_TYPE, ""
            )
            if class_id.lower() == class_label.lower():
                return class_obj

        return {}

    def _clean_schema_for_prompt(self, schema: dict[str, Any]) -> dict[str, Any]:
        """
        Clean JSON Schema by removing IDP custom fields (x-aws-idp-*) for the prompt.
        Keeps all standard JSON Schema fields including descriptions.

        Args:
            schema: JSON Schema definition

        Returns:
            Cleaned JSON Schema
        """
        cleaned = {}

        for key, value in schema.items():
            # Skip IDP custom fields
            if key.startswith("x-aws-idp-"):
                continue

            # Recursively clean nested objects and arrays
            if isinstance(value, dict):
                cleaned[key] = self._clean_schema_for_prompt(value)
            elif isinstance(value, list):
                cleaned[key] = [
                    (
                        self._clean_schema_for_prompt(item)
                        if isinstance(item, dict)
                        else item
                    )
                    for item in value
                ]
            else:
                cleaned[key] = value

        return cleaned

    def _format_schema_for_prompt(self, schema: dict[str, Any]) -> str:
        """
        Format JSON Schema for inclusion in the extraction prompt.

        Args:
            schema: JSON Schema definition

        Returns:
            Formatted JSON Schema as a string with IDP custom fields removed
        """
        # Clean the schema to remove IDP custom fields
        cleaned_schema = self._clean_schema_for_prompt(schema)

        # Return the cleaned JSON Schema with nice formatting
        return json.dumps(cleaned_schema, indent=2)

    def _prepare_prompt_from_template(
        self,
        prompt_template: str,
        substitutions: dict[str, str],
        required_placeholders: list[str] | None = None,
    ) -> str:
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

    def _build_prompt_content(
        self,
        prompt_template: str,
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
                    self._build_text_and_image_content(parts[0], image_content)
                )

                # Add few-shot examples
                content.extend(self._build_few_shot_examples_content())

                # Process after examples (only pass images if not already used)
                image_for_after = (
                    None if "{DOCUMENT_IMAGE}" in parts[0] else image_content
                )
                content.extend(
                    self._build_text_and_image_content(parts[1], image_for_after)
                )

                return content

        # No FEW_SHOT_EXAMPLES, just handle text and images
        return self._build_text_and_image_content(prompt_template, image_content)

    def _build_text_and_image_content(
        self,
        prompt_template: str,
        image_content: Any = None,
    ) -> list[dict[str, Any]]:
        """
        Build content array with text and optionally images based on DOCUMENT_IMAGE placeholder.

        Args:
            prompt_template: Template that may contain {DOCUMENT_IMAGE}
            image_content: Optional image content

        Returns:
            List of content items
        """
        content: list[dict[str, Any]] = []

        # Handle DOCUMENT_IMAGE placeholder
        if "{DOCUMENT_IMAGE}" in prompt_template:
            parts = prompt_template.split("{DOCUMENT_IMAGE}")
            if len(parts) == 2:
                # Add text before image
                before_text = self._prepare_prompt_from_template(
                    parts[0], self._substitutions, required_placeholders=[]
                )
                if before_text.strip():
                    content.append({"text": before_text})

                # Add images
                if image_content:
                    content.extend(self._prepare_image_attachments(image_content))

                # Add text after image
                after_text = self._prepare_prompt_from_template(
                    parts[1], self._substitutions, required_placeholders=[]
                )
                if after_text.strip():
                    content.append({"text": after_text})

                return content
            else:
                logger.warning("Invalid DOCUMENT_IMAGE placeholder usage")

        # No image placeholder, just text
        task_prompt = self._prepare_prompt_from_template(
            prompt_template, self._substitutions, required_placeholders=[]
        )
        content.append({"text": task_prompt})

        return content

    def _prepare_image_attachments(self, image_content: Any) -> list[dict[str, Any]]:
        """
        Prepare image attachments for Bedrock - no image limit.

        Args:
            image_content: Single image or list of images

        Returns:
            List of image attachment dicts
        """
        attachments: list[dict[str, Any]] = []

        if isinstance(image_content, list):
            # Multiple images - no limit with latest Bedrock API
            logger.info(f"Attaching {len(image_content)} images to extraction prompt")
            for img in image_content:
                attachments.append(image.prepare_bedrock_image_attachment(img))
        else:
            # Single image
            attachments.append(image.prepare_bedrock_image_attachment(image_content))

        return attachments

    def _build_shard_payloads(
        self,
        prompt_template: str,
        send_images: bool,
        max_shards: int,
        table_boundary_pages: frozenset[int] | None = None,
    ) -> list[dict[str, Any]]:
        """Split the section into token-budgeted page shards and render each
        shard's prompt content independently.

        Each shard's content is built with the SAME prompt path as the single
        pass (``_build_prompt_content``) by temporarily scoping
        ``self._document_text`` and ``self._page_images`` to the shard's page
        slice — so few-shot / {DOCUMENT_IMAGE} / placeholder handling is
        identical. The section's first-page text is prepended as shared header
        context to every shard but the first, so column headers and page-1
        scalar context survive the split.

        Returns a list of payload dicts: ``{"content", "page_start", "page_end",
        "total_pages"}``. Falls back to a single whole-section payload when
        per-page text isn't available.
        """
        page_texts = self._page_texts
        num_pages = len(page_texts)
        if num_pages <= 1:
            # Nothing to shard; let the caller use the single-pass path.
            return []

        # Header context = the first page's *header region* (title / account
        # context / table COLUMN HEADERS), prepended to later shards so they
        # retain column meaning. We deliberately DROP page-1 data rows here: the
        # full page 1 is already in shard 0, and re-including its data rows in
        # later shards makes the deterministic table parser re-emit them ->
        # duplicate rows after merge. Truncate at the Markdown table separator
        # (the `|---|` line) so only the header survives; fall back to a small
        # line cap for non-table documents.
        header_context = self._table_header_context(page_texts[0] if page_texts else "")

        # Reserve the header-context tokens from the per-shard budget so the
        # *rendered* shard (own pages + prepended header) still respects the
        # configured budget — otherwise a shard packed to the budget would
        # exceed it once the header is added. Page 0's own shard carries no
        # added header, but using the reduced budget for all shards is the safe
        # (conservative) choice. Never reduce below a small floor.
        full_budget = self._shard_token_budget()
        header_tokens = estimate_tokens(header_context)
        effective_budget = max(1000, full_budget - header_tokens)

        shards = plan_shards(
            page_texts,
            token_budget=effective_budget,
            max_shards=max_shards,
            max_pages_per_shard=self._max_pages_per_shard(),
            table_boundary_pages=table_boundary_pages,
        )
        if len(shards) <= 1:
            return []

        # Save the full-section context to restore afterwards.
        saved_text = self._document_text
        saved_images = self._page_images
        payloads: list[dict[str, Any]] = []
        try:
            for shard in shards:
                shard_page_texts = page_texts[shard.start : shard.end]
                # Build this shard's document text with PAGE markers preserved.
                parts: list[str] = []
                if shard.start > 0 and header_context.strip():
                    parts.append(
                        "--- DOCUMENT HEADER (page 1, for context only) ---\n"
                        f"{header_context}"
                    )
                for offset, text in enumerate(shard_page_texts):
                    page_num = shard.start + offset + 1
                    parts.append(f"--- PAGE {page_num} ---\n{text}")
                self._document_text = "\n".join(parts)
                self._page_images = (
                    self._cap_agent_images(
                        self._slice_images(saved_images, shard.start, shard.end)
                    )
                    if send_images
                    else []
                )
                shard_images = self._page_images if send_images else None
                content = self._build_prompt_content(prompt_template, shard_images)
                payloads.append(
                    {
                        "content": content,
                        "page_start": shard.start,
                        "page_end": shard.end,
                        "total_pages": num_pages,
                        # Raw (un-rendered) shard text + images, kept so an
                        # in-shard assessment pass (integrated-assessment feature)
                        # can reuse AssessmentService.assess_results over the SAME
                        # pages without re-reading S3. Always page images here (not
                        # gated on send_images): assessment benefits from the image
                        # even when the extraction prompt has no {DOCUMENT_IMAGE}.
                        # These never cross the SFN JSON boundary — each shard Lambda
                        # rebuilds payloads locally — so bytes in the dict are safe.
                        "assess_document_text": self._document_text,
                        "assess_page_images": self._cap_agent_images(
                            self._slice_images(saved_images, shard.start, shard.end)
                        ),
                        # Integrated mode: tell the shard agent to emit per-field
                        # confidence/bbox inline (one inference, no second pass).
                        "emit_field_assessment": self._integrated_assessment_enabled(),
                    }
                )
        finally:
            self._document_text = saved_text
            self._page_images = saved_images

        logger.info(
            "Built %d input shards for concurrent extraction "
            "(budget=%d tokens, header-reserved=%d)",
            len(payloads),
            effective_budget,
            header_tokens,
        )
        return payloads

    @staticmethod
    def _slice_images(images: list[bytes], start: int, end: int) -> list[bytes]:
        """Slice page images to a page range, tolerating an empty/short list."""
        if not images:
            return []
        return images[start:end]

    def _cap_agent_images(self, images: list[bytes]) -> list[bytes]:
        """Cap how many page images are attached to one agent invocation.

        Sending many large page images in a single Bedrock request can cause an
        oversized first turn and a read timeout (a 25-page doc with
        ``{DOCUMENT_IMAGE}`` is the classic failure). Beyond
        ``agentic.max_images_per_agent`` (0 = unlimited), attach only the first N
        and log a warning — the agent still has the full OCR text and can pull
        specific pages on demand via the view_image tool.
        """
        cap = getattr(self.config.extraction.agentic, "max_images_per_agent", 0) or 0
        if cap <= 0 or not images or len(images) <= cap:
            return images
        logger.warning(
            "Capping agent page-images from %d to %d (agentic.max_images_per_agent) "
            "to avoid oversized-request read timeouts; OCR text is still complete "
            "and the agent can fetch other pages via the view_image tool.",
            len(images),
            cap,
        )
        return images[:cap]

    def _shard_token_budget(self) -> int:
        """Per-shard input-token budget (config override or default)."""
        agentic = self.config.extraction.agentic
        budget = getattr(agentic, "shard_token_budget", None)
        return int(budget) if budget else DEFAULT_SHARD_TOKEN_BUDGET

    def _max_pages_per_shard(self) -> int:
        """Per-shard page ceiling (config override or default).

        Returns the configured ``extraction.agentic.max_pages_per_shard``. A
        configured ``0`` disables the page ceiling (token budget only); a
        missing field (older configs) falls back to the default. Distinguishes
        missing (``None``) from an explicit ``0``.
        """
        agentic = self.config.extraction.agentic
        cap = getattr(agentic, "max_pages_per_shard", None)
        if cap is None:
            return DEFAULT_MAX_PAGES_PER_SHARD
        return int(cap)

    @staticmethod
    def _table_header_context(page_one_text: str, max_lines: int = 30) -> str:
        """Return the *header region* of page 1 for prepending to later shards.

        Includes title/account context and the table's COLUMN HEADERS but DROPS
        the page-1 data rows so the deterministic table parser doesn't re-emit
        them in every later shard (which would duplicate rows after merge).

        Strategy:
        - If the text contains a Markdown table separator line (``|---|---|``),
          keep everything up to and including that line and drop the rest (the
          data rows that follow). This preserves the column header exactly once.
        - Otherwise (no detectable table header) keep at most ``max_lines`` lines
          so account-level context still propagates without dragging a full page
          of data into every shard.
        """
        if not page_one_text:
            return ""
        lines = page_one_text.split("\n")
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Markdown separator row: pipes/dashes/colons/spaces and >=1 dash.
            if (
                "-" in stripped
                and set(stripped) <= set("|-: ")
                and stripped.count("-") >= 3
            ):
                return "\n".join(lines[: i + 1])
        return "\n".join(lines[:max_lines])

    def _build_few_shot_examples_content(self) -> list[dict[str, Any]]:
        """
        Build content items for few-shot examples from the configuration for a specific class.

        Returns:
            List of content items containing text and image content for examples
        """
        content: list[dict[str, Any]] = []

        # Use the stored class schema
        if not self._class_schema:
            logger.warning(
                f"No class schema found for '{self._class_label}' for few-shot examples"
            )
            return content

        # Get examples from the JSON Schema for this specific class
        content = build_few_shot_extraction_examples_content(self._class_schema)

        return content

    def _make_json_serializable(self, obj: Any) -> Any:
        """
        Recursively convert any object to a JSON-serializable format.

        Args:
            obj: Object to make JSON serializable

        Returns:
            JSON-serializable version of the object
        """
        from enum import Enum

        if isinstance(obj, dict):
            return {
                key: self._make_json_serializable(value) for key, value in obj.items()
            }
        elif isinstance(obj, (list, tuple)):
            return [self._make_json_serializable(item) for item in obj]
        elif isinstance(obj, Enum):
            return obj.value
        elif hasattr(obj, "__dict__"):
            # Handle custom objects by converting to dict
            return self._make_json_serializable(obj.__dict__)
        elif hasattr(obj, "to_dict"):
            # Handle objects with to_dict method
            return self._make_json_serializable(obj.to_dict())
        elif isinstance(obj, bytes):
            # Convert bytes to base64 string or placeholder
            return f"<bytes_object_{len(obj)}_bytes>"
        else:
            try:
                # Test if it's already JSON serializable
                json.dumps(obj)
                return obj
            except (TypeError, ValueError):
                # Convert non-serializable objects to string representation
                return str(obj)

    def _invoke_custom_prompt_lambda(
        self, lambda_arn: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Invoke custom prompt generator Lambda function with JSON-serializable payload.

        Args:
            lambda_arn: ARN of the Lambda function to invoke
            payload: Payload to send to Lambda function (must be JSON serializable)

        Returns:
            Dict containing system_prompt and task_prompt_content

        Raises:
            Exception: If Lambda invocation fails or returns invalid response
        """
        import boto3

        lambda_client = boto3.client("lambda", region_name=self.region)

        try:
            logger.info(f"Invoking custom prompt Lambda: {lambda_arn}")
            response = lambda_client.invoke(
                FunctionName=lambda_arn,
                InvocationType="RequestResponse",
                Payload=json.dumps(payload),
            )

            if response.get("FunctionError"):
                error_payload = response.get("Payload", b"").read().decode()
                error_msg = f"Custom prompt Lambda failed: {error_payload}"
                logger.error(error_msg)
                raise Exception(error_msg)

            result = json.loads(response["Payload"].read())
            logger.info("Custom prompt Lambda invoked successfully")

            # Validate response structure
            if not isinstance(result, dict):
                error_msg = f"Custom prompt Lambda returned invalid response format: expected dict, got {type(result)}"
                logger.error(error_msg)
                raise Exception(error_msg)

            if "system_prompt" not in result:
                error_msg = "Custom prompt Lambda response missing required field: system_prompt"
                logger.error(error_msg)
                raise Exception(error_msg)

            if "task_prompt_content" not in result:
                error_msg = "Custom prompt Lambda response missing required field: task_prompt_content"
                logger.error(error_msg)
                raise Exception(error_msg)

            return result

        except Exception as e:
            error_msg = f"Failed to invoke custom prompt Lambda {lambda_arn}: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def _reset_context(self) -> None:
        """Reset instance variables for clean state before processing."""
        self._document_text = ""
        self._class_label = ""
        self._attribute_descriptions = ""
        self._class_schema = {}
        self._page_images = []
        self._image_uris = []
        self._grounded_assessment = None

    def _validate_and_find_section(
        self, document: Document, section_id: str
    ) -> Any | None:
        """
        Validate document and find section by ID.

        Args:
            document: Document to validate
            section_id: ID of section to find

        Returns:
            Section if found, None otherwise (errors added to document)
        """
        if not document:
            logger.error("No document provided")
            return None

        if not document.sections:
            logger.error("Document has no sections to process")
            document.errors.append("Document has no sections to process")
            return None

        # Find the section with the given ID
        for section in document.sections:
            if section.section_id == section_id:
                return section

        error_msg = f"Section {section_id} not found in document"
        logger.error(error_msg)
        document.errors.append(error_msg)
        return None

    def _prepare_section_info(self, document: Document, section: Any) -> SectionInfo:
        """
        Prepare section metadata and output paths.

        Args:
            document: Document being processed
            section: Section being processed

        Returns:
            SectionInfo with all metadata
        """
        class_label = section.classification
        output_bucket = document.output_bucket
        output_prefix = document.input_key
        output_key = f"{output_prefix}/sections/{section.section_id}/result.json"
        output_uri = f"s3://{output_bucket}/{output_key}"

        # Check if the section has required pages
        if not section.page_ids:
            error_msg = f"Section {section.section_id} has no page IDs"
            logger.error(error_msg)
            document.errors.append(error_msg)
            raise ValueError(error_msg)

        # Sort pages by page number
        sorted_page_ids = sorted(section.page_ids, key=int)
        start_page = int(sorted_page_ids[0])
        end_page = int(sorted_page_ids[-1])

        # Use pre-calculated page_indices from classification service if available
        # This ensures consistent page_indices calculation across all sections in a document packet
        if section.attributes and "page_indices" in section.attributes:
            page_indices = section.attributes["page_indices"]
            logger.info(
                f"Using pre-calculated page_indices from section attributes: {page_indices}"
            )
        else:
            # Fallback: calculate page_indices for backward compatibility
            # This handles sections processed before the fix was implemented
            try:
                # Find minimum page ID across all available sections
                all_page_ids = []
                for sec in document.sections:
                    all_page_ids.extend(sec.page_ids)

                if all_page_ids:
                    global_min_page_id = min(int(page_id) for page_id in all_page_ids)
                else:
                    global_min_page_id = 1

                page_indices = [
                    int(page_id) - global_min_page_id for page_id in sorted_page_ids
                ]
                logger.warning(
                    f"page_indices not found in section attributes, calculated: {page_indices} (global_min_page_id={global_min_page_id})"
                )
            except (ValueError, TypeError) as e:
                # Final fallback: assume 1-indexed page IDs
                page_indices = [int(page_id) - 1 for page_id in sorted_page_ids]
                logger.warning(
                    f"Error calculating page_indices, using 1-indexed fallback: {page_indices} - {e}"
                )

        logger.info(
            f"Processing {len(sorted_page_ids)} pages, class {class_label}: {start_page}-{end_page}"
        )

        # Track metrics
        metrics.put_metric("InputDocuments", 1)
        metrics.put_metric("InputDocumentPages", len(section.page_ids))

        return SectionInfo(
            class_label=class_label,
            sorted_page_ids=sorted_page_ids,
            page_indices=page_indices,
            output_bucket=output_bucket,
            output_key=output_key,
            output_uri=output_uri,
            start_page=start_page,
            end_page=end_page,
        )

    def _load_page_texts(
        self, document: Document, sorted_page_ids: list[str]
    ) -> dict[str, str]:
        """Load OCR text for each page in the section, preserving page IDs.

        Pages missing from ``document.pages`` are recorded as errors and
        omitted from the result.
        """
        t0 = time.time()
        page_id_to_text: dict[str, str] = {}
        for page_id in sorted_page_ids:
            if page_id not in document.pages:
                error_msg = f"Page {page_id} not found in document"
                logger.error(error_msg)
                document.errors.append(error_msg)
                continue
            page = document.pages[page_id]
            text_path = page.parsed_text_uri
            page_id_to_text[page_id] = s3.get_text_content(text_path)
        logger.info(f"Time taken to read text content: {time.time() - t0:.2f} seconds")
        return page_id_to_text

    def _format_document_text(
        self,
        sorted_page_ids: list[str],
        page_id_to_text: dict[str, str],
        page_type_presence: PageTypePresence | None = None,
    ) -> str:
        """Concatenate per-page text with sequential page markers.

        When ``page_type_presence`` resolves a page type for a page, the
        marker is annotated as ``--- PAGE N [PageType] ---`` so the LLM
        gets a soft hint about the page's role.
        """
        page_id_to_type: dict[str, str] = (
            page_type_presence.page_id_to_page_type if page_type_presence else {}
        )
        parts: list[str] = []
        for idx, page_id in enumerate(
            pid for pid in sorted_page_ids if pid in page_id_to_text
        ):
            page_num = idx + 1
            page_type = page_id_to_type.get(page_id)
            marker = (
                f"--- PAGE {page_num} [{page_type}] ---"
                if page_type
                else f"--- PAGE {page_num} ---"
            )
            parts.append(f"{marker}\n{page_id_to_text[page_id]}")
        return "\n".join(parts)

    def _load_document_text(
        self, document: Document, sorted_page_ids: list[str]
    ) -> str:
        """Backwards-compatible loader that returns the concatenated text only.

        Prefer :meth:`_load_page_texts` + :meth:`_format_document_text` when
        per-page text is also needed (e.g., for page-type resolution).
        """
        page_id_to_text = self._load_page_texts(document, sorted_page_ids)
        return self._format_document_text(sorted_page_ids, page_id_to_text)

    def _load_confidence_data(
        self, document: Document, sorted_page_ids: list[str]
    ) -> dict[str, str]:
        """
        Load OCR confidence data for pages in a section.

        Reads text_confidence_uri from each page to provide confidence scores
        to the table parsing tool.

        Args:
            document: Document containing pages
            sorted_page_ids: Sorted list of page IDs

        Returns:
            Dict mapping page IDs to confidence data strings
        """
        confidence_data: dict[str, str] = {}
        for page_id in sorted_page_ids:
            if page_id not in document.pages:
                continue
            page = document.pages[page_id]
            confidence_uri = getattr(page, "text_confidence_uri", None)
            if confidence_uri:
                try:
                    conf_text = s3.get_text_content(confidence_uri)
                    if conf_text:
                        confidence_data[page_id] = conf_text
                except Exception as e:
                    logger.warning(
                        f"Failed to load confidence data for page {page_id}: {e}"
                    )
        return confidence_data

    def _load_document_images(
        self, document: Document, sorted_page_ids: list[str]
    ) -> list[Any]:
        """
        Load images from all pages.

        Args:
            document: Document containing pages
            sorted_page_ids: Sorted list of page IDs

        Returns:
            List of prepared images
        """
        t0 = time.time()
        target_width = self.config.extraction.image.target_width
        target_height = self.config.extraction.image.target_height

        page_images = []
        for page_id in sorted_page_ids:
            if page_id not in document.pages:
                continue

            page = document.pages[page_id]
            image_uri = page.image_uri
            image_content = image.prepare_image(image_uri, target_width, target_height)
            page_images.append(image_content)

        t1 = time.time()
        logger.info(f"Time taken to read images: {t1 - t0:.2f} seconds")

        return page_images

    def _initialize_extraction_context(
        self,
        class_label: str,
        document_text: str,
        page_images: list[Any],
        sorted_page_ids: list[str],
        document: Document,
    ) -> tuple[dict[str, Any], str]:
        """
        Initialize extraction context and set instance variables.

        Args:
            class_label: Document class
            document_text: Text content
            page_images: Prepared images
            sorted_page_ids: Sorted page IDs
            document: Document being processed

        Returns:
            Tuple of (class_schema, attribute_descriptions)
        """
        # Get JSON Schema for this document class
        class_schema = self._get_class_schema(class_label)
        attribute_descriptions = self._format_schema_for_prompt(class_schema)

        # Store context in instance variables
        self._document_text = document_text
        self._class_label = class_label
        self._attribute_descriptions = attribute_descriptions
        self._class_schema = class_schema
        self._page_images = page_images

        # Prepare image URIs for Lambda
        image_uris = []
        for page_id in sorted_page_ids:
            if page_id in document.pages:
                page = document.pages[page_id]
                if page.image_uri:
                    image_uris.append(page.image_uri)
        self._image_uris = image_uris

        return class_schema, attribute_descriptions

    def _handle_empty_schema(
        self,
        document: Document,
        section: Any,
        section_info: SectionInfo,
        section_id: str,
        t0: float,
    ) -> Document:
        """
        Handle case when schema has no attributes - skip LLM and return empty result.

        Args:
            document: Document being processed
            section: Section being processed
            section_info: Section metadata
            section_id: Section ID
            t0: Start time

        Returns:
            Updated document
        """
        logger.info(
            f"No attributes defined for class {section_info.class_label}, skipping LLM extraction"
        )

        # Create empty result structure
        extracted_fields = {}
        metering = {
            "input_tokens": 0,
            "output_tokens": 0,
            "invocation_count": 0,
            "total_cost": 0.0,
        }
        total_duration = 0.0
        parsing_succeeded = True

        # Write to S3
        output = {
            "document_class": {"type": section_info.class_label},
            "split_document": {"page_indices": section_info.page_indices},
            "inference_result": extracted_fields,
            "metadata": {
                "parsing_succeeded": parsing_succeeded,
                "extraction_time_seconds": total_duration,
                "skipped_due_to_empty_attributes": True,
            },
        }
        s3.write_content(
            output,
            section_info.output_bucket,
            section_info.output_key,
            content_type="application/json",
        )

        # Update section and document
        section.extraction_result_uri = section_info.output_uri
        document.metering = utils.merge_metering_data(document.metering, metering)

        t3 = time.time()
        logger.info(
            f"Skipped extraction for section {section_id} due to empty attributes: {t3 - t0:.2f} seconds"
        )
        return document

    def _build_extraction_content(
        self,
        document: Document,
        page_images: list[Any],
    ) -> tuple[list[dict[str, Any]], str]:
        """
        Build prompt content (with or without custom Lambda).

        Args:
            document: Document being processed
            page_images: Prepared page images

        Returns:
            Tuple of (content, system_prompt)
        """
        # Resolve prompts — use per-class system/task prompt overrides if
        # specified on the class schema, otherwise fall back to the global
        # extraction prompts. Backward compatible: classes without overrides
        # use the global prompts unchanged.
        class_system_prompt_override = self._class_schema.get(
            X_AWS_IDP_EXTRACTION_SYSTEM_PROMPT
        )
        system_prompt = (
            class_system_prompt_override or self.config.extraction.system_prompt
        )
        if class_system_prompt_override:
            logger.info(
                f"Using per-class extraction system prompt override for "
                f"'{self._class_label}'"
            )

        from idp_common.extraction.prompt_assembly import (
            select_extraction_task_prompt,
        )

        class_task_prompt_override = self._class_schema.get(
            X_AWS_IDP_EXTRACTION_TASK_PROMPT
        )
        # Select the extraction task prompt per settings: integrated mode uses the
        # extraction+confidence template (+ bbox for LLM-box geometry); otherwise
        # the plain extraction template. A per-class override still wins.
        task_prompt = class_task_prompt_override or select_extraction_task_prompt(
            self.config.extraction
        )
        if class_task_prompt_override:
            logger.info(
                f"Using per-class extraction task prompt override for "
                f"'{self._class_label}'"
            )

        custom_lambda_arn = self.config.extraction.custom_prompt_lambda_arn

        if custom_lambda_arn and custom_lambda_arn.strip():
            logger.info(f"Using custom prompt Lambda: {custom_lambda_arn}")

            prompt_placeholders = {
                "DOCUMENT_TEXT": self._document_text,
                "DOCUMENT_CLASS": self._class_label,
                "ATTRIBUTE_NAMES_AND_DESCRIPTIONS": self._attribute_descriptions,
                "DOCUMENT_IMAGE": self._image_uris,
            }

            logger.info(
                f"Lambda will receive {len(self._image_uris)} image URIs in DOCUMENT_IMAGE placeholder"
            )

            # Build default content for Lambda input
            prompt_template = task_prompt
            if prompt_template:
                default_content = self._build_prompt_content(
                    prompt_template, page_images
                )
            else:
                default_content = self._get_default_prompt_content()

            # Prepare Lambda payload
            try:
                document_dict = document.to_dict()
            except Exception as e:
                logger.warning(f"Error serializing document for Lambda payload: {e}")
                document_dict = {"id": getattr(document, "id", "unknown")}

            payload = {
                "config": self._make_json_serializable(self.config),
                "prompt_placeholders": prompt_placeholders,
                "default_task_prompt_content": self._make_json_serializable(
                    default_content
                ),
                "serialized_document": document_dict,
            }

            # Invoke custom Lambda
            lambda_result = self._invoke_custom_prompt_lambda(
                custom_lambda_arn, payload
            )

            # Use Lambda results
            system_prompt = lambda_result.get("system_prompt", system_prompt)
            content = lambda_result.get("task_prompt_content", default_content)

            logger.info("Successfully applied custom prompt from Lambda function")
        else:
            # Use default prompt logic
            logger.info(
                "No custom prompt Lambda configured - using default prompt generation"
            )
            prompt_template = task_prompt

            if not prompt_template:
                content = self._get_default_prompt_content()
            else:
                try:
                    content = self._build_prompt_content(prompt_template, page_images)
                except ValueError as e:
                    logger.warning(
                        f"Error formatting prompt template: {str(e)}. Using default prompt."
                    )
                    content = self._get_default_prompt_content()

        return content, system_prompt

    def _analyze_schema_for_table_requirements(
        self, schema: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Analyze schema to detect large array fields that require table parsing.

        NOTE: This is OPTIONAL - minItems is not required for tool usage.
        OCR analysis is the primary adaptive trigger. Schema analysis only
        provides additional signal when minItems is explicitly set.

        Returns:
            Dict with analysis results including whether tool usage is recommended
        """
        large_arrays = []
        max_min_items = 0

        properties = schema.get(SCHEMA_PROPERTIES, {})
        for field_name, field_def in properties.items():
            if field_def.get("type") == "array":
                # minItems can arrive as a string after a config round-trip
                # (the Configuration table stores numeric schema fields as
                # strings); coerce defensively so the comparison never raises.
                try:
                    min_items = int(field_def.get("minItems", 0) or 0)
                except (TypeError, ValueError):
                    min_items = 0
                if min_items > 50:  # Match OCR threshold for consistency
                    large_arrays.append(
                        {
                            "field": field_name,
                            "min_items": min_items,
                            "description": field_def.get("description", ""),
                        }
                    )
                    max_min_items = max(max_min_items, min_items)

        recommendation = len(large_arrays) > 0

        return {
            "large_array_fields": [arr["field"] for arr in large_arrays],
            "max_min_items": max_min_items,
            "field_details": large_arrays,
            "tool_usage_recommended": recommendation,
            "recommendation_reason": (
                f"Schema has {len(large_arrays)} array field(s) with minItems > 50"
                if recommendation
                else "No large array constraints detected"
            ),
            "recommendation_strength": (
                "MANDATORY"
                if max_min_items >= 500  # Match OCR threshold
                else "STRONGLY_RECOMMENDED"
                if max_min_items >= 100  # Medium-large
                else "RECOMMENDED"
                if max_min_items >= 50  # Medium
                else "OPTIONAL"
            ),
        }

    def _analyze_ocr_for_tables(self, ocr_text: str) -> dict[str, Any]:
        """
        Analyze OCR text to detect large Markdown tables.

        This is the PRIMARY trigger for table parsing tool guidance, adapting
        automatically to documents of any size without requiring specific minItems.

        Returns:
            Dict with table detection results
        """
        import re

        # Detect Markdown table rows (lines with | delimiters)
        table_rows = []
        lines = ocr_text.split("\n")

        for i, line in enumerate(lines):
            stripped = line.strip()
            # Skip separator rows (e.g., |---|---|)
            if "|" in stripped and not re.match(r"^[\s|:-]+$", stripped):
                table_rows.append(i)

        # Estimate table count by gaps
        tables_detected = 0
        estimated_total_rows = 0
        if table_rows:
            tables_detected = 1
            gap_threshold = 5
            for i in range(1, len(table_rows)):
                if table_rows[i] - table_rows[i - 1] > gap_threshold:
                    tables_detected += 1
            estimated_total_rows = len(table_rows)

        # Adaptive thresholds - lower for better real-world coverage
        # These are optimized for automatic detection without minItems requirement
        recommendation = estimated_total_rows > 30

        return {
            "tables_detected": tables_detected,
            "estimated_row_count": estimated_total_rows,
            "tool_usage_recommended": recommendation,
            "recommendation_reason": (
                f"Detected {tables_detected} table(s) with ~{estimated_total_rows} total rows"
                if recommendation
                else "No large tables detected in OCR text"
            ),
            "recommendation_strength": (
                "MANDATORY"
                if estimated_total_rows >= 500  # Large documents
                else "STRONGLY_RECOMMENDED"
                if estimated_total_rows >= 100  # Medium-large tables
                else "RECOMMENDED"
                if estimated_total_rows >= 50  # Medium tables
                else "OPTIONAL"
            ),
        }

    def _build_table_parsing_guidance(
        self, schema_analysis: dict[str, Any], ocr_analysis: dict[str, Any]
    ) -> str:
        """Build custom table parsing guidance based on pre-flight analysis."""

        # Determine overall recommendation strength
        strengths = [
            schema_analysis.get("recommendation_strength", "OPTIONAL"),
            ocr_analysis.get("recommendation_strength", "OPTIONAL"),
        ]

        # Get the strongest recommendation
        strength_order = [
            "OPTIONAL",
            "RECOMMENDED",
            "STRONGLY_RECOMMENDED",
            "MANDATORY",
        ]
        max_strength = max(
            strengths,
            key=lambda x: strength_order.index(x) if x in strength_order else 0,
        )

        if max_strength == "MANDATORY":
            # For very large tables (500+ rows detected by OCR)
            guidance = """
**CRITICAL - MANDATORY TABLE PARSING TOOL USAGE**:
This document contains a large table with {row_count}+ rows detected by OCR analysis.
You MUST use the parse_table tool for complete and accurate extraction:

1. IMMEDIATELY call parse_table with the full document text or table section
2. DO NOT attempt manual row-by-row LLM extraction for large tables
3. Verify parse_table returned ALL expected rows (check row_count in response)
4. If parse_table returns fewer rows than expected, investigate warnings and ensure all
   table fragments are parsed (tables may be split across pages)

FAILURE TO USE parse_table will result in:
- Incomplete extraction (missing rows) - you will miss hundreds of data points
- Schema validation failures
- Excessive token usage (may hit context limits)
- Poor extraction performance

This is not optional - use the tool immediately for any tabular data.
"""
            return guidance.format(
                row_count=ocr_analysis.get("estimated_row_count", "500"),
            )

        elif max_strength == "STRONGLY_RECOMMENDED":
            # For medium-large tables (100-499 rows) - still use explicit instructions
            guidance = """
**IMPORTANT - USE TABLE PARSING TOOL**:
This document contains tabular data with {row_count}+ rows detected.
You MUST use the parse_table tool for accurate and complete extraction:

1. Call parse_table with the document text containing the table
2. The tool handles OCR artifacts (empty lines, page breaks) automatically
3. Verify the row_count matches your expectation
4. Review any warnings about table fragmentation
5. Map the parsed columns to the required schema fields

Using the tool ensures:
- Complete data extraction (no missing rows)
- Faster processing (10x more efficient than manual)
- Better accuracy (deterministic parsing of well-structured tables)

Do NOT attempt manual row-by-row extraction for tables with 100+ rows.
"""
            return guidance.format(
                row_count=ocr_analysis.get("estimated_row_count", "100"),
            )

        elif max_strength == "RECOMMENDED":
            # For medium tables (50-99 rows) - gentler guidance
            guidance = """
**RECOMMENDED - TABLE PARSING TOOL**:
Detected a table with {row_count}+ rows. Consider using the parse_table tool:

1. Call parse_table to extract the table data efficiently
2. Review the quality metrics and warnings
3. Fall back to LLM extraction if parse quality is poor

Benefits: Faster, more accurate, handles OCR artifacts automatically.
"""
            return guidance.format(
                row_count=ocr_analysis.get("estimated_row_count", "50"),
            )

        # Return empty for optional cases (standard TABLE_PARSING_PROMPT_ADDENDUM will be used)
        return ""

    def _explain_tool_usage_decision(
        self,
        expected: bool,
        actual: bool,
        schema_analysis: dict[str, Any] | None,
        ocr_analysis: dict[str, Any] | None,
    ) -> str:
        """Generate human-readable explanation of tool usage."""

        if expected and actual:
            return "Tool was recommended and used as expected"
        elif expected and not actual:
            reasons = []
            if schema_analysis and schema_analysis.get("tool_usage_recommended"):
                reasons.append(schema_analysis.get("recommendation_reason", ""))
            if ocr_analysis and ocr_analysis.get("tool_usage_recommended"):
                reasons.append(ocr_analysis.get("recommendation_reason", ""))
            return (
                f"Tool was recommended but NOT used. Reasons: {'; '.join(reasons)}. "
                f"This may indicate incomplete extraction."
            )
        elif not expected and actual:
            return "Tool was used even though not required (agent chose to use it)"
        else:
            return "Tool usage was not required and was not used"

    def _check_completeness_detailed(
        self,
        extracted_fields: dict[str, Any],
        schema: dict[str, Any],
        tool_used: bool,
    ) -> dict[str, Any]:
        """Detailed completeness check with violations."""

        violations = []
        properties = schema.get(SCHEMA_PROPERTIES, {})

        for field_name, field_def in properties.items():
            if field_def.get("type") == "array":
                min_items = field_def.get("minItems", 0)
                actual_items = len(extracted_fields.get(field_name) or [])

                if min_items > 0 and actual_items < min_items:
                    violations.append(
                        {
                            "field": field_name,
                            "constraint": f"minItems: {min_items}",
                            "actual": actual_items,
                            "shortfall": min_items - actual_items,
                            "completeness_pct": round(
                                100 * actual_items / min_items, 1
                            ),
                            "message": (
                                f"Extracted {actual_items} items but schema requires "
                                f"minimum {min_items} ({100 * actual_items / min_items:.1f}% complete)"
                            ),
                            "possible_cause": (
                                "Agent did not use table parsing tool"
                                if not tool_used
                                else "Table parsing may have stopped early"
                            ),
                        }
                    )

        return {
            "schema_constraints_met": len(violations) == 0,
            "violations": violations,
            "summary": (
                "All schema constraints satisfied"
                if not violations
                else f"{len(violations)} constraint violation(s) detected - extraction may be incomplete"
            ),
        }

    @staticmethod
    def _count_schema_leaf_fields(
        schema_node: dict[str, Any], value: Any
    ) -> tuple[int, int, list[str]]:
        """Recursively count schema-defined leaf fields vs. populated ones.

        Walks the schema's ``properties`` (descending into nested ``object``
        properties and the ``items`` of ``array`` properties) and, in parallel,
        the extracted ``value``. Returns ``(defined, populated, empty_paths)``:

        - ``defined``  — number of leaf (scalar) fields the schema declares.
        - ``populated`` — how many of those have a non-empty value
          (not None, not "" / [] / {}).
        - ``empty_paths`` — dotted paths of the leaf fields that came back empty.

        For arrays of objects, the item schema's leaves are counted once per
        present row (so a 0-row array contributes its leaves as "defined but
        empty", surfacing tables that extracted nothing). This is the signal
        that catches silent nested-field loss (all-null nested objects).
        """
        defined = 0
        populated = 0
        empty: list[str] = []

        node_type = schema_node.get(SCHEMA_TYPE)
        properties = schema_node.get(SCHEMA_PROPERTIES) or {}

        if node_type == TYPE_OBJECT or properties:
            value_dict = value if isinstance(value, dict) else {}
            for prop_name, prop_schema in properties.items():
                if not isinstance(prop_schema, dict):
                    continue
                prop_type = prop_schema.get(SCHEMA_TYPE)
                child_value = value_dict.get(prop_name)
                path = prop_name

                if prop_type == TYPE_OBJECT or (prop_schema.get(SCHEMA_PROPERTIES)):
                    d, p, e = ExtractionService._count_schema_leaf_fields(
                        prop_schema, child_value
                    )
                    defined += d
                    populated += p
                    empty.extend(f"{path}.{sub}" for sub in e)
                elif prop_type == TYPE_ARRAY:
                    item_schema = prop_schema.get(SCHEMA_ITEMS) or {}
                    rows = child_value if isinstance(child_value, list) else []
                    if isinstance(item_schema, dict) and item_schema.get(
                        SCHEMA_PROPERTIES
                    ):
                        if rows:
                            for idx, row in enumerate(rows):
                                d, p, e = ExtractionService._count_schema_leaf_fields(
                                    item_schema, row
                                )
                                defined += d
                                populated += p
                                empty.extend(f"{path}[{idx}].{sub}" for sub in e)
                        else:
                            # Empty array: count the item leaves once as "missing".
                            d, _p, _e = ExtractionService._count_schema_leaf_fields(
                                item_schema, {}
                            )
                            defined += d
                            empty.append(path)
                    else:
                        # Array of scalars.
                        defined += 1
                        if rows:
                            populated += 1
                        else:
                            empty.append(path)
                else:
                    # Scalar leaf.
                    defined += 1
                    if child_value not in (None, "", [], {}):
                        populated += 1
                    else:
                        empty.append(path)

        return defined, populated, empty

    def _check_population_completeness(
        self, extracted_fields: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Heuristic: how much of the schema actually got populated.

        Unlike ``_check_completeness_detailed`` (which only flags hard
        ``minItems`` constraint violations), this flags *suspiciously sparse*
        extractions — e.g. an agentic run that returned a correct top-level
        object but null for nearly every nested field. It cannot know a field
        *should* have had a value, so it is advisory (a warning signal), not a
        hard failure: a genuinely sparse document will also score low.
        """
        defined, populated, empty_paths = self._count_schema_leaf_fields(
            schema, extracted_fields
        )
        ratio = (populated / defined) if defined else 1.0
        threshold = self.config.extraction.agentic.validation.min_population_ratio
        below = defined > 0 and ratio < threshold

        if below:
            logger.warning(
                "Extraction populated only %d/%d schema fields (%.0f%%), below the "
                "%.0f%% completeness threshold — possible silent extraction loss "
                "(e.g. nested fields not captured).",
                populated,
                defined,
                ratio * 100,
                threshold * 100,
                extra={"empty_fields": empty_paths[:50]},
            )

        return {
            "fields_defined": defined,
            "fields_populated": populated,
            "population_ratio": round(ratio, 3),
            "threshold": threshold,
            "below_threshold": below,
            # Cap the echoed list so a huge sparse schema can't bloat metadata.
            "empty_fields": empty_paths[:50],
        }

    def _generate_processing_report(self, metadata: dict[str, Any]) -> str:
        """Generate user-friendly processing report."""

        report_lines = [
            "=== EXTRACTION PROCESSING REPORT ===",
            "",
            f"Extraction Method: {metadata.get('extraction_method', 'N/A').upper()}",
            f"Processing Time: {metadata.get('extraction_time_seconds', 0):.1f} seconds",
            f"Status: {'SUCCESS' if metadata.get('parsing_succeeded') else 'FAILED'}",
            "",
        ]

        # Schema analysis
        if "schema_analysis" in metadata:
            schema_info = metadata["schema_analysis"]
            report_lines.extend(
                [
                    "Schema Analysis:",
                    f"  - Large array fields detected: {len(schema_info.get('large_array_fields', []))}",
                    f"  - Maximum minItems constraint: {schema_info.get('max_min_items', 0)}",
                    f"  - Tool usage recommendation: {schema_info.get('recommendation_strength', 'N/A')}",
                    "",
                ]
            )

        # OCR analysis
        if "ocr_analysis" in metadata:
            ocr_info = metadata["ocr_analysis"]
            report_lines.extend(
                [
                    "OCR Table Detection:",
                    f"  - Tables detected: {ocr_info.get('tables_detected', 0)}",
                    f"  - Estimated total rows: {ocr_info.get('estimated_row_count', 0)}",
                    f"  - Tool usage recommendation: {ocr_info.get('recommendation_strength', 'N/A')}",
                    "",
                ]
            )

        # Tool usage decision
        if "tool_usage_decision" in metadata:
            decision = metadata["tool_usage_decision"]
            status_icon = "✓" if not decision.get("mismatch") else "⚠"
            report_lines.extend(
                [
                    f"{status_icon} Table Parsing Tool Decision:",
                    f"  - Expected usage: {'YES' if decision.get('expected') else 'NO'}",
                    f"  - Actual usage: {'YES' if decision.get('actual') else 'NO'}",
                    f"  - Explanation: {decision.get('explanation', 'N/A')}",
                    "",
                ]
            )

        # Completeness check
        if "completeness_check" in metadata:
            check = metadata["completeness_check"]
            status_icon = "✓" if check.get("schema_constraints_met") else "✗"
            report_lines.extend(
                [
                    f"{status_icon} Completeness Validation:",
                    f"  - {check.get('summary', 'N/A')}",
                    "",
                ]
            )

            if check.get("violations"):
                report_lines.append("  Detected Issues:")
                for v in check["violations"]:
                    report_lines.append(f"    • Field '{v['field']}': {v['message']}")
                    report_lines.append(f"      Possible cause: {v['possible_cause']}")
                report_lines.append("")

        # Table parsing stats (if used)
        if (
            metadata.get("table_parsing_tool_used")
            and "table_parsing_stats" in metadata
        ):
            stats = metadata["table_parsing_stats"]
            report_lines.extend(
                [
                    "✓ Table Parsing Tool Results:",
                    f"  - Tables parsed: {stats.get('tables_parsed', 0)}",
                    f"  - Total rows extracted: {stats.get('rows_parsed', 0)}",
                    f"  - Parse success rate: {stats.get('parse_success_rate') or 0:.1%}",
                    f"  - Avg OCR confidence: {stats.get('avg_confidence') or 0:.1f}%",
                    "",
                ]
            )

            if stats.get("warnings"):
                report_lines.append("  Warnings:")
                for w in stats["warnings"]:
                    report_lines.append(f"    {w}")
                report_lines.append("")

        report_lines.append("=" * 40)

        return "\n".join(report_lines)

    def _resolve_escalation_model(self) -> str | None:
        """Pick the model used to re-extract on validation failure.

        Precedence: per-class ``x-aws-idp-extraction-escalation-model`` >
        global ``validation.escalation_model``. Returns None when neither is
        set, in which case escalation falls back to the extraction model and is
        effectively a plain retry (still useful as a second attempt).
        """
        return (
            self._class_schema.get(X_AWS_IDP_EXTRACTION_ESCALATION_MODEL)
            or self.config.extraction.agentic.validation.escalation_model
        )

    def _build_schema_validator(self):
        """Return an in-loop schema-validation callback, or None when disabled.

        The callback validates an extracted dict against the full class JSON
        Schema (notably ``format`` keywords the Pydantic model does not enforce)
        and returns ``(is_valid, agent_feedback)`` for the agent to self-correct.
        """
        vcfg = self.config.extraction.agentic.validation
        if not vcfg.enabled:
            return None

        class_schema = self._class_schema
        check_formats = vcfg.check_formats

        def _validate(data: dict[str, Any]) -> tuple[bool, str]:
            report = validate_extraction(
                data, class_schema, check_formats=check_formats
            )
            return report.valid, report.agent_feedback()

        return _validate

    def _validate_and_maybe_escalate(
        self,
        extracted_fields: dict[str, Any],
        structured_data: Any,
        data_model: Any,
        model_id: str,
        message_prompt: Any,
        agentic_images: list[bytes],
        custom_instruction: str | None,
        section_info: SectionInfo,
        parsing_succeeded: bool,
    ) -> tuple[dict[str, Any], Any, dict[str, Any] | None, dict[str, Any], bool]:
        """Validate the final extraction and optionally escalate to a stronger model.

        Returns ``(extracted_fields, structured_data, validation_metadata,
        escalation_metering, parsing_succeeded)``. A no-op (returns inputs
        unchanged with ``validation_metadata=None``) unless
        ``extraction.agentic.validation.enabled``.
        """
        vcfg = self.config.extraction.agentic.validation
        escalation_metering: dict[str, Any] = {}
        if not vcfg.enabled:
            return (
                extracted_fields,
                structured_data,
                None,
                escalation_metering,
                parsing_succeeded,
            )

        report: ValidationReport = validate_extraction(
            extracted_fields, self._class_schema, check_formats=vcfg.check_formats
        )
        initial_error_count = len(report.errors)
        initial_failed_fields = sorted(report.failed_top_level_fields)

        escalated = False
        escalation_model: str | None = None
        escalation_scope: str | None = None
        escalation_fields: list[str] = []
        if not report.valid:
            logger.warning(
                "Extraction failed full-schema validation for "
                f"'{section_info.class_label}'",
                extra={
                    "error_count": initial_error_count,
                    "failed_fields": initial_failed_fields,
                    "fail_action": vcfg.fail_action,
                },
            )

        # Escalate: re-extract ONLY the failing top-level fields with a stronger
        # model, then merge the corrected fields back into the full result. This
        # is cheaper/faster than re-running the whole section and preserves the
        # fields that already validated.
        if not report.valid and vcfg.fail_action == "escalate":
            escalation_model = self._resolve_escalation_model() or model_id
            escalated = True
            escalation_fields = initial_failed_fields
            (
                extracted_fields,
                structured_data,
                report,
                escalation_metering,
                escalation_scope,
            ) = self._escalate_failing_fields(
                extracted_fields=extracted_fields,
                structured_data=structured_data,
                data_model=data_model,
                full_report=report,
                escalation_model=escalation_model,
                message_prompt=message_prompt,
                agentic_images=agentic_images,
                custom_instruction=custom_instruction,
                section_info=section_info,
            )

        # reject: surface the failure so downstream/HITL can act on it.
        if not report.valid and vcfg.fail_action == "reject":
            parsing_succeeded = False

        # Rich audit trail: what was enforced, what failed, what we did about it.
        validation_metadata: dict[str, Any] = {
            **report.to_metadata(),
            "check_formats": vcfg.check_formats,
            "fail_action": vcfg.fail_action,
            "escalated": escalated,
            "initial_error_count": initial_error_count,
            "initial_failed_fields": initial_failed_fields,
        }
        if escalated:
            validation_metadata["escalation_model"] = escalation_model
            validation_metadata["escalation_scope"] = escalation_scope
            validation_metadata["escalation_fields"] = escalation_fields
            validation_metadata["resolved_by_escalation"] = report.valid

        return (
            extracted_fields,
            structured_data,
            validation_metadata,
            escalation_metering,
            parsing_succeeded,
        )

    def _escalate_failing_fields(
        self,
        extracted_fields: dict[str, Any],
        structured_data: Any,
        data_model: Any,
        full_report: ValidationReport,
        escalation_model: str,
        message_prompt: Any,
        agentic_images: list[bytes],
        custom_instruction: str | None,
        section_info: SectionInfo,
    ) -> tuple[dict[str, Any], Any, ValidationReport, dict[str, Any], str]:
        """Re-extract only the failing top-level fields with a stronger model.

        Builds a reduced schema containing just ``full_report.failed_top_level_fields``,
        runs a scoped extraction, merges the corrected fields back into the full
        result and re-validates. Falls back to a whole-section re-extraction when
        a usable subset schema can't be built (e.g. failures are root-level only).

        Returns ``(extracted_fields, structured_data, report, metering, scope)``
        where ``scope`` is ``"field-subset"`` or ``"full-section"``. On any error
        the original inputs are returned unchanged with an empty metering dict.
        """
        failed_fields = sorted(full_report.failed_top_level_fields)
        subset_schema = build_subset_schema(self._class_schema, failed_fields)
        scope = (
            "field-subset"
            if subset_schema is not self._class_schema
            else "full-section"
        )

        logger.info(
            f"Escalating extraction for '{section_info.class_label}' to model "
            f"{escalation_model} (scope={scope}, fields={failed_fields})",
        )

        check_formats = self.config.extraction.agentic.validation.check_formats
        instruction = (
            (custom_instruction + "\n\n" if custom_instruction else "")
            + "A previous extraction attempt produced data that violated the "
            "schema. Carefully re-extract and correct these issues:\n"
            + full_report.agent_feedback()
        )

        try:
            if scope == "field-subset":
                subset_model = create_pydantic_model_from_json_schema(
                    schema=subset_schema,
                    class_label=f"{section_info.class_label}__escalation",
                    clean_schema=False,
                )
                # Seed with current values for the failing fields only.
                seed = {k: extracted_fields.get(k) for k in failed_fields}
                try:
                    existing_model = subset_model(
                        **{k: v for k, v in seed.items() if v is not None}
                    )
                except Exception:
                    existing_model = None

                esc_data, esc_response = structured_output(
                    model_id=escalation_model,
                    data_format=subset_model,
                    prompt=message_prompt,
                    existing_data=existing_model,
                    page_images=agentic_images,
                    config=self.config,
                    context="ExtractionEscalation",
                    custom_instruction=instruction,
                    schema_validator=None,  # validated against the full schema below
                )
                metering = esc_response.get("metering", {}) or {}
                metering.pop("_table_parsing_stats", None)

                # Merge corrected subset fields back into the full result.
                merged = dict(extracted_fields)
                merged.update(esc_data.model_dump(mode="json"))
            else:
                # Fallback: whole-section re-extraction with the full model.
                try:
                    existing_model = data_model(**extracted_fields)
                except Exception:
                    existing_model = None
                esc_data, esc_response = structured_output(
                    model_id=escalation_model,
                    data_format=data_model,
                    prompt=message_prompt,
                    existing_data=existing_model,
                    page_images=agentic_images,
                    config=self.config,
                    context="ExtractionEscalation",
                    custom_instruction=instruction,
                    schema_validator=self._build_schema_validator(),
                )
                metering = esc_response.get("metering", {}) or {}
                metering.pop("_table_parsing_stats", None)
                merged = esc_data.model_dump(mode="json")

            esc_report = validate_extraction(
                merged, self._class_schema, check_formats=check_formats
            )

            # Keep the escalated result only if it's valid or strictly improves.
            if esc_report.valid or len(esc_report.errors) < len(full_report.errors):
                # Re-validate the merged dict through the full Pydantic model so
                # the returned structured_data stays consistent with the fields.
                try:
                    structured_data = data_model(**merged)
                except Exception:
                    pass  # keep prior structured_data; fields dict is source of truth
                return merged, structured_data, esc_report, metering, scope

            logger.info(
                "Escalation did not improve validation; keeping original result",
                extra={
                    "original_errors": len(full_report.errors),
                    "escalated_errors": len(esc_report.errors),
                },
            )
            return extracted_fields, structured_data, full_report, metering, scope
        except Exception as e:
            logger.error(
                "Escalation re-extraction failed; keeping original result",
                extra={"error": str(e)},
                exc_info=True,
            )
            return extracted_fields, structured_data, full_report, {}, scope

    def _check_extraction_completeness(
        self,
        extracted_data: Any,
        data_model: Any,
        section_label: str,
    ) -> None:
        """
        Check if extraction meets schema constraints (e.g., min_length for arrays).

        Logs warnings if extracted data appears incomplete based on schema constraints.
        This helps catch cases where table parsing or extraction stopped early.

        Args:
            extracted_data: The extracted data instance (Pydantic model)
            data_model: The Pydantic model class with constraints
            section_label: Section label for logging context
        """
        if not hasattr(data_model, "model_fields"):
            return

        for field_name, field_info in data_model.model_fields.items():
            field_value = getattr(extracted_data, field_name, None)

            # Check array min_length constraints
            if isinstance(field_value, list) and hasattr(field_info, "metadata"):
                for constraint in field_info.metadata:
                    if hasattr(constraint, "min_length"):
                        expected_min = constraint.min_length
                        actual_count = len(field_value)

                        if actual_count < expected_min:
                            logger.warning(
                                f"Extraction may be INCOMPLETE for {section_label}: "
                                f"field '{field_name}' has {actual_count} items, "
                                f"but schema expects at least {expected_min}. "
                                f"Verify all table rows were extracted.",
                                extra={
                                    "field": field_name,
                                    "actual_count": actual_count,
                                    "expected_min": expected_min,
                                    "completeness_ratio": f"{actual_count}/{expected_min}",
                                },
                            )
                        elif actual_count == expected_min:
                            logger.info(
                                f"Extraction meets minimum constraint for {section_label}: "
                                f"field '{field_name}' has exactly {actual_count} items "
                                f"(minimum: {expected_min})"
                            )
                        else:
                            logger.debug(
                                f"Extraction exceeds minimum constraint for {section_label}: "
                                f"field '{field_name}' has {actual_count} items "
                                f"(minimum: {expected_min})"
                            )

    def _invoke_extraction_model(
        self,
        content: list[dict[str, Any]],
        system_prompt: str,
        section_info: SectionInfo,
        checkpoint_data: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        """
        Invoke Bedrock model (agentic or standard) and parse response.

        Args:
            content: Prompt content
            system_prompt: System prompt
            section_info: Section metadata

        Returns:
            ExtractionResult with extracted fields and metering
        """
        logger.info(
            f"Extracting fields for {section_info.class_label} document, section"
        )

        # Clear any per-section audit state from a previously processed section.
        self._pending_validation_metadata = None
        self._pending_extraction_model = None

        # Get extraction config — use per-class model override if specified,
        # otherwise fall back to the global extraction model.
        class_model_override = self._class_schema.get(X_AWS_IDP_EXTRACTION_MODEL)
        model_id = class_model_override or self.config.extraction.model
        # Record the resolved model for audit metadata (set here so it is
        # captured even on the non-agentic/standard path).
        self._pending_extraction_model = model_id
        if class_model_override:
            logger.info(
                f"Using per-class extraction model override for "
                f"'{section_info.class_label}': {model_id}"
            )
        temperature = self.config.extraction.temperature
        top_k = self.config.extraction.top_k
        top_p = self.config.extraction.top_p
        reasoning_effort = self.config.extraction.reasoning_effort
        max_tokens = (
            self.config.extraction.max_tokens
            if self.config.extraction.max_tokens
            else None
        )

        # Time the model invocation
        request_start_time = time.time()

        # Initialize repair tracking variables
        output_truncated = False
        output_repaired = False
        repair_method = None

        # Initialize analysis tracking
        schema_analysis: dict[str, Any] | None = None
        ocr_analysis: dict[str, Any] | None = None

        # OpenAI GPT-5.x models are served via the bedrock-mantle Responses API
        # and are incompatible with agentic (Strands) extraction, which relies on
        # the Converse API. This combination is rejected at config-validate time;
        # fail loudly here too rather than silently changing the extraction mode,
        # so a config that bypassed validation surfaces the error immediately.
        use_agentic = self.config.extraction.agentic.enabled
        if use_agentic and is_openai_responses_model(model_id):
            raise ValueError(
                f"OpenAI Responses model '{model_id}' is not compatible with agentic "
                "extraction (extraction.agentic.enabled=true). Set agentic.enabled=false "
                "or choose a non-OpenAI model. (This is also enforced by "
                "'idp-cli config-validate'.)"
            )

        if use_agentic:
            if not AGENTIC_AVAILABLE:
                raise ImportError(
                    "Agentic extraction requires Python 3.12+ and strands-agents dependencies. "
                    "Install with: pip install 'idp_common[agents]' or use agentic=False"
                )

            # Pre-flight analysis: Detect large tables and assess tool requirements
            schema_analysis = self._analyze_schema_for_table_requirements(
                self._class_schema
            )
            ocr_analysis = self._analyze_ocr_for_tables(self._document_text)

            logger.info(
                "Pre-flight analysis complete",
                extra={
                    "schema_recommendation": schema_analysis.get(
                        "recommendation_strength"
                    ),
                    "ocr_recommendation": ocr_analysis.get("recommendation_strength"),
                    "schema_max_min_items": schema_analysis.get("max_min_items"),
                    "ocr_estimated_rows": ocr_analysis.get("estimated_row_count"),
                },
            )

            # Create dynamic Pydantic model from JSON Schema
            dynamic_model = create_pydantic_model_from_json_schema(
                schema=self._class_schema,
                class_label=section_info.class_label,
                clean_schema=False,  # Already cleaned
            )

            # Log schema for debugging
            model_schema = dynamic_model.model_json_schema()
            logger.debug(f"Pydantic model schema for {section_info.class_label}:")
            logger.debug(json.dumps(model_schema, indent=2))

            # Use agentic extraction
            if isinstance(content, list):
                message_prompt = {"role": "user", "content": content}
            else:
                message_prompt = content

            logger.info("Using Agentic extraction")
            logger.debug(f"Using input: {str(message_prompt)}")

            # Convert checkpoint data for resume-on-timeout
            existing_data_model = None
            checkpoint_buffer = None
            if checkpoint_data:
                # Check if this is a buffer checkpoint (from intermediate_extraction)
                checkpoint_source = checkpoint_data.pop(
                    "_checkpoint_source", "current_extraction"
                )
                if checkpoint_source == "intermediate_extraction":
                    # Buffer checkpoint — load into agent's intermediate_extraction state
                    checkpoint_buffer = checkpoint_data
                    logger.info(
                        "Resuming agentic extraction from buffer checkpoint "
                        "(intermediate_extraction)"
                    )
                else:
                    # Validated extraction checkpoint — load as existing_data
                    try:
                        existing_data_model = dynamic_model(**checkpoint_data)
                        logger.info("Resuming agentic extraction from checkpoint data")
                    except Exception as e:
                        logger.warning(
                            f"Failed to validate checkpoint data, starting fresh: {e}"
                        )
                        existing_data_model = None

            # Build dynamic custom instruction based on pre-flight analysis
            custom_instruction = None
            if schema_analysis and ocr_analysis:
                dynamic_guidance = self._build_table_parsing_guidance(
                    schema_analysis=schema_analysis, ocr_analysis=ocr_analysis
                )
                if dynamic_guidance:
                    custom_instruction = dynamic_guidance
                    logger.info(
                        "Injecting dynamic table parsing guidance into agent instructions",
                        extra={
                            "schema_strength": schema_analysis.get(
                                "recommendation_strength"
                            ),
                            "ocr_strength": ocr_analysis.get("recommendation_strength"),
                        },
                    )

            # Pre-flight table parsing: parse all tables BEFORE LLM to avoid
            # the LLM having to call parse_table and then generate JSON row-by-row.
            # The LLM only needs to provide a column-to-field mapping, and the
            # map_table_to_schema tool does the bulk transformation instantly.
            preflight_parse_result = None
            if (
                self.config.extraction.agentic.table_parsing.enabled
                and ocr_analysis.get("estimated_row_count", 0) >= 50
            ):
                from idp_common.extraction.tools.table_parser import (
                    parse_markdown_tables,
                )

                tp_config = self.config.extraction.agentic.table_parsing
                preflight_parse_result = parse_markdown_tables(
                    text=self._document_text,
                    max_empty_line_gap=tp_config.max_empty_line_gap,
                    auto_merge_adjacent_tables=tp_config.auto_merge_adjacent_tables,
                )

                if preflight_parse_result.get("status") == "success":
                    total_rows = sum(
                        t.get("row_count", 0)
                        for t in preflight_parse_result.get("tables", [])
                    )
                    columns = preflight_parse_result.get("columns", [])
                    table_count = preflight_parse_result.get("table_count", 0)

                    logger.info(
                        "Pre-flight table parsing complete",
                        extra={
                            "total_rows": total_rows,
                            "table_count": table_count,
                            "columns": columns,
                        },
                    )

                    # Build efficient extraction guidance with pre-parsed summary
                    preflight_guidance = (
                        f"\n\n**PRE-PARSED TABLE DATA AVAILABLE**:\n"
                        f"Found {table_count} table(s) with {total_rows} total rows.\n"
                        f"Table columns: {columns}\n\n"
                        f"PAGE MARKERS: The document text contains '--- PAGE N ---' "
                        f"markers between pages. When you are assigned a page range, "
                        f"extract ONLY text between markers for your pages before "
                        f"calling parse_table.\n\n"
                        f"EFFICIENT EXTRACTION WORKFLOW:\n"
                        f"1. Extract scalar fields from your pages' text\n"
                        f"2. Call parse_table with your pages' text\n"
                        f"3. Call map_table_to_schema with column_mapping + static_fields\n"
                        f"   (merged rows are auto-split — no manual handling needed)\n"
                        f"4. Call finalize_table_extraction with table_array_field + "
                        f"scalar_fields\n\n"
                        f"finalize reads mapped rows from state — no JSON generation needed."
                    )

                    if custom_instruction:
                        custom_instruction += preflight_guidance
                    else:
                        custom_instruction = preflight_guidance

            # Determine if images should be sent to the agentic model.
            # If the task prompt does not reference {DOCUMENT_IMAGE}, sending
            # page images is wasteful and can cause context-window overflow
            # on large documents.
            from idp_common.extraction.prompt_assembly import (
                select_extraction_task_prompt,
            )

            prompt_template = (
                select_extraction_task_prompt(self.config.extraction) or ""
            )
            send_images = "{DOCUMENT_IMAGE}" in prompt_template
            agentic_images = (
                self._cap_agent_images(self._page_images) if send_images else []
            )
            num_pages = len(self._page_images) or len(section_info.sorted_page_ids)

            if not send_images and self._page_images:
                logger.info(
                    "Skipping image attachment for agentic extraction "
                    "(task prompt does not reference {DOCUMENT_IMAGE})",
                    extra={"page_count": num_pages},
                )

            # Build the in-loop schema validator (None unless validation enabled).
            # Used only on the single-agent path: per-batch validation would
            # falsely fail minItems before the batches are merged, so batch
            # output is validated once after merge below.
            schema_validator = self._build_schema_validator()

            # Use concurrent SHARDED extraction if configured and enough pages.
            # Each shard's prompt contains only its pages' text/images (built by
            # _build_shard_payloads), so no agent loads the whole document —
            # this bounds the context window in addition to parallelizing.
            num_batches = self.config.extraction.agentic.max_concurrent_batches
            shard_payloads: list[dict[str, Any]] = []
            if (
                num_batches > 1
                and num_pages > 1
                and len(self._page_texts) > 1
                and not existing_data_model  # Don't use concurrent mode for resume
                and not checkpoint_buffer
            ):
                shard_payloads = self._build_shard_payloads(
                    prompt_template=prompt_template,
                    send_images=send_images,
                    max_shards=num_batches,
                )

            if shard_payloads:
                import asyncio as _asyncio

                logger.info(
                    f"Using sharded concurrent extraction: {len(shard_payloads)} "
                    f"shard(s), parallelism {num_batches}, for {num_pages} pages"
                )
                from idp_common.extraction.runtime import select_runtime

                runtime = select_runtime(self.config, num_batches)
                structured_data, response_with_metering = _asyncio.run(
                    concurrent_structured_output_async(
                        model_id=model_id,
                        data_format=dynamic_model,
                        shard_payloads=shard_payloads,
                        max_parallelism=num_batches,
                        config=self.config,
                        context="Extraction",
                        checkpoint_callback=self._checkpoint_callback,
                        custom_instruction=custom_instruction,
                        section_id=(
                            f"{section_info.class_label}_"
                            f"{section_info.start_page}_{section_info.end_page}"
                        ),
                        persistence=self._shard_persistence,
                        runtime=runtime,
                        assess_runner=self._build_assess_runner(section_info),
                    )
                )
            else:
                structured_data, response_with_metering = structured_output(
                    model_id=model_id,
                    data_format=dynamic_model,
                    prompt=message_prompt,
                    existing_data=existing_data_model,
                    page_images=agentic_images,
                    config=self.config,
                    context="Extraction",
                    checkpoint_callback=self._checkpoint_callback,
                    checkpoint_buffer_data=checkpoint_buffer,
                    custom_instruction=custom_instruction,
                    schema_validator=schema_validator,
                    emit_field_assessment=self._integrated_assessment_enabled(),
                )

            extracted_fields = structured_data.model_dump(mode="json")
            metering = response_with_metering["metering"]
            parsing_succeeded = True

            # Full JSON-Schema validation of the final result, with optional
            # bounded escalation to a stronger model. No-op unless
            # extraction.agentic.validation.enabled. Updates extracted_fields,
            # may flip parsing_succeeded (fail_action="reject"), and records the
            # outcome under metadata["validation"].
            (
                extracted_fields,
                structured_data,
                validation_metadata,
                escalation_metering,
                parsing_succeeded,
            ) = self._validate_and_maybe_escalate(
                extracted_fields=extracted_fields,
                structured_data=structured_data,
                data_model=dynamic_model,
                model_id=model_id,
                message_prompt=message_prompt,
                agentic_images=agentic_images,
                custom_instruction=custom_instruction,
                section_info=section_info,
                parsing_succeeded=parsing_succeeded,
            )
            if validation_metadata is not None:
                self._pending_validation_metadata = validation_metadata
            if escalation_metering:
                from idp_common.extraction.agentic_idp import _accumulate_metering

                _accumulate_metering(metering, escalation_metering)

            # Check extraction completeness (warns if schema constraints not met)
            self._check_extraction_completeness(
                extracted_data=structured_data,
                data_model=dynamic_model,
                section_label=section_info.class_label,
            )

            # In-shard assessment for the NON-sharded single-agent agentic path
            # (sharding did not engage). Equivalent to a single full-section
            # shard: assess the final (post-escalation) values over all pages,
            # then let _save_results ground + emit explainability_info. Mirrors
            # the sharded path's _merged_assessment metering marker.
            if not shard_payloads and self._inshard_assessment_enabled():
                self._assess_single_agent(
                    extracted_fields=extracted_fields,
                    section_info=section_info,
                    metering=metering,
                )
            elif not shard_payloads and self._integrated_assessment_enabled():
                # Integrated mode, single-agent: the agent already emitted
                # confidence/bbox inline. Lift it from metering into the
                # _merged_assessment slot so _save_results grounds + emits it.
                inline = metering.pop("_integrated_field_assessment", None)
                if inline:
                    metering["_merged_assessment"] = inline
                    metering["_merged_assessment_alerts"] = []
        else:
            # Standard Bedrock invocation
            response_with_metering = bedrock.invoke_model(
                model_id=model_id,
                system_prompt=system_prompt,
                content=content,
                temperature=temperature,
                top_k=top_k,
                top_p=top_p,
                max_tokens=max_tokens,
                context="Extraction",
                model_lambda_hook_arn=self.config.extraction.model_lambda_hook_arn,
                reasoning_effort=reasoning_effort,
            )

            extracted_text = bedrock.extract_text_from_response(
                dict(response_with_metering)
            )
            metering = response_with_metering["metering"]

            # Parse response into JSON
            extracted_fields = {}
            parsing_succeeded = True
            output_truncated = False
            output_repaired = False
            repair_method = None

            try:
                extracted_fields = json.loads(extract_json_from_text(extracted_text))

                # Handle case where LLM returns a single-element array instead of dict
                # This happens when models mistakenly wrap the extraction in an array
                if isinstance(extracted_fields, list):
                    if len(extracted_fields) == 1:
                        logger.warning(
                            "LLM returned single-element array instead of object, unwrapping",
                            extra={"original_type": "list", "element_count": 1},
                        )
                        extracted_fields = extracted_fields[0]
                    elif len(extracted_fields) == 0:
                        logger.error(
                            "LLM returned empty array when single object expected",
                            extra={"element_count": 0},
                        )
                        extracted_fields = {
                            "error": "Received empty array instead of single object",
                        }
                        parsing_succeeded = False
                    else:  # len > 1
                        logger.error(
                            "LLM returned multi-element array when single object expected",
                            extra={"element_count": len(extracted_fields)},
                        )
                        extracted_fields = {
                            "error": f"Received array with {len(extracted_fields)} elements instead of single object",
                            "raw_array": extracted_fields,
                        }
                        parsing_succeeded = False

            except Exception as e:
                logger.warning(
                    f"Error parsing LLM output - attempting JSON repair: {e}"
                )

                # Attempt to repair truncated JSON
                repaired_data, repair_info = repair_truncated_json(extracted_text)
                output_truncated = repair_info.get("was_truncated", False)

                if repaired_data:
                    # Repair succeeded
                    extracted_fields = repaired_data

                    # Handle case where repaired data is also a single-element array
                    if isinstance(extracted_fields, list):
                        if len(extracted_fields) == 1:
                            logger.warning(
                                "Repaired JSON is single-element array, unwrapping",
                                extra={"original_type": "list", "element_count": 1},
                            )
                            extracted_fields = extracted_fields[0]
                        elif len(extracted_fields) == 0:
                            logger.error(
                                "Repaired JSON is empty array when single object expected",
                                extra={"element_count": 0},
                            )
                            extracted_fields = {
                                "error": "Repaired empty array instead of single object",
                            }
                            parsing_succeeded = False
                        else:  # len > 1
                            logger.error(
                                "Repaired JSON is multi-element array when single object expected",
                                extra={"element_count": len(extracted_fields)},
                            )
                            extracted_fields = {
                                "error": f"Repaired array with {len(extracted_fields)} elements instead of single object",
                                "raw_array": extracted_fields,
                            }
                            parsing_succeeded = False

                    output_repaired = True
                    repair_method = repair_info.get("repair_method")
                    if parsing_succeeded:
                        logger.info(
                            f"JSON repair successful using '{repair_method}': "
                            f"recovered {repair_info.get('fields_recovered', 0)} fields"
                        )
                else:
                    # Repair failed - store raw output
                    logger.error(
                        f"JSON repair failed: {repair_info.get('error', 'unknown error')}. "
                        f"Raw output preview: {extracted_text[:500]}..."
                    )
                    extracted_fields = {"raw_output": extracted_text}
                    parsing_succeeded = False

        total_duration = time.time() - request_start_time
        logger.info(f"Time taken for extraction: {total_duration:.2f} seconds")

        return ExtractionResult(
            extracted_fields=extracted_fields,
            metering=metering,
            parsing_succeeded=parsing_succeeded,
            total_duration=total_duration,
            output_truncated=output_truncated,
            output_repaired=output_repaired,
            repair_method=repair_method,
            schema_analysis=schema_analysis,
            ocr_analysis=ocr_analysis,
        )

    def _apply_missing_field_handling(
        self,
        extracted_fields: dict[str, Any],
        class_schema: dict[str, Any],
        section_info: SectionInfo,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Mark or remove fields whose source pages were not present.

        Returns the (possibly mutated) extracted_fields and a report listing
        the fields treated as MISSING. When the feature is disabled, the
        config doesn't declare page-types, or no top-level property has
        ``x-aws-idp-source-page-types``, the input is returned unchanged
        with an empty report.
        """
        cfg = self.config.extraction.missing_field_handling
        presence = section_info.page_type_presence
        if not cfg.enabled or presence is None or not presence.declared:
            return extracted_fields, []

        properties = class_schema.get(SCHEMA_PROPERTIES) or {}
        if not properties:
            return extracted_fields, []

        present = presence.present_page_types
        report: list[dict[str, Any]] = []
        # Operate on a copy so we don't mutate the agent's result in place.
        fields_out = dict(extracted_fields)

        for prop_name, prop_schema in properties.items():
            if not isinstance(prop_schema, dict):
                continue
            declared_pages = prop_schema.get(X_AWS_IDP_SOURCE_PAGE_TYPES)
            if not declared_pages:
                continue
            if not isinstance(declared_pages, list):
                logger.warning(
                    "Property %s declares %s as %s; expected list — ignoring",
                    prop_name,
                    X_AWS_IDP_SOURCE_PAGE_TYPES,
                    type(declared_pages).__name__,
                )
                continue
            if any(p in present for p in declared_pages):
                # At least one source page-type is present → field is BLANK
                # if empty, not MISSING. Leave it alone.
                continue
            report.append(
                {
                    "field": prop_name,
                    "reason": "page types not present",
                    "expected_page_types": list(declared_pages),
                }
            )
            if cfg.representation == "omit":
                fields_out.pop(prop_name, None)
            else:  # null_with_metadata
                fields_out[prop_name] = None

        return fields_out, report

    @staticmethod
    def _normalize_table_parsing_stats(stats: dict[str, Any]) -> dict[str, Any]:
        """Sanitize merged table-parsing stats for display in metadata.

        Drops the internal ``_rate_weight`` accumulator and defensively clamps
        the quality metrics to their valid ranges (rate 0-1, confidence 0-100) so
        a stats-merge regression can never again surface impossible values like
        a 500% parse-success rate or 496% confidence in the Processing Report.
        """
        clean = {k: v for k, v in stats.items() if k != "_rate_weight"}
        rate = clean.get("parse_success_rate")
        if isinstance(rate, (int, float)):
            clean["parse_success_rate"] = max(0.0, min(1.0, float(rate)))
        conf = clean.get("avg_confidence")
        if isinstance(conf, (int, float)):
            clean["avg_confidence"] = max(0.0, min(100.0, float(conf)))
        return clean

    def _attach_explainability(
        self,
        *,
        output_metadata: dict[str, Any],
        merged_assessment: dict[str, Any],
        merged_assessment_alerts: list[dict[str, Any]],
        extracted_fields: dict[str, Any],
        document: Document,
        section: Any,
        section_info: SectionInfo,
    ) -> None:
        """Ground the merged in-shard assessment and stage it for output.

        Grounds field geometry in real OCR data over the whole section (one pass,
        same as the standalone Assessment step), stashes the grounded assessment
        in ``self._grounded_assessment`` for ``_save_results`` to emit as
        ``explainability_info``, sets ``section.confidence_threshold_alerts``, and
        records lightweight metadata mirroring the standalone path. Best-effort:
        grounding never fails extraction.
        """
        # AUTHORITATIVE alignment point: reconcile the fully-merged assessment
        # against the fully-merged, final extracted_fields here — AFTER shard
        # merge (which drops phantom rows from data) and any escalation. Doing it
        # only per-shard is not enough: the data list is phantom-filtered on
        # merge, so per-shard counts can drift from the final data. This single
        # post-merge reconcile guarantees explainability_info[field][i] lines up
        # with inference_result[field][i] for every list field.
        merged_assessment = self._reconcile_assessment_to_data(
            merged_assessment, extracted_fields
        )

        grounded = merged_assessment
        geometry_mode = self.config.extraction.geometry.mode
        if geometry_mode not in ("llm", "off"):
            try:
                from idp_common.assessment.ocr_grounding import (
                    ground_assessment_geometry,
                    load_page_ocr_data,
                )

                page_data_by_page = load_page_ocr_data(
                    document.pages, section_info.sorted_page_ids
                )
                if page_data_by_page:
                    grounded = ground_assessment_geometry(
                        merged_assessment,
                        extracted_fields,
                        page_data_by_page,
                        geometry_mode,
                        self._class_schema,
                    )
            except Exception as e:  # noqa: BLE001 - grounding is advisory
                logger.warning(
                    "OCR geometry grounding failed for in-shard assessment "
                    "(keeping existing boxes): %s",
                    e,
                )

        self._grounded_assessment = grounded
        section.confidence_threshold_alerts = merged_assessment_alerts
        output_metadata["assessment_integrated_in_extraction"] = True
        output_metadata["assessment_alert_count"] = len(merged_assessment_alerts)

    def _save_results(
        self,
        document: Document,
        section: Any,
        result: ExtractionResult,
        section_info: SectionInfo,
        section_id: str,
        t0: float,
    ) -> None:
        """
        Save extraction results to S3 and update document.

        Args:
            document: Document being processed
            section: Section being processed
            result: Extraction result
            section_info: Section metadata
            section_id: Section ID
            t0: Start time
        """
        # Determine extraction method
        extraction_method = (
            "agentic" if self.config.extraction.agentic.enabled else "traditional"
        )

        # Check if table parsing tool was used (extract from metering before building metadata)
        tool_used = False
        table_stats = None
        shard_conflicts = None
        merged_assessment = None
        merged_assessment_alerts = None
        if extraction_method == "agentic" and result.metering:
            table_stats = result.metering.pop("_table_parsing_stats", None)
            tool_used = table_stats is not None
            if table_stats:
                table_stats = self._normalize_table_parsing_stats(table_stats)
            # Scalar conflicts surfaced by sharded concurrent extraction.
            shard_conflicts = result.metering.pop("_shard_scalar_conflicts", None)
            # Per-field confidence/bbox assessment collated from in-shard
            # assessment (integrated-assessment feature). Popped here so it does
            # not leak into metering; emitted as explainability_info below.
            merged_assessment = result.metering.pop("_merged_assessment", None)
            merged_assessment_alerts = result.metering.pop(
                "_merged_assessment_alerts", None
            )

        # Build base metadata
        metadata: dict[str, Any] = {
            "parsing_succeeded": result.parsing_succeeded,
            "extraction_time_seconds": result.total_duration,
            "extraction_method": extraction_method,
        }

        # Audit: which model actually ran this section, and whether it came from
        # a per-class override vs the global extraction model.
        if self._pending_extraction_model is not None:
            metadata["extraction_model"] = self._pending_extraction_model
            metadata["extraction_model_overridden"] = (
                self._class_schema.get(X_AWS_IDP_EXTRACTION_MODEL) is not None
            )

        # Add pre-flight analysis results (if agentic)
        if extraction_method == "agentic":
            if result.schema_analysis:
                metadata["schema_analysis"] = result.schema_analysis
            if result.ocr_analysis:
                metadata["ocr_analysis"] = result.ocr_analysis

            # Track tool usage decision
            tool_expected = False
            if result.schema_analysis or result.ocr_analysis:
                tool_expected = (
                    result.schema_analysis.get("tool_usage_recommended", False)
                    if result.schema_analysis
                    else False
                ) or (
                    result.ocr_analysis.get("tool_usage_recommended", False)
                    if result.ocr_analysis
                    else False
                )

                metadata["tool_usage_decision"] = {
                    "expected": tool_expected,
                    "actual": tool_used,
                    "mismatch": tool_expected != tool_used,
                    "explanation": self._explain_tool_usage_decision(
                        expected=tool_expected,
                        actual=tool_used,
                        schema_analysis=result.schema_analysis,
                        ocr_analysis=result.ocr_analysis,
                    ),
                }

            # Validate completeness
            if result.schema_analysis or result.ocr_analysis:
                metadata["completeness_check"] = self._check_completeness_detailed(
                    extracted_fields=result.extracted_fields,
                    schema=self._class_schema,
                    tool_used=tool_used,
                )

            # Population heuristic: flag suspiciously sparse extractions (e.g.
            # nested fields silently returning null). Advisory only.
            metadata["population_check"] = self._check_population_completeness(
                extracted_fields=result.extracted_fields,
                schema=self._class_schema,
            )

        # Add table parsing stats if tool was used
        if tool_used and table_stats:
            metadata["table_parsing_tool_used"] = True
            metadata["table_parsing_stats"] = table_stats
        elif (
            extraction_method == "agentic"
            and self.config.extraction.agentic.table_parsing.enabled
        ):
            metadata["table_parsing_tool_used"] = False

        # Add truncation/repair metadata when relevant
        if result.output_truncated:
            metadata["output_truncated"] = True
        if result.output_repaired:
            metadata["output_repaired"] = True
            metadata["repair_method"] = result.repair_method

        # Add full-schema validation outcome (set by _validate_and_maybe_escalate
        # when extraction.agentic.validation.enabled).
        if self._pending_validation_metadata is not None:
            metadata["validation"] = self._pending_validation_metadata

        # Record scalar-field conflicts detected when merging sharded concurrent
        # extraction (two shards disagreed on a scalar; first value kept).
        if shard_conflicts:
            metadata["shard_scalar_conflicts"] = shard_conflicts

        # Apply BLANK vs MISSING field handling (no-op unless configured + declared).
        fields_for_output, missing_fields_report = self._apply_missing_field_handling(
            result.extracted_fields,
            self._class_schema,
            section_info,
        )

        # Generate user-friendly processing report
        processing_report = self._generate_processing_report(metadata)
        logger.info(f"Processing Report:\n{processing_report}")

        # In-shard assessment (integrated-assessment feature): ground the merged
        # per-field assessment in real OCR geometry over the WHOLE section (one
        # pass, identical to the standalone Assessment step) and emit it as
        # explainability_info — the same output contract the standalone path
        # produces, so all downstream consumers (HITL, UI, evaluation) are
        # unchanged. No-op when in-shard assessment did not run.
        if merged_assessment:
            # Align against fields_for_output (what becomes inference_result), so
            # explainability_info[field][i] matches inference_result[field][i]
            # exactly — including after missing-field handling.
            self._attach_explainability(
                output_metadata=metadata,
                merged_assessment=merged_assessment,
                merged_assessment_alerts=merged_assessment_alerts or [],
                extracted_fields=fields_for_output,
                document=document,
                section=section,
                section_info=section_info,
            )

        # Write to S3 with processing report
        output: dict[str, Any] = {
            "document_class": {"type": section_info.class_label},
            "split_document": {"page_indices": section_info.page_indices},
            "inference_result": fields_for_output,
            "metadata": metadata,
            "processing_report": processing_report,
        }
        if merged_assessment is not None:
            output["explainability_info"] = [self._grounded_assessment]
        # Surface page-type resolution and the missing-field report when the
        # feature is in use, so downstream consumers can act on the signal.
        presence = section_info.page_type_presence
        if presence is not None and presence.declared:
            output["page_type_resolution"] = presence.to_output_dict()
        if missing_fields_report:
            output["missing_fields_report"] = missing_fields_report
            if self.config.extraction.missing_field_handling.representation == (
                "null_with_metadata"
            ):
                output["missing_fields"] = [
                    entry["field"] for entry in missing_fields_report
                ]
        s3.write_content(
            output,
            section_info.output_bucket,
            section_info.output_key,
            content_type="application/json",
        )

        # Update section and document
        section.extraction_result_uri = section_info.output_uri
        document.metering = utils.merge_metering_data(
            document.metering, result.metering or {}
        )

        t3 = time.time()
        logger.info(
            f"Total extraction time for section {section_id}: {t3 - t0:.2f} seconds"
        )

    def process_document_section(
        self,
        document: Document,
        section_id: str,
        checkpoint_data: dict[str, Any] | None = None,
    ) -> Document:
        """
        Process a single section from a Document object.

        Args:
            document: Document object containing section to process
            section_id: ID of the section to process
            checkpoint_data: Optional partial extraction data from a previous
                timed-out invocation.  When provided the agentic agent will
                resume from this state instead of starting from scratch.

        Returns:
            Document: Updated Document object with extraction results for the section
        """
        # Reset state
        self._reset_context()

        # Validate and get section
        section = self._validate_and_find_section(document, section_id)
        if not section:
            return document

        # Short-circuit: skip sections whose class is marked
        # x-aws-idp-exclude-from-processing=true (e.g., static instruction
        # pages). A stub result.json is written so reporting / UI can show
        # a meaningful message.
        from idp_common.section_exclusion import (
            is_section_excluded,
            write_skipped_stub,
        )

        if is_section_excluded(section):
            output_bucket = document.output_bucket
            output_key = (
                f"{document.input_key}/sections/{section.section_id}/result.json"
                if document.input_key
                else None
            )
            stub_uri = write_skipped_stub(
                document,
                section,
                stage="extraction",
                output_bucket=output_bucket,
                output_key=output_key,
            )
            if stub_uri:
                section.extraction_result_uri = stub_uri
            logger.info(
                "Extraction skipped for excluded section %s (class=%s, reason=%s)",
                section.section_id,
                section.classification,
                section.exclusion_reason or "excluded",
            )
            return document

        # Prepare section metadata
        try:
            section_info = self._prepare_section_info(document, section)
        except ValueError:
            return document

        try:
            t0 = time.time()

            prepared = self._prepare_section_context(document, section, section_info)
            if prepared is None:
                # Empty schema — already handled (stub written).
                return self._handle_empty_schema(
                    document, section, section_info, section_id, t0
                )
            content, system_prompt = prepared

            # Invoke model (pass checkpoint_data for agentic resume-on-timeout)
            result = self._invoke_extraction_model(
                content, system_prompt, section_info, checkpoint_data=checkpoint_data
            )

            # Save results
            self._save_results(document, section, result, section_info, section_id, t0)

        except Exception as e:
            error_msg = f"Error processing section {section_id}: {str(e)}"
            logger.error(error_msg)
            document.errors.append(error_msg)
            raise

        return document

    def _prepare_section_context(
        self,
        document: Document,
        section: Section,
        section_info: SectionInfo,
    ) -> tuple[list[dict[str, Any]], str] | None:
        """Load page text/images, resolve page types, init context, build prompt.

        Populates the per-section instance state (``self._page_texts``,
        ``self._document_text``, ``self._page_images``, ``self._class_schema`` …)
        and returns ``(content, system_prompt)``. Returns ``None`` when the class
        schema is empty (caller writes the skip stub). Extracted from
        ``process_document_section`` so the SFN shard/merge entry points can reuse
        the identical preparation without duplicating it (single source of truth).
        """
        # Load per-page text first so the page-type resolver and the
        # prompt-formatter can both consume it without re-reading S3.
        page_id_to_text = self._load_page_texts(document, section_info.sorted_page_ids)
        class_schema_for_resolver = self._get_class_schema(section_info.class_label)
        section_info.page_type_presence = resolve_page_types(
            class_schema_for_resolver, page_id_to_text
        )
        if section_info.page_type_presence.declared:
            logger.info(
                "Page-type resolution for section %s: present=%s missing=%s",
                section.section_id,
                sorted(section_info.page_type_presence.present_page_types),
                sorted(section_info.page_type_presence.missing_page_types),
            )
        document_text = self._format_document_text(
            section_info.sorted_page_ids,
            page_id_to_text,
            section_info.page_type_presence,
        )
        page_images = self._load_document_images(document, section_info.sorted_page_ids)
        # Stash the per-page OCR text (in section page order) so the agentic
        # path can shard the input by page range when concurrent batches are
        # configured. Pages missing from page_id_to_text contribute "".
        self._page_texts = [
            page_id_to_text.get(pid, "") for pid in section_info.sorted_page_ids
        ]

        # Initialize extraction context
        class_schema, attribute_descriptions = self._initialize_extraction_context(
            section_info.class_label,
            document_text,
            page_images,
            section_info.sorted_page_ids,
            document,
        )

        # Handle empty schema case (signal to caller).
        if (
            not class_schema.get(SCHEMA_PROPERTIES)
            or not attribute_descriptions.strip()
        ):
            return None

        # Build prompt content
        content, system_prompt = self._build_extraction_content(document, page_images)

        # Load OCR confidence data for table parsing tool (if enabled)
        # Confidence data is only available from Textract OCR backend.
        # For Bedrock OCR or other backends, skip loading — the tool
        # handles missing confidence gracefully (confidence_available=false).
        if (
            AGENTIC_AVAILABLE
            and self.config.extraction.agentic.enabled
            and self.config.extraction.agentic.table_parsing.enabled
            and self.config.extraction.agentic.table_parsing.use_confidence_data
            and self.config.ocr.backend == "textract"
        ):
            confidence_data_by_page = self._load_confidence_data(
                document, section_info.sorted_page_ids
            )
            set_confidence_data(confidence_data_by_page)
            logger.info(
                f"Loaded OCR confidence data for table parsing tool: "
                f"{len(confidence_data_by_page)} pages"
            )
        elif AGENTIC_AVAILABLE and self.config.extraction.agentic.enabled:
            set_confidence_data(None)
            if (
                self.config.extraction.agentic.table_parsing.enabled
                and self.config.ocr.backend != "textract"
            ):
                logger.info(
                    "Table parsing tool enabled without confidence data "
                    f"(OCR backend: {self.config.ocr.backend})"
                )

        return content, system_prompt

    def _inshard_assessment_enabled(self) -> bool:
        """Whether the SEPARATE-mode in-shard assessment pass should run.

        True only when assessment is enabled AND the integration mode keeps a
        *separate* assessment inference (the second-turn per-shard path). The
        ``integrated`` (single-prompt) mode does NOT use this — the extraction
        inference itself emits confidence/bbox via ``_integrated_assessment_enabled``.
        Either way the standalone AssessmentStep is bypassed for the agentic path.
        """
        if not self.config.extraction.confidence.enabled:
            return False
        return self.config.extraction.confidence.mode == "separate"

    def _integrated_assessment_enabled(self) -> bool:
        """Whether the agent should emit confidence/bbox INLINE (single inference).

        True when confidence is enabled AND ``confidence.mode == "integrated"``.
        In this mode the extraction agent calls ``provide_field_assessment`` in its
        own session (document already in cached context — no second Bedrock pass),
        and the result rides the same collation/grounding/emit path as separate mode.
        """
        if not self.config.extraction.confidence.enabled:
            return False
        return self.config.extraction.confidence.mode == "integrated"

    @staticmethod
    def _reconcile_assessment_to_data(
        assessment: dict[str, Any], extraction_results: dict[str, Any]
    ) -> dict[str, Any]:
        """Force per-field assessment to index-align with the extracted data.

        The assessment LLM frequently emits a *different* number of list-item
        assessments than the data has rows (a 120-row table may come back with
        only 44 row assessments). Downstream consumers (HITL, UI) index
        ``explainability_info[0][field][i]`` against ``inference_result[field][i]``,
        so a length mismatch silently misattributes confidence to the wrong row —
        and in the sharded path the drift compounds across shards on merge.

        For every list-valued data field this truncates an over-long assessment
        list and pads a too-short one so ``len(assessment[field]) ==
        len(data[field])`` exactly — including the case where the model OMITTED
        the list field entirely (common for large tables: the shard extracted N
        rows but the assessment response left the field out, so without this every
        such row would be unassessed AND ungroundable).

        Crucially, each padded row is a **per-sub-field placeholder mirroring the
        data row's structure** — a ``{"confidence": null, ...}`` leaf for each
        sub-field the data row populated (e.g. ``date``, ``description``,
        ``amount``). This gives OCR geometry grounding a real value to match per
        sub-field, so an un-assessed row still gets a correct bounding box from its
        extracted values; only the LLM ``confidence`` is null. A scalar/non-dict
        row element falls back to a single neutral leaf.

        Scalar/group fields are left untouched. Mutates and returns ``assessment``.
        """
        if not isinstance(assessment, dict):
            return assessment

        def _row_placeholder(data_row: Any) -> dict[str, Any]:
            reason = (
                "Not individually assessed (assessment returned fewer items "
                "than were extracted)."
            )
            # Mirror the data row's sub-fields so grounding can attach a box per
            # populated sub-field from its actual value.
            if isinstance(data_row, dict):
                leaves = {
                    sub: {"confidence": None, "confidence_reason": reason}
                    for sub, sv in data_row.items()
                    if sv is not None and not isinstance(sv, (dict, list))
                }
                if leaves:
                    return leaves
            # Scalar row element (or all-null/nested row): single neutral leaf.
            return {"confidence": None, "confidence_reason": reason}

        def _expand_row_to_per_column(row_assess: Any, data_row: Any) -> Any:
            """Normalize a per-ROW confidence into per-COLUMN leaves.

            Some models (esp. integrated mode) emit ONE ``{"confidence", ...}`` object
            for an entire list row. Downstream (HITL, UI, grounding) index confidence
            per sub-field, so when the data row is a dict but the assessment row is a
            single confidence leaf, fan that one score out across the row's populated
            scalar columns (preserving the model's confidence/reason on each). Rows
            that already carry per-column leaves, or scalar row elements, pass through.
            """
            if (
                isinstance(row_assess, dict)
                and "confidence" in row_assess
                and isinstance(data_row, dict)
            ):
                leaf = {
                    "confidence": row_assess.get("confidence"),
                    "confidence_reason": row_assess.get("confidence_reason"),
                }
                cols = {
                    sub: dict(leaf)
                    for sub, sv in data_row.items()
                    if sv is not None and not isinstance(sv, (dict, list))
                }
                if cols:
                    return cols
            return row_assess

        for field, data_val in extraction_results.items():
            if not isinstance(data_val, list):
                continue
            target = len(data_val)
            assessed = assessment.get(field)
            assessed = assessed if isinstance(assessed, list) else []
            if len(assessed) > target:
                assessed = assessed[:target]
            elif len(assessed) < target:
                assessed = assessed + [
                    _row_placeholder(data_val[i]) for i in range(len(assessed), target)
                ]
            # Normalize any per-row scalar confidence to per-column leaves so every
            # list-item field gets its own confidence + geometry downstream.
            assessment[field] = [
                _expand_row_to_per_column(assessed[i], data_val[i])
                for i in range(target)
            ]
        return assessment

    def _assess_results_batched(
        self,
        assessment_service: Any,
        *,
        class_label: str,
        extraction_results: dict[str, Any],
        document_text: str,
        page_images: list[bytes],
    ) -> dict[str, Any]:
        """Assess one scope, batching large list fields across multiple inferences.

        A single assessment call over a large list (e.g. 75 transaction rows) is
        unreliable — the model under-enumerates or omits the list, leaving rows
        unassessed. When the largest list field exceeds
        ``assessment.inshard_list_batch_size``, the list is sliced into batches; each
        batch is assessed with the SAME scalars/context (so scalar assessments and
        the document context are preserved) but only that batch's rows, and the
        per-row assessments are concatenated in order. Scalar/group assessments come
        from the first batch. Returns ``{"assessment", "alerts", "metering"}``.

        Falls back to a single call when no list field exceeds the batch size.
        """
        from idp_common.extraction.agentic_idp import _accumulate_metering

        batch_size = self.config.extraction.confidence.list_batch_size
        # Identify the single largest list field (the table being assessed).
        list_fields = {
            k: v
            for k, v in extraction_results.items()
            if isinstance(v, list) and len(v) > batch_size
        }

        def _one_call(results: dict[str, Any]) -> Any:
            return assessment_service.assess_results(
                class_label=class_label,
                extraction_results=results,
                document_text=document_text,
                page_images=page_images,
                ocr_text_confidence="",
            )

        if not list_fields:
            core = _one_call(extraction_results)
            return {
                "assessment": self._reconcile_assessment_to_data(
                    core.enhanced_assessment, extraction_results
                ),
                "alerts": core.confidence_threshold_alerts,
                "metering": core.metering,
            }

        # Batch by the largest list field; other (smaller) list fields ride the
        # first batch and are reconciled afterward.
        big_field = max(list_fields, key=lambda k: len(list_fields[k]))
        rows = extraction_results[big_field]
        merged_assessment: dict[str, Any] = {}
        merged_alerts: list[dict[str, Any]] = []
        merged_metering: dict[str, Any] = {}
        big_field_acc: list[Any] = []

        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            # Same scalars/context every batch; only the big list is sliced.
            batch_results = dict(extraction_results)
            batch_results[big_field] = chunk
            core = _one_call(batch_results)
            enhanced = self._reconcile_assessment_to_data(
                core.enhanced_assessment, batch_results
            )
            # Accumulate the big list's per-row assessments in order.
            big_field_acc.extend(
                enhanced.get(big_field, [])
                if isinstance(enhanced.get(big_field), list)
                else []
            )
            _accumulate_metering(merged_metering, core.metering or {})
            merged_alerts.extend(core.confidence_threshold_alerts or [])
            # Scalars/other fields: keep the first batch's assessment.
            if not merged_assessment:
                merged_assessment = enhanced
        merged_assessment[big_field] = big_field_acc
        # Final alignment against the full extraction (pads any residual gap).
        merged_assessment = self._reconcile_assessment_to_data(
            merged_assessment, extraction_results
        )
        return {
            "assessment": merged_assessment,
            "alerts": merged_alerts,
            "metering": merged_metering,
        }

    def _build_assess_runner(self, section_info: SectionInfo) -> "Any | None":
        """Build the per-shard assess_runner closure (or None when disabled).

        The closure reuses ``AssessmentService.assess_results`` over a single
        shard's extracted values + that shard's already-loaded text/images, so
        the in-shard assessment is byte-for-byte the same logic the standalone
        Assessment step runs — just scoped to the shard and with no S3 round
        trip. Returns ``None`` when in-shard assessment is not enabled, leaving
        the default (no-assessment) extraction path completely unchanged.
        """
        if not self._inshard_assessment_enabled():
            return None

        from idp_common.assessment.service import AssessmentService

        assessment_service = AssessmentService(region=self.region, config=self.config)
        class_label = section_info.class_label

        async def _assess_runner(
            *, extracted_fields: dict[str, Any], payload: dict[str, Any]
        ) -> dict[str, Any] | None:
            extraction_results = extracted_fields or {}
            if not extraction_results:
                return None
            document_text = payload.get("assess_document_text", "") or ""
            page_images = payload.get("assess_page_images", []) or []

            # assess_results does Bedrock I/O; run it off the event loop so the
            # concurrent shard scheduler is not blocked.
            import asyncio as _asyncio

            def _run() -> dict[str, Any]:
                # Batch large list fields across multiple inferences so the model
                # reliably enumerates every row (a single call over a big list
                # under-enumerates/omits it). Reconciliation inside keeps the
                # per-row assessment index-aligned with the shard's data.
                return self._assess_results_batched(
                    assessment_service,
                    class_label=class_label,
                    extraction_results=extraction_results,
                    document_text=document_text,
                    page_images=page_images,
                )

            return await _asyncio.to_thread(_run)

        return _assess_runner

    def _assess_single_agent(
        self,
        *,
        extracted_fields: dict[str, Any],
        section_info: SectionInfo,
        metering: dict[str, Any],
    ) -> None:
        """Run assessment over the whole section for the non-sharded agentic path.

        Equivalent to a single full-section shard: builds the assessment over the
        already-loaded section text/images (no S3 re-read) and writes the result
        into ``metering`` under the same ``_merged_assessment`` markers the
        sharded path uses, so ``_save_results`` grounds + emits it identically.
        Best-effort: assessment never fails extraction.
        """
        if not extracted_fields:
            return
        try:
            from idp_common.assessment.service import AssessmentService
            from idp_common.extraction.agentic_idp import _accumulate_metering

            assessment_service = AssessmentService(
                region=self.region, config=self.config
            )
            # Batch large list fields (same as the sharded path) so the model
            # reliably enumerates every row instead of omitting/under-counting it.
            batched = self._assess_results_batched(
                assessment_service,
                class_label=section_info.class_label,
                extraction_results=extracted_fields,
                document_text=self._document_text,
                page_images=self._page_images,
            )
            metering["_merged_assessment"] = batched["assessment"]
            metering["_merged_assessment_alerts"] = batched["alerts"]
            _accumulate_metering(metering, batched["metering"])
        except Exception as e:  # noqa: BLE001 - assessment is advisory
            logger.warning(
                "Single-agent in-shard assessment failed (keeping extraction): %s", e
            )

    def _build_agentic_shard_plan(
        self, section_info: SectionInfo
    ) -> tuple[str, type, list[dict[str, Any]], str | None]:
        """Build the agentic shard plan for the SFN runtime.

        Returns ``(model_id, dynamic_model, shard_payloads, custom_instruction)``
        mirroring the construction in ``_invoke_extraction_model``'s agentic
        branch, but standalone so the per-shard SFN Lambda (and the merge step)
        can each rebuild the identical plan deterministically. Requires
        ``_prepare_section_context`` to have populated the per-section state.
        """
        class_model_override = self._class_schema.get(X_AWS_IDP_EXTRACTION_MODEL)
        model_id = class_model_override or self.config.extraction.model

        dynamic_model = create_pydantic_model_from_json_schema(
            schema=self._class_schema,
            class_label=section_info.class_label,
            clean_schema=False,
        )

        schema_analysis = self._analyze_schema_for_table_requirements(
            self._class_schema
        )
        ocr_analysis = self._analyze_ocr_for_tables(self._document_text)
        custom_instruction = self._build_table_parsing_guidance(
            schema_analysis=schema_analysis, ocr_analysis=ocr_analysis
        )

        prompt_template = self.config.extraction.task_prompt or ""
        send_images = "{DOCUMENT_IMAGE}" in prompt_template
        shard_payloads = self._build_shard_payloads(
            prompt_template=prompt_template,
            send_images=send_images,
            max_shards=self.config.extraction.agentic.max_concurrent_batches,
        )
        return model_id, dynamic_model, shard_payloads, custom_instruction

    def _persist_section_id(self, section_info: SectionInfo) -> str:
        """Deterministic per-section id used for shard persistence keys."""
        return (
            f"{section_info.class_label}_"
            f"{section_info.start_page}_{section_info.end_page}"
        )

    def run_one_section_shard(
        self,
        document: Document,
        section_id: str,
        shard_index: int,
        persistence: Any,
    ) -> dict[str, Any]:
        """Run ONE shard of a section — the nested-SFN Distributed Map body.

        Reuses ``extract_one_shard`` (idempotent skip-if-complete) over the SAME
        shard plan the in-process runtime builds. The shard's full result is
        persisted to S3 via ``persistence``; this returns a small descriptor so
        the Map collects only pointers. This is the SFN counterpart to one
        asyncio task in ``InProcessRuntime`` — same primitive, different scheduler.
        """
        import asyncio as _asyncio

        from idp_common.extraction.agentic_idp import default_shard_runner
        from idp_common.extraction.runtime import extract_one_shard

        self._reset_context()
        section = self._validate_and_find_section(document, section_id)
        if not section:
            raise ValueError(f"Section {section_id} not found")
        section_info = self._prepare_section_info(document, section)
        if self._prepare_section_context(document, section, section_info) is None:
            return {"status": "empty_schema", "shard_index": shard_index}

        model_id, dynamic_model, shard_payloads, custom_instruction = (
            self._build_agentic_shard_plan(section_info)
        )
        if not shard_payloads or shard_index >= len(shard_payloads):
            raise ValueError(
                f"Shard index {shard_index} out of range "
                f"(planned {len(shard_payloads)} shards)"
            )
        payload = shard_payloads[shard_index]

        fields, response = _asyncio.run(
            extract_one_shard(
                shard_index=shard_index,
                total_shards=len(shard_payloads),
                payload=payload,
                model_id=model_id,
                data_format=dynamic_model,
                config=self.config,
                section_id=self._persist_section_id(section_info),
                custom_instruction=custom_instruction,
                persistence=persistence,
                shard_runner=default_shard_runner,
                assess_runner=self._build_assess_runner(section_info),
            )
        )
        return {
            "status": "complete",
            "shard_index": shard_index,
            "page_start": payload["page_start"],
            "page_end": payload["page_end"],
        }

    def plan_section_shards(
        self, document: Document, section_id: str
    ) -> dict[str, Any]:
        """Plan the shards for a section (the SFN runtime's planning step).

        Returns ``{shard_mode, num_shards, shards:[{shard_index,page_start,
        page_end}]}``. ``shard_mode`` is False when sharding does not apply
        (single-pass, in-process runtime, or <=1 shard) — the caller then runs
        the normal whole-section path instead of the Distributed Map.
        """
        self._reset_context()
        section = self._validate_and_find_section(document, section_id)
        if not section:
            raise ValueError(f"Section {section_id} not found")
        section_info = self._prepare_section_info(document, section)

        agentic = self.config.extraction.agentic
        runtime_choice = (getattr(agentic, "runtime", None) or "in_process").lower()
        num_batches = agentic.max_concurrent_batches
        if (
            not agentic.enabled
            or runtime_choice not in ("step_functions", "stepfunctions", "sfn")
            or num_batches <= 1
        ):
            return {"shard_mode": False, "num_shards": 0, "shards": []}

        if self._prepare_section_context(document, section, section_info) is None:
            return {"shard_mode": False, "num_shards": 0, "shards": []}

        _model_id, _dyn, shard_payloads, _ci = self._build_agentic_shard_plan(
            section_info
        )
        if len(shard_payloads) <= 1:
            return {
                "shard_mode": False,
                "num_shards": len(shard_payloads),
                "shards": [],
            }

        shards = [
            {
                "shard_index": i,
                "page_start": p["page_start"],
                "page_end": p["page_end"],
            }
            for i, p in enumerate(shard_payloads)
        ]
        return {
            "shard_mode": True,
            "num_shards": len(shards),
            "shards": shards,
            "persist_section_id": self._persist_section_id(section_info),
        }

    def merge_section_shards(
        self,
        document: Document,
        section_id: str,
        persistence: Any,
    ) -> Document:
        """Merge per-shard results from S3 into the final section result.

        The SFN merge state calls this after the Distributed Map completes. It
        reloads every shard's persisted result, merges them with
        ``merge_shard_dicts`` (page-ordered), runs the same validation/escalation
        + completeness checks as the in-process path, and saves results — so the
        SFN path and in-process path produce identical output.
        """
        from idp_common.extraction.runtime import merge_shard_dicts

        t0 = time.time()
        self._reset_context()
        section = self._validate_and_find_section(document, section_id)
        if not section:
            raise ValueError(f"Section {section_id} not found")
        section_info = self._prepare_section_info(document, section)
        if self._prepare_section_context(document, section, section_info) is None:
            return self._handle_empty_schema(
                document, section, section_info, section_id, t0
            )

        model_id, dynamic_model, shard_payloads, _ci = self._build_agentic_shard_plan(
            section_info
        )
        persist_section_id = self._persist_section_id(section_info)

        # Load each shard's persisted result.
        shard_dicts: list[dict[str, Any]] = []
        missing: list[int] = []
        for i, p in enumerate(shard_payloads):
            cached = persistence.load(
                persist_section_id, p["page_start"], p["page_end"]
            )
            if not cached or cached.get("extracted_fields") is None:
                missing.append(i)
            else:
                shard_dicts.append(cached)
        if missing:
            raise RuntimeError(
                f"Cannot merge section {section_id}: shard(s) {missing} have no "
                "persisted result (Distributed Map should have completed them)."
            )

        merged_dict, merged_metering, conflicts = merge_shard_dicts(
            shard_dicts, dynamic_model
        )
        structured_data = dynamic_model(**merged_dict)
        extracted_fields = structured_data.model_dump(mode="json")
        if conflicts:
            merged_metering["_shard_scalar_conflicts"] = conflicts
        parsing_succeeded = True

        # Same validation/escalation + completeness as the in-process path.
        self._pending_validation_metadata = None
        self._pending_extraction_model = model_id
        message_prompt: Any = ""
        (
            extracted_fields,
            structured_data,
            validation_metadata,
            escalation_metering,
            parsing_succeeded,
        ) = self._validate_and_maybe_escalate(
            extracted_fields=extracted_fields,
            structured_data=structured_data,
            data_model=dynamic_model,
            model_id=model_id,
            message_prompt=message_prompt,
            agentic_images=[],
            custom_instruction=None,
            section_info=section_info,
            parsing_succeeded=parsing_succeeded,
        )
        if validation_metadata is not None:
            self._pending_validation_metadata = validation_metadata
        if escalation_metering:
            from idp_common.extraction.agentic_idp import _accumulate_metering

            _accumulate_metering(merged_metering, escalation_metering)
        self._check_extraction_completeness(
            extracted_data=structured_data,
            data_model=dynamic_model,
            section_label=section_info.class_label,
        )

        result = ExtractionResult(
            extracted_fields=extracted_fields,
            metering=merged_metering,
            parsing_succeeded=parsing_succeeded,
            total_duration=time.time() - t0,
        )
        self._save_results(document, section, result, section_info, section_id, t0)
        return document
