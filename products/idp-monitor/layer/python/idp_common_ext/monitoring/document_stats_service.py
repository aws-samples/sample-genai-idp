# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Backward-compatibility shim for ``DocumentStatsService``.

The real implementation has been refactored into two separate classes:

* :class:`~idp_common.monitoring.operational_document_service.OperationalDocumentService`
  — real-time DynamoDB queries (volume, status, failures, doc-type distribution,
  config info).  This is the direct replacement for ``DocumentStatsService``.

* :class:`~idp_common.monitoring.analytics_cost_service.AnalyticsCostService`
  — cost/token analytics via Athena (10–30× faster, historical data, GROUP BY
  aggregations).  The ``get_cost_metrics()`` method previously on
  ``DocumentStatsService`` has moved here.

This file keeps ``DocumentStatsService`` as a live alias so all existing imports
continue to work without any change::

    # Still works — resolves to OperationalDocumentService
    from idp_common_ext.monitoring import DocumentStatsService
    from idp_common_ext.monitoring.document_stats_service import DocumentStatsService

Deprecation notice:
    Prefer ``OperationalDocumentService`` for new code.
    Use ``AnalyticsCostService.get_cost_metrics()`` for cost/token queries.
"""

from idp_common_ext.monitoring.operational_document_service import (
    OperationalDocumentService,
)  # noqa: F401

# Legacy alias — prefer OperationalDocumentService for new code
DocumentStatsService = OperationalDocumentService

__all__ = ["DocumentStatsService"]
