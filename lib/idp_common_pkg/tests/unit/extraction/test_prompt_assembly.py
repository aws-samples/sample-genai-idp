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


def _cfg(mode="separate", geom="ocr_only", enabled=True):
    return ExtractionConfig(
        task_prompt="EXTRACT-ONLY {DOCUMENT_TEXT}",
        task_prompt_extraction_with_confidence="INTEGRATED provide_field_assessment\n<<CACHEPOINT>>\n{DOCUMENT_TEXT}",
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

    def test_integrated_uses_integrated_template(self):
        p = select_extraction_task_prompt(_cfg(mode="integrated", geom="ocr_only"))
        assert "provide_field_assessment" in p
        assert "spatial-localization" not in p  # ocr_only -> no bbox

    def test_integrated_llm_grounded_appends_bbox(self):
        p = select_extraction_task_prompt(_cfg(mode="integrated", geom="llm_grounded"))
        assert "provide_field_assessment" in p
        assert "spatial-localization" in p
        # bbox spliced before the cachepoint/document marker
        assert p.index("spatial-localization") < p.index("<<CACHEPOINT>>")

    def test_integrated_llm_appends_bbox(self):
        p = select_extraction_task_prompt(_cfg(mode="integrated", geom="llm"))
        assert "spatial-localization" in p


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
