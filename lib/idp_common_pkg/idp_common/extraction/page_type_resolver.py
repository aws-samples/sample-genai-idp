# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Page-type resolution for the extraction pipeline.

Given a section's per-page OCR text and a class JSON Schema that declares
named page sub-types via ``x-aws-idp-page-types`` (each carrying a
``x-aws-idp-document-page-content-regex``), determine which page sub-types
are present in the section and which are absent. This information lets the
extraction service distinguish properties whose source pages were submitted
(BLANK if empty) from those whose source pages were omitted (MISSING).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from idp_common.config.schema_constants import (
    X_AWS_IDP_PAGE_CONTENT_REGEX,
    X_AWS_IDP_PAGE_TYPES,
)

logger = logging.getLogger(__name__)


@dataclass
class PageTypePresence:
    """Page-type detection result for a single section."""

    present_page_types: set[str] = field(default_factory=set)
    missing_page_types: set[str] = field(default_factory=set)
    page_id_to_page_type: dict[str, str] = field(default_factory=dict)
    declared: bool = False

    def to_output_dict(self) -> dict[str, Any]:
        """Render for inclusion in the section's result.json."""
        return {
            "declared": self.declared,
            "present_page_types": sorted(self.present_page_types),
            "missing_page_types": sorted(self.missing_page_types),
            "page_id_to_page_type": dict(self.page_id_to_page_type),
        }


def _compile_page_type_patterns(
    class_schema: dict[str, Any],
) -> list[tuple[str, re.Pattern[str]]]:
    """Extract and compile ``(name, pattern)`` pairs from a class schema.

    Page-type entries without a name or without a valid regex are skipped
    with a warning so a single bad entry doesn't break the whole resolver.
    """
    page_types_raw = class_schema.get(X_AWS_IDP_PAGE_TYPES) or []
    if not isinstance(page_types_raw, list):
        logger.warning(
            "Ignoring %s: expected a list, got %s",
            X_AWS_IDP_PAGE_TYPES,
            type(page_types_raw).__name__,
        )
        return []

    compiled: list[tuple[str, re.Pattern[str]]] = []
    for entry in page_types_raw:
        if not isinstance(entry, dict):
            logger.warning("Skipping non-dict page-type entry: %r", entry)
            continue
        name = entry.get("name")
        pattern_str = entry.get(X_AWS_IDP_PAGE_CONTENT_REGEX)
        if not name or not pattern_str:
            logger.warning(
                "Skipping page-type entry missing 'name' or %s: %r",
                X_AWS_IDP_PAGE_CONTENT_REGEX,
                entry,
            )
            continue
        try:
            compiled.append((name, re.compile(pattern_str)))
        except re.error as exc:
            logger.warning(
                "Skipping page-type %s with invalid regex %r: %s",
                name,
                pattern_str,
                exc,
            )
    return compiled


def resolve_page_types(
    class_schema: dict[str, Any],
    page_id_to_text: dict[str, str],
) -> PageTypePresence:
    """Detect which declared page sub-types appear in this section's pages.

    First match wins per page — page-type ordering in config is the
    precedence. Pages that match nothing are left out of
    ``page_id_to_page_type`` entirely.
    """
    patterns = _compile_page_type_patterns(class_schema)
    if not patterns:
        return PageTypePresence(declared=False)

    declared_names = {name for name, _ in patterns}
    page_id_to_page_type: dict[str, str] = {}
    present: set[str] = set()

    for page_id, text in page_id_to_text.items():
        if not text:
            continue
        for name, pattern in patterns:
            if pattern.search(text):
                page_id_to_page_type[page_id] = name
                present.add(name)
                break

    return PageTypePresence(
        declared=True,
        present_page_types=present,
        missing_page_types=declared_names - present,
        page_id_to_page_type=page_id_to_page_type,
    )
