# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Document evaluation functionality.

This module provides services and models for evaluating document extraction results.
"""

from idp_common.evaluation.comparator import (
    compare_exact,
    compare_fuzzy,
    compare_hungarian,
    compare_numeric,
    compare_values,
)
from idp_common.evaluation.metrics import calculate_metrics
from idp_common.evaluation.models import (
    AttributeEvaluationResult,
    DocumentEvaluationResult,
    EvaluationAttribute,
    EvaluationMethod,
    SectionEvaluationResult,
)
from idp_common.evaluation.service import EvaluationService
from idp_common.evaluation.stickler_service import SticklerEvaluationService

__all__ = [
    "EvaluationMethod",
    "EvaluationAttribute",
    "AttributeEvaluationResult",
    "SectionEvaluationResult",
    "DocumentEvaluationResult",
    "EvaluationService",
    "SticklerEvaluationService",
    "compare_values",
    "compare_exact",
    "compare_numeric",
    "compare_fuzzy",
    "compare_hungarian",
    "calculate_metrics",
]
