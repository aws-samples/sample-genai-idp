# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Bedrock Data Automation (BDA) as a pure OCR engine.

BDA "standard output" for documents is a managed OCR product: given a page it
returns reading-order markdown (with tables and layout), plus word-level
bounding boxes and confidence. This module adapts that output to the same
Amazon Textract response shape the OCR service already consumes, so the rest of
the pipeline (``_parse_textract_response``, ``_generate_text_confidence_data``,
``_build_page_data``) works unchanged.

Two things about BDA standard output drive the design here (both verified
against the live service):

- **Sync ``InvokeDataAutomation`` is capped at ~10 pages.** The OCR service
  therefore invokes BDA one page at a time (feeding each already-rendered page
  image), which also gives per-page concurrency and retry isolation. So the
  converter here operates on the single-page standard output.
- **BDA line-level confidence is unreliable** (observed ~0.01 for every line),
  while word-level confidence is sound. We reconstruct each line's confidence as
  the mean of its child words' confidence.

BDA confidences are 0-1; Textract confidences are 0-100, so we scale by 100.
BDA bounding boxes are already normalized 0-1 ({left, top, width, height}),
matching Textract's convention.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional, Union

import boto3

logger = logging.getLogger(__name__)

# Well-known name for the auto-managed pure-OCR BDA project.
OCR_PROJECT_NAME = "GENAIIDP-OCR-StandardOutput"


