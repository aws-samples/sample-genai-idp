# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Discovery module for IDP document class discovery.

Provides both single-document discovery (ClassesDiscovery) and
multi-document discovery with clustering and agentic analysis.
"""

from idp_common.discovery.classes_discovery import ClassesDiscovery

# MultiDocumentDiscovery and MultiDocDiscoveryResult are imported lazily
# to avoid pulling in heavy dependencies (scikit-learn, scipy, numpy)
# unless the multi_document_discovery extra is installed.
# Usage: from idp_common.discovery.multi_document_discovery import MultiDocumentDiscovery

__all__ = [
    "ClassesDiscovery",
]
