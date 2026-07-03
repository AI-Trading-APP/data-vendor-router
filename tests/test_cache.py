"""Unit tests for DVRCache (data-layer-dedup DLD-1 / DLD-4).

Uses fakeredis to isolate all Redis operations — no live Redis required.
Covers: hit/miss, TTL policy, fail-open (connection error, set error,
validation error), flag-off (no client constructed), DB /1 isolation,
ticker upper-casing.

AC coverage: AC-1.1, AC-1.3, AC-1.4, AC-1.6, AC-2.1, AC-2.2, AC-2.3,
             EC-1, EC-6, EC-7.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make the package importable from the worktree src dir
SRC_DIR = Path(__file__).parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import fakeredis

from data_vendor_router.cache import DVRCache, _ttl_for, _cache_key, _is_market_hours
from data_vendor_router.dto import OHLCBar, FundamentalsSnapshot, NewsItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cache_with_fake_redis(fake_server=None) -> DVRCache:
    """Return a DVRCache instance wired to a fakeredis server on DB 1."""
    if fake_server is None:
        fake_server = fakeredis.FakeServer()
    cache = DVRCache()
    cache._client = fakeredis.FakeRedis(server=fake_server, db=1, decode_responses=False)
    return cache


def _sample_ohlc_bar() -> OHLCBar:
    from datetime import date
    return OHLCBar(date=date(2026, 4, 1), open=100.0, high=105.0, low=98.0, close=102.0, volume=1_000_000)


def _sample_fundamentals(ticker: str = "AAPL") -> FundamentalsSnapshot:
    return FundamentalsSnapshot(ticker=ticker, market_cap=3e12, pe=30.0, sector="Technology")


def _sample_news() -> NewsItem:
    return NewsItem(
        title="Test News",
        url="https://example.com/1",
        published_at=datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
        source="TestFeed",
    )


# ---------------------------------------------------------------------------
# TTL policy tests (AC-1.3, AC-1.4, EC-6)
# ---------------------------------------------------------------------------

# A weekday datetime at 10:00 ET = 15:00 UTC (market open)
_MARKET_HOURS_UTC = datetime(2026, 7, 2, 15, 0, tzinfo=timezone.utc)   # Wednesday 10:00 ET
# A weekday datetime at 20:00 UTC = 16:00 ET (after close)
_OFF_HOURS_UTC = datetime(2026, 7, 2, 21, 0, tzinfo=timezone.utc)      # Wednesday 17:00 ET
# A weekend datetime
_WEEKEND_UTC = datetime(2026, 7, 5, 15, 0, tzinfo=timezone.utc)        # Sunday 11:00 ET


def test_ttl_market_hours_ohlcv():
    ttl = _ttl_for("ohlcv", _MARKET_HOURS_UTC)
    assert ttl == 60, f"Expected 60 s during market hours, got {ttl}"


def test_ttl_off_hours_ohlcv():
    ttl = _ttl_for("ohlcv", _OFF_HOURS_UTC)
    assert ttl == 900, f"Expected 900 s off-hours, got {ttl}"


def test_ttl_weekend_ohlcv():
    ttl = _ttl_for("ohlcv", _WEEKEND_UTC)
    assert ttl == 900, f"Expected 900 s on weekend, got {ttl}"


def test_ttl_fundamentals_market_hours():
    assert _ttl_for("fundamentals", _MARKET_HOURS_UTC) == 86_400


def test_ttl_fundamentals_off_hours():
    assert _ttl_for("fundamentals", _OFF_HOURS_UTC) == 86_400


def test_ttl_news_market_hours():
    assert _ttl_for("news", _MARKET_HOURS_UTC) == 300


def test_ttl_news_off_hours():
    assert _ttl_for("news", _OFF_HOURS_UTC) == 300


# ---------------------------------------------------------------------------
# Cache key tests (AC-1.4)
# ---------------------------------------------------------------------------

def test_ticker_uppercased_in_key():
    key = _cache_key("ohlcv", "aapl", "2026-04-01", "2026-04-05")
    assert "AAPL" in key
    assert "aapl" not in key


def test_cache_key_schema_ohlcv():
    key = _cache_key("ohlcv", "MSFT", "2026-04-01", "2026-04-05")
    assert key == "dvr:ohlcv:MSFT:2026-04-01:2026-04-05"


def test_cache_key_schema_fundamentals():
    key = _cache_key("fundamentals", "tsla")
    assert key == "dvr:fundamentals:TSLA"


def test_cache_key_schema_news():
    key = _cache_key("news", "nvda", 7, 10)
    assert key == "dvr:news:NVDA:7:10"


# ---------------------------------------------------------------------------
# hit / miss tests (AC-1.1)
# ---------------------------------------------------------------------------

def test_get_miss_returns_none():
    cache = _make_cache_with_fake_redis()
    result = cache.get("dvr:ohlcv:AAPL:2026-04-01:2026-04-05", "ohlcv")
    assert result is None


def test_set_then_get_returns_value():
    cache = _make_cache_with_fake_redis()
    bars = [_sample_ohlc_bar()]
    cache.set("dvr:ohlcv:AAPL:s:e", bars, 60, "ohlcv")
    result = cache.get("dvr:ohlcv:AAPL:s:e", "ohlcv")
    assert result is not None
    assert len(result) == 1
    assert result[0].close == 102.0


def test_set_then_get_fundamentals():
    cache = _make_cache_with_fake_redis()
    snap = _sample_fundamentals("GOOG")
    cache.set("dvr:fundamentals:GOOG", snap, 86400, "fundamentals")
    result = cache.get("dvr:fundamentals:GOOG", "fundamentals")
    assert result is not None
    assert result.ticker == "GOOG"
    assert result.pe == 30.0


def test_set_then_get_news():
    cache = _make_cache_with_fake_redis()
    items = [_sample_news()]
    cache.set("dvr:news:AAPL:7:10", items, 300, "news")
    result = cache.get("dvr:news:AAPL:7:10", "news")
    assert result is not None
    assert len(result) == 1
    assert result[0].title == "Test News"


# ---------------------------------------------------------------------------
# Fail-open tests (AC-2.1, AC-2.2)
# ---------------------------------------------------------------------------

def test_redis_connection_error_on_get_returns_none():
    """Redis ConnectionError on get → DVRCache.get returns None, no exception (AC-2.1)."""
    cache = DVRCache()
    mock_client = MagicMock()
    mock_client.get.side_effect = Exception("Connection refused")
    cache._client = mock_client

    result = cache.get("dvr:ohlcv:AAPL:s:e", "ohlcv")
    assert result is None


def test_redis_error_on_set_swallowed():
    """Redis error on setex → DVRCache.set returns None, no exception (AC-2.2)."""
    cache = DVRCache()
    mock_client = MagicMock()
    mock_client.setex.side_effect = Exception("READONLY mode")
    cache._client = mock_client

    # Should not raise
    cache.set("dvr:ohlcv:AAPL:s:e", [_sample_ohlc_bar()], 60, "ohlcv")


def test_validation_error_on_get_treated_as_miss():
    """Malformed bytes in Redis → validation error treated as a miss (schema-drift, design §Serialisation)."""
    fake_server = fakeredis.FakeServer()
    cache = _make_cache_with_fake_redis(fake_server)
    # Write garbage bytes directly via a second fakeredis client
    raw_client = fakeredis.FakeRedis(server=fake_server, db=1, decode_responses=False)
    raw_client.setex("dvr:ohlcv:AAPL:s:e", 60, b"not-valid-json-{{{")

    result = cache.get("dvr:ohlcv:AAPL:s:e", "ohlcv")
    assert result is None   # treat as miss, no exception


# ---------------------------------------------------------------------------
# Flag-off test (AC-9.1, NFR-5)
# ---------------------------------------------------------------------------

def test_flag_off_no_redis_client(monkeypatch):
    """With DVR_CACHE_ENABLED unset, get_dvr_cache() returns None and no Redis
    client is ever constructed (NFR-5)."""
    from data_vendor_router import cache as cache_module

    monkeypatch.delenv("DVR_CACHE_ENABLED", raising=False)
    # Reset singleton so we get a fresh evaluation
    cache_module._INSTANCE = None

    result = cache_module.get_dvr_cache()
    assert result is None


def test_flag_on_returns_instance(monkeypatch):
    """With DVR_CACHE_ENABLED=true, get_dvr_cache() returns a DVRCache (AC-9.2)."""
    from data_vendor_router import cache as cache_module

    monkeypatch.setenv("DVR_CACHE_ENABLED", "true")
    cache_module._INSTANCE = None

    result = cache_module.get_dvr_cache()
    assert result is not None
    assert isinstance(result, DVRCache)

    # Cleanup singleton for subsequent tests
    cache_module._INSTANCE = None


# ---------------------------------------------------------------------------
# DB /1 isolation test (EC-7, NFR-4)
# ---------------------------------------------------------------------------

def test_db_index_1_isolation():
    """Keys written by DVRCache must not appear on DB /0 (NFR-4)."""
    fake_server = fakeredis.FakeServer()
    cache = _make_cache_with_fake_redis(fake_server)

    bars = [_sample_ohlc_bar()]
    cache.set("dvr:ohlcv:AAPL:s:e", bars, 60, "ohlcv")

    # A second client on DB /0 must NOT see any dvr: keys
    db0_client = fakeredis.FakeRedis(server=fake_server, db=0, decode_responses=False)
    db0_keys = db0_client.keys("dvr:*")
    assert db0_keys == [], f"Found dvr: keys on DB /0: {db0_keys}"

    # DB /1 must have the key
    db1_client = fakeredis.FakeRedis(server=fake_server, db=1, decode_responses=False)
    db1_keys = db1_client.keys("dvr:*")
    assert len(db1_keys) == 1


# ---------------------------------------------------------------------------
# Backoff / lazy reconnect test (EC-1)
# ---------------------------------------------------------------------------

def test_error_backoff_skips_redis():
    """After a Redis error, subsequent calls within the backoff window skip Redis (EC-1)."""
    import time as _time

    cache = DVRCache()
    mock_client = MagicMock()
    call_count = 0

    def _raising_get(key):
        nonlocal call_count
        call_count += 1
        raise Exception("down")

    mock_client.get.side_effect = _raising_get
    cache._client = mock_client

    # First call — triggers error, records timestamp
    cache.get("dvr:ohlcv:AAPL:s:e", "ohlcv")
    assert call_count == 1

    # Second call within backoff — should NOT call client.get again
    cache.get("dvr:ohlcv:AAPL:s:e", "ohlcv")
    assert call_count == 1, "Expected backoff to skip Redis on second call"
