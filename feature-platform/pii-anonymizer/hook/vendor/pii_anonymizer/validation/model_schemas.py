# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Model I/O validation with dataclasses"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
import json
import logging
import re

logger = logging.getLogger(__name__)


# INPUT VALIDATION


@dataclass
class InferenceConfig:
    """Inference parameters validated from config.yaml model.inference section."""

    temperature: float = 0
    max_tokens: int = 64000

    @classmethod
    def from_config(cls, config: Dict) -> "InferenceConfig":
        """Parse and validate inference config."""
        inf = config.get("detection", config.get("model", {}).get("inference", {}))
        instance = cls(
            temperature=float(inf.get("temperature", cls.temperature)),
            max_tokens=int(inf.get("max_tokens", cls.max_tokens)),
        )
        logger.info(
            f"Inference config: temperature={instance.temperature}, max_tokens={instance.max_tokens}"
        )
        return instance

    def to_dict(self) -> dict:
        """Convert to Bedrock API format."""
        return {"temperature": self.temperature, "maxTokens": self.max_tokens}


def validate_image_input(
    model_id: str, messages: List[Dict], system: Optional[List[Dict]] = None
):
    """Validate image-based model input before sending to Bedrock"""
    if not model_id:
        raise ValueError("Model ID is required")
    if not messages:
        raise ValueError("Messages are required")
    for msg in messages:
        if "role" not in msg:
            raise ValueError("Message missing 'role' field")
        if "content" not in msg:
            raise ValueError("Message missing 'content' field")


def validate_text_input(model_id: str, prompt: str, system_prompt: str):
    """Validate text-based model input before sending to Bedrock"""
    if not model_id:
        raise ValueError("Model ID is required")
    if not prompt:
        raise ValueError("Prompt is required")
    if not system_prompt:
        raise ValueError("System prompt is required")


# IMAGE-BASED APPROACH
@dataclass
class PIIDetection:
    """Single PII detection from image-based approach"""

    type: str = "UNKNOWN"
    content: str = ""
    confidence: float = 0.0
    bounding_box: Optional[Dict] = None


@dataclass
class ImageBasedOutput:
    """Output from image-based PII detection"""

    pii_detections: List[Dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict) -> "ImageBasedOutput":
        """Parse and validate image-based output"""
        if not isinstance(data, dict):
            logger.warning("Invalid output format, returning empty")
            return cls()

        validated = []
        for item in data.get("pii_detections", []):
            det = PIIDetection(
                type=item.get("type", "UNKNOWN"),
                content=item.get("content", ""),
                confidence=item.get("confidence", 0.0),
                bounding_box=item.get("bounding_box"),
            )
            if det.content:  # Only include if has content
                validated.append(item)

        logger.debug(
            f"Image-based output validation successful: {len(validated)} detections"
        )
        return cls(pii_detections=validated)


# TEXT-BASED APPROACH
@dataclass
class PIIMapping:
    """PII mapping from text-based approach"""

    original: str = ""
    synthetic: str = ""
    type: str = "UNKNOWN"
    confidence: float = 1.0


@dataclass
class TextBasedOutput:
    """Output from text-based PII detection (detect-only, same format as image-based)"""

    pii_detections: List[Dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict) -> "TextBasedOutput":
        """Parse and validate text-based output"""
        if not isinstance(data, dict):
            logger.warning("Invalid output format, returning empty")
            return cls()

        validated = []
        for item in data.get("pii_detections", []):
            if item.get("content") and item.get("type"):
                validated.append(item)

        logger.info(
            f"Text-based output validation successful: {len(validated)} detections"
        )
        return cls(pii_detections=validated)


