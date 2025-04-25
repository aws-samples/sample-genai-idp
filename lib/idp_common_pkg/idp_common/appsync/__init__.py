"""
AppSync integration module for IDP Common package.

This module provides classes and functions for interacting with AWS AppSync
to store and retrieve document data.
"""

from idp_common.appsync.client import AppSyncClient, AppSyncError
from idp_common.appsync.mutations import CREATE_DOCUMENT, UPDATE_DOCUMENT
from idp_common.appsync.service import DocumentAppSyncService

__all__ = [
    'AppSyncClient', 
    'AppSyncError',
    'CREATE_DOCUMENT',
    'UPDATE_DOCUMENT',
    'DocumentAppSyncService'
]