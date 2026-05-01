# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Low-level Athena query execution service for monitoring analytics.

Handles query submission, polling, result retrieval, and row-to-dict
conversion.  No business logic lives here — this is a thin wrapper around
boto3's Athena client used exclusively by the higher-level analytics services
(``AnalyticsCostService``, ``AnalyticsEvaluationService``).

Environment variables read:
    ATHENA_DATABASE        — Glue database name (e.g. ``mystack-reporting-db``)
    ATHENA_OUTPUT_LOCATION — S3 URI for query results (e.g. ``s3://bucket/athena-results/``)

Graceful degradation:
    When either env var is absent, ``is_configured()`` returns ``False`` and all
    query methods return ``None`` / ``[]`` rather than raising.  This ensures
    stacks deployed without a reporting bucket continue to work as before.

Usage::

    from idp_common_ext.monitoring.analytics_athena_service import AnalyticsAthenaService

    athena = AnalyticsAthenaService()
    if athena.is_configured():
        rows = athena.execute_query("SELECT COUNT(*) FROM metering")
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

import boto3

logger = logging.getLogger(__name__)

# Athena query terminal states
_TERMINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELLED"}


class AnalyticsNotConfiguredError(Exception):
    """Raised when Athena environment variables are not set."""


class AnalyticsQueryError(Exception):
    """Raised when an Athena query fails or times out."""


class AnalyticsAthenaService:
    """
    Low-level Athena query execution service for monitoring analytics.

    Handles query submission, polling, result retrieval, and row-to-dict
    conversion.  All higher-level analytics services delegate to this class.

    Usage::

        athena = AnalyticsAthenaService()
        if athena.is_configured():
            rows = athena.execute_query(
                "SELECT service_api, SUM(estimated_cost) AS cost "
                "FROM metering WHERE date = '2025-01-01' GROUP BY service_api"
            )
    """

    def __init__(
        self,
        database: Optional[str] = None,
        output_location: Optional[str] = None,
        region: Optional[str] = None,
        poll_interval_seconds: float = 1.0,
        timeout_seconds: int = 60,
    ) -> None:
        """
        Args:
            database:              Glue database name.  Defaults to env var
                                   ``ATHENA_DATABASE``.
            output_location:       S3 URI for results.  Defaults to env var
                                   ``ATHENA_OUTPUT_LOCATION``.
            region:                AWS region.  Defaults to boto3 session region.
            poll_interval_seconds: Seconds to wait between status polls (default 1).
            timeout_seconds:       Maximum seconds to wait for a query (default 60).
        """
        self._database = database or os.environ.get("ATHENA_DATABASE", "")
        self._output_location = output_location or os.environ.get(
            "ATHENA_OUTPUT_LOCATION", ""
        )
        self._region = region
        self._poll_interval = poll_interval_seconds
        self._timeout = timeout_seconds
        self._client: Optional[Any] = None

    # ------------------------------------------------------------------
    # Configuration check
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        """Return ``True`` if both Athena environment variables are set."""
        return bool(self._database and self._output_location)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_client(self) -> Any:
        """Lazily create and cache the Athena boto3 client."""
        if self._client is None:
            kwargs: Dict[str, Any] = {}
            if self._region:
                kwargs["region_name"] = self._region
            self._client = boto3.client("athena", **kwargs)
        return self._client

    def _start_query(self, query: str) -> str:
        """
        Submit a query to Athena and return the execution ID.

        Args:
            query: SQL query string.

        Returns:
            Athena query execution ID.

        Raises:
            AnalyticsNotConfiguredError: If Athena env vars are not set.
            AnalyticsQueryError:         On boto3 errors.
        """
        if not self.is_configured():
            raise AnalyticsNotConfiguredError(
                "ATHENA_DATABASE and ATHENA_OUTPUT_LOCATION must be set"
            )

        client = self._get_client()
        try:
            response = client.start_query_execution(
                QueryString=query,
                QueryExecutionContext={"Database": self._database},
                ResultConfiguration={"OutputLocation": self._output_location},
            )
            return response["QueryExecutionId"]
        except Exception as exc:
            raise AnalyticsQueryError(f"Failed to start Athena query: {exc}") from exc

    def _wait_for_query(self, execution_id: str, timeout_seconds: Optional[int]) -> str:
        """
        Poll until the query reaches a terminal state.

        Args:
            execution_id:    Athena query execution ID.
            timeout_seconds: Max seconds to wait; falls back to ``self._timeout``.

        Returns:
            Terminal state string: ``"SUCCEEDED"`` if successful.

        Raises:
            AnalyticsQueryError: If the query fails, is cancelled, or times out.
        """
        client = self._get_client()
        deadline = time.monotonic() + (timeout_seconds or self._timeout)

        while True:
            try:
                resp = client.get_query_execution(QueryExecutionId=execution_id)
                status = resp["QueryExecution"]["Status"]
                state = status["State"]
            except Exception as exc:
                raise AnalyticsQueryError(
                    f"Failed to poll Athena query {execution_id}: {exc}"
                ) from exc

            if state in _TERMINAL_STATES:
                if state != "SUCCEEDED":
                    reason = status.get("StateChangeReason", "unknown reason")
                    raise AnalyticsQueryError(
                        f"Athena query {execution_id} ended with state {state}: {reason}"
                    )
                return state

            if time.monotonic() > deadline:
                raise AnalyticsQueryError(
                    f"Athena query {execution_id} timed out after "
                    f"{timeout_seconds or self._timeout}s"
                )

            time.sleep(self._poll_interval)

    def _fetch_results(self, execution_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve all rows from a completed Athena query as a list of dicts.

        The first row from Athena's GetQueryResults is the header row.  This
        method extracts column names from that header and maps subsequent rows
        to dicts keyed by column name.

        Args:
            execution_id: Athena query execution ID (must be in SUCCEEDED state).

        Returns:
            List of dicts, one per data row, keyed by column name.

        Raises:
            AnalyticsQueryError: On boto3 errors.
        """
        client = self._get_client()
        rows: List[Dict[str, Any]] = []
        next_token: Optional[str] = None
        header: Optional[List[str]] = None

        while True:
            try:
                kwargs: Dict[str, Any] = {
                    "QueryExecutionId": execution_id,
                    "MaxResults": 1000,
                }
                if next_token:
                    kwargs["NextToken"] = next_token

                resp = client.get_query_results(**kwargs)
                result_set = resp.get("ResultSet", {})
                raw_rows = result_set.get("Rows", [])
                column_info = result_set.get("ResultSetMetadata", {}).get(
                    "ColumnInfo", []
                )

                # Extract header from column metadata on first page
                if header is None:
                    if column_info:
                        header = [col["Name"] for col in column_info]
                    elif raw_rows:
                        # Fallback: first row is the header
                        header = [
                            d.get("VarCharValue", "")
                            for d in raw_rows[0].get("Data", [])
                        ]
                        raw_rows = raw_rows[1:]  # skip header row

                if header is None:
                    break

                for raw_row in raw_rows:
                    data = raw_row.get("Data", [])
                    row_dict: Dict[str, Any] = {}
                    for i, cell in enumerate(data):
                        col_name = header[i] if i < len(header) else f"col_{i}"
                        row_dict[col_name] = cell.get("VarCharValue")
                    rows.append(row_dict)

                next_token = resp.get("NextToken")
                if not next_token:
                    break

            except Exception as exc:
                raise AnalyticsQueryError(
                    f"Failed to fetch Athena query results for {execution_id}: {exc}"
                ) from exc

        return rows

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute_query(
        self,
        query: str,
        timeout_seconds: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute a SQL query and return all rows as a list of dicts.

        This is the primary method used by higher-level analytics services.
        Each row is a dict keyed by column name with string values (Athena
        always returns values as strings — callers must cast as needed).

        Args:
            query:           SQL query string.
            timeout_seconds: Override the default timeout for this query.

        Returns:
            List of row dicts.  Empty list if no rows returned.

        Raises:
            AnalyticsNotConfiguredError: If Athena env vars are not set.
            AnalyticsQueryError:         If the query fails or times out.
        """
        execution_id = self._start_query(query)
        logger.debug("Athena query started: %s", execution_id)

        self._wait_for_query(execution_id, timeout_seconds)
        logger.debug("Athena query succeeded: %s", execution_id)

        rows = self._fetch_results(execution_id)
        logger.debug("Athena query returned %d rows: %s", len(rows), execution_id)
        return rows

    def execute_query_scalar(
        self,
        query: str,
        timeout_seconds: Optional[int] = None,
    ) -> Optional[Any]:
        """
        Execute a query that returns a single value (first column of first row).

        Convenience wrapper for aggregation queries such as ``SELECT COUNT(*)``.

        Args:
            query:           SQL query string.
            timeout_seconds: Override the default timeout.

        Returns:
            The scalar value as a string, or ``None`` if no rows were returned.

        Raises:
            AnalyticsNotConfiguredError: If Athena env vars are not set.
            AnalyticsQueryError:         If the query fails or times out.
        """
        rows = self.execute_query(query, timeout_seconds=timeout_seconds)
        if not rows:
            return None
        first_row = rows[0]
        if not first_row:
            return None
        return next(iter(first_row.values()), None)
