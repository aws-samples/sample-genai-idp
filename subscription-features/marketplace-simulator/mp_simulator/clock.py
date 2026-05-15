"""Mockable clock.

Production Marketplace has real wall-clock behaviour. For tests, we need to
advance time instantly (free trial expiry, >6h metering window, etc). This
clock exposes a configurable offset that the admin API ``/admin/time/advance``
can push forward.

Seconds since epoch, UTC. Never go backwards.
"""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_offset_seconds: float = 0.0


def now() -> float:
    """Current simulator time (epoch seconds, UTC)."""
    return time.time() + _offset_seconds


def now_ms() -> int:
    return int(now() * 1000)


def advance(seconds: float) -> float:
    """Advance the simulator clock by ``seconds`` (must be >= 0). Returns new now()."""
    global _offset_seconds
    if seconds < 0:
        raise ValueError("cannot go backwards")
    with _lock:
        _offset_seconds += seconds
    return now()


def reset() -> None:
    """Reset offset. Tests only."""
    global _offset_seconds
    with _lock:
        _offset_seconds = 0.0


def offset() -> float:
    return _offset_seconds
