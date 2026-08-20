"""Tests for unregistered-vendor skip in the default chain (DLD-18 FINDING-1, v0.2.1).

Root cause: get_adapter raised ValueError for vendors whose SDK is not installed,
escaping per-vendor except clauses → HTTP 500 on staging (watchlistservice 8/10 500s
when polygon+tiingo breakers were open and alpaca was next in the chain).

AC coverage:
  - default chain with one unregistered vendor: skips it, continues to next, succeeds
  - default chain with all vendors unregistered: raises AllVendorsFailed (not ValueError)
  - explicit provider_chain with unknown vendor: still raises ValueError (MIN-3 unchanged)
  - unregistered vendor recorded in attempts list with reason "not_registered"
  - belt-and-braces ValueError from get_adapter in loop: skips vendor, continues
  - cache-hit INFO log emitted on Redis hit (AC-3.4)
"""
from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

SRC_DIR = Path(__file__).parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from data_vendor_router import get_ohlcv, get_fundamentals  # noqa: E402
from data_vendor_router import vendors  # noqa: E402
from data_vendor_router.exceptions import AllVendorsFailed, _RateLimitError  # noqa: E402
from tests.conftest import returns, raises, sample_ohlc_bars  # noqa: E402


# ============== DLD-18 FINDING-1 — unregistered vendor skip ==============


def test_default_chain_unregistered_vendor_skipped_and_fallback_succeeds(make_stub, monkeypatch):
    """Default chain polygon,alpaca,yfinance — alpaca not registered (SDK absent).

    Expected: alpaca is skipped, yfinance is called and returns data.
    The result is returned without raising ValueError or AllVendorsFailed.
    """
    # alpaca is intentionally NOT registered; polygon and yfinance are
    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "polygon,alpaca,yfinance")
    pg = make_stub("polygon")
    yf = make_stub("yfinance")
    # alpaca not registered — simulates missing alpaca-py SDK
    pg.program("get_ohlcv", raises(_RateLimitError("429")))
    yf.program("get_ohlcv", returns(sample_ohlc_bars(3)))

    bars = get_ohlcv("AAPL", date(2026, 4, 1), date(2026, 4, 5))

    assert len(bars) == 3
    assert len(pg.call_log) == 1    # polygon was tried (then failed)
    assert len(yf.call_log) == 1    # yfinance was called as next registered vendor
    # alpaca was never called (no stub registered for it)


def test_default_chain_unregistered_vendor_recorded_in_attempts(make_stub, monkeypatch):
    """Unregistered vendor must appear in AllVendorsFailed.attempts with reason 'not_registered'."""
    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "alpaca,polygon")
    pg = make_stub("polygon")
    # alpaca not registered — simulates missing SDK
    pg.program("get_ohlcv", raises(_RateLimitError("429")))

    with pytest.raises(AllVendorsFailed) as exc_info:
        get_ohlcv("MSFT", date(2026, 4, 1), date(2026, 4, 2))

    attempts = exc_info.value.attempts
    attempt_vendors = [v for v, _ in attempts]
    attempt_reasons = [r for _, r in attempts]

    assert "alpaca" in attempt_vendors, f"alpaca missing from attempts: {attempts}"
    alpaca_reason = attempt_reasons[attempt_vendors.index("alpaca")]
    assert alpaca_reason == "not_registered", (
        f"Expected 'not_registered', got {alpaca_reason!r}"
    )


def test_all_unregistered_raises_all_vendors_failed_not_value_error(monkeypatch):
    """When ALL vendors in the default chain are unregistered, AllVendorsFailed is raised.

    The pre-fix bug: the FIRST unregistered vendor caused ValueError to escape,
    wrapping as HTTP 500. Now AllVendorsFailed is raised (honest, catchable).
    """
    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "alpaca,some_ghost_vendor")
    # Neither alpaca nor some_ghost_vendor is registered

    with pytest.raises(AllVendorsFailed):
        get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 2))


