"""
Extraction module for IDP documents.

This module provides services and models for extracting structured information 
from documents using LLMs.
"""

from idp_common.extraction.service import ExtractionService
from idp_common.extraction.models import (
    ExtractedAttribute,
    ExtractionResult,
    PageInfo
)

__all__ = [
    'ExtractionService',
    'ExtractedAttribute',
    'ExtractionResult',
    'PageInfo'
]