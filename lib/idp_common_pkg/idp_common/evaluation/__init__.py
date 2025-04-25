"""
Document evaluation functionality.

This module provides services and models for evaluating document extraction results.
"""

from idp_common.evaluation.models import (
    EvaluationMethod,
    EvaluationAttribute,
    AttributeEvaluationResult,
    SectionEvaluationResult,
    DocumentEvaluationResult
)
from idp_common.evaluation.service import EvaluationService
from idp_common.evaluation.comparator import (
    compare_values,
    compare_exact,
    compare_numeric,
    compare_fuzzy,
    compare_hungarian
)
from idp_common.evaluation.metrics import calculate_metrics

__all__ = [
    'EvaluationMethod',
    'EvaluationAttribute',
    'AttributeEvaluationResult',
    'SectionEvaluationResult',
    'DocumentEvaluationResult',
    'EvaluationService',
    'compare_values',
    'compare_exact',
    'compare_numeric',
    'compare_fuzzy',
    'compare_hungarian',
    'calculate_metrics'
]