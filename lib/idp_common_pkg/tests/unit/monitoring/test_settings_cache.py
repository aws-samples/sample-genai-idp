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


class _FakeClock:
    """
    Controllable stand-in for ``time.monotonic``.

    Lets tests assert on retry *behaviour* (does a second read call SSM before or
    after the retry window?) instead of on a derived age in seconds, and lets
    them start from a low value to emulate a freshly-booted CI container
    (GitHub #609).
    """

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _patch_clock(monkeypatch, start: float = 0.0) -> _FakeClock:
    """Install a :class:`_FakeClock` as the module's ``time.monotonic``."""
    import idp_common.monitoring.settings_cache as sc_mod

    clock = _FakeClock(start)
    monkeypatch.setattr(sc_mod.time, "monotonic", clock)
    return clock


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
        After a first-load SSM failure (empty cache), the next attempt happens
        after the short ~30s window rather than a full TTL, so callers don't run
        with no settings at all for the whole TTL.  Asserted on behaviour: does a
        later read call SSM again?
        """
        clock = _patch_clock(monkeypatch, start=9.0)  # fresh-container uptime
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = MagicMock()
        ssm.get_parameter.side_effect = Exception("SSM unavailable")
        # Use a long TTL to make clear the full-TTL window is bypassed
        cache = SettingsCache(ttl_seconds=300, ssm_client=ssm)

        # First call — SSM fails, cache is still empty → short retry window set
        cache.get("Key")
        assert ssm.get_parameter.call_count == 1

        # Inside the 30s window: no retry.
        clock.advance(29)
        cache.get("Key")
        assert ssm.get_parameter.call_count == 1, (
            "should not retry SSM before the 30s window elapses"
        )

        # Just past the 30s window: retry, well before the 300s TTL.
        clock.advance(2)
        cache.get("Key")
        assert ssm.get_parameter.call_count == 2, (
            "should retry SSM once the ~30s window elapses, not after a full TTL"
        )

    def test_empty_cache_retry_window_never_exceeds_ttl(self, monkeypatch):
        """A TTL shorter than the 30s retry window must not be lengthened by it."""
        clock = _patch_clock(monkeypatch, start=3.0)
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = MagicMock()
        ssm.get_parameter.side_effect = Exception("SSM unavailable")
        cache = SettingsCache(ttl_seconds=5, ssm_client=ssm)

        cache.get("Key")
        assert ssm.get_parameter.call_count == 1

        clock.advance(6)  # past the 5s TTL but inside a naive 30s window
        cache.get("Key")
        assert ssm.get_parameter.call_count == 2, (
            "retry window must be capped at the TTL when TTL < 30s"
        )

    def test_ssm_failure_on_stale_cache_defers_full_ttl(self, monkeypatch):
        """
        After a refresh failure when stale data is already cached, the retry is
        deferred for a full TTL period to avoid hammering SSM.

        Regression test for GitHub #609: this used to be asserted via a derived
        age computed from a back-dated ``_cache_time``, which broke when
        ``time.monotonic()`` (seconds since boot) was small on a low-uptime CI
        runner.  The clock is now explicit, so a low start value is the norm.
        """
        clock = _patch_clock(monkeypatch, start=9.0)  # fresh-container uptime
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = MagicMock()
        # First call succeeds, all later calls fail
        ssm.get_parameter.side_effect = [
            {"Parameter": {"Value": '{"Key": "cached-value"}'}},
            Exception("SSM unavailable"),
            Exception("SSM unavailable"),
        ]
        cache = SettingsCache(ttl_seconds=300, ssm_client=ssm)

        assert cache.get("Key") == "cached-value"  # succeeds — cache now has data
        assert ssm.get_parameter.call_count == 1

        clock.advance(301)  # TTL elapsed → refresh attempted, and it fails
        assert cache.get("Key") == "cached-value", "stale value must still be served"
        assert ssm.get_parameter.call_count == 2

        # Inside the deferral window: stale data is served without hitting SSM.
        clock.advance(299)
        assert cache.get("Key") == "cached-value"
        assert ssm.get_parameter.call_count == 2, (
            "should defer a full TTL before retrying when stale data is available"
        )

        # Past the full-TTL deferral: retry.
        clock.advance(2)
        cache.get("Key")
        assert ssm.get_parameter.call_count == 3

    def test_recovery_after_failure_restores_normal_ttl(self, monkeypatch):
        """Once a refresh succeeds, expiry goes back to plain TTL-based ageing."""
        clock = _patch_clock(monkeypatch, start=4.0)
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = MagicMock()
        ssm.get_parameter.side_effect = [
            Exception("SSM unavailable"),
            _make_ssm_response({"Key": "recovered"}),
        ]
        cache = SettingsCache(ttl_seconds=300, ssm_client=ssm)

        assert cache.get("Key") == ""  # first load fails
        clock.advance(31)  # short retry window elapses
        assert cache.get("Key") == "recovered"
        assert ssm.get_parameter.call_count == 2

        # Fresh data: no further SSM calls until the TTL expires.
        clock.advance(299)
        cache.get("Key")
        assert ssm.get_parameter.call_count == 2

    def test_invalidate_overrides_pending_retry_window(self, monkeypatch):
        """invalidate() means 'refresh now', even mid-retry-deferral."""
        _patch_clock(monkeypatch, start=7.0)
        monkeypatch.setenv("SETTINGS_PARAMETER_NAME", "/my/param")
        ssm = MagicMock()
        ssm.get_parameter.side_effect = [
            Exception("SSM unavailable"),
            _make_ssm_response({"Key": "v1"}),
        ]
        cache = SettingsCache(ttl_seconds=300, ssm_client=ssm)

        cache.get("Key")  # fails → retry deadline pending
        assert ssm.get_parameter.call_count == 1

        cache.invalidate()
        assert cache.get("Key") == "v1"  # no clock movement needed
        assert ssm.get_parameter.call_count == 2


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
