# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Assessment module for document extraction confidence evaluation.

This module provides services for assessing the confidence and accuracy of
extraction results by analyzing them against source documents using LLMs.

Large lists (e.g. hundreds of transaction rows) are handled by the standalone
:class:`AssessmentService`, which batches oversized list fields via
``extraction.confidence.list_batch_size`` (see ``assessment/batching.py``). The
former "granular assessment" service has been retired.
"""

import logging
from typing import Optional

from idp_common.config.models import IDPConfig

from .models import AssessmentResult, AttributeAssessment
from .service import AssessmentService as OriginalAssessmentService

logger = logging.getLogger(__name__)


class AssessmentService:
    """
    Backward-compatible AssessmentService wrapper.

    Retained for API compatibility with callers that constructed
    ``idp_common.assessment.AssessmentService`` directly. It now always delegates
    to the standalone :class:`~idp_common.assessment.service.AssessmentService`
    (the granular implementation has been removed).
    """

    def __init__(self, region: str | None = None, config: IDPConfig | None = None):
        """
        Initialize the assessment service.

        Args:
            region: AWS region for Bedrock
            config: Configuration dictionary
        """
        if config is None:
            config = IDPConfig()
        elif isinstance(config, dict):
            config = IDPConfig(**config)

        self._service = create_assessment_service(region=region, config=config)

    def process_document_section(
        self, document, section_id: str, deadline_epoch: Optional[float] = None
    ):
        """Process a single section from a Document object to assess extraction confidence.

        ``deadline_epoch`` (absolute epoch seconds from the Lambda context) is
        forwarded to the self-healing ladder's wall-clock guard (1.5).
        """
        return self._service.process_document_section(
            document, section_id, deadline_epoch=deadline_epoch
        )

    def assess_document(self, document):
        """Assess extraction confidence for all sections in a document."""
        return self._service.assess_document(document)


def create_assessment_service(
    region: Optional[str] = None, config: Optional[IDPConfig] = None
):
    """
    Factory function to create the assessment service.

    Always returns the standalone :class:`OriginalAssessmentService`, which
    batches large list fields on its own. Kept as a factory for API stability.

    Args:
        region: AWS region for Bedrock
        config: Configuration dictionary

    Returns:
        OriginalAssessmentService
    """
    if not config:
        config = IDPConfig()
    return OriginalAssessmentService(region=region, config=config)


__all__ = [
    "AssessmentService",
    "OriginalAssessmentService",
    "AssessmentResult",
    "AttributeAssessment",
    "create_assessment_service",
]
