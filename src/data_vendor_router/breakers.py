"""Per-vendor circuit breaker registry. REQ-DVR-004.

Each vendor gets its own pybreaker instance. Default: opens after 5 failures
in 60s, half-open after 30s. CTO M4 resolution: retries (REQ-DVR-008) happen
INSIDE the breaker call, so 1 retry = 1 breaker event (not N).
"""
from __future__ import annotations

import pybreaker

DEFAULT_FAIL_MAX = 5
DEFAULT_RESET_TIMEOUT_SECONDS = 30

_BREAKERS: dict[str, pybreaker.CircuitBreaker] = {}


def get_breaker(vendor_name: str) -> pybreaker.CircuitBreaker:
    """Lazy-create per-vendor breaker."""
    if vendor_name not in _BREAKERS:
        _BREAKERS[vendor_name] = pybreaker.CircuitBreaker(
            fail_max=DEFAULT_FAIL_MAX,
            reset_timeout=DEFAULT_RESET_TIMEOUT_SECONDS,
            name=f"vendor.{vendor_name}",
        )
    return _BREAKERS[vendor_name]


def is_open(vendor_name: str) -> bool:
    """Return True if the vendor's breaker is currently open (skip this vendor)."""
    return get_breaker(vendor_name).current_state == "open"


def reset_all() -> None:
    """Test helper — close all breakers and clear the registry."""
    for breaker in _BREAKERS.values():
        try:
            breaker.close()
        except Exception:
            pass
    _BREAKERS.clear()


def force_open(vendor_name: str) -> None:
    """Test helper — force a breaker open without triggering N failures."""
    breaker = get_breaker(vendor_name)
    breaker.open()
