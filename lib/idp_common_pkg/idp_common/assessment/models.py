# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Models for document assessment using LLMs.

This module provides data models for assessment results that evaluate
the confidence and accuracy of extraction results.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class AttributeAssessment:
    """Assessment result for a single extracted attribute"""

    attribute_name: str
    confidence: float
    confidence_reason: str
    extracted_value: Any = None


@dataclass
class AssessmentResult:
    """Result of assessment for a document section"""

    section_id: str
    document_class: str
    attribute_assessments: List[AttributeAssessment]
    overall_confidence: float = 0.0
    raw_response: Optional[str] = None
    metering: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    output_uri: Optional[str] = None


@dataclass
class DocumentAssessmentResult:
    """Assessment result for an entire document"""

    document_id: str
    section_assessments: List[AssessmentResult]
    overall_document_confidence: float = 0.0
    total_attributes_assessed: int = 0
    high_confidence_attributes: int = 0
    medium_confidence_attributes: int = 0
    low_confidence_attributes: int = 0
    assessment_summary: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
