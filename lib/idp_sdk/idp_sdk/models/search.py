# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Search operation models."""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class SearchCitation:
    """Citation reference to source document."""

    document_id: str
    page: int
    text: str


@dataclass
class SearchDocumentReference:
    """Reference to a source document."""

    document_id: str
    title: Optional[str] = None
    metadata: Optional[dict] = None


@dataclass
class SearchResult:
    """Result from knowledge base query."""

    answer: str
    citations: List[SearchCitation]
    sources: List[SearchDocumentReference]
    confidence: Optional[float] = None
    next_token: Optional[str] = None
