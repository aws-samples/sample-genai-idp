"""
Classification module for IDP Common Package.

Provides a service for classifying documents using LLMs.
"""

from idp_common.classification.service import ClassificationService
from idp_common.classification.models import DocumentClassification, ClassificationResult

__all__ = ['ClassificationService', 'DocumentClassification', 'ClassificationResult']