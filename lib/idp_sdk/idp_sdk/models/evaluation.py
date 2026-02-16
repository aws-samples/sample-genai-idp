# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Evaluation operation models."""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class BaselineResult:
    """Result from baseline creation."""

    document_id: str
    status: str  # "BASELINE_COPYING", "BASELINE_AVAILABLE", "BASELINE_ERROR"
    s3_location: str
    created_date: Optional[datetime] = None


@dataclass
class BaselineInfo:
    """Information about a baseline."""

    document_id: str
    s3_location: str
    created_date: datetime
    size_bytes: Optional[int] = None


@dataclass
class EvaluationBaselineListResult:
    """Paginated list of baselines."""

    baselines: List[BaselineInfo]
    next_token: Optional[str] = None
    total_count: Optional[int] = None


@dataclass
class FieldComparison:
    """Field-level comparison result."""

    attribute: str
    expected: str
    actual: str
    matched: bool
    score: float
    method: str
    reason: str


@dataclass
class EvaluationReport:
    """Evaluation report for a document."""

    document_id: str
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    field_comparisons: List[FieldComparison]
    markdown_report: Optional[str] = None
    json_report: Optional[dict] = None


@dataclass
class EvaluationMetrics:
    """Aggregate evaluation metrics."""

    total_documents: int
    avg_accuracy: float
    avg_precision: float
    avg_recall: float
    avg_f1_score: float
    start_date: Optional[str] = None
    end_date: Optional[str] = None


@dataclass
class DeleteResult:
    """Result from delete operation."""

    document_id: str
    status: str  # "DELETED", "NOT_FOUND", "ERROR"
    message: Optional[str] = None