# COMMON HELPER
def safe_get_response_content(response: Dict) -> str:
    """Safely extract text content from Bedrock response.
    Handles both standard and extended thinking responses."""
    try:
        stop_reason = response.get("stopReason", "unknown")
        if stop_reason == "max_tokens":
            logger.warning(
                "Response truncated: stopReason=max_tokens. Increase max_tokens in config.yaml"
            )
        content_blocks = response["output"]["message"]["content"]
        # With thinking enabled, find the text block (skip thinking blocks)
        for block in content_blocks:
            if block.get("type") == "text" or "text" in block:
                return block["text"]
        # Fallback to first block
        return content_blocks[0]["text"]
    except (KeyError, IndexError, TypeError) as e:
        logger.error(f"Failed to extract response content: {e}")
        raise ValueError(f"Invalid response structure: {e}")


def is_truncated_response(response: Dict) -> bool:
    """True if the model stopped because it hit its output-token limit.

    Converse (Claude/Nova) reports stopReason='max_tokens'; the OpenAI Responses
    translation reports 'incomplete'. A truncated DETECTION response means some
    PII was cut off — callers in the detection path must treat this as a failure
    (never a partial success), since silently dropping the tail leaks PII.
    """
    return (response or {}).get("stopReason", "") in ("max_tokens", "incomplete")


def _try_load_json(candidate: str) -> Optional[Dict[str, Any]]:
    """Lenient JSON parse. Returns a dict on success, else None.

    strict=False allows raw control characters (literal newlines, tabs, codes
    0-31) inside string values — the most common malformation from OpenAI/GPT
    models, which strict json.loads rejects ("Invalid control character").
    """
    try:
        parsed = json.loads(candidate, strict=False)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _strip_code_fence(text: str) -> Optional[str]:
    """Return the contents of a ```json or ``` code fence, if present."""
    for marker in ("```json", "```"):
        if marker in text:
            start = text.find(marker) + len(marker)
            end = text.find("```", start)
            if end == -1:  # opening fence but no close (truncated) — take the rest
                return text[start:].strip()
            return text[start:end].strip()
    return None


def _first_balanced_object(text: str) -> Optional[str]:
    """Return the first complete, brace-balanced ``{...}`` object.

    Scans from the first '{' tracking nesting depth and string state, so it
    correctly ignores braces inside string values and stops at the matching
    close brace. This drops any trailing prose or extra objects after the first
    complete one (e.g. ``{...} thanks!`` or ``{...}{...}``). Returns None if no
    balanced object exists (e.g. truncated output).
    """
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        char = text[i]
        if escape_next:
            escape_next = False
            continue
        if char == "\\":
            escape_next = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if not in_string:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


def _remove_trailing_commas(text: str) -> str:
    """Remove commas that immediately precede a closing ``}`` or ``]``.

    Trailing commas (``{"a": 1,}`` / ``[1, 2,]``) are a common LLM JSON error
    that strict json rejects. Applied only as a fallback after clean parses
    fail, so the rare case of a comma-then-brace inside a string value is not a
    concern in practice.
    """
    return re.sub(r",(\s*[}\]])", r"\1", text)


def _close_truncated(text: str) -> Optional[str]:
    """Return a repaired string for JSON cut off mid-output, or None.

    Walks the text tracking open braces/brackets and string state, then appends
    the characters needed to close everything that was left open. Recovers the
    data that arrived before a max_tokens truncation.
    """
    start = text.find("{")
    if start == -1:
        return None
    text = text[start:]

    stack: List[str] = []
    in_string = False
    escape_next = False

    for char in text:
        if escape_next:
            escape_next = False
            continue
        if char == "\\":
            escape_next = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if not in_string:
            if char == "{":
                stack.append("}")
            elif char == "[":
                stack.append("]")
            elif char == "}" and stack and stack[-1] == "}":
                stack.pop()
            elif char == "]" and stack and stack[-1] == "]":
                stack.pop()

    if not stack and not in_string:
        return None  # nothing was open — not actually truncated

    repaired = text
    if in_string:  # close a dangling open string
        repaired += '"'
    # Drop a dangling trailing comma/colon before closing (e.g. '..."a":' or '...,')
    repaired = re.sub(r"[,:]\s*$", "", repaired.rstrip())
    repaired += "".join(reversed(stack))
    return repaired