def test_all_unregistered_does_not_raise_value_error(monkeypatch):
    """Regression guard: ValueError must NOT escape when the default chain has no registered vendors."""
    monkeypatch.setenv("DVR_FUNDAMENTALS_PRIORITY", "alpaca,ghost_vendor")

    try:
        get_fundamentals("AAPL")
        pytest.fail("Expected AllVendorsFailed to be raised")
    except AllVendorsFailed:
        pass  # correct
    except ValueError as e:
        pytest.fail(
            f"ValueError escaped from _route — pre-fix bug still present: {e}"
        )


def test_explicit_provider_chain_unknown_vendor_still_raises_value_error(make_stub, monkeypatch):
    """MIN-3 must be preserved: an unknown vendor in an explicit provider_chain raises ValueError.

    Explicit chains are caller-controlled (not SDK-availability), so the loud error
    is intentional — it surfaces bugs in the calling code.
    """
    make_stub("yfinance")

    with pytest.raises(ValueError, match="Unknown vendor"):
        get_ohlcv(
            "NVDA",
            date(2026, 4, 1),
            date(2026, 4, 2),
            provider_chain=["yfinance", "nonexistent_vendor"],
        )


def test_belt_and_braces_get_adapter_value_error_skips_vendor(make_stub, monkeypatch):
    """If get_adapter raises ValueError inside the loop (future regression guard),
    the vendor is skipped and the next registered vendor is tried.

    Simulates a corner case where is_registered() returns True but get_adapter()
    still raises (should not happen under normal operation, but belt-and-braces
    protects against future code changes).
    """
    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "polygon,yfinance")
    make_stub("polygon")
    yf = make_stub("yfinance")
    yf.program("get_ohlcv", returns(sample_ohlc_bars(2)))

    # Force get_adapter to raise ValueError for polygon despite it being registered
    original_get_adapter = vendors.get_adapter

    def patched_get_adapter(name):
        if name == "polygon":
            raise ValueError("Simulated unexpected get_adapter failure")
        return original_get_adapter(name)

    with patch.object(vendors, "get_adapter", patched_get_adapter):
        bars = get_ohlcv("AAPL", date(2026, 4, 1), date(2026, 4, 5))

    assert len(bars) == 2
    assert len(yf.call_log) == 1   # yfinance was the fallback


# ============== AC-3.4 — cache-hit INFO log ==============


def test_cache_hit_emits_info_log(make_stub, monkeypatch, caplog):
    """On a cache hit, _route emits INFO log with dvr_cache_hit + category + ticker."""
    try:
        import fakeredis
    except ImportError:
        pytest.skip("fakeredis not installed")

    from data_vendor_router import cache as _cache_module

    monkeypatch.setenv("DVR_CACHE_ENABLED", "true")
    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "yfinance")

    fake_server = fakeredis.FakeServer()
    fake_client = fakeredis.FakeRedis(server=fake_server, db=1, decode_responses=False)
    cache_instance = _cache_module.DVRCache()
    cache_instance._client = fake_client
    _cache_module._INSTANCE = cache_instance

    try:
        yf = make_stub("yfinance")
        yf.program("get_ohlcv", returns(sample_ohlc_bars(1)))

        # First call — cache miss, vendor called, result stored
        get_ohlcv("TSLA", date(2026, 4, 1), date(2026, 4, 3))
        assert len(yf.call_log) == 1

        # Second call — cache HIT; check log
        with caplog.at_level(logging.INFO, logger="data_vendor_router.core"):
            get_ohlcv("TSLA", date(2026, 4, 1), date(2026, 4, 3))

        hit_logs = [r for r in caplog.records if "dvr_cache_hit" in r.message]
        assert len(hit_logs) >= 1, (
            f"Expected at least one 'dvr_cache_hit' INFO log on cache hit; "
            f"captured log records: {[r.message for r in caplog.records]}"
        )
        # Verify structured fields present in the log message
        assert "ohlcv" in hit_logs[0].message, "category 'ohlcv' missing from cache-hit log"
        assert "TSLA" in hit_logs[0].message, "ticker 'TSLA' missing from cache-hit log"
        # Vendor must NOT have been called a second time
        assert len(yf.call_log) == 1, "Vendor was called on cache hit — cache not working"
    finally:
        _cache_module._INSTANCE = None
