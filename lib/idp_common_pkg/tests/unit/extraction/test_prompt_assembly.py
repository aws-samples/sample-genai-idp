# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for settings-aware prompt template selection (v0.6)."""

import pytest

from idp_common.config.models import ExtractionConfig
from idp_common.extraction.prompt_assembly import (
    geometry_requires_llm_boxes,
    select_confidence_task_prompt,
    select_extraction_task_prompt,
)


def _cfg(mode="separate", geom="ocr_only", enabled=True, agentic=True):
    # agentic=True (advanced) selects the tool-based integrated prompt; agentic=
    # False (simple) selects the 1S-TopK prompt.
    return ExtractionConfig(
        task_prompt="EXTRACT-ONLY {DOCUMENT_TEXT}",
        task_prompt_extraction_with_confidence="INTEGRATED provide_field_assessment\n<<CACHEPOINT>>\n{DOCUMENT_TEXT}",
        task_prompt_extraction_with_confidence_topk="TOPK G1/P1 candidates\n<<CACHEPOINT>>\n{DOCUMENT_TEXT}",
        agentic={"enabled": agentic},
        confidence={
            "enabled": enabled,
            "mode": mode,
            "task_prompt": "CONFIDENCE-ONLY\n<<CACHEPOINT>>\n{EXTRACTION_RESULTS}",
        },
        geometry={
            "mode": geom,
            "task_prompt_bbox": "<spatial-localization>bbox here</spatial-localization>",
        },
    )


class TestGeometryRequiresLlmBoxes:
    @pytest.mark.parametrize(
        "mode,expected",
        [
            ("llm", True),
            ("llm_grounded", True),
            ("ocr_only", False),
            ("off", False),
            ("", False),
        ],
    )
    def test_modes(self, mode, expected):
        assert geometry_requires_llm_boxes(mode) is expected


class TestSelectExtractionTaskPrompt:
    def test_separate_uses_plain_extraction(self):
        p = select_extraction_task_prompt(_cfg(mode="separate", geom="ocr_only"))
        assert p.startswith("EXTRACT-ONLY")
        assert "provide_field_assessment" not in p

    def test_confidence_disabled_uses_plain_extraction(self):
        p = select_extraction_task_prompt(_cfg(mode="integrated", enabled=False))
        assert p.startswith("EXTRACT-ONLY")

    def test_advanced_integrated_uses_tool_template(self):
        p = select_extraction_task_prompt(
            _cfg(mode="integrated", geom="ocr_only", agentic=True)
        )
        assert "provide_field_assessment" in p
        assert "spatial-localization" not in p  # ocr_only -> no bbox

    def test_simple_integrated_uses_topk_template(self):
        # Simple (non-agentic) integrated -> 1S-TopK prompt, not the tool prompt.
        p = select_extraction_task_prompt(
            _cfg(mode="integrated", geom="ocr_only", agentic=False)
        )
        assert "TOPK" in p and "provide_field_assessment" not in p

    def test_simple_integrated_falls_back_to_task_prompt(self):
        # If no TopK template is set, simple integrated falls back to task_prompt.
        cfg = _cfg(mode="integrated", geom="ocr_only", agentic=False)
        cfg.task_prompt_extraction_with_confidence_topk = ""
        p = select_extraction_task_prompt(cfg)
        assert p.startswith("EXTRACT-ONLY")

    def test_advanced_integrated_llm_grounded_appends_bbox(self):
        p = select_extraction_task_prompt(
            _cfg(mode="integrated", geom="llm_grounded", agentic=True)
        )
        assert "provide_field_assessment" in p
        assert "spatial-localization" in p
        # bbox spliced before the cachepoint/document marker
        assert p.index("spatial-localization") < p.index("<<CACHEPOINT>>")

    def test_advanced_integrated_llm_appends_bbox(self):
        p = select_extraction_task_prompt(
            _cfg(mode="integrated", geom="llm", agentic=True)
        )
        assert "spatial-localization" in p

    def test_simple_integrated_topk_llm_appends_bbox(self):
        # TopK + llm geometry: the bbox block splices into the TopK prompt too,
        # before the cachepoint marker (contracts do not collide).
        p = select_extraction_task_prompt(
            _cfg(mode="integrated", geom="llm", agentic=False)
        )
        assert "TOPK" in p
        assert "spatial-localization" in p
        assert p.index("spatial-localization") < p.index("<<CACHEPOINT>>")


class TestSelectConfidenceTaskPrompt:
    def test_ocr_only_no_bbox(self):
        c = select_confidence_task_prompt(_cfg(mode="separate", geom="ocr_only"))
        assert c.startswith("CONFIDENCE-ONLY")
        assert "spatial-localization" not in c

    @pytest.mark.parametrize("geom", ["llm", "llm_grounded"])
    def test_llm_modes_append_bbox(self, geom):
        c = select_confidence_task_prompt(_cfg(mode="separate", geom=geom))
        assert "spatial-localization" in c

    def test_off_no_bbox(self):
        c = select_confidence_task_prompt(_cfg(mode="separate", geom="off"))
        assert "spatial-localization" not in c

    def test_bbox_not_doubled_if_already_present(self):
        cfg = _cfg(mode="separate", geom="llm")
        cfg.confidence.task_prompt = "has spatial-localization already\n<<CACHEPOINT>>"
        c = select_confidence_task_prompt(cfg)
        assert c.count("spatial-localization") == 1
