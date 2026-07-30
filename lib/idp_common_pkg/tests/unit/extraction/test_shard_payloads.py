# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for ExtractionService._build_shard_payloads (input sharding).

These exercise the service-level sharding/prompt-rendering path without Bedrock
or Strands (pure prompt construction), so they run as plain unit tests.
"""

import pytest

from idp_common.extraction.service import ExtractionService

pytestmark = pytest.mark.unit

PROMPT = "Extract from:\n{DOCUMENT_TEXT}\nEnd."


def _service(max_batches: int = 4, budget: int = 5000) -> ExtractionService:
    cfg = {
        "extraction": {
            "task_prompt": PROMPT,
            "agentic": {
                "enabled": True,
                "max_concurrent_batches": max_batches,
                "shard_token_budget": budget,
            },
        },
        "classes": [
            {"$id": "Doc", "type": "object", "properties": {"x": {"type": "string"}}}
        ],
    }
    svc = ExtractionService(region="us-west-2", config=cfg)
    svc._class_label = "Doc"
    svc._class_schema = cfg["classes"][0]
    svc._attribute_descriptions = "x: a field"
    return svc


def _set_pages(svc: ExtractionService, page_texts: list[str]) -> None:
    svc._page_texts = page_texts
    svc._document_text = "\n".join(page_texts)
    svc._page_images = []


def _shard_text(payload) -> str:
    return "".join(c.get("text", "") for c in payload["content"])


class TestBuildShardPayloads:
    def test_dense_pages_split_and_cover_all(self):
        svc = _service(max_batches=4, budget=5000)
        _set_pages(svc, [f"PAGE{i} " + ("w" * 12000) for i in range(6)])
        payloads = svc._build_shard_payloads(
            prompt_template=PROMPT, send_images=False, max_shards=4
        )
        assert len(payloads) == 4  # cap binds
        # contiguous full coverage
        prev = 0
        for p in payloads:
            assert p["page_start"] == prev
            prev = p["page_end"]
        assert prev == 6

    def test_header_context_only_on_later_shards(self):
        svc = _service(max_batches=4, budget=5000)
        _set_pages(svc, [f"PAGE{i} " + ("w" * 12000) for i in range(6)])
        payloads = svc._build_shard_payloads(
            prompt_template=PROMPT, send_images=False, max_shards=4
        )
        assert "DOCUMENT HEADER" not in _shard_text(payloads[0])
        assert all("DOCUMENT HEADER" in _shard_text(p) for p in payloads[1:])

    def test_restores_instance_state(self):
        svc = _service()
        pages = [f"PAGE{i} " + ("w" * 12000) for i in range(6)]
        _set_pages(svc, pages)
        svc._build_shard_payloads(
            prompt_template=PROMPT, send_images=False, max_shards=4
        )
        # _document_text / _page_images must be restored to the full section.
        assert svc._document_text == "\n".join(pages)
        assert svc._page_images == []

    def test_small_doc_returns_no_shards(self):
        # Light content that fits one budget -> single shard -> caller uses single pass.
        svc = _service(max_batches=4, budget=40000)
        _set_pages(svc, ["short page a", "short page b", "short page c"])
        payloads = svc._build_shard_payloads(
            prompt_template=PROMPT, send_images=False, max_shards=4
        )
        assert payloads == []

    def test_single_page_returns_no_shards(self):
        svc = _service()
        _set_pages(svc, ["only one page " + "w" * 100000])
        payloads = svc._build_shard_payloads(
            prompt_template=PROMPT, send_images=False, max_shards=4
        )
        assert payloads == []

    def test_page_markers_present_in_shard_text(self):
        svc = _service(max_batches=4, budget=5000)
        _set_pages(svc, [f"content{i} " + ("w" * 12000) for i in range(6)])
        payloads = svc._build_shard_payloads(
            prompt_template=PROMPT, send_images=False, max_shards=4
        )
        # Each shard's text uses 1-based PAGE markers for its own pages.
        first = _shard_text(payloads[0])
        assert "--- PAGE 1 ---" in first


class TestTableHeaderContext:
    """Header context prepended to later shards must include the table column
    header but DROP page-1 data rows (else the parser re-emits them -> dup)."""

    def test_truncates_at_markdown_separator(self):
        txt = (
            "# Statement\n\nAccount: X\n\n"
            "| RowID | Symbol |\n|-------|--------|\n"
            "| 1 | A |\n| 2 | B |\n| 3 | C |"
        )
        out = ExtractionService._table_header_context(txt)
        assert "| RowID | Symbol |" in out  # column header kept
        assert "|-------|--------|" in out  # separator kept
        assert "| 1 | A |" not in out  # data rows dropped
        assert "| 2 | B |" not in out

    def test_non_table_falls_back_to_line_cap(self):
        txt = "\n".join(f"line{i}" for i in range(50))
        out = ExtractionService._table_header_context(txt, max_lines=10)
        assert out.count("\n") == 9  # 10 lines
        assert "line0" in out and "line49" not in out

    def test_empty(self):
        assert ExtractionService._table_header_context("") == ""


class TestAnalyzeSchemaMinItems:
    """minItems can arrive as a string after a config round-trip; the schema
    analysis must coerce it instead of raising TypeError on `min_items > 50`."""

    def test_string_min_items_does_not_raise(self):
        svc = _service()
        schema = {
            "properties": {
                "rows": {"type": "array", "minItems": "100", "description": "t"}
            }
        }
        result = svc._analyze_schema_for_table_requirements(schema)
        assert result["tool_usage_recommended"] is True

    def test_string_min_items_below_threshold(self):
        svc = _service()
        schema = {"properties": {"rows": {"type": "array", "minItems": "5"}}}
        result = svc._analyze_schema_for_table_requirements(schema)
        assert result["tool_usage_recommended"] is False

    def test_invalid_min_items_treated_as_zero(self):
        svc = _service()
        schema = {"properties": {"rows": {"type": "array", "minItems": "abc"}}}
        result = svc._analyze_schema_for_table_requirements(schema)
        assert result["tool_usage_recommended"] is False
