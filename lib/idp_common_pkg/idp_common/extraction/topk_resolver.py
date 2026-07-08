# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
1S-TopK candidate resolution: single-step extraction + assessment.

When the extraction prompt instructs the LLM to return top-k guesses with
probabilities (G1/P1, G2/P2, G3/P3, G4/P4), this module resolves those into
the standard inference_result + explainability_info format so that the
downstream assessment Lambda auto-skips and the UI displays confidence scores.

Used by the non-agentic (simple mode) integrated confidence path.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Union

from pydantic import BaseModel, create_model, field_validator

logger = logging.getLogger(__name__)

X_AWS_IDP_CONFIDENCE_THRESHOLD = "x-aws-idp-confidence-threshold"
DEFAULT_CONFIDENCE_THRESHOLD = 0.8


class CandidateGuesses(BaseModel):
    """Validated structure for top-k candidate extractions."""

    G1: Optional[Union[str, float, int]] = None
    P1: float
    G2: Optional[Union[str, float, int]] = None
    P2: Optional[float] = 0.0
    G3: Optional[Union[str, float, int]] = None
    P3: Optional[float] = 0.0
    G4: Optional[Union[str, float, int]] = None
    P4: Optional[float] = 0.0

    @field_validator("P1", "P2", "P3", "P4", mode="before")
    @classmethod
    def prob_in_range(cls, v):
        if v is None:
            return 0.0
        v = float(v)
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Probability must be between 0.0 and 1.0, got {v}")
        return v


def build_extraction_model(class_schema: dict[str, Any]):
    """Build a Pydantic model from the class schema to validate TopK LLM output."""
    props = class_schema.get("properties", {})
    defs = class_schema.get("$defs", {})
    fields = {}

    for name, prop in props.items():
        if prop.get("type") == "array":
            item_schema = prop.get("items", {})
            if "$ref" in item_schema:
                def_name = item_schema["$ref"].split("/")[-1]
                item_schema = defs.get(def_name, item_schema)
            item_fields = {
                sub_name: (CandidateGuesses, ...)
                for sub_name in item_schema.get("properties", {})
            }
            ItemModel = create_model(f"{name}Item", **item_fields)
            fields[name] = (list[ItemModel], ...)
        else:
            fields[name] = (CandidateGuesses, ...)

    return create_model("ExtractionResult", **fields)


def is_topk_response(extracted_fields: dict[str, Any]) -> bool:
    """Detect if the LLM response is in TopK candidate format (G1/P1 structure)."""
    for value in extracted_fields.values():
        if isinstance(value, dict) and "G1" in value and "P1" in value:
            return True
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    for sub_val in item.values():
                        if (
                            isinstance(sub_val, dict)
                            and "G1" in sub_val
                            and "P1" in sub_val
                        ):
                            return True
    return False


def resolve_candidates(
    raw_result: dict[str, Any],
    schema: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """
    Resolve top-k candidate guesses into inference_result and explainability_info.

    Handles nested candidates inside array items (e.g., LineItems).

    Supports two LLM output formats for arrays:
      1. Wrapped:  {"LineItems": {"G1": [...], "P1": 1.0, ...}}
      2. Direct:   {"LineItems": [{sub_attr: {G1, P1, ...}, ...}, ...]}

    Returns:
        tuple: (inference_result dict, assessment_data dict, candidates_metadata dict)
    """
    inference_result = {}
    assessment_data = {}
    candidates_metadata = {}
    props = schema.get("properties", {})
    defs = schema.get("$defs", {})

    for attr_name, value in raw_result.items():
        attr_schema = props.get(attr_name, {})

        # Resolve item schema for arrays
        item_schema = {}
        if attr_schema.get("type") == "array":
            item_schema = attr_schema.get("items", {})
            if "$ref" in item_schema:
                def_name = item_schema["$ref"].split("/")[-1]
                item_schema = defs.get(def_name, item_schema)

        # Case 1: Wrapped candidate — {"G1": <value>, "P1": <prob>, ...}
        if isinstance(value, dict) and "G1" in value:
            inner = value.get("G1")
            confidence = _safe_prob(value.get("P1", 0.0))

            if attr_schema.get("type") == "array" and isinstance(inner, list):
                resolved_items, item_assessments = _resolve_list_items(
                    inner, item_schema
                )
                inference_result[attr_name] = resolved_items
                assessment_data[attr_name] = item_assessments
            else:
                v = inner
                if attr_schema.get("type") == "number" and v is not None:
                    try:
                        v = float(v)
                    except (ValueError, TypeError):
                        pass
                inference_result[attr_name] = v
                threshold = _get_threshold(attr_schema)
                assessment_data[attr_name] = {
                    "confidence": confidence,
                    "confidence_threshold": threshold,
                }
            candidates_metadata[attr_name] = value

        # Case 2: Direct array — [{sub_attr: {G1, P1, ...}, ...}, ...]
        elif isinstance(value, list) and attr_schema.get("type") == "array":
            resolved_items, item_assessments = _resolve_list_items(value, item_schema)
            inference_result[attr_name] = resolved_items
            assessment_data[attr_name] = item_assessments
            candidates_metadata[attr_name] = value

        # Case 3: Non-candidate value (pass through)
        else:
            inference_result[attr_name] = value

    return inference_result, assessment_data, candidates_metadata


def _resolve_list_items(
    items_list: list, item_schema: dict[str, Any]
) -> tuple[list[dict], list[dict]]:
    """Resolve candidate dicts within array items."""
    resolved_items = []
    item_assessments = []
    item_props = item_schema.get("properties", {})

    for item in items_list:
        if not isinstance(item, dict):
            resolved_items.append(item)
            item_assessments.append({})
            continue
        resolved_item = {}
        item_assess = {}
        for key, val in item.items():
            sub_schema = item_props.get(key, {})
            if isinstance(val, dict) and "G1" in val:
                v = val.get("G1")
                if sub_schema.get("type") == "number" and v is not None:
                    try:
                        v = float(v)
                    except (ValueError, TypeError):
                        pass
                resolved_item[key] = v
                confidence = _safe_prob(val.get("P1", 0.0))
                threshold = _get_threshold(sub_schema)
                item_assess[key] = {
                    "confidence": confidence,
                    "confidence_threshold": threshold,
                }
            else:
                resolved_item[key] = val
        resolved_items.append(resolved_item)
        item_assessments.append(item_assess)
    return resolved_items, item_assessments


def _safe_prob(v: Any) -> float:
    """Safely convert probability to float in [0, 1]."""
    try:
        f = float(v) if v is not None else 0.0
        return max(0.0, min(1.0, f))
    except (ValueError, TypeError):
        return 0.0


def _get_threshold(schema: dict[str, Any]) -> float:
    """Get confidence threshold from schema or use default."""
    raw = schema.get(X_AWS_IDP_CONFIDENCE_THRESHOLD, DEFAULT_CONFIDENCE_THRESHOLD)
    try:
        return float(raw)
    except (ValueError, TypeError):
        return DEFAULT_CONFIDENCE_THRESHOLD
