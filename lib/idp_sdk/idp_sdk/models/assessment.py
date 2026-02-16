# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Assessment operation models."""

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class AssessmentFieldConfidence:
    """Confidence data for a single field."""

    confidence: float
    confidence_threshold: Optional[float]
    reason: str
    meets_threshold: Optional[bool]


@dataclass
class AssessmentConfidenceResult:
    """Confidence assessment data for a document section."""

    document_id: str
    section_id: int
    attributes: Dict[str, AssessmentFieldConfidence]


@dataclass
class AssessmentFieldGeometry:
    """Spatial location data for a field."""

    page: int
    bbox: List[float]  # [x1, y1, x2, y2] in 0-1000 scale
    bounding_box: dict  # {top, left, width, height} in 0-1 scale


@dataclass
class AssessmentGeometryResult:
    """Spatial location data for a document section."""

    document_id: str
    section_id: int
    attributes: Dict[str, AssessmentFieldGeometry]


@dataclass
class AssessmentMetrics:
    """Aggregate quality metrics for a document."""

    document_id: str
    avg_confidence: float
    low_confidence_count: int
    fields_below_threshold: List[str]
    total_fields: int
