# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Assessment module for IDP Common Package.

This module provides services for assessing the confidence and accuracy
of extraction results by analyzing them against source documents.
"""

from .models import AssessmentResult, AttributeAssessment
from .service import AssessmentService

__all__ = ["AssessmentService", "AssessmentResult", "AttributeAssessment"]
