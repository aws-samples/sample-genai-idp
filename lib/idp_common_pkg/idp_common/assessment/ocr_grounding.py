# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Ground assessment ``explainability_info`` geometry in real OCR data.

After the assessment LLM produces per-field bounding boxes (LLM-estimated, on a
0-1000 scale that the service rescales to 0-1), this module matches each extracted
attribute *value* against the real OCR lines in the consolidated ``pageData.json``
artifact (LINE-primary, geometry already normalized 0-1) and, on a confident match,
replaces the LLM-estimated box with the real OCR box and tags its provenance.

Design notes (see scratch/assessment-ocr-grounding-plan.md):

- **Coordinate space:** ``pageData`` geometry is already 0-1, so grounded boxes skip
  the /1000 rescale that LLM boxes go through. This module never rescales; it only
  ever produces 0-1 boxes, matching what the UI bounding-box renderer consumes.
- **Backward compatible / safe fallback:** when ``pageData.json`` is absent (older
  documents, missing URI), a page has ``geometryAvailable: false`` (plain LLM OCR,
  Chandra, ``none`` backend), or no OCR line matches the extracted value, the
  field's existing LLM-estimated box is left untouched. Worst case == today.
- **explainability_info contract:** the grounded box *replaces* the contents of the
  existing ``geometry`` array (same shape, ``[{boundingBox:{left,top,width,height},
  page}]``, 0-1, 1-indexed page). Two additive keys are written on the field
  assessment: ``geometry_source`` ("ocr" | "ocr-paragraph" | "llm") and, when a
  matched line carries OCR confidence, ``ocr_confidence`` (0-1). The LLM
  ``confidence`` / ``confidence_reason`` are never overwritten, so HITL thresholds
  and ``confidence_threshold_alerts`` are unaffected.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from idp_common import s3

logger = logging.getLogger(__name__)

# Minimum Jaccard token-overlap for a fuzzy single-line match.
_FUZZY_MATCH_THRESHOLD = 0.6

# Cap on how many adjacent lines a single value may span (multi-line union).
# Keeps unions tight; multi-line addresses/cells are typically 2-4 lines.
_MAX_SPAN_LINES = 6


def _normalize(text: Any) -> str:
    """Casefold, collapse whitespace, and strip surrounding punctuation."""
    if text is None:
        return ""
    s = str(text).casefold()
    # Collapse all whitespace runs to single spaces.
    s = re.sub(r"\s+", " ", s).strip()
    # Strip leading/trailing punctuation that commonly differs between an
    # extracted value and the OCR line it came from (e.g. "$1,234.00" vs "1,234.00").
    s = s.strip(" \t\n\r.,;:!?\"'()[]{}<>|$%*#-_=")
    return s


def _tokens(text: str) -> set:
    """Word-token set of an already-normalized string."""
    return set(re.findall(r"[^\W_]+", text)) if text else set()


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def load_page_ocr_data(
    pages: Dict[str, Any], page_ids: List[str]
) -> Dict[int, Dict[str, Any]]:
    """
    Load ``pageData.json`` for each page in ``page_ids`` keyed by 1-indexed page number.

    Pages without an ``ocr_page_data_uri`` (older documents) or whose artifact cannot
    be read are simply omitted from the result, so callers degrade gracefully.

    Args:
        pages: Document.pages mapping (page_id -> Page).
        page_ids: Page IDs belonging to the section (1-indexed strings).

    Returns:
        Mapping of ``int(page_id)`` -> parsed pageData dict, only for pages that have
        usable data.
    """
    result: Dict[int, Dict[str, Any]] = {}
    for page_id in page_ids:
        page = pages.get(page_id)
        if page is None:
            continue
        uri = getattr(page, "ocr_page_data_uri", None)
        if not uri:
            continue
        try:
            page_data = s3.get_json_content(uri)
        except Exception as e:
            logger.warning(
                f"Could not read pageData.json for page {page_id} ({uri}): {e}"
            )
            continue
        if isinstance(page_data, dict):
            try:
                result[int(page_id)] = page_data
            except (TypeError, ValueError):
                logger.warning(f"Non-numeric page_id '{page_id}' skipped for grounding")
    return result


