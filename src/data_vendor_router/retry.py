"""Per-vendor single-retry decorator. REQ-DVR-008.

Vendors known to be flaky on transient errors (yfinance) get one immediate
retry on NetworkError/timeout (NOT on rate-limit or 5xx). Paid vendors fall
back to the next vendor in the chain on first failure.

CTO M4 resolution: retries happen INSIDE the breaker call, so a single
retry costs 1 breaker event (not 2).
"""
from __future__ import annotations

import time
from functools import wraps
from typing import Callable, TypeVar

from .exceptions import _NetworkError

T = TypeVar("T")

# Vendors that opt-in to retry-once-on-transient.
RETRY_ON_TRANSIENT_VENDORS: set[str] = {"yfinance"}

RETRY_BACKOFF_SECONDS = 0.1   # ≤ 100ms per spec


def with_retry(vendor_name: str) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator factory. Wraps a callable with one retry on _NetworkError if vendor opted in."""

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            try:
                return fn(*args, **kwargs)
            except _NetworkError:
                if vendor_name not in RETRY_ON_TRANSIENT_VENDORS:
                    raise
                time.sleep(RETRY_BACKOFF_SECONDS)
                return fn(*args, **kwargs)   # second failure propagates

        return wrapper

    return decorator