def _bbox_to_geometry(bbox: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Convert a BDA bounding_box (0-1) to a Textract-format Geometry, or None."""
    if not isinstance(bbox, dict):
        return None
    left = bbox.get("left", 0.0)
    top = bbox.get("top", 0.0)
    width = bbox.get("width", 0.0)
    height = bbox.get("height", 0.0)
    return {
        "BoundingBox": {
            "Left": left,
            "Top": top,
            "Width": width,
            "Height": height,
        },
        # Synthesize a rectangular polygon so downstream geometry consumers
        # (UI highlighting) have the same shape Textract provides.
        "Polygon": [
            {"X": left, "Y": top},
            {"X": left + width, "Y": top},
            {"X": left + width, "Y": top + height},
            {"X": left, "Y": top + height},
        ],
    }


def _first_bbox(unit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pull the first bounding_box out of a BDA text_line / text_word.

    BDA sometimes serializes ``locations`` as a list of {page_index,
    bounding_box} and sometimes as a single object; tolerate both.
    """
    locations = unit.get("locations")
    if isinstance(locations, list):
        for loc in locations:
            if isinstance(loc, dict) and isinstance(loc.get("bounding_box"), dict):
                return loc["bounding_box"]
        return None
    if isinstance(locations, dict):
        bb = locations.get("bounding_box")
        return bb if isinstance(bb, dict) else None
    return None


def bda_standard_output_to_textract_blocks(
    standard_output: Union[str, Dict[str, Any]],
    page_index: Optional[int] = None,
) -> Dict[str, Any]:
    """Convert a BDA document standard-output payload to a Textract-format dict.

    Args:
        standard_output: The BDA ``standardOutput`` object (or its JSON string,
            as returned inline by the sync API). Expected keys include
            ``pages``, ``text_lines``, ``text_words``.
        page_index: If provided, only lines/words on this 0-based page index are
            included (used when a payload spans multiple pages). When None, all
            lines/words are included (the common single-page-invocation case).

    Returns:
        ``{"DocumentMetadata": {"Pages": 1}, "Blocks": [...]}`` with PAGE, LINE
        and WORD blocks. LINE confidence is the mean of its child WORD
        confidences; geometry and confidence are scaled to Textract conventions.
    """
    if isinstance(standard_output, str):
        standard_output = json.loads(standard_output)

    text_lines: List[Dict[str, Any]] = standard_output.get("text_lines", []) or []
    text_words: List[Dict[str, Any]] = standard_output.get("text_words", []) or []

    def _on_page(unit: Dict[str, Any]) -> bool:
        if page_index is None:
            return True
        return unit.get("page_index") == page_index

    # Index words by their parent line id so LINE -> WORD CHILD relationships and
    # per-line confidence averaging both work.
    words_by_line: Dict[Optional[str], List[Dict[str, Any]]] = {}
    for word in text_words:
        if not _on_page(word):
            continue
        words_by_line.setdefault(word.get("line_id"), []).append(word)

    blocks: List[Dict[str, Any]] = []

    # A single synthetic PAGE block spanning the whole page.
    page_block_id = "page-0"
    page_block: Dict[str, Any] = {
        "BlockType": "PAGE",
        "Id": page_block_id,
        "Geometry": {
            "BoundingBox": {"Left": 0.0, "Top": 0.0, "Width": 1.0, "Height": 1.0},
            "Polygon": [
                {"X": 0.0, "Y": 0.0},
                {"X": 1.0, "Y": 0.0},
                {"X": 1.0, "Y": 1.0},
                {"X": 0.0, "Y": 1.0},
            ],
        },
        "Relationships": [],
    }
    blocks.append(page_block)
    page_child_ids: List[str] = []

    for line in text_lines:
        if not _on_page(line):
            continue
        line_id = line.get("id") or f"line-{len(blocks)}"
        child_words = words_by_line.get(line.get("id"), [])

        # Build WORD blocks first so we can average their confidence for the LINE.
        word_ids: List[str] = []
        word_blocks: List[Dict[str, Any]] = []
        word_confidences: List[float] = []
        for word in child_words:
            wconf = word.get("confidence")
            wid = word.get("id") or f"word-{len(blocks) + len(word_blocks)}"
            if isinstance(wconf, (int, float)):
                word_confidences.append(float(wconf))
                wconf_scaled = float(wconf) * 100.0
            else:
                wconf_scaled = 0.0
            word_blocks.append(
                {
                    "BlockType": "WORD",
                    "Id": wid,
                    "Text": word.get("text", ""),
                    "Confidence": wconf_scaled,
                    "Geometry": _bbox_to_geometry(_first_bbox(word)),
                }
            )
            word_ids.append(wid)

        # LINE confidence = mean of child word confidences (BDA line confidence
        # is unreliable). Fall back to the line's own value only if no words.
        if word_confidences:
            line_conf = (sum(word_confidences) / len(word_confidences)) * 100.0
        else:
            lc = line.get("confidence")
            line_conf = float(lc) * 100.0 if isinstance(lc, (int, float)) else 0.0

        line_block: Dict[str, Any] = {
            "BlockType": "LINE",
            "Id": line_id,
            "Text": line.get("text", ""),
            "Confidence": line_conf,
            "Geometry": _bbox_to_geometry(_first_bbox(line)),
        }
        if word_ids:
            line_block["Relationships"] = [{"Type": "CHILD", "Ids": word_ids}]
        blocks.append(line_block)
        blocks.extend(word_blocks)
        page_child_ids.append(line_id)

    if page_child_ids:
        page_block["Relationships"] = [{"Type": "CHILD", "Ids": page_child_ids}]

    return {"DocumentMetadata": {"Pages": 1}, "Blocks": blocks}


def extract_markdown(
    standard_output: Union[str, Dict[str, Any]],
    page_index: Optional[int] = None,
) -> str:
    """Extract page markdown (preferred) or plain text from BDA standard output.

    Args:
        standard_output: BDA ``standardOutput`` object or JSON string.
        page_index: 0-based page to extract; None selects the first page present.

    Returns:
        The page's markdown representation, falling back to plain text, else "".
    """
    if isinstance(standard_output, str):
        standard_output = json.loads(standard_output)

    pages = standard_output.get("pages", []) or []
    target = None
    if page_index is None:
        target = pages[0] if pages else None
    else:
        for page in pages:
            if page.get("page_index") == page_index:
                target = page
                break

    if target is not None:
        rep = target.get("representation", {}) or {}
        return rep.get("markdown") or rep.get("text") or ""

    # No per-page representation: fall back to document-level text.
    doc_rep = (standard_output.get("document", {}) or {}).get(
        "representation", {}
    ) or {}
    return doc_rep.get("markdown") or doc_rep.get("text") or ""


def build_ocr_project_standard_output_config() -> Dict[str, Any]:
    """Standard-output-only configuration for a pure-OCR BDA project.

    Suitable for a ``projectType="SYNC"`` project: exactly one text format
    (MARKDOWN), bounding boxes on, generative fields off (no LLM summaries),
    additional file formats off (sync emits none anyway).
    """
    return {
        "document": {
            "extraction": {
                "granularity": {"types": ["PAGE", "ELEMENT", "WORD", "LINE"]},
                "boundingBox": {"state": "ENABLED"},
            },
            "generativeField": {"state": "DISABLED"},
            "outputFormat": {
                "textFormat": {"types": ["MARKDOWN"]},
                "additionalFileFormat": {"state": "DISABLED"},
            },
        }
    }


def build_ocr_project_override_config() -> Dict[str, Any]:
    """Override configuration forcing image inputs to DOCUMENT modality.

    We feed BDA rendered page images (JPEG/PNG). Without routing overrides, BDA
    semantically classifies some page images as IMAGE (returning image analysis
    instead of document text extraction), producing empty OCR output. Forcing
    jpeg/png routing to DOCUMENT guarantees document text extraction.
    """
    return {"modalityRouting": {"jpeg": "DOCUMENT", "png": "DOCUMENT"}}


def _ensure_project_routing_override(client: Any, project_arn: str) -> None:
    """Ensure an existing OCR project has jpeg/png -> DOCUMENT modality routing.

    A project created by an earlier build may predate the routing override.
    Without it, rendered page images misclassify as IMAGE and produce empty
    OCR. If the override is missing or incomplete, update the project in place.
    """
    try:
        project = client.get_data_automation_project(projectArn=project_arn)["project"]
    except Exception:
        logger.warning(
            "Could not fetch BDA OCR project %s to verify routing", project_arn
        )
        return

    routing = (project.get("overrideConfiguration") or {}).get("modalityRouting") or {}
    if routing.get("jpeg") == "DOCUMENT" and routing.get("png") == "DOCUMENT":
        return

    logger.info(
        "Updating BDA OCR project %s to add jpeg/png->DOCUMENT modality routing",
        project_arn,
    )
    client.update_data_automation_project(
        projectArn=project_arn,
        standardOutputConfiguration=build_ocr_project_standard_output_config(),
        overrideConfiguration=build_ocr_project_override_config(),
    )


def resolve_ocr_project_arn(
    region: Optional[str] = None,
    bda_control_client: Optional[Any] = None,
) -> str:
    """Find or create the auto-managed pure-OCR standard-output SYNC project.

    Looks for a project named :data:`OCR_PROJECT_NAME`; creates it (projectType
    ``SYNC``, standard output only) if absent and waits for it to reach
    ``COMPLETED``. Returns the project ARN.

    Args:
        region: AWS region (defaults to the client/session region).
        bda_control_client: Optional pre-built ``bedrock-data-automation`` client.
    """
    client = bda_control_client or boto3.client(
        "bedrock-data-automation", region_name=region
    )

    # Reuse an existing project of this name if present.
    paginator = None
    try:
        paginator = client.get_paginator("list_data_automation_projects")
    except Exception:
        paginator = None

    existing_arn = None
    if paginator is not None:
        for page in paginator.paginate():
            for proj in page.get("projects", []):
                if proj.get("projectName") == OCR_PROJECT_NAME:
                    existing_arn = proj["projectArn"]
                    break
            if existing_arn:
                break
    else:
        for proj in client.list_data_automation_projects().get("projects", []):
            if proj.get("projectName") == OCR_PROJECT_NAME:
                existing_arn = proj["projectArn"]
                break

    if existing_arn:
        # Verify the project carries the modality-routing override. A project
        # left over from an earlier build may lack it, which silently breaks OCR
        # (page images misroute to IMAGE -> empty text). Repair it in place.
        _ensure_project_routing_override(client, existing_arn)
        logger.info("Reusing BDA OCR project %s", existing_arn)
        return existing_arn

    logger.info("Creating BDA OCR project %s", OCR_PROJECT_NAME)
    try:
        resp = client.create_data_automation_project(
            projectName=OCR_PROJECT_NAME,
            projectDescription="Auto-managed GenAIIDP pure-OCR standard-output project",
            projectStage="LIVE",
            projectType="SYNC",
            standardOutputConfiguration=build_ocr_project_standard_output_config(),
            overrideConfiguration=build_ocr_project_override_config(),
        )
        project_arn = resp["projectArn"]
    except client.exceptions.ConflictException:
        # Another concurrent worker created it first; re-fetch by name.
        logger.info("BDA OCR project already created concurrently; re-fetching")
        for proj in client.list_data_automation_projects().get("projects", []):
            if proj.get("projectName") == OCR_PROJECT_NAME:
                return proj["projectArn"]
        raise

    # A freshly created project is IN_PROGRESS until provisioned.
    for _ in range(60):
        status = client.get_data_automation_project(projectArn=project_arn)["project"][
            "status"
        ]
        if status == "COMPLETED":
            break
        time.sleep(2)
    return project_arn


def build_profile_arn(region: str, account_id: str) -> str:
    """Construct the standard data-automation profile ARN for a region/account."""
    region_prefix = region.split("-")[0]
    return (
        f"arn:aws:bedrock:{region}:{account_id}:data-automation-profile/"
        f"{region_prefix}.data-automation-v1"
    )
