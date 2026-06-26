#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Offline unit tests for the Mistral -> Textract translation in index.py.

These tests do NOT call the Mistral API or AWS — they validate the pure
translation logic (markdown extraction, block geometry normalization, per-word
confidence scaling, and metering). Run with:

    python test_translation.py
or
    pytest test_translation.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import index  # noqa: E402, I001


# A representative Mistral OCR response for a single image page.
# Markdown layout (char offsets for start_index):
#   "# Invoice"      -> offsets  0.. 8
#   ""  (blank)      -> offset   9 (the first \n) .. 10 (second \n is at 10)
#   "Account: 12345" -> offsets 11..24
#   "Total: $99.00"  -> offsets 26..38
_MARKDOWN = "# Invoice\n\nAccount: 12345\nTotal: $99.00"
SAMPLE_RESPONSE = {
    "model": "mistral-ocr-2505",
    "pages": [
        {
            "index": 0,
            "markdown": _MARKDOWN,
            "dimensions": {"dpi": 150, "width": 1000, "height": 2000},
            "blocks": [
                {
                    "type": "title",
                    "content": "# Invoice",
                    "top_left_x": 100,
                    "top_left_y": 50,
                    "bottom_right_x": 500,
                    "bottom_right_y": 150,
                },
                {
                    "type": "text",
                    "content": "Account: 12345",
                    "top_left_x": 100,
                    "top_left_y": 200,
                    "bottom_right_x": 600,
                    "bottom_right_y": 260,
                },
            ],
            "confidence_scores": {
                "average_page_confidence_score": 0.97,
                "minimum_page_confidence_score": 0.85,
                "word_confidence_scores": [
                    {"text": "Invoice", "confidence": 1.00, "start_index": 2},
                    {"text": "Account:", "confidence": 0.90, "start_index": 11},
                    {"text": "12345", "confidence": 0.80, "start_index": 20},
                    # "Total: $99.00" line has NO per-word entries -> page avg
                ],
            },
        }
    ],
    "usage_info": {"pages_processed": 1, "doc_size_bytes": 12345},
}


def test_markdown_and_blocks():
    text, textract, pages = index.build_textract_response(SAMPLE_RESPONSE)
    assert "Invoice" in text
    assert pages == 1

    blocks = textract["Blocks"]
    types = [b["BlockType"] for b in blocks]
    assert "PAGE" in types
    # One LINE per physical (non-empty) markdown line: 3 lines
    line_blocks = [b for b in blocks if b["BlockType"] == "LINE"]
    assert [b["Text"] for b in line_blocks] == [
        "# Invoice",
        "Account: 12345",
        "Total: $99.00",
    ]
    assert types.count("WORD") == 3  # three word confidence entries

    # Per-line confidence is the average of the words on that line:
    #   "# Invoice"      -> Invoice=100             -> 100.0
    #   "Account: 12345" -> (Account:90 + 12345:80) -> 85.0
    #   "Total: $99.00"  -> no words -> page avg 0.97 -> 97.0
    conf_by_text = {b["Text"]: b.get("Confidence") for b in line_blocks}
    assert conf_by_text["# Invoice"] == 100.0
    assert conf_by_text["Account: 12345"] == 85.0
    assert conf_by_text["Total: $99.00"] == 97.0

    # Geometry attached from the containing Mistral block, normalized to 0-1
    title_line = next(b for b in line_blocks if b["Text"] == "# Invoice")
    geom = title_line["Geometry"]["BoundingBox"]
    assert abs(geom["Left"] - 0.1) < 1e-6  # 100/1000
    assert abs(geom["Top"] - 0.025) < 1e-6  # 50/2000
    assert abs(geom["Width"] - 0.4) < 1e-6  # (500-100)/1000
    assert 0.0 < geom["Height"] <= 1.0

    # Per-word confidence scaled to 0-100
    word = next(
        b for b in blocks if b["BlockType"] == "WORD" and b["Text"] == "Invoice"
    )
    assert word["Confidence"] == 100.0
    print("test_markdown_and_blocks: PASS")


def test_no_words_falls_back_to_page_average():
    """When per-word scores are absent, every line gets the page average."""
    resp = {
        "pages": [
            {
                "index": 0,
                "markdown": "Line one\nLine two",
                "dimensions": {"width": 800, "height": 1000},
                "confidence_scores": {"average_page_confidence_score": 88.0},
            }
        ],
        "usage_info": {"pages_processed": 1},
    }
    text, textract, pages = index.build_textract_response(resp)
    line_blocks = [b for b in textract["Blocks"] if b["BlockType"] == "LINE"]
    assert len(line_blocks) == 2
    assert line_blocks[0]["Text"] == "Line one"
    # Already 0-100 scale, kept as-is
    assert line_blocks[0]["Confidence"] == 88.0
    assert line_blocks[1]["Confidence"] == 88.0
    print("test_no_words_falls_back_to_page_average: PASS")


def test_word_confidence_dict_shape():
    """word_confidence_scores as a {word: score} dict is also handled."""
    resp = {
        "pages": [
            {
                "index": 0,
                "markdown": "Hello world",
                "dimensions": {"width": 100, "height": 100},
                "blocks": [],
                "confidence_scores": {
                    "average_page_confidence_score": 0.95,
                    "word_confidence_scores": {"Hello": 0.9, "world": 0.8},
                },
            }
        ],
        "usage_info": {"pages_processed": 1},
    }
    _, textract, _ = index.build_textract_response(resp)
    words = {
        b["Text"]: b.get("Confidence")
        for b in textract["Blocks"]
        if b["BlockType"] == "WORD"
    }
    assert words == {"Hello": 90.0, "world": 80.0}
    print("test_word_confidence_dict_shape: PASS")


def test_empty_pages():
    text, textract, pages = index.build_textract_response({"pages": []})
    assert text == ""
    assert textract["Blocks"] == []
    print("test_empty_pages: PASS")


if __name__ == "__main__":
    test_markdown_and_blocks()
    test_no_words_falls_back_to_page_average()
    test_word_confidence_dict_shape()
    test_empty_pages()
    print("\nAll translation tests passed.")
