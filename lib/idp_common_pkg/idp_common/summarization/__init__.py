"""
Document summarization module for IDP Common Package.

This module provides functionality for summarizing documents using LLMs.
"""

from idp_common.summarization.service import SummarizationService
from idp_common.summarization.models import DocumentSummary

__all__ = ["SummarizationService", "DocumentSummary"]
