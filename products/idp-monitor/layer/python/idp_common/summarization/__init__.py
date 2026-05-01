# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Document summarization module for IDP Common Package.

This module provides functionality for summarizing documents using LLMs.
"""

from idp_common.summarization.models import DocumentSummary
from idp_common.summarization.service import SummarizationService

__all__ = ["SummarizationService", "DocumentSummary"]