def _union_box(boxes: List[Dict[str, float]]) -> Dict[str, float]:
    """Union a list of 0-1 ``{left,top,width,height}`` boxes into a bounding box."""
    lefts = [b["left"] for b in boxes]
    tops = [b["top"] for b in boxes]
    rights = [b["left"] + b["width"] for b in boxes]
    bottoms = [b["top"] + b["height"] for b in boxes]
    left = min(lefts)
    top = min(tops)
    return {
        "left": left,
        "top": top,
        "width": max(rights) - left,
        "height": max(bottoms) - top,
    }


def _line_box(line: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Return a line's 0-1 boundingBox dict, or None if it has no geometry."""
    geom = line.get("geometry")
    if not isinstance(geom, dict):
        return None
    bb = geom.get("boundingBox")
    if not isinstance(bb, dict):
        return None
    # Defensive: require the four expected keys.
    if not all(k in bb for k in ("left", "top", "width", "height")):
        return None
    return {
        "left": bb["left"],
        "top": bb["top"],
        "width": bb["width"],
        "height": bb["height"],
    }


# Match precision tiers (lower = more precise). The caller keeps only the best tier
# that matched, then disambiguates ties spatially. Ordering rationale:
#   EXACT     - line text equals the value
#   SUBSTRING - value contained in a single line (whole value covered)
#   SPAN      - value reconstructed by joining consecutive lines (whole value covered)
#   PARTIAL   - a single line is a fragment of the value (partial coverage)
#   FUZZY     - token-overlap only
# Full-coverage matches (SUBSTRING/SPAN) rank above PARTIAL fragments so a multi-line
# value grounds to the unioned span rather than to one of its individual fragments.
_TIER_EXACT = 1
_TIER_SUBSTRING = 2
_TIER_SPAN = 3
_TIER_PARTIAL = 4
_TIER_FUZZY = 5


def _collect_candidates_in_page(
    norm_value: str, value_tokens: set, page_data: Dict[str, Any], page_num: int
) -> List[Tuple[int, Dict[str, Any], str, Optional[float]]]:
    """
    Collect *all* matching OCR lines on one page, each tagged with a precision tier.

    Returns a list of ``(tier, geometry, geometry_source, ocr_confidence)`` where
    ``geometry`` is ``{"boundingBox": {...0-1...}, "page": page_num}``. The caller
    picks the best tier globally and disambiguates ties spatially — critical for
    repeated values (e.g. the same transaction amount on several rows), where
    returning the first match would collapse every row onto one line.
    """
    if not norm_value or not page_data.get("geometryAvailable"):
        return []

    lines = page_data.get("lines")
    if not isinstance(lines, list) or not lines:
        return []

    # Pre-compute normalized line text once.
    norm_lines: List[Tuple[str, Dict[str, Any]]] = []
    for line in lines:
        if isinstance(line, dict):
            norm_lines.append((_normalize(line.get("text")), line))

    candidates: List[Tuple[int, Dict[str, Any], str, Optional[float]]] = []

    for norm_text, line in norm_lines:
        if not norm_text:
            continue
        if norm_text == norm_value:
            tier = _TIER_EXACT
        elif norm_value in norm_text:
            # Whole value covered by one line.
            tier = _TIER_SUBSTRING
        elif norm_text in norm_value:
            # A single line is a fragment of a longer value (partial coverage).
            tier = _TIER_PARTIAL
        else:
            continue
        match = _build_match(line, page_num, tier)
        if match is not None:
            candidates.append(match)

    # Multi-line spans (value == concatenation of consecutive lines).
    candidates.extend(_collect_span_candidates(norm_value, norm_lines, page_num))

    # Token-overlap fuzzy: include every line at/above the threshold (only matters
    # when no higher-precision tier matched, since the caller filters by best tier).
    for norm_text, line in norm_lines:
        if not norm_text:
            continue
        if _jaccard(value_tokens, _tokens(norm_text)) >= _FUZZY_MATCH_THRESHOLD:
            match = _build_match(line, page_num, _TIER_FUZZY)
            if match is not None:
                candidates.append(match)

    return candidates


def _collect_span_candidates(
    norm_value: str,
    norm_lines: List[Tuple[str, Dict[str, Any]]],
    page_num: int,
) -> List[Tuple[int, Dict[str, Any], str, Optional[float]]]:
    """Collect multi-line span matches (consecutive lines whose text joins to value)."""
    results: List[Tuple[int, Dict[str, Any], str, Optional[float]]] = []
    n = len(norm_lines)
    for i in range(n):
        if not norm_lines[i][0]:
            continue
        combined = norm_lines[i][0]
        # Single lines are handled by exact/substring; spans start at 2 lines.
        for j in range(i + 1, min(i + _MAX_SPAN_LINES, n)):
            nxt = norm_lines[j][0]
            if not nxt:
                continue
            combined = f"{combined} {nxt}"
            if combined == norm_value:
                span_lines = [norm_lines[k][1] for k in range(i, j + 1)]
                boxes = [b for b in (_line_box(line) for line in span_lines) if b]
                if boxes:
                    source = (
                        "ocr-paragraph"
                        if any(
                            line.get("geometrySource") == "paragraph"
                            for line in span_lines
                        )
                        else "ocr"
                    )
                    confs = [
                        float(c)
                        for line in span_lines
                        if isinstance((c := line.get("confidence")), (int, float))
                    ]
                    ocr_conf = (sum(confs) / len(confs) / 100.0) if confs else None
                    results.append(
                        (
                            _TIER_SPAN,
                            {"boundingBox": _union_box(boxes), "page": page_num},
                            source,
                            ocr_conf,
                        )
                    )
                break
            if len(combined) > len(norm_value):
                break
    return results


def _build_match(
    line: Dict[str, Any], page_num: int, tier: int
) -> Optional[Tuple[int, Dict[str, Any], str, Optional[float]]]:
    """Build a candidate tuple from a single OCR line, or None if it lacks geometry."""
    box = _line_box(line)
    if box is None:
        return None
    source = "ocr-paragraph" if line.get("geometrySource") == "paragraph" else "ocr"
    conf = line.get("confidence")
    ocr_conf = conf / 100.0 if isinstance(conf, (int, float)) else None
    return (tier, {"boundingBox": box, "page": page_num}, source, ocr_conf)


def _box_center(geometry: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """Center (cx, cy) of a ``{boundingBox:{...}}`` geometry, or None."""
    bb = geometry.get("boundingBox") if isinstance(geometry, dict) else None
    if not isinstance(bb, dict):
        return None
    try:
        return (bb["left"] + bb["width"] / 2.0, bb["top"] + bb["height"] / 2.0)
    except (KeyError, TypeError):
        return None


def _ref_from_llm_geometry(
    preferred_geometry: Optional[Dict[str, Any]],
) -> Optional[Tuple[int, float, float]]:
    """Extract ``(page, cx, cy)`` from the LLM-estimated geometry, if usable."""
    if not isinstance(preferred_geometry, dict):
        return None
    page_val = preferred_geometry.get("page")
    if isinstance(page_val, str) and page_val.isdigit():
        page_val = int(page_val)
    if not isinstance(page_val, int):
        return None
    center = _box_center(preferred_geometry)
    if center is None:
        return None
    return (page_val, center[0], center[1])


def match_value_to_geometry(
    value: Any,
    page_data_by_page: Dict[int, Dict[str, Any]],
    preferred_geometry: Optional[Dict[str, Any]] = None,
) -> Optional[Tuple[Dict[str, Any], str, Optional[float]]]:
    """
    Match an extracted value to a real OCR line across the section's pages.

    Collects every candidate line across all pages, keeps only the best (most
    precise) tier, and resolves ties **spatially** using the LLM-estimated box as a
    reference: among equally-good text matches, the one whose center is nearest the
    LLM box wins. This is what keeps repeated values (e.g. identical transaction
    amounts on different rows) from all collapsing onto the first matching line — the
    LLM placed each row's box at a roughly-correct, distinct position, so proximity
    selects the right occurrence.

    Safe fallback: if multiple candidates remain and there is **no** usable LLM
    reference box to disambiguate (or the reference is on a different page than all
    candidates), the match is treated as ambiguous and None is returned, so the
    caller keeps the existing LLM-estimated box rather than risk the wrong one.

    Args:
        value: The extracted attribute value (scalar; coerced to string).
        page_data_by_page: Mapping of 1-indexed page number -> pageData dict.
        preferred_geometry: The LLM-estimated ``{boundingBox, page}`` for this field,
            used as the spatial/page reference.

    Returns:
        ``(geometry, geometry_source, ocr_confidence)`` where ``geometry`` is
        ``{"boundingBox": {...0-1...}, "page": <int>}``, or None when no confident,
        unambiguous match is found.
    """
    if value is None or not page_data_by_page:
        return None

    norm_value = _normalize(value)
    if not norm_value:
        return None
    value_tokens = _tokens(norm_value)

    ref = _ref_from_llm_geometry(preferred_geometry)

    # Collect candidates across all pages.
    candidates: List[Tuple[int, Dict[str, Any], str, Optional[float]]] = []
    for page_num in sorted(page_data_by_page):
        candidates.extend(
            _collect_candidates_in_page(
                norm_value, value_tokens, page_data_by_page[page_num], page_num
            )
        )

    if not candidates:
        return None

    # Keep only the most precise tier that matched (exact beats substring beats
    # span beats fuzzy), so a high-precision hit is never displaced by fuzzy noise.
    best_tier = min(tier for tier, *_ in candidates)
    best = [c for c in candidates if c[0] == best_tier]

    if len(best) == 1:
        _, geometry, source, ocr_conf = best[0]
        return (geometry, source, ocr_conf)

    # Ambiguous: multiple equally-good text matches (e.g. a value repeated across
    # table rows). Disambiguate by proximity to the LLM-estimated box, which sits at
    # a roughly-correct distinct position per occurrence. Prefer candidates on the
    # LLM's page; among those, pick the nearest box center.
    if ref is not None:
        ref_page, ref_cx, ref_cy = ref
        on_ref_page = [c for c in best if c[1].get("page") == ref_page]
        pool = on_ref_page or best

        def _distance(c: Tuple[int, Dict[str, Any], str, Optional[float]]) -> float:
            center = _box_center(c[1])
            if center is None:
                return float("inf")
            return (center[0] - ref_cx) ** 2 + (center[1] - ref_cy) ** 2

        nearest = min(pool, key=_distance)
        if _distance(nearest) != float("inf"):
            _, geometry, source, ocr_conf = nearest
            return (geometry, source, ocr_conf)

    # No usable LLM reference to disambiguate -> ambiguous; keep the LLM box.
    logger.debug(
        "Ambiguous OCR grounding for value '%s' (%d candidates, no usable reference); "
        "keeping LLM box",
        norm_value,
        len(best),
    )
    return None


def _ground_node(
    assessment_node: Any,
    extraction_node: Any,
    page_data_by_page: Dict[int, Dict[str, Any]],
) -> None:
    """
    Recursively walk an assessment subtree, grounding leaf geometries in place.

    The recursion mirrors ``_extract_geometry_from_assessment``: a dict with a
    ``confidence`` key is a leaf assessment; otherwise it is a group; lists are
    walked element-wise alongside the parallel extraction list.
    """
    if isinstance(assessment_node, dict):
        if "confidence" in assessment_node:
            _ground_leaf(assessment_node, extraction_node, page_data_by_page)
            return
        # Group: descend into each child alongside the matching extraction value.
        #
        # Two extraction shapes occur here:
        #  - True group: the extraction value is a dict, so each child key maps to a
        #    sub-value (e.g. CompanyAddress -> {State, ZipCode}).
        #  - Decomposed string: the schema field is a plain string, but the assessment
        #    LLM split it into sub-keyed assessments where each *key* is a fragment of
        #    the value (e.g. "Insurance Company": {"Fake Insurance Co": {...},
        #    "650 Davis Street": {...}}). The extraction value is then a string, not a
        #    dict. In that case the sub-key name itself is the text to ground, but only
        #    when it is actually part of the extracted string — otherwise a genuine
        #    group with a missing extraction value could spuriously match label text.
        extraction_is_str = isinstance(extraction_node, str)
        norm_parent = _normalize(extraction_node) if extraction_is_str else ""
        for key, child in assessment_node.items():
            if isinstance(extraction_node, dict):
                child_extraction = extraction_node.get(key)
            elif (
                extraction_is_str and _normalize(key) and _normalize(key) in norm_parent
            ):
                # Decomposed-string fragment: match the fragment key text.
                child_extraction = key
            else:
                child_extraction = None
            _ground_node(child, child_extraction, page_data_by_page)
    elif isinstance(assessment_node, list):
        for idx, item in enumerate(assessment_node):
            item_extraction = (
                extraction_node[idx]
                if isinstance(extraction_node, list) and idx < len(extraction_node)
                else None
            )
            _ground_node(item, item_extraction, page_data_by_page)


def _ground_leaf(
    leaf: Dict[str, Any],
    value: Any,
    page_data_by_page: Dict[int, Dict[str, Any]],
) -> None:
    """Ground a single leaf assessment (has a ``confidence`` key) in place."""
    # The existing (LLM-estimated) box doubles as the spatial reference used to
    # disambiguate repeated values across table rows.
    existing_geometry = leaf.get("geometry")
    preferred_geometry: Optional[Dict[str, Any]] = None
    if (
        isinstance(existing_geometry, list)
        and existing_geometry
        and isinstance(existing_geometry[0], dict)
    ):
        preferred_geometry = existing_geometry[0]

    match = match_value_to_geometry(value, page_data_by_page, preferred_geometry)
    if match is None:
        # No OCR match -> keep the LLM box. Tag provenance only if a box exists.
        if existing_geometry:
            leaf["geometry_source"] = "llm"
        return

    geometry, source, ocr_conf = match
    leaf["geometry"] = [geometry]
    leaf["geometry_source"] = source
    if ocr_conf is not None:
        leaf["ocr_confidence"] = round(ocr_conf, 4)


def ground_assessment_geometry(
    enhanced_assessment: Dict[str, Any],
    extraction_results: Dict[str, Any],
    page_data_by_page: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Replace LLM-estimated field geometry with real OCR geometry where matchable.

    Mutates and returns ``enhanced_assessment``. Safe to call unconditionally: when
    ``page_data_by_page`` is empty (no OCR geometry anywhere), it is a near no-op
    (only tags ``geometry_source: "llm"`` on fields that already had a box).

    Args:
        enhanced_assessment: The per-field assessment dict (the object that becomes
            ``explainability_info[0]``).
        extraction_results: The original ``inference_result`` values, used to look up
            each field's extracted value for matching.
        page_data_by_page: Mapping of 1-indexed page number -> pageData dict, from
            ``load_page_ocr_data``.

    Returns:
        The same ``enhanced_assessment`` dict, grounded in place.
    """
    try:
        for attr_name, attr_assessment in enhanced_assessment.items():
            extraction_value = (
                extraction_results.get(attr_name)
                if isinstance(extraction_results, dict)
                else None
            )
            _ground_node(attr_assessment, extraction_value, page_data_by_page)
    except Exception as e:
        # Grounding is best-effort enrichment; never fail assessment over it.
        logger.warning(f"OCR geometry grounding failed; keeping LLM boxes: {e}")
    return enhanced_assessment
