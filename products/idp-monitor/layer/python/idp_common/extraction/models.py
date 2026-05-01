# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Models for document extraction using LLMs.

This module provides data models for extraction results.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ExtractedAttribute:
    """A single extracted attribute from a document"""

    name: str
    value: Any
    confidence: float = 1.0


@dataclass
class ExtractionResult:
    """Result of extraction for a document section"""

    section_id: str
    document_class: str
    attributes: List[ExtractedAttribute]
    raw_response: Optional[str] = None
    metering: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    output_uri: Optional[str] = None


@dataclass
class PageInfo:
    """Information about a page used in extraction"""

    page_id: str
    text_uri: Optional[str] = None
    image_uri: Optional[str] = None
    raw_text_uri: Optional[str] = None
