# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Document evaluation functionality.

This module provides services and models for evaluating document extraction results
using the Stickler library for structured object comparison.
"""

# Stickler integration components
from idp_common.evaluation.llm_comparator import LLMComparator
from idp_common.evaluation.models import (
    AttributeEvaluationResult,
    DocumentEvaluationResult,
    EvaluationAttribute,
    EvaluationMethod,
    SectionEvaluationResult,
)

# Stickler-based evaluation service
from idp_common.evaluation.service import EvaluationService
from idp_common.evaluation.stickler_mapper import SticklerConfigMapper

__all__ = [
    # Core models and enums
    "EvaluationMethod",
    "EvaluationAttribute",
    "AttributeEvaluationResult",
    "SectionEvaluationResult",
    "DocumentEvaluationResult",
    # Main service (Stickler-based)
    "EvaluationService",
    # Stickler components
    "SticklerConfigMapper",
    "LLMComparator",
]
