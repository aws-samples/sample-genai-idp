# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Extraction-completeness ProcessingIssues (ExtractionService._build_extraction_issues).

An extraction that PARSES but under-produces (e.g. an empty large-table list on
Simple mode) must NOT be reported as a clean success — it emits an
``extraction_incomplete`` warning, and when Simple mode under-produced it
recommends Advanced (agentic) extraction.
"""

from __future__ import annotations

from idp_common.config.models import IDPConfig
from idp_common.extraction.service import ExtractionService


def _svc(*, agentic: bool):
    cfg = IDPConfig(**{"extraction": {"agentic": {"enabled": agentic}}})
    svc = ExtractionService(config=cfg)
    # A schema with one array field (the large table) + a scalar.
    svc._class_schema = {
        "type": "object",
        "properties": {
            "PortfolioDetail": {"type": "array", "items": {"type": "object"}},
            "AccountNumber": {"type": "string"},
        },
    }
    svc._pending_extraction_model = "us.anthropic.claude-sonnet-5"
    return svc


def test_empty_list_field_flags_extraction_incomplete_simple_recommends_advanced():
    svc = _svc(agentic=False)
    issues = svc._build_extraction_issues(
        extracted_fields={"PortfolioDetail": [], "AccountNumber": "X"},
        metadata={},
        section_id="2",
    )
    codes = [i.code for i in issues]
    assert "extraction_incomplete" in codes
    inc = next(i for i in issues if i.code == "extraction_incomplete")
    assert inc.severity == "warning"
    assert "PortfolioDetail" in inc.message
    # Simple mode → recommends Advanced (agentic) extraction.
    assert "agentic" in inc.message.lower() or "advanced" in inc.message.lower()


def test_empty_list_field_advanced_does_not_recommend_advanced():
    svc = _svc(agentic=True)
    issues = svc._build_extraction_issues(
        extracted_fields={"PortfolioDetail": [], "AccountNumber": "X"},
        metadata={},
        section_id="2",
    )
    inc = next(i for i in issues if i.code == "extraction_incomplete")
    # Already agentic → no "switch to advanced" recommendation.
    assert "recommended" not in inc.message.lower()


def test_populated_list_produces_no_extraction_incomplete():
    svc = _svc(agentic=False)
    issues = svc._build_extraction_issues(
        extracted_fields={"PortfolioDetail": [{"a": 1}], "AccountNumber": "X"},
        metadata={},
        section_id="1",
    )
    assert not any(i.code == "extraction_incomplete" for i in issues)


def test_below_threshold_population_flags_sparse():
    svc = _svc(agentic=True)
    issues = svc._build_extraction_issues(
        extracted_fields={"PortfolioDetail": [{"a": 1}], "AccountNumber": "X"},
        metadata={
            "population_check": {
                "fields_populated": 1,
                "fields_defined": 10,
                "population_ratio": 0.1,
                "threshold": 0.5,
                "below_threshold": True,
                "empty_fields": ["x", "y"],
            }
        },
        section_id="1",
    )
    assert any(i.code == "extraction_sparse" and i.severity == "info" for i in issues)
