# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Document evaluation functionality.

This module provides services and models for evaluating document extraction results
using the Stickler library for structured object comparison.
"""

# Legacy comparator functions (deprecated - kept for backward compatibility)
from idp_common.evaluation.comparator import (
    compare_exact,
    compare_fuzzy,
    compare_hungarian,
    compare_numeric,
    compare_values,
)

# Stickler integration components
from idp_common.evaluation.llm_comparator import LLMComparator

# Core evaluation components
from idp_common.evaluation.metrics import calculate_metrics
from idp_common.evaluation.models import (
    AttributeEvaluationResult,
    DocumentEvaluationResult,
    EvaluationAttribute,
    EvaluationMethod,
    SectionEvaluationResult,
)

# Stickler-based evaluation service (replaces legacy implementation)
from idp_common.evaluation.service import EvaluationService
from idp_common.evaluation.stickler_mapper import SticklerConfigMapper

__all__ = [
    # Core models and enums
    "EvaluationMethod",
    "EvaluationAttribute",
    "AttributeEvaluationResult",
    "SectionEvaluationResult",
    "DocumentEvaluationResult",
    # Main service (now Stickler-based)
    "EvaluationService",
    # Stickler components
    "SticklerConfigMapper",
    "LLMComparator",
    # Metrics
    "calculate_metrics",
    # Legacy comparison functions (deprecated)
    "compare_values",
    "compare_exact",
    "compare_numeric",
    "compare_fuzzy",
    "compare_hungarian",
]
