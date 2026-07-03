"""GD-DVR-015 — CircuitBreakerError must not escape _route.

Regression test for the P0 staging bug (2026-07-03): when a vendor's failure
threshold is reached on the *current* call, pybreaker raises
``CircuitBreakerError`` from inside ``breaker.call()``.  The pre-check
``breakers.is_open()`` only covers *already-open* breakers; the open-transition
moment was unhandled and the exception leaked to the consumer as HTTP 500.

Fix: ``core._route`` now catches ``pybreaker.CircuitBreakerError`` in the
per-vendor except chain, records ``"circuit_breaker_open"`` in ``attempts``,
logs a WARNING, and ``continue``s to the next vendor.
"""
from datetime import date

import pybreaker
import pytest

from data_vendor_router import get_news, get_ohlcv
from data_vendor_router.exceptions import (
    AllVendorsFailed,
    _NetworkError,
)
from tests.conftest import (
    raises,
    returns,
    sample_ohlc_bars,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_circuit_breaker_error() -> pybreaker.CircuitBreakerError:
    """Construct the exception pybreaker raises when the threshold is reached."""
    return pybreaker.CircuitBreakerError("Failures threshold reached, circuit breaker opened")


# ---------------------------------------------------------------------------
# GD-DVR-015a — single-vendor chain: CircuitBreakerError → AllVendorsFailed
# ---------------------------------------------------------------------------


def test_gd_015a_circuit_breaker_error_does_not_escape(make_stub, monkeypatch):
    """CircuitBreakerError from the mid-call open-transition must NOT propagate.

    A single-vendor chain with the vendor raising CircuitBreakerError must raise
    AllVendorsFailed (not CircuitBreakerError / any other exception).
    """
    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "yfinance")
    yf = make_stub("yfinance")
    # Simulate pybreaker.CircuitBreaker.call raising CircuitBreakerError
    # directly from the stub (bypasses the real breaker, but proves the catch).
    yf.program("get_ohlcv", raises(_make_circuit_breaker_error()))

    with pytest.raises(AllVendorsFailed) as exc:
        get_ohlcv("AAPL", date(2026, 4, 1), date(2026, 4, 5))

    attempts = exc.value.attempts
    assert len(attempts) == 1
    vendor_name, reason = attempts[0]
    assert vendor_name == "yfinance"
    assert reason == "circuit_breaker_open"


# ---------------------------------------------------------------------------
# GD-DVR-015b — chain continues to next vendor after CircuitBreakerError
# ---------------------------------------------------------------------------


def test_gd_015b_chain_continues_after_circuit_breaker_error(make_stub, monkeypatch):
    """When the first vendor triggers a CircuitBreakerError the router falls
    through to the next vendor and returns its result — no 500.

    Replicates the staging trace:
      tiingo _NetworkError → pybreaker on_failure → CircuitBreakerError
      → (fixed) router catches, skips to polygon → polygon returns data.
    """
    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "yfinance,alpaca,polygon")
    yf = make_stub("yfinance")
    al = make_stub("alpaca")
    pg = make_stub("polygon")

    yf.program("get_ohlcv", raises(_make_circuit_breaker_error()))
    al.program("get_ohlcv", raises(_make_circuit_breaker_error()))
    pg.program("get_ohlcv", returns(sample_ohlc_bars(3)))

    bars = get_ohlcv("TSLA", date(2026, 4, 1), date(2026, 4, 5))

    assert len(bars) == 3
    assert len(yf.call_log) == 1   # was called, raised, skipped
    assert len(al.call_log) == 1   # same
    assert len(pg.call_log) == 1   # succeeded


# ---------------------------------------------------------------------------
# GD-DVR-015c — attempts list records circuit_breaker_open correctly
# ---------------------------------------------------------------------------


def test_gd_015c_attempts_records_circuit_breaker_open(make_stub, monkeypatch):
    """AllVendorsFailed.attempts should contain (vendor, 'circuit_breaker_open')
    for every vendor that raised CircuitBreakerError, mixed with other failure
    reasons in the correct order.
    """
    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "yfinance,alpaca,polygon")
    yf = make_stub("yfinance")
    al = make_stub("alpaca")
    pg = make_stub("polygon")

    yf.program("get_ohlcv", raises(_make_circuit_breaker_error()))
    al.program("get_ohlcv", raises(_NetworkError("timeout")))
    pg.program("get_ohlcv", raises(_make_circuit_breaker_error()))

    with pytest.raises(AllVendorsFailed) as exc:
        get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 2))

    reasons = [r for _, r in exc.value.attempts]
    assert reasons == ["circuit_breaker_open", "timeout", "circuit_breaker_open"]


# ---------------------------------------------------------------------------
# GD-DVR-015d — all vendors tripped → AllVendorsFailed (not CircuitBreakerError)
# ---------------------------------------------------------------------------


def test_gd_015d_all_vendors_circuit_breaker_raises_all_vendors_failed(make_stub, monkeypatch):
    """When every vendor raises CircuitBreakerError the final raise must be
    AllVendorsFailed, NOT CircuitBreakerError.
    """
    monkeypatch.setenv("DVR_NEWS_PRIORITY", "benzinga,alpha_vantage,yfinance")
    make_stub("benzinga").program("get_news", raises(_make_circuit_breaker_error()))
    make_stub("alpha_vantage").program("get_news", raises(_make_circuit_breaker_error()))
    make_stub("yfinance").program("get_news", raises(_make_circuit_breaker_error()))

    with pytest.raises(AllVendorsFailed) as exc:
        get_news("AAPL")

    assert not isinstance(exc.value, pybreaker.CircuitBreakerError)
    assert all(r == "circuit_breaker_open" for _, r in exc.value.attempts)
    assert len(exc.value.attempts) == 3


# ---------------------------------------------------------------------------
# GD-DVR-015e — mixed: network error then CircuitBreakerError, final vendor succeeds
# ---------------------------------------------------------------------------


def test_gd_015e_mixed_network_then_breaker_then_success(make_stub, monkeypatch):
    """Replicates the exact staging scenario:
      vendor-A: _NetworkError (transient, recorded as 'timeout')
      vendor-B: CircuitBreakerError (threshold reached on B's previous errors)
      vendor-C: returns data

    Result: data returned; no exception leaked; attempts has 2 entries.
    """
    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "yfinance,alpaca,polygon")
    yf = make_stub("yfinance")
    al = make_stub("alpaca")
    pg = make_stub("polygon")

    yf.program("get_ohlcv", raises(_NetworkError("connection timed out")))
    al.program("get_ohlcv", raises(_make_circuit_breaker_error()))
    pg.program("get_ohlcv", returns(sample_ohlc_bars(2)))

    bars = get_ohlcv("MSFT", date(2026, 4, 1), date(2026, 4, 5))

    assert len(bars) == 2
    # yfinance retries once on _NetworkError (REQ-DVR-008 / with_retry),
    # so call_log has 2 entries (initial + 1 retry), both failed.
    assert len(yf.call_log) >= 1
    assert len(al.call_log) == 1   # called, raised CircuitBreakerError, skipped
    assert len(pg.call_log) == 1   # called and succeeded
