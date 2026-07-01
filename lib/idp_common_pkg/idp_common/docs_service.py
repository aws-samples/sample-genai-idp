# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Document service factory module for IDP Common package.

Document tracking is backed by **DynamoDB** (the TrackingTable). AppSync support
has been removed — the solution now uses an API Gateway HTTP API for the UI and
writes document state directly to DynamoDB. The factory API is retained for
backward compatibility with existing call sites; any ``mode`` argument is
accepted but ignored (DynamoDB is always used).
"""

import logging
from typing import Optional

from idp_common.dynamodb import DocumentDynamoDBService

logger = logging.getLogger(__name__)

# Retained for backward compatibility with callers that reference these.
DYNAMODB_MODE = "dynamodb"
SUPPORTED_MODES = [DYNAMODB_MODE]
DEFAULT_MODE = DYNAMODB_MODE


class DocumentServiceFactory:
    """Factory for the document service. Always returns a DynamoDB-backed service."""

    @staticmethod
    def create_service(mode: Optional[str] = None, **kwargs) -> DocumentDynamoDBService:
        """Create the DynamoDB-backed document service.

        The ``mode`` argument is accepted for backward compatibility but ignored;
        only DynamoDB is supported. ``api_url`` (a legacy AppSync kwarg) is
        dropped if present.
        """
        kwargs.pop("api_url", None)
        return DocumentDynamoDBService(**kwargs)

    @staticmethod
    def get_current_mode() -> str:
        return DYNAMODB_MODE

    @staticmethod
    def is_appsync_mode() -> bool:
        return False

    @staticmethod
    def is_dynamodb_mode() -> bool:
        return True


# Convenience function for creating services
def create_document_service(
    mode: Optional[str] = None, **kwargs
) -> DocumentDynamoDBService:
    """Create the DynamoDB-backed document service (``mode`` is ignored)."""
    return DocumentServiceFactory.create_service(mode=mode, **kwargs)


def get_document_tracking_mode() -> str:
    """Return the document tracking mode (always 'dynamodb')."""
    return DYNAMODB_MODE


def is_appsync_mode() -> bool:
    """AppSync has been removed; always False."""
    return False


def is_dynamodb_mode() -> bool:
    """DynamoDB is the only backend; always True."""
    return True


__all__ = [
    "DocumentServiceFactory",
    "create_document_service",
    "get_document_tracking_mode",
    "is_appsync_mode",
    "is_dynamodb_mode",
    "DYNAMODB_MODE",
    "DEFAULT_MODE",
]
