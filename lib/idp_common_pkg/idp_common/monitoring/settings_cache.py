# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Thread-safe SSM settings cache with TTL invalidation.

Provides a centralised configuration cache so that system settings are fetched
from AWS SSM once and reused, rather than making a network call every time a
setting is needed.

The parameter name is read from the ``SETTINGS_PARAMETER_NAME`` environment
variable (set by CloudFormation ``!Ref SettingsParameter``), which is the same
convention used by the existing error analyzer ``cloudwatch_tool.py``.

Usage::

    from idp_common.monitoring.settings_cache import SettingsCache

    cache = SettingsCache(ttl_seconds=300)
    log_groups = cache.get_cloudwatch_log_groups()

Or use the module-level singleton::

    from idp_common.monitoring.settings_cache import get_setting, get_cloudwatch_log_groups

    log_groups = get_cloudwatch_log_groups()
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

import boto3

logger = logging.getLogger(__name__)

#: Retry window used when the first-ever SSM load fails and the cache is still
#: empty. Deliberately much shorter than the TTL so callers don't silently run
#: with no settings at all for the full TTL period.
_EMPTY_CACHE_RETRY_SECONDS = 30


class SettingsCache:
    """
    Thread-safe cache for IDP stack settings stored in AWS SSM Parameter Store.

    Settings are loaded lazily on first access and refreshed when the TTL
    expires.  Concurrent reads are safe; only one thread performs the refresh.

    Args:
        ttl_seconds: Cache lifetime in seconds before a fresh SSM call is made.
                     Default is 300 (5 minutes).
        ssm_client:  Optional pre-constructed boto3 SSM client (useful in tests).
    """

    def __init__(
        self,
        ttl_seconds: int = 300,
        ssm_client: Optional[Any] = None,
    ) -> None:
        self._cache: Dict[str, Any] = {}
        # None means "never loaded". Do NOT use 0.0 as the sentinel: expiry is
        # measured with time.monotonic() (seconds since the host/microVM booted),
        # which on a cold-start Lambda can be far below the TTL. With a 0.0
        # sentinel, `monotonic() - 0.0 > ttl` is False on a fresh microVM, so the
        # cache is wrongly treated as fresh, _refresh() never runs, and every
        # get() returns empty (observed as "CloudWatchLogGroups not found in SSM
        # Settings" on cold starts). None makes "never loaded" always-expired.
        self._cache_time: Optional[float] = None
        # Explicit monotonic deadline for the next allowed refresh attempt, used
        # instead of back-dating _cache_time. Back-dating (_cache_time =
        # monotonic() - ttl + 30) produced a value whose meaning depended on the
        # clock's origin: time.monotonic() counts from boot, so on a young
        # container it can be smaller than the TTL and the subtraction goes
        # negative, making the "age" arithmetic nonsense (GitHub #609). A
        # forward-looking deadline never depends on the origin.
        self._retry_after: Optional[float] = None
        self._ttl: int = ttl_seconds
        self._lock: threading.Lock = threading.Lock()
        self._ssm_client: Optional[Any] = ssm_client

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_ssm_client(self) -> Any:
        """Return (and lazily create) the boto3 SSM client."""
        if self._ssm_client is None:
            self._ssm_client = boto3.client("ssm")
        return self._ssm_client

    def _is_expired(self) -> bool:
        """
        Return True if a refresh is due.

        A refresh is due when the cache has never been loaded or has passed its
        TTL — except while a post-failure retry deadline is pending, which holds
        the refresh back until that deadline passes.
        """
        if self._retry_after is not None:
            # A refresh attempt failed; hold off until the retry deadline.
            if time.monotonic() < self._retry_after:
                return False
            return True
        if self._cache_time is None:
            return True
        return (time.monotonic() - self._cache_time) > self._ttl

    def _refresh(self) -> None:
        """
        Reload all stack settings from SSM.

        Reads the parameter whose *name* is stored in the
        ``SETTINGS_PARAMETER_NAME`` environment variable.  The parameter value
        must be a JSON object.

        Silently logs a warning and leaves the cache empty if the variable is
        not set or the SSM call fails — callers should handle the case where
        ``get()`` returns ``""``.
        """
        param_name = os.environ.get("SETTINGS_PARAMETER_NAME", "")
        if not param_name:
            logger.warning(
                "SETTINGS_PARAMETER_NAME environment variable is not set; "
                "settings cache will be empty"
            )
            return

        try:
            ssm = self._get_ssm_client()
            response = ssm.get_parameter(Name=param_name)
            raw_value: str = response.get("Parameter", {}).get("Value", "{}")
            settings: Dict[str, Any] = json.loads(raw_value)
            self._cache = settings
            self._cache_time = time.monotonic()
            self._retry_after = None  # success — back to normal TTL expiry
            logger.debug(
                "Settings cache refreshed from SSM parameter '%s' (%d keys)",
                param_name,
                len(settings),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to refresh settings cache from SSM parameter '%s': %s",
                param_name,
                exc,
            )
            # Keep the stale cache rather than crashing callers, and set an
            # explicit forward-looking deadline for the next attempt.
            # If data was already cached (stale), defer the next retry for a full
            # TTL to avoid hammering SSM.  If the cache is still empty (first-ever
            # load), use a much shorter window so callers don't silently run with
            # no settings for the full TTL period.
            delay = (
                self._ttl if self._cache else min(_EMPTY_CACHE_RETRY_SECONDS, self._ttl)
            )
            self._retry_after = time.monotonic() + delay

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str, default: str = "") -> str:
        """
        Return a single string setting by key.

        Refreshes the cache if the TTL has expired.

        Args:
            key:     Setting key, e.g. ``"CloudWatchLogGroups"``.
            default: Value to return if the key is absent.

        Returns:
            The setting value as a string, or *default* if not found.
        """
        with self._lock:
            if self._is_expired():
                self._refresh()
            return str(self._cache.get(key, default))

    def get_all(self) -> Dict[str, Any]:
        """
        Return a copy of the full settings dictionary.

        Refreshes the cache if the TTL has expired.
        """
        with self._lock:
            if self._is_expired():
                self._refresh()
            return dict(self._cache)

    def get_cloudwatch_log_groups(self) -> List[str]:
        """
        Return the list of CloudWatch log group names from the settings cache.

        Reads the ``CloudWatchLogGroups`` key, which is expected to contain a
        comma-separated list of log group names.

        Returns:
            List of non-empty log group name strings.
        """
        raw = self.get("CloudWatchLogGroups", "")
        if not raw:
            return []
        return [lg.strip() for lg in raw.split(",") if lg.strip()]

    def invalidate(self) -> None:
        """Force the next ``get()`` call to refresh from SSM."""
        with self._lock:
            # None (not 0.0) so the next _is_expired() returns True regardless of
            # the current monotonic clock value (see __init__ for why).
            self._cache_time = None
            # Also drop any pending post-failure retry deadline — an explicit
            # invalidate() means "refresh now", and a pending deadline would
            # otherwise suppress that refresh.
            self._retry_after = None


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

