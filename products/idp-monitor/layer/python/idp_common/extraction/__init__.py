# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Extraction module for IDP documents.

This module provides services and models for extracting structured information
from documents using LLMs.
"""

from idp_common.extraction.models import ExtractedAttribute, ExtractionResult, PageInfo
from idp_common.extraction.service import ExtractionService

__all__ = ["ExtractionService", "ExtractedAttribute", "ExtractionResult", "PageInfo"]
