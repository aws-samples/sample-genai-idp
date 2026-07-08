# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for BDA-as-OCR conversion (idp_common.bda.bda_ocr).
"""

# ruff: noqa: E402, I001

import json

import pytest

from unittest.mock import MagicMock

from idp_common.bda.bda_ocr import (
    OCR_PROJECT_NAME,
    bda_standard_output_to_textract_blocks,
    build_ocr_project_override_config,
    build_ocr_project_standard_output_config,
    extract_markdown,
    resolve_ocr_project_arn,
)


def _sample_standard_output():
    """A minimal single-page BDA standard-output payload with two lines."""
    return {
        "metadata": {"semantic_modality": "DOCUMENT", "number_of_pages": 1},
        "document": {"representation": {"markdown": "# Title\n\n| a | b |"}},
        "pages": [
            {
                "page_index": 0,
                "representation": {
                    "markdown": "# Title\n\n| a | b |",
                    "text": "Title a b",
                },
            }
        ],
        "text_lines": [
            {
                "id": "line-1",
                "text": "Title",
                "confidence": 0.008,  # BDA's broken line confidence
                "page_index": 0,
                "locations": [
                    {
                        "page_index": 0,
                        "bounding_box": {
                            "left": 0.1,
                            "top": 0.2,
                            "width": 0.3,
                            "height": 0.05,
                        },
                    }
                ],
            },
            {
                "id": "line-2",
                "text": "a b",
                "confidence": 0.01,
                "page_index": 0,
                "locations": [
                    {
                        "page_index": 0,
                        "bounding_box": {
                            "left": 0.1,
                            "top": 0.3,
                            "width": 0.4,
                            "height": 0.05,
                        },
                    }
                ],
            },
        ],
        "text_words": [
            {
                "id": "w1",
                "text": "Title",
                "confidence": 0.99,
                "line_id": "line-1",
                "page_index": 0,
                "locations": [
                    {
                        "bounding_box": {
                            "left": 0.1,
                            "top": 0.2,
                            "width": 0.15,
                            "height": 0.05,
                        }
                    }
                ],
            },
            {
                "id": "w2",
                "text": "a",
                "confidence": 0.90,
                "line_id": "line-2",
                "page_index": 0,
                "locations": [
                    {
                        "bounding_box": {
                            "left": 0.1,
                            "top": 0.3,
                            "width": 0.1,
                            "height": 0.05,
                        }
                    }
                ],
            },
            {
                "id": "w3",
                "text": "b",
                "confidence": 0.80,
                "line_id": "line-2",
                "page_index": 0,
                "locations": [
                    {
                        "bounding_box": {
                            "left": 0.25,
                            "top": 0.3,
                            "width": 0.1,
                            "height": 0.05,
                        }
                    }
                ],
            },
        ],
    }


@pytest.mark.unit
def test_block_structure_and_counts():
    out = bda_standard_output_to_textract_blocks(_sample_standard_output())
    assert out["DocumentMetadata"]["Pages"] == 1
    types = {}
    for b in out["Blocks"]:
        types[b["BlockType"]] = types.get(b["BlockType"], 0) + 1
    assert types == {"PAGE": 1, "LINE": 2, "WORD": 3}


@pytest.mark.unit
def test_line_confidence_is_word_average_not_broken_bda_value():
    out = bda_standard_output_to_textract_blocks(_sample_standard_output())
    lines = {b["Id"]: b for b in out["Blocks"] if b["BlockType"] == "LINE"}
    # line-1 has one word at 0.99 -> 99.0 (NOT the 0.008 broken source value)
    assert lines["line-1"]["Confidence"] == pytest.approx(99.0)
    # line-2 = mean(0.90, 0.80) = 0.85 -> 85.0
    assert lines["line-2"]["Confidence"] == pytest.approx(85.0)


@pytest.mark.unit
def test_word_confidence_scaled_to_0_100():
    out = bda_standard_output_to_textract_blocks(_sample_standard_output())
    words = {b["Id"]: b for b in out["Blocks"] if b["BlockType"] == "WORD"}
    assert words["w1"]["Confidence"] == pytest.approx(99.0)
    assert words["w2"]["Confidence"] == pytest.approx(90.0)


@pytest.mark.unit
def test_line_to_word_child_relationships():
    out = bda_standard_output_to_textract_blocks(_sample_standard_output())
    lines = {b["Id"]: b for b in out["Blocks"] if b["BlockType"] == "LINE"}
    assert lines["line-1"]["Relationships"][0]["Ids"] == ["w1"]
    assert lines["line-2"]["Relationships"][0]["Ids"] == ["w2", "w3"]


@pytest.mark.unit
def test_geometry_is_normalized_boundingbox_and_polygon():
    out = bda_standard_output_to_textract_blocks(_sample_standard_output())
    line1 = next(b for b in out["Blocks"] if b.get("Id") == "line-1")
    bb = line1["Geometry"]["BoundingBox"]
    assert bb == {"Left": 0.1, "Top": 0.2, "Width": 0.3, "Height": 0.05}
    poly = line1["Geometry"]["Polygon"]
    assert poly[0] == {"X": 0.1, "Y": 0.2}
    assert poly[2] == {"X": pytest.approx(0.4), "Y": pytest.approx(0.25)}


@pytest.mark.unit
def test_accepts_json_string_input():
    out = bda_standard_output_to_textract_blocks(json.dumps(_sample_standard_output()))
    assert any(b["BlockType"] == "LINE" for b in out["Blocks"])


@pytest.mark.unit
def test_page_index_filter_excludes_other_pages():
    payload = _sample_standard_output()
    payload["text_lines"].append(
        {"id": "p1-line", "text": "other page", "confidence": 0.5, "page_index": 1}
    )
    payload["text_words"].append(
        {
            "id": "p1w",
            "text": "other",
            "confidence": 0.5,
            "line_id": "p1-line",
            "page_index": 1,
        }
    )
    out = bda_standard_output_to_textract_blocks(payload, page_index=0)
    texts = [b.get("Text") for b in out["Blocks"] if b["BlockType"] == "LINE"]
    assert "other page" not in texts


@pytest.mark.unit
def test_line_with_no_words_falls_back_to_own_confidence():
    payload = {
        "pages": [{"page_index": 0, "representation": {"markdown": "x"}}],
        "text_lines": [
            {
                "id": "l",
                "text": "x",
                "confidence": 0.42,
                "page_index": 0,
                "locations": [],
            }
        ],
        "text_words": [],
    }
    out = bda_standard_output_to_textract_blocks(payload)
    line = next(b for b in out["Blocks"] if b["BlockType"] == "LINE")
    assert line["Confidence"] == pytest.approx(42.0)
    assert "Relationships" not in line
    assert line["Geometry"] is None


@pytest.mark.unit
def test_extract_markdown_prefers_page_markdown():
    assert extract_markdown(_sample_standard_output()) == "# Title\n\n| a | b |"


@pytest.mark.unit
def test_extract_markdown_by_page_index_falls_back_to_text():
    payload = {
        "pages": [{"page_index": 0, "representation": {"text": "plain only"}}],
    }
    assert extract_markdown(payload, page_index=0) == "plain only"


@pytest.mark.unit
def test_extract_markdown_document_level_fallback():
    payload = {"document": {"representation": {"markdown": "doc md"}}}
    assert extract_markdown(payload) == "doc md"


@pytest.mark.unit
def test_ocr_project_config_is_sync_compatible():
    cfg = build_ocr_project_standard_output_config()["document"]
    # SYNC projects allow exactly one text format
    assert cfg["outputFormat"]["textFormat"]["types"] == ["MARKDOWN"]
    # No LLM generative fields (cost/latency) for pure OCR
    assert cfg["generativeField"]["state"] == "DISABLED"
    assert cfg["extraction"]["boundingBox"]["state"] == "ENABLED"


@pytest.mark.unit
def test_override_config_routes_images_to_document():
    routing = build_ocr_project_override_config()["modalityRouting"]
    assert routing["jpeg"] == "DOCUMENT"
    assert routing["png"] == "DOCUMENT"


def _mock_control_client(existing_projects, project_detail):
    client = MagicMock()
    client.get_paginator.side_effect = Exception("no paginator")
    client.list_data_automation_projects.return_value = {"projects": existing_projects}
    client.get_data_automation_project.return_value = {"project": project_detail}
    return client


@pytest.mark.unit
def test_resolve_reuses_project_and_repairs_missing_routing():
    """A pre-existing project without modality routing must be repaired in place."""
    arn = "arn:aws:bedrock:us-west-2:111122223333:data-automation-project/abc"
    client = _mock_control_client(
        existing_projects=[{"projectName": OCR_PROJECT_NAME, "projectArn": arn}],
        project_detail={"status": "COMPLETED", "overrideConfiguration": {}},
    )
    result = resolve_ocr_project_arn(bda_control_client=client)
    assert result == arn
    client.create_data_automation_project.assert_not_called()
    # Missing routing -> project updated with the override.
    client.update_data_automation_project.assert_called_once()
    kwargs = client.update_data_automation_project.call_args.kwargs
    assert kwargs["overrideConfiguration"]["modalityRouting"]["jpeg"] == "DOCUMENT"


@pytest.mark.unit
def test_resolve_reuses_project_without_update_when_routing_present():
    arn = "arn:aws:bedrock:us-west-2:111122223333:data-automation-project/abc"
    client = _mock_control_client(
        existing_projects=[{"projectName": OCR_PROJECT_NAME, "projectArn": arn}],
        project_detail={
            "status": "COMPLETED",
            "overrideConfiguration": {
                "modalityRouting": {"jpeg": "DOCUMENT", "png": "DOCUMENT"}
            },
        },
    )
    result = resolve_ocr_project_arn(bda_control_client=client)
    assert result == arn
    client.update_data_automation_project.assert_not_called()


@pytest.mark.unit
def test_roundtrip_through_ocr_service_helpers():
    """The converted blocks must work with OcrService's existing helpers."""
    from idp_common.ocr.service import OcrService

    blocks = bda_standard_output_to_textract_blocks(_sample_standard_output())
    svc = OcrService.__new__(OcrService)  # bypass __init__/AWS clients

    tc = OcrService._generate_text_confidence_data(svc, blocks)
    assert "| Title | 99.0 |" in tc["text"]

    md = extract_markdown(_sample_standard_output())
    pd = OcrService._build_page_data(svc, blocks, md, "bda")
    assert pd["provider"] == "bda"
    assert pd["confidenceAvailable"] is True
    assert pd["geometryAvailable"] is True
    assert pd["wordsAvailable"] is True
    assert len(pd["lines"]) == 2
