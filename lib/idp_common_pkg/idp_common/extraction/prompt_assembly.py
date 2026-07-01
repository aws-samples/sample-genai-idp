# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Modular confidence/geometry prompt assembly (v0.6).

Rather than shipping one monolithic confidence task-prompt that always asks the
model for bounding boxes — and then *ignoring* those boxes in the default
``ocr_only`` geometry mode (wasted output tokens that measurably starve long-list
enumeration) — the prompt is composed from opt-in **sections**:

    [confidence_core]                      (always)
    [confidence_core] + [geometry_block]   (only when the model must emit boxes:
                                             geometry.mode in {llm, llm_grounded})

The confidence task-prompt stored in config (``extraction.confidence.task_prompt``)
is the bbox-free CORE. When geometry requires LLM boxes, ``GEOMETRY_INSTRUCTIONS``
is spliced in *before* the trailing ``<<CACHEPOINT>>`` / document sections so the
static instruction block stays cache-friendly. In ``ocr_only`` (default) and
``off`` no geometry block is added — geometry comes from OCR value-matching (or not
at all), and the model is never asked for coordinates.

This replaces the reverted dynamic bbox-*stripping* hack: sections are composed,
never regex-stripped.
"""

from __future__ import annotations

# Geometry-localization instructions appended to the confidence core ONLY in the
# LLM-box modes. Kept as a section constant (not per-config) so every class/preset
# gets consistent bbox guidance without duplicating it in each stored prompt.
GEOMETRY_INSTRUCTIONS = """
<spatial-localization-guidelines>
Additionally, for each field provide bounding box coordinates:
- bbox: [x1, y1, x2, y2] coordinates in normalized 0-1000 scale
- page: Page number where the field appears (starting from 1)

Coordinate system:
- Use normalized scale 0-1000 for both x and y axes
- x1, y1 = top-left corner; x2, y2 = bottom-right corner (ensure x2 > x1, y2 > y1)
- Make bounding boxes tight around the actual text content
- If a field spans multiple lines, encompass all relevant text
Include the bbox/page alongside each field's confidence in the JSON you return.
</spatial-localization-guidelines>
"""

# Modes in which the model is asked to emit bounding boxes.
_LLM_BOX_MODES = ("llm", "llm_grounded")

# --- INTEGRATED (single-inference) confidence section -----------------------
# When extraction.confidence.mode == "integrated", the extraction agent emits
# per-field confidence INLINE (via the provide_field_assessment tool) in its own
# inference — no second model pass. These sections are composed ONTO the
# extraction system prompt the same way the separate-mode geometry block is
# composed onto the confidence prompt, so both modes share one assembly module.

# Confidence-only core (geometry comes from OCR — no bbox asked of the model).
INTEGRATED_CONFIDENCE_CORE = """

INTEGRATED CONFIDENCE ASSESSMENT (REQUIRED FINAL STEP):
After the extraction is complete and correct, you MUST call the
provide_field_assessment tool exactly once to record your confidence in each
extracted value. Mirror the extraction structure:
- For each scalar or group field: an object
  {"confidence": <0.0-1.0>, "confidence_reason": "<brief>"}.
- For each list field (e.g. a table): a LIST with ONE assessment object per
  extracted row, in the SAME ORDER as the rows you extracted. Provide an entry
  for EVERY row — do not summarize or skip rows.
Do NOT include bounding boxes — field locations are derived automatically from OCR.
confidence = your calibrated certainty the value matches the source document
(1.0 = certain, lower = ambiguous/illegible/inferred). This is your last action.
"""

# Bbox suffix appended to the integrated core ONLY in the LLM-box geometry modes.
INTEGRATED_CONFIDENCE_BBOX_SUFFIX = """
Additionally, for each assessment object include "bbox": [x1,y1,x2,y2] (normalized
0-1000 scale) and "page": <n> giving the value's location in the document.
"""

# Splice geometry instructions before the first of these markers so the trailing
# dynamic document sections (and cache points) stay after it.
_SPLICE_MARKERS = ("<<CACHEPOINT>>", "<document-image>", "{DOCUMENT_IMAGE}")


def geometry_requires_llm_boxes(geometry_mode: str) -> bool:
    """True when the given geometry mode needs the model to emit bounding boxes."""
    return geometry_mode in _LLM_BOX_MODES


def assemble_confidence_prompt(core_task_prompt: str, geometry_mode: str) -> str:
    """Compose the confidence task-prompt for the active geometry mode.

    - ``ocr_only`` (default) / ``off``: returns the bbox-free core unchanged.
    - ``llm`` / ``llm_grounded``: splices ``GEOMETRY_INSTRUCTIONS`` into the core
      (before the first document/cache-point marker, else appended) so the model
      also emits bounding boxes.

    Idempotent-ish: if the core already contains the geometry block (e.g. a legacy
    prompt that still carries bbox directions), it is returned unchanged to avoid
    duplication.
    """
    if not core_task_prompt or not geometry_requires_llm_boxes(geometry_mode):
        return core_task_prompt
    if "spatial-localization-guidelines" in core_task_prompt:
        # Core already carries geometry directions (legacy prompt) — don't double up.
        return core_task_prompt

    block = GEOMETRY_INSTRUCTIONS.strip("\n")
    for marker in _SPLICE_MARKERS:
        idx = core_task_prompt.find(marker)
        if idx != -1:
            return core_task_prompt[:idx] + block + "\n\n" + core_task_prompt[idx:]
    # No marker found — append at the end.
    return core_task_prompt.rstrip() + "\n\n" + block + "\n"


def build_integrated_confidence_section(geometry_mode: str) -> str:
    """Return the integrated-mode confidence instruction section to append to the
    extraction system prompt.

    The confidence core is always included; the bbox suffix is added only in the
    LLM-box geometry modes (``llm``, ``llm_grounded``), mirroring separate-mode
    geometry composition. Callers append the result to the extraction system
    prompt when ``extraction.confidence.mode == "integrated"``.
    """
    section = INTEGRATED_CONFIDENCE_CORE
    if geometry_requires_llm_boxes(geometry_mode):
        section = section + INTEGRATED_CONFIDENCE_BBOX_SUFFIX
    return section


def assemble_integrated_extraction_prompt(
    extraction_system_prompt: str, geometry_mode: str
) -> str:
    """Compose the integrated confidence section onto an extraction system prompt.

    This is the integrated-mode analogue of ``assemble_confidence_prompt``: the
    extraction agent will emit confidence inline, so the confidence instructions
    are appended to its system prompt (geometry directions included only for the
    LLM-box modes).
    """
    return (extraction_system_prompt or "") + build_integrated_confidence_section(
        geometry_mode
    )
