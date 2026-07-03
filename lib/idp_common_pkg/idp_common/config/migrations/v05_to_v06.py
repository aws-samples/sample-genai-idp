# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""v0.5 → v0.6 config-shape migration.

v0.6 reframes per-field confidence and geometry as OUTPUTS OF EXTRACTION rather
than a separate stage:

    extraction.assessment_integration       -> extraction.confidence.mode
    assessment.{model,prompts,image,...}     -> extraction.confidence.*
    assessment.inshard_list_batch_size       -> extraction.confidence.list_batch_size
    assessment.granular                      -> DROPPED (granular assessment retired)
    assessment.geometry_mode / legacy flag   -> extraction.geometry.mode  (renamed values)
    assessment.hitl_enabled                  -> hitl.enabled
    assessment.default_confidence_threshold  -> hitl.confidence_threshold

The top-level ``assessment`` block is slimmed to the standalone-step carrier
(``enabled`` + ``postHook``) so the ``postAssessment`` pipeline-hook point and the
step's own enable/bypass keep working until the step is retired.

The transform is a pure ``dict -> dict`` and is IDEMPOTENT: it short-circuits once
a config is stamped ``config_format_version == "0.6"``, so it is safe to apply on
every read (both on the raw custom delta before merge and again after merge inside
``IDPConfig`` validation).
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

TARGET_VERSION = "0.6"

# Geometry mode value renames (v0.5 -> v0.6).
_GEOMETRY_MODE_RENAME = {
    "ocr_only": "ocr_only",
    "llm_with_ocr_grounding": "llm_grounded",
    "llm_only": "llm",
    # Already-v0.6 values pass through untouched.
    "llm_grounded": "llm_grounded",
    "llm": "llm",
    "off": "off",
}

# assessment.* inference keys that move verbatim into extraction.confidence.*
# (NOTE: the confidence TASK prompt does NOT live here — v0.6 moves it to the
# top-level extraction.task_prompt_confidence; see the mapping below.)
_CONFIDENCE_PASSTHROUGH_KEYS = (
    "model",
    "model_lambda_hook_arn",
    "system_prompt",
    "temperature",
    "top_p",
    "top_k",
    "reasoning_effort",
    "max_tokens",
    "image",
)


def _has_legacy_markers(config: Dict[str, Any]) -> bool:
    """True if the config still carries any v0.5-shaped assessment keys.

    This is the robust trigger: the deep-merge path can produce a dict stamped
    ``config_format_version == "0.6"`` (inherited from the full default) that
    still carries a v0.5-shaped ``assessment`` delta from a sparse custom
    override. Relying on the stamp alone would skip such a hybrid; the presence
    of any legacy key forces the migration to run. In v0.6 the entire
    ``assessment`` block is retired, so ANY ``assessment`` key is a legacy marker.
    """
    extraction = config.get("extraction")
    if isinstance(extraction, dict) and "assessment_integration" in extraction:
        return True
    if isinstance(config.get("assessment"), dict):
        return True
    return False


def _needs_migration(config: Dict[str, Any]) -> bool:
    """True when the config is pre-v0.6 or still carries legacy assessment keys."""
    if str(config.get("config_format_version", "")) != TARGET_VERSION:
        return True
    return _has_legacy_markers(config)


def migrate_v05_to_v06(config: Dict[str, Any]) -> Dict[str, Any]:
    """Return a v0.6-shaped copy of ``config``.

    Operates only on keys that are present, so it works on both full configs and
    sparse override deltas without injecting unrelated defaults. Idempotent.
    """
    if not isinstance(config, dict):
        return config
    if not _needs_migration(config):
        return config

    result = copy.deepcopy(config)

    extraction = result.get("extraction")
    extraction = extraction if isinstance(extraction, dict) else {}
    assessment = result.get("assessment")
    assessment = assessment if isinstance(assessment, dict) else {}

    confidence: Dict[str, Any] = {}
    geometry: Dict[str, Any] = {}
    hitl: Dict[str, Any] = {}

    # --- integration mode: extraction.assessment_integration -> confidence.mode ---
    if "assessment_integration" in extraction:
        confidence["mode"] = extraction.pop("assessment_integration")

    # --- confidence enablement + inference knobs (from assessment.*) ---
    # v0.6 folds enable+integration into a single confidence.mode
    # (off|separate|integrated). A legacy assessment.enabled=false (bool or the
    # string "false"/"0"/"no"/"off") becomes 'off' and overrides the integration
    # mode; otherwise assessment_integration (above) supplies the mode.
    _enabled = assessment.get("enabled")
    _enabled_is_false = _enabled is False or (
        isinstance(_enabled, str)
        and _enabled.strip().lower() in ("false", "0", "no", "off")
    )
    if _enabled_is_false:
        confidence["mode"] = "off"
    if "inshard_list_batch_size" in assessment:
        confidence["list_batch_size"] = assessment["inshard_list_batch_size"]
    for key in _CONFIDENCE_PASSTHROUGH_KEYS:
        if key in assessment:
            confidence[key] = assessment[key]

    # --- geometry: geometry_mode (renamed) with legacy ground_geometry_in_ocr ---
    if "geometry_mode" in assessment:
        old = str(assessment["geometry_mode"]).strip().lower()
        geometry["mode"] = _GEOMETRY_MODE_RENAME.get(old, old)
    elif assessment.get("ground_geometry_in_ocr") is False:
        # Legacy explicit opt-out of OCR grounding == "use LLM boxes as-is".
        geometry["mode"] = "llm"

    # --- confidence TASK prompt -> extraction.confidence.task_prompt ---
    # (v0.6: the confidence prompt lives in the confidence sub-config.) Only set it
    # if the target isn't already present (explicit v0.6 wins).
    if assessment.get("task_prompt") and "task_prompt" not in confidence:
        confidence["task_prompt"] = assessment["task_prompt"]

    # --- HITL: hitl_enabled / default_confidence_threshold -> top-level hitl ---
    if "hitl_enabled" in assessment:
        hitl["enabled"] = assessment["hitl_enabled"]
    if "default_confidence_threshold" in assessment:
        hitl["confidence_threshold"] = assessment["default_confidence_threshold"]

    # --- write the new homes (merge into any pre-existing v0.6 keys) ---
    if confidence:
        existing = extraction.get("confidence")
        existing = existing if isinstance(existing, dict) else {}
        # Pre-existing explicit v0.6 keys win over migrated legacy values.
        merged = {**confidence, **existing}
        extraction["confidence"] = merged
    if geometry:
        existing = extraction.get("geometry")
        existing = existing if isinstance(existing, dict) else {}
        extraction["geometry"] = {**geometry, **existing}
    if extraction:
        result["extraction"] = extraction
    if hitl:
        existing = result.get("hitl")
        existing = existing if isinstance(existing, dict) else {}
        result["hitl"] = {**hitl, **existing}

    # --- drop the assessment block entirely (v0.6) ---
    # Confidence inference knobs, geometry, HITL, and enablement all moved to
    # extraction.confidence / extraction.geometry / hitl above. The standalone
    # `assessment` block (including its postAssessment pipeline-hook point) is
    # retired; IDPConfig ignores any leftover on read.
    result.pop("assessment", None)

    if any([confidence, geometry, hitl]):
        logger.info(
            "Migrated config v0.5 -> v0.6 "
            "(assessment.* -> extraction.confidence/geometry + hitl)"
        )

    result["config_format_version"] = TARGET_VERSION
    return result
