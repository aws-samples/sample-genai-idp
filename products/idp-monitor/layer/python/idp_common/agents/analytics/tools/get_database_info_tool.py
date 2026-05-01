# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Tool for retrieving database schema information for the analytics agent.
"""

import logging
import time

from strands import tool

from ..analytics_logger import analytics_logger
from ..schema_provider import get_database_overview as _get_database_overview
from ..schema_provider import get_table_info as _get_table_info

logger = logging.getLogger(__name__)


@tool
def get_database_overview() -> str:
    """
    Get a fast, lightweight overview of available database tables with brief descriptions.

    This is the first step in a two-step progressive disclosure system for better performance.
    Use this to quickly understand what tables are available and which ones you need for your query.
    Then use get_table_info() to get detailed schemas for specific tables.

    Returns:
        str: Concise overview of all available tables with usage guidance
    """
    start_time = time.time()
    try:
        logger.info("Retrieving database overview")
        overview = _get_database_overview()
        logger.debug(f"Retrieved database overview of length: {len(overview)}")

        analytics_logger.log_content("get_database_overview", overview)
        return overview
    finally:
        analytics_logger.log_event("get_database_overview", time.time() - start_time)


@tool
def get_table_info(table_names: list[str]) -> str:
    """
    Get detailed schema information for specific database tables.

    This is the second step in a two-step progressive disclosure system. After using
    get_database_overview() to see what tables are available, use this tool to get
    complete column listings and sample queries for the tables you need.

    Args:
        table_names: List of table names to get detailed information for.
                    Common tables include: 'metering', 'document_sections_w2',
                    'document_evaluations', etc.

    Returns:
        str: Detailed schema information for the requested tables
    """
    start_time = time.time()
    try:
        logger.info(f"Retrieving detailed info for tables: {table_names}")
        table_info = _get_table_info(table_names)
        logger.debug(f"Retrieved table info of length: {len(table_info)}")

        analytics_logger.log_content("get_table_info", table_info)
        return table_info
    finally:
        analytics_logger.log_event("get_table_info", time.time() - start_time)
