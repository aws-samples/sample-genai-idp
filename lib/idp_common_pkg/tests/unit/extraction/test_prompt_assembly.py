# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for modular confidence/geometry prompt assembly (v0.6)."""

import pytest
from idp_common.extraction.prompt_assembly import (
    assemble_confidence_prompt,
    geometry_requires_llm_boxes,
)

CORE = (
    "<task>score confidence</task>\n\n"
    "<<CACHEPOINT>>\n<document-image>{DOCUMENT_IMAGE}</document-image>"
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


class TestAssembleConfidencePrompt:
    def test_ocr_only_returns_core_unchanged(self):
        assert assemble_confidence_prompt(CORE, "ocr_only") == CORE

    def test_off_returns_core_unchanged(self):
        assert assemble_confidence_prompt(CORE, "off") == CORE

    def test_llm_splices_geometry_before_cachepoint(self):
        out = assemble_confidence_prompt(CORE, "llm")
        assert "spatial-localization-guidelines" in out
        assert out.index("spatial-localization") < out.index("<<CACHEPOINT>>")

    def test_llm_grounded_splices_geometry(self):
        assert "spatial-localization-guidelines" in assemble_confidence_prompt(
            CORE, "llm_grounded"
        )

    def test_legacy_prompt_with_bbox_not_doubled(self):
        legacy = (
            "<spatial-localization-guidelines>x</spatial-localization-guidelines>\n"
            "<<CACHEPOINT>>"
        )
        out = assemble_confidence_prompt(legacy, "llm")
        # unchanged (the existing block's open+close tag == 2 substring hits)
        assert out == legacy

    def test_no_marker_appends_geometry(self):
        out = assemble_confidence_prompt("just a core prompt", "llm")
        assert "spatial-localization-guidelines" in out
        assert out.startswith("just a core prompt")

    def test_empty_core_returns_empty(self):
        assert assemble_confidence_prompt("", "llm") == ""
