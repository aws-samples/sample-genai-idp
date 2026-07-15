# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Unit tests for idp_common.monitoring.settings_cache
"""

import json
import threading
from unittest.mock import MagicMock

from idp_common.monitoring.settings_cache import SettingsCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ssm_response(settings: dict) -> dict:
    """Build a mock SSM get_parameter response."""
    return {"Parameter": {"Value": json.dumps(settings)}}


def _make_mock_ssm(settings: dict) -> MagicMock:
    """Return a mock SSM client that returns *settings* from get_parameter."""
    mock = MagicMock()
    mock.get_parameter.return_value = _make_ssm_response(settings)
    return mock


# ---------------------------------------------------------------------------
# Basic cache behaviour
# ---------------------------------------------------------------------------


class TestSettingsCache:
    def test_get_returns_value_on_first_call(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = _make_mock_ssm({"TrackingTableName": "my-table"})
        cache = SettingsCache(ttl_seconds=300, ssm_client=ssm)

        result = cache.get("TrackingTableName")

        assert result == "my-table"
        ssm.get_parameter.assert_called_once_with(Name="/my/param")

    def test_get_returns_cached_value_on_second_call(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = _make_mock_ssm({"Key": "value"})
        cache = SettingsCache(ttl_seconds=300, ssm_client=ssm)

        # Two calls
        cache.get("Key")
        cache.get("Key")

        # SSM should only be called once
        assert ssm.get_parameter.call_count == 1

    def test_get_returns_default_for_missing_key(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = _make_mock_ssm({})
        cache = SettingsCache(ttl_seconds=300, ssm_client=ssm)

        result = cache.get("NonExistentKey", default="fallback")
        assert result == "fallback"

    def test_cache_expires_after_ttl_and_refetches(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = _make_mock_ssm({"Key": "v1"})
        cache = SettingsCache(ttl_seconds=0, ssm_client=ssm)  # TTL = 0 → always expired

        cache.get("Key")
        cache.get("Key")

        # With TTL=0, every call should refresh
        assert ssm.get_parameter.call_count == 2

    def test_invalidate_forces_refresh(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = _make_mock_ssm({"Key": "v1"})
        cache = SettingsCache(ttl_seconds=300, ssm_client=ssm)

        cache.get("Key")  # loads cache
        cache.invalidate()  # marks cache as expired
        cache.get("Key")  # should reload

        assert ssm.get_parameter.call_count == 2

    def test_get_all_returns_copy_of_settings(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        settings = {"A": "1", "B": "2"}
        ssm = _make_mock_ssm(settings)
        cache = SettingsCache(ttl_seconds=300, ssm_client=ssm)

        result = cache.get_all()
        assert result == settings
        # Modifying the result should not affect the cache
        result["A"] = "mutated"
        assert cache.get("A") == "1"


# ---------------------------------------------------------------------------
# CloudWatch log groups helper
# ---------------------------------------------------------------------------


class TestGetCloudWatchLogGroups:
    def test_returns_list_from_comma_separated_string(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/p")
        ssm = _make_mock_ssm(
            {"CloudWatchLogGroups": "/aws/lambda/fn1,/aws/lambda/fn2, /aws/lambda/fn3 "}
        )
        cache = SettingsCache(ssm_client=ssm)
        groups = cache.get_cloudwatch_log_groups()
        assert groups == ["/aws/lambda/fn1", "/aws/lambda/fn2", "/aws/lambda/fn3"]

    def test_returns_empty_list_when_key_missing(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/p")
        ssm = _make_mock_ssm({})
        cache = SettingsCache(ssm_client=ssm)
        assert cache.get_cloudwatch_log_groups() == []

    def test_returns_empty_list_when_value_is_empty_string(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/p")
        ssm = _make_mock_ssm({"CloudWatchLogGroups": ""})
        cache = SettingsCache(ssm_client=ssm)
        assert cache.get_cloudwatch_log_groups() == []


# ---------------------------------------------------------------------------
# Missing SETTINGS_PARAMETER_NAME env var
# ---------------------------------------------------------------------------


class TestMissingEnvVar:
    def test_get_returns_default_when_param_name_not_set(self, monkeypatch):
        monkeypatch.delenv("SETTINGS_PARAMETER_NAME", raising=False)
        ssm = MagicMock()
        cache = SettingsCache(ssm_client=ssm)

        result = cache.get("AnyKey", default="my-default")

        # SSM should NOT be called
        ssm.get_parameter.assert_not_called()
        assert result == "my-default"


# ---------------------------------------------------------------------------
# SSM failure resilience
# ---------------------------------------------------------------------------


class TestSSMFailureResilience:
    def test_ssm_exception_does_not_raise(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = MagicMock()
        ssm.get_parameter.side_effect = Exception("SSM unavailable")
        cache = SettingsCache(ssm_client=ssm)

        # Should not raise — returns default
        result = cache.get("Key", default="safe")
        assert result == "safe"

    def test_ssm_failure_on_empty_cache_retries_after_short_window(self, monkeypatch):
        """
        After a first-load SSM failure (empty cache), the cache_time is advanced
        by (TTL - 30s) so that the next retry happens after ~30 seconds, NOT
        after a full TTL period.  This prevents Lambda cold-start silent failures.
        """
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = MagicMock()
        ssm.get_parameter.side_effect = Exception("SSM unavailable")
        # Use a long TTL to make clear the full-TTL window is bypassed
        cache = SettingsCache(ttl_seconds=300, ssm_client=ssm)

        # First call — SSM fails, cache is still empty → short retry window set
        cache.get("Key")
        assert ssm.get_parameter.call_count == 1

        # Simulate time passing past the 30-second short window by resetting
        # _cache_time to a value that would be expired relative to the 30s window.
        # (We test the logic by checking _cache_time was set to approximately
        # now - TTL + 30, meaning it will expire very soon again.)
        # The TTL after a first-load failure should be close to -(TTL - 30) from now,
        # i.e. it should expire far sooner than the full TTL.
        import time

        assert cache._cache_time is not None  # refresh-failure path sets it
        time_remaining = cache._ttl - (time.monotonic() - cache._cache_time)
        # With a 300s TTL, remaining window should be close to 30s, not 300s
        assert time_remaining < 60, (
            f"Expected retry window ≈30s after empty-cache failure, got {time_remaining:.1f}s"
        )

    def test_ssm_failure_on_stale_cache_defers_full_ttl(self, monkeypatch):
        """
        After a refresh failure when stale data is already cached, the retry is
        deferred for a full TTL period to avoid hammering SSM.
        """
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = MagicMock()
        # First call succeeds, second call fails
        ssm.get_parameter.side_effect = [
            {"Parameter": {"Value": '{"Key": "cached-value"}'}},
            Exception("SSM unavailable"),
        ]
        cache = SettingsCache(ttl_seconds=0, ssm_client=ssm)  # TTL=0 → always expired

        cache.get("Key")  # succeeds — cache now has data
        cache.get("Key")  # fails — stale data available, defer for full TTL
        assert ssm.get_parameter.call_count == 2

        # After stale-cache failure, the retry window should be a full TTL away
        # (for TTL=0, this means cache_time ≈ now, so _is_expired() is True again
        # immediately — that's correct, TTL=0 always expires)
        cache2 = SettingsCache(ttl_seconds=300, ssm_client=ssm)
        cache2._cache = {"Key": "stale"}  # pre-populate to simulate stale data
        cache2._cache_time = 0.0  # mark as expired

        ssm2 = MagicMock()
        ssm2.get_parameter.side_effect = Exception("SSM unavailable")
        cache2._ssm_client = ssm2

        import time

        cache2.get("Key")  # fails but has stale data → should defer full TTL
        assert cache2._cache_time is not None  # refresh-failure path sets it
        time_remaining = cache2._ttl - (time.monotonic() - cache2._cache_time)
        # Should be close to the full 300s TTL
        assert time_remaining > 250, (
            f"Expected full TTL retry window after stale-cache failure, got {time_remaining:.1f}s"
        )


# ---------------------------------------------------------------------------
# Cold-start monotonic-clock regression (GitHub #504 follow-up)
# ---------------------------------------------------------------------------


class TestColdStartMonotonic:
    """
    Regression tests for the cold-start bug where a never-loaded cache was
    treated as fresh because ``time.monotonic()`` on a freshly-booted Lambda
    microVM can be below the TTL, so ``monotonic() - 0.0 > ttl`` was False and
    ``_refresh()`` never ran (surfaced as "CloudWatchLogGroups not found in SSM
    Settings" on cold starts, blocking the Error Analyzer agent's log search).
    """

    def test_first_load_refreshes_when_monotonic_below_ttl(self, monkeypatch):
        # Simulate a cold-start microVM: monotonic() well below the 300s TTL.
        import idp_common.monitoring.settings_cache as sc_mod

        monkeypatch.setattr(sc_mod.time, "monotonic", lambda: 12.0)
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = _make_mock_ssm({"CloudWatchLogGroups": "/aws/lambda/fn1"})
        cache = SettingsCache(ttl_seconds=300, ssm_client=ssm)

        # Before the fix this returned [] because _refresh() was skipped.
        assert cache.get_cloudwatch_log_groups() == ["/aws/lambda/fn1"]
        ssm.get_parameter.assert_called_once()

    def test_never_loaded_cache_is_expired_regardless_of_clock(self, monkeypatch):
        import idp_common.monitoring.settings_cache as sc_mod

        monkeypatch.setattr(sc_mod.time, "monotonic", lambda: 5.0)
        cache = SettingsCache(ttl_seconds=300)
        assert cache._is_expired() is True

    def test_invalidate_forces_refresh_on_low_monotonic(self, monkeypatch):
        # invalidate() must force expiry even when monotonic() < TTL.
        import idp_common.monitoring.settings_cache as sc_mod

        monkeypatch.setattr(sc_mod.time, "monotonic", lambda: 20.0)
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = _make_mock_ssm({"Key": "v1"})
        cache = SettingsCache(ttl_seconds=300, ssm_client=ssm)

        cache.get("Key")  # first load
        cache.invalidate()
        cache.get("Key")  # must reload despite low, non-advancing monotonic

        assert ssm.get_parameter.call_count == 2


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_reads_all_succeed(self, monkeypatch):
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = _make_mock_ssm({"SharedKey": "thread-safe-value"})
        cache = SettingsCache(ttl_seconds=300, ssm_client=ssm)

        results = []
        errors = []

        def read():
            try:
                results.append(cache.get("SharedKey"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=read) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errors in concurrent reads: {errors}"
        assert all(r == "thread-safe-value" for r in results)
        # Cache should only be loaded once despite 20 concurrent reads
        assert ssm.get_parameter.call_count == 1