#: Shared default cache instance used by module-level helper functions.
#: Callers that need custom TTL or test injection should create their own
#: ``SettingsCache`` instance.
_default_cache: SettingsCache = SettingsCache()


def get_setting(key: str, default: str = "") -> str:
    """
    Return a single setting value from the shared default cache.

    Args:
        key:     Setting key (e.g. ``"TrackingTableName"``).
        default: Fallback value if the key is absent.
    """
    return _default_cache.get(key, default)


def get_cloudwatch_log_groups() -> List[str]:
    """Return the CloudWatch log group list from the shared default cache."""
    return _default_cache.get_cloudwatch_log_groups()


def reset_default_cache(
    ttl_seconds: int = 300,
    ssm_client: Optional[Any] = None,
) -> None:
    """
    Replace the module-level singleton with a fresh :class:`SettingsCache`.

    **For testing only.**  Call this in test fixtures or ``teardown`` to
    prevent state leakage between test cases that exercise the module-level
    helpers (:func:`get_setting`, :func:`get_cloudwatch_log_groups`).

    Args:
        ttl_seconds: TTL for the new cache (default: 300).
        ssm_client:  Optional pre-built SSM mock client to inject.
    """
    global _default_cache
    _default_cache = SettingsCache(ttl_seconds=ttl_seconds, ssm_client=ssm_client)
