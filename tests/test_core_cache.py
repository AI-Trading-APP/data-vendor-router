"""Integration tests for _route + DVRCache (data-layer-dedup DLD-2 / DLD-4).

Uses fakeredis for Redis and StubAdapter from conftest for the vendor layer.
No live API calls, no live Redis.

AC coverage: AC-1.1, AC-1.2, AC-2.1, AC-3.1, AC-3.2, AC-3.3, AC-9.1, NFR-5.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SRC_DIR = Path(__file__).parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import fakeredis

from data_vendor_router import get_ohlcv, get_news, get_fundamentals
from data_vendor_router import cache as _cache_module
from data_vendor_router.exceptions import AllVendorsFailed
from tests.conftest import returns, sample_ohlc_bars, sample_fundamentals_snapshot


# ---------------------------------------------------------------------------
# Fixture: wire fakeredis into DVRCache singleton for each test
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_cache(monkeypatch):
    """Enable DVR_CACHE_ENABLED and wire a clean fakeredis into the singleton."""
    monkeypatch.setenv("DVR_CACHE_ENABLED", "true")

    fake_server = fakeredis.FakeServer()
    fake_client = fakeredis.FakeRedis(server=fake_server, db=1, decode_responses=False)

    cache_instance = _cache_module.DVRCache()
    cache_instance._client = fake_client

    # Inject as the module singleton so get_dvr_cache() returns it
    _cache_module._INSTANCE = cache_instance
    yield cache_instance

    # Teardown: reset singleton so other tests start clean
    _cache_module._INSTANCE = None


@pytest.fixture()
def no_cache(monkeypatch):
    """Ensure DVR_CACHE_ENABLED is off for flag-off tests."""
    monkeypatch.delenv("DVR_CACHE_ENABLED", raising=False)
    _cache_module._INSTANCE = None
    yield
    _cache_module._INSTANCE = None


# ---------------------------------------------------------------------------
# test_cache_hit_skips_vendor (AC-1.1, AC-1.2)
# ---------------------------------------------------------------------------

def test_cache_hit_skips_vendor(fake_cache, make_stub, monkeypatch):
    """Second call for the same ticker/range returns cached result; vendor called once."""
    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "yfinance")
    yf = make_stub("yfinance")
    yf.program("get_ohlcv", returns(sample_ohlc_bars(2)))

    bars1 = get_ohlcv("AAPL", date(2026, 4, 1), date(2026, 4, 5))
    bars2 = get_ohlcv("AAPL", date(2026, 4, 1), date(2026, 4, 5))

    # Vendor must have been called exactly once
    assert len(yf.call_log) == 1, f"Expected 1 vendor call, got {len(yf.call_log)}"
    # Both results must be identical
    assert len(bars1) == len(bars2) == 2
    assert bars1[0].close == bars2[0].close


def test_cache_miss_calls_vendor(fake_cache, make_stub, monkeypatch):
    """Cold cache: vendor called once and result written to Redis (AC-1.1)."""
    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "yfinance")
    yf = make_stub("yfinance")
    yf.program("get_ohlcv", returns(sample_ohlc_bars(1)))

    bars = get_ohlcv("MSFT", date(2026, 4, 1), date(2026, 4, 3))

    assert len(yf.call_log) == 1
    assert len(bars) == 1

    # Confirm key is now in fakeredis (write-through)
    keys = fake_cache._client.keys("dvr:ohlcv:MSFT:*")
    assert len(keys) == 1, "Expected one ohlcv key in cache after miss+fill"


# ---------------------------------------------------------------------------
# Flag-off regression (AC-9.1, NFR-5)
# ---------------------------------------------------------------------------

def test_flag_off_vendor_called_each_time(no_cache, make_stub, monkeypatch):
    """With DVR_CACHE_ENABLED=false, vendor is called on every invocation (NFR-5)."""
    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "yfinance")
    yf = make_stub("yfinance")
    yf.program("get_ohlcv", returns(sample_ohlc_bars(1)))

    get_ohlcv("AAPL", date(2026, 4, 1), date(2026, 4, 3))
    get_ohlcv("AAPL", date(2026, 4, 1), date(2026, 4, 3))

    assert len(yf.call_log) == 2, (
        f"Expected 2 vendor calls with flag off, got {len(yf.call_log)}"
    )


def test_flag_off_no_counter_increment(no_cache, make_stub, monkeypatch):
    """With flag off, cache counters must stay at zero (AC-9.1)."""
    from prometheus_client import REGISTRY
    from data_vendor_router import observability

    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "yfinance")
    yf = make_stub("yfinance")
    yf.program("get_ohlcv", returns(sample_ohlc_bars(1)))

    # Read baseline (counters accumulate across tests)
    def _current_hits():
        try:
            return observability.cache_hits_total.labels(category="ohlcv")._value.get()
        except Exception:
            return 0.0

    def _current_misses():
        try:
            return observability.cache_misses_total.labels(category="ohlcv")._value.get()
        except Exception:
            return 0.0

    hits_before = _current_hits()
    misses_before = _current_misses()

    get_ohlcv("AAPL", date(2026, 4, 1), date(2026, 4, 3))

    assert _current_hits() == hits_before, "Cache hits counter must not increment when flag is off"
    assert _current_misses() == misses_before, "Cache misses counter must not increment when flag is off"


# ---------------------------------------------------------------------------
# Fail-open: Redis down (AC-2.1)
# ---------------------------------------------------------------------------

def test_redis_down_falls_through_to_vendor(monkeypatch, make_stub):
    """When Redis is unreachable, vendor is still called and result returned (AC-2.1)."""
    monkeypatch.setenv("DVR_CACHE_ENABLED", "true")

    # Create a DVRCache whose Redis client always errors
    cache_instance = _cache_module.DVRCache()
    mock_client = MagicMock()
    mock_client.get.side_effect = Exception("Connection refused")
    mock_client.setex.side_effect = Exception("Connection refused")
    cache_instance._client = mock_client
    _cache_module._INSTANCE = cache_instance

    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "yfinance")
    yf = make_stub("yfinance")
    yf.program("get_ohlcv", returns(sample_ohlc_bars(3)))

    try:
        bars = get_ohlcv("NVDA", date(2026, 4, 1), date(2026, 4, 5))
        assert len(bars) == 3
        assert len(yf.call_log) == 1
    finally:
        _cache_module._INSTANCE = None


# ---------------------------------------------------------------------------
# Counter tests (AC-3.1, AC-3.2)
# ---------------------------------------------------------------------------

def test_cache_miss_counter_incremented(fake_cache, make_stub, monkeypatch):
    """On a cache miss, dvr_cache_misses_total must increment (AC-3.2)."""
    from data_vendor_router import observability

    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "yfinance")
    yf = make_stub("yfinance")
    yf.program("get_ohlcv", returns(sample_ohlc_bars(1)))

    before = observability.cache_misses_total.labels(category="ohlcv")._value.get()
    get_ohlcv("IBM", date(2026, 4, 1), date(2026, 4, 3))
    after = observability.cache_misses_total.labels(category="ohlcv")._value.get()

    assert after == before + 1, f"Expected misses +1, got before={before} after={after}"


def test_cache_hit_counter_incremented(fake_cache, make_stub, monkeypatch):
    """On a cache hit, dvr_cache_hits_total must increment (AC-3.1)."""
    from data_vendor_router import observability

    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "yfinance")
    yf = make_stub("yfinance")
    yf.program("get_ohlcv", returns(sample_ohlc_bars(1)))

    # First call — miss + fill
    get_ohlcv("GS", date(2026, 4, 1), date(2026, 4, 3))

    before_hits = observability.cache_hits_total.labels(category="ohlcv")._value.get()
    # Second call — should hit
    get_ohlcv("GS", date(2026, 4, 1), date(2026, 4, 3))
    after_hits = observability.cache_hits_total.labels(category="ohlcv")._value.get()

    assert after_hits == before_hits + 1, f"Expected hits +1, got before={before_hits} after={after_hits}"


# ---------------------------------------------------------------------------
# Span attribute test (AC-3.3)
# ---------------------------------------------------------------------------

def test_root_span_cache_hit_attribute(fake_cache, make_stub, monkeypatch):
    """After a cache hit, root_span record must have cache_hit=True (AC-3.3).

    We patch observability.root_span to capture the record yielded to _route.
    """
    from contextlib import contextmanager
    from data_vendor_router import observability

    monkeypatch.setenv("DVR_OHLCV_PRIORITY", "yfinance")
    yf = make_stub("yfinance")
    yf.program("get_ohlcv", returns(sample_ohlc_bars(1)))

    captured_records: list[dict] = []
    original_root_span = observability.root_span

    @contextmanager
    def _capturing_root_span(category, ticker):
        with original_root_span(category, ticker) as record:
            captured_records.append(record)
            yield record

    with patch.object(observability, "root_span", _capturing_root_span):
        # Miss + fill
        get_ohlcv("BA", date(2026, 4, 1), date(2026, 4, 3))
        # Hit
        get_ohlcv("BA", date(2026, 4, 1), date(2026, 4, 3))

    assert len(captured_records) == 2
    miss_record, hit_record = captured_records
    # Miss: cache_hit should be False (set by write-through on vendor success)
    assert miss_record.get("cache_hit") == False, f"Miss record cache_hit={miss_record.get('cache_hit')!r}"
    # Hit: cache_hit should be True
    assert hit_record.get("cache_hit") == True, f"Hit record cache_hit={hit_record.get('cache_hit')!r}"
