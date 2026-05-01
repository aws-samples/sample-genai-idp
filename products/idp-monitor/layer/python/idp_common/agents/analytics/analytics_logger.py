# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Analytics agent logger utility for monitoring tool execution and context flow.
"""

import json
import logging
from typing import Any, Dict, List


class AnalyticsLogger:
    """Logger for analytics agent events and content."""

    def __init__(self):
        self._events: Dict[str, str] = {}  # event -> time_string mapping
        self._event_counters: Dict[str, int] = {}  # track multiple calls
        self._queries: List[str] = []  # capture all queries for debugging
        self._logger = logging.getLogger(__name__)

    def log_event(self, event: str, duration: float) -> None:
        """
        Log event execution time and store in events map.

        Args:
            event: Name of the event/tool that was executed
            duration: Duration in seconds
        """
        # Handle multiple calls by adding counter
        if event in self._event_counters:
            self._event_counters[event] += 1
            event_key = f"{event}_{self._event_counters[event]}"
        else:
            self._event_counters[event] = 1
            event_key = f"{event}_1"

        duration_str = f"{duration:.2f}"
        self._events[event_key] = duration_str

        self._logger.info(f"[{event}][{duration_str}s]")

    def log_content(self, event: str, content: Any, mode: str = "size") -> None:
        """
        Log content with different display modes (separate from events map).

        Args:
            event: Name of the event for context
            content: Content to log
            mode: Display mode - "size", "preview", or "full"
        """
        if content is None:
            self._logger.info(f"[{event}] Content: None")
            return

        try:
            if isinstance(content, (dict, list)):
                content_str = json.dumps(content, indent=2)
            else:
                content_str = str(content)

            char_count = len(content_str)

            if mode == "size":
                kb_size = char_count / 1024
                if kb_size > 1:
                    size_info = f"{kb_size:.1f}KB"
                else:
                    size_info = f"{char_count} chars"
                self._logger.info(f"[{event}] Content size: {size_info}")

            elif mode == "preview":
                preview = (
                    content_str[:100] + "..." if len(content_str) > 100 else content_str
                )
                self._logger.info(f"[{event}] Content preview: {preview}")

            elif mode == "full":
                self._logger.info(f"[{event}] Full content:")
                self._logger.info(content_str)

        except Exception as e:
            self._logger.error(f"[{event}] Error logging content: {e}")

    def log_query(self, query: str) -> None:
        """
        Log and capture SQL queries for troubleshooting.

        Args:
            query: SQL query string
        """
        # Sanitize query for logging
        sanitized_query = query.replace("\n", " ").replace("\t", " ")
        while "  " in sanitized_query:
            sanitized_query = sanitized_query.replace("  ", " ")

        # Add to queries list for debugging
        self._queries.append(sanitized_query)

        # Log complete query
        self._logger.info(f"{sanitized_query}")

    def get_events(self) -> Dict[str, str]:
        """
        Return copy of events map.

        Returns:
            Dict mapping event names to duration strings
        """
        return self._events.copy()

    def get_queries(self) -> List[str]:
        """
        Return copy of all captured queries.

        Returns:
            List of all queries with their types
        """
        return self._queries.copy()

    def clear(self) -> None:
        """
        Clear all stored events, counters, and queries.
        """
        self._events.clear()
        self._event_counters.clear()
        self._queries.clear()

    def display_summary(self) -> None:
        """
        Display formatted table of all events.
        """

        if self._queries:
            self._logger.info("Queries Executed:")
            for i, query in enumerate(self._queries, 1):
                self._logger.info("[Query #" + str(i) + "] " + query)

        if self._events:
            self._logger.info("Analytics Events:")
            self._logger.info(f"{'TOOL':<40} [{'TIME':<0}]")
            self._logger.info("-" * 48)
            total_time = 0.0
            for event, duration_str in self._events.items():
                self._logger.info(f"{event:<40} [{duration_str}s]")
                try:
                    total_time += float(duration_str)
                except ValueError:
                    self._logger.warning(f"Invalid duration format: {duration_str}")
            self._logger.info("-" * 48)
            self._logger.info(f"{'Total Tool Runtime':<40} [{total_time:.2f}s]")


# Singleton instance
analytics_logger = AnalyticsLogger()
