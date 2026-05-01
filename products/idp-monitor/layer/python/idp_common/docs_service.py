# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Document service factory module for IDP Common package.

This module provides a factory function to create document services based on
the DOCUMENT_TRACKING_MODE environment variable. It allows switching between
AppSync and DynamoDB implementations while maintaining the same interface.
"""

import logging
import os
from typing import Optional, Union

from idp_common.appsync import DocumentAppSyncService
from idp_common.dynamodb import DocumentDynamoDBService

logger = logging.getLogger(__name__)

# Supported document tracking modes
APPSYNC_MODE = "appsync"
DYNAMODB_MODE = "dynamodb"
SUPPORTED_MODES = [APPSYNC_MODE, DYNAMODB_MODE]

# Default mode
DEFAULT_MODE = APPSYNC_MODE


class DocumentServiceFactory:
    """
    Factory class for creating document services based on configuration.

    This factory allows switching between AppSync and DynamoDB implementations
    while maintaining the same interface for document operations.
    """

    @staticmethod
    def create_service(
        mode: Optional[str] = None, **kwargs
    ) -> Union[DocumentAppSyncService, DocumentDynamoDBService]:
        """
        Create a document service based on the specified mode.

        Args:
            mode: Optional mode override. If not provided, uses DOCUMENT_TRACKING_MODE
                  environment variable, defaulting to 'appsync'
            **kwargs: Additional arguments passed to the service constructor

        Returns:
            DocumentAppSyncService or DocumentDynamoDBService instance

        Raises:
            ValueError: If an unsupported mode is specified

        Examples:
            # Use environment variable (default behavior)
            service = DocumentServiceFactory.create_service()

            # Override mode explicitly
            service = DocumentServiceFactory.create_service(mode='dynamodb')

            # Pass additional arguments
            service = DocumentServiceFactory.create_service(
                mode='appsync',
                api_url='https://example.appsync-api.us-east-1.amazonaws.com/graphql'
            )
        """
        # Determine the mode
        if mode is None:
            mode = os.environ.get("DOCUMENT_TRACKING_MODE", DEFAULT_MODE).lower()
        else:
            mode = mode.lower()

        # Validate mode
        if mode not in SUPPORTED_MODES:
            raise ValueError(
                f"Unsupported document tracking mode: '{mode}'. "
                f"Supported modes are: {', '.join(SUPPORTED_MODES)}"
            )

        logger.info(f"Creating document service with mode: {mode}")

        # Create the appropriate service
        if mode == APPSYNC_MODE:
            return DocumentAppSyncService(**kwargs)
        elif mode == DYNAMODB_MODE:
            return DocumentDynamoDBService(**kwargs)
        else:
            # This should never happen due to validation above, but included for completeness
            raise ValueError(f"Unsupported mode: {mode}")

    @staticmethod
    def get_current_mode() -> str:
        """
        Get the current document tracking mode from environment variable.

        Returns:
            Current mode string ('appsync' or 'dynamodb')
        """
        return os.environ.get("DOCUMENT_TRACKING_MODE", DEFAULT_MODE).lower()

    @staticmethod
    def is_appsync_mode() -> bool:
        """
        Check if current mode is AppSync.

        Returns:
            True if current mode is AppSync, False otherwise
        """
        return DocumentServiceFactory.get_current_mode() == APPSYNC_MODE

    @staticmethod
    def is_dynamodb_mode() -> bool:
        """
        Check if current mode is DynamoDB.

        Returns:
            True if current mode is DynamoDB, False otherwise
        """
        return DocumentServiceFactory.get_current_mode() == DYNAMODB_MODE


# Convenience function for creating services
def create_document_service(
    mode: Optional[str] = None, **kwargs
) -> Union[DocumentAppSyncService, DocumentDynamoDBService]:
    """
    Convenience function to create a document service.

    This is a shorthand for DocumentServiceFactory.create_service().

    Args:
        mode: Optional mode override. If not provided, uses DOCUMENT_TRACKING_MODE
              environment variable, defaulting to 'appsync'
        **kwargs: Additional arguments passed to the service constructor

    Returns:
        DocumentAppSyncService or DocumentDynamoDBService instance

    Examples:
        # Simple usage
        service = create_document_service()

        # With mode override
        service = create_document_service(mode='dynamodb')

        # With additional parameters
        service = create_document_service(
            mode='appsync',
            api_url='https://example.appsync-api.us-east-1.amazonaws.com/graphql'
        )
    """
    return DocumentServiceFactory.create_service(mode=mode, **kwargs)


# Convenience functions for mode checking
def get_document_tracking_mode() -> str:
    """Get the current document tracking mode."""
    return DocumentServiceFactory.get_current_mode()


def is_appsync_mode() -> bool:
    """Check if current mode is AppSync."""
    return DocumentServiceFactory.is_appsync_mode()


def is_dynamodb_mode() -> bool:
    """Check if current mode is DynamoDB."""
    return DocumentServiceFactory.is_dynamodb_mode()


__all__ = [
    "DocumentServiceFactory",
    "create_document_service",
    "get_document_tracking_mode",
    "is_appsync_mode",
    "is_dynamodb_mode",
    "APPSYNC_MODE",
    "DYNAMODB_MODE",
    "DEFAULT_MODE",
]