def _try_candidate(candidate: str) -> Optional[Dict[str, Any]]:
    """Try to parse a candidate string, applying progressive repairs.

    Order: as-is, whitespace-normalized, trailing-commas-removed, and both
    combined. Returns the first variant that yields a dict, else None.
    """
    normalized = re.sub(r"\s+", " ", candidate)
    for variant in (
        candidate,
        normalized,
        _remove_trailing_commas(candidate),
        _remove_trailing_commas(normalized),
    ):
        result = _try_load_json(variant)
        if result is not None:
            return result
    return None


def extract_json_dict(text: str) -> Optional[Dict[str, Any]]:
    """Extract a JSON object from LLM response text, repairing common defects.

    LLMs are prompted to return JSON but return it as free text, which may
    include a preamble, markdown code fences, raw (unescaped) control characters
    inside strings, trailing commas, trailing prose, or be truncated when the
    token limit is hit. Strict json.loads rejects all of these. In the detection
    path a parse failure silently drops a page's PII, so this tries layered
    repair before giving up.

    Strategies are tried in order, returning the first that yields a dict:
      1. Lenient parse of the whole text (handles raw control characters)
      2. For each candidate substring — code fence, first balanced object,
         outermost braces — try as-is, whitespace-normalized, and with trailing
         commas removed
      3. Repair truncation by closing open braces/brackets

    Note: only JSON *objects* (dicts) are returned; a bare top-level array
    yields None, since the detection schemas require an object wrapper.

    Args:
        text: Raw text content returned by the model.

    Returns:
        Parsed dict, or None if no strategy could recover valid JSON.
    """
    if not text or not text.strip():
        logger.warning("extract_json_dict: empty text")
        return None

    # 1. Try parsing the whole text first. If it is valid JSON, respect its
    #    top-level type: accept an object, but reject a valid-but-non-object
    #    (e.g. a bare array) rather than digging for a sub-object — the
    #    detection schemas require an object wrapper. Extraction/repair below
    #    only runs when the text is NOT valid JSON as-is.
    try:
        whole = json.loads(text, strict=False)
        if isinstance(whole, dict):
            return whole
        logger.warning(
            "extract_json_dict: top-level JSON is %s, not an object",
            type(whole).__name__,
        )
        return None
    except (json.JSONDecodeError, TypeError):
        pass

    # 2. Try each extraction candidate with progressive repairs.
    candidates = []
    fenced = _strip_code_fence(text)
    if fenced:
        candidates.append(fenced)
    balanced = _first_balanced_object(text)
    if balanced:
        candidates.append(balanced)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        result = _try_candidate(candidate)
        if result is not None:
            return result

    # 3. Truncation repair (close open structures), then parse with repairs.
    truncation_target = candidates[-1] if candidates else text
    repaired = _close_truncated(truncation_target)
    if repaired is not None:
        result = _try_candidate(repaired)
        if result is not None:
            logger.info("extract_json_dict: recovered via truncation repair")
            return result

    logger.error("extract_json_dict: all strategies failed; could not parse JSON")
    return None


def validate_synthetic_input(detections: List[Dict]) -> List[Dict]:
    """Validate detections before batch synthetic generation.
    Filters out items with empty content. Assigns 'other' type if type is missing."""
    validated = []
    skipped = 0
    for det in detections:
        if not det.get("content"):
            skipped += 1
            continue
        if not det.get("type"):
            det["type"] = "other"
        validated.append(det)
    if skipped:
        logger.warning(
            f"Skipped {skipped} detections with empty content — nothing to replace"
        )
    logger.info(f"Synthetic input validation: {len(validated)}/{len(detections)} valid")
    return validated


def validate_synthetic_output(
    mapping: Dict[str, str], detections: List[Dict]
) -> Dict[str, str]:
    """Validate synthetic mapping — log items where original has no synthetic."""
    missing = []
    for det in detections:
        original = det.get("content", "")
        if original and original not in mapping:
            missing.append(original)
    if missing:
        logger.warning(f"Synthetic generation missing {len(missing)} items")
    logger.info(
        f"Synthetic output validation: {len(mapping)} mappings, {len(missing)} missing"
    )
    return mapping
