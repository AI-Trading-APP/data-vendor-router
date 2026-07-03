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


# ---------------------------------------------------------------------------
# F1: DB isolation — URL with /0 path must still land keys on DB 1 (EC-7)
# ---------------------------------------------------------------------------

def test_cache_redis_url_with_db0_path_still_uses_db1(monkeypatch):
    """CACHE_REDIS_URL=redis://host:6379/0 must not bypass DB /1 isolation (F1/EC-7).

    Verifies that keys written via DVRCache are not visible on DB /0 even when
    the URL carries a /0 path that redis-py would otherwise honour.
    """
    import fakeredis

    fake_server = fakeredis.FakeServer()

    # Patch Redis.from_url so that the sanitised URL (with /0 stripped) is used,
    # and we can confirm the client actually targets DB 1.
    original_from_url = None
    captured_kwargs: dict = {}

    import data_vendor_router.cache as cache_module

    def _patched_from_url(url, **kwargs):
        captured_kwargs.update(kwargs)
        captured_kwargs["url"] = url
        # Return a real FakeRedis on DB 1 so subsequent set/get work
        return fakeredis.FakeRedis(server=fake_server, db=kwargs.get("db", 1), decode_responses=False)

    monkeypatch.setenv("CACHE_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(cache_module._redis_module.Redis, "from_url", staticmethod(_patched_from_url))

    cache = DVRCache()
    # Trigger lazy client construction
    client = cache._client_or_none()

    assert client is not None, "Expected a Redis client to be constructed"
    # The URL passed to from_url must NOT contain /0
    assert not captured_kwargs.get("url", "").endswith("/0"), (
        f"URL passed to from_url still contains /0: {captured_kwargs.get('url')}"
    )
    # db kwarg must be 1
    assert captured_kwargs.get("db") == 1, (
        f"Expected db=1, got db={captured_kwargs.get('db')}"
    )

    # Write a key and confirm it is NOT visible on DB /0
    bars = [_sample_ohlc_bar()]
    cache.set("dvr:ohlcv:AAPL:s:e", bars, 60, "ohlcv")

    db0_client = fakeredis.FakeRedis(server=fake_server, db=0, decode_responses=False)
    assert db0_client.keys("dvr:*") == [], "Keys must not appear on DB /0"


def test_cache_redis_url_path_with_query_still_uses_db1(monkeypatch):
    """redis://host:6379/0?socket_timeout=1 — path + other query params (F1 form 1).

    The /0 path must be stripped; non-db query params (socket_timeout) must be
    preserved; db=1 must be passed to from_url.
    """
    import fakeredis
    import data_vendor_router.cache as cache_module

    fake_server = fakeredis.FakeServer()
    captured_kwargs: dict = {}

    def _patched_from_url(url, **kwargs):
        captured_kwargs.update(kwargs)
        captured_kwargs["url"] = url
        return fakeredis.FakeRedis(server=fake_server, db=kwargs.get("db", 1), decode_responses=False)

    monkeypatch.setenv("CACHE_REDIS_URL", "redis://localhost:6379/0?socket_timeout=1")
    monkeypatch.setattr(cache_module._redis_module.Redis, "from_url", staticmethod(_patched_from_url))

    cache = DVRCache()
    client = cache._client_or_none()

    assert client is not None
    url_used = captured_kwargs.get("url", "")
    # Path /0 must be gone
    from urllib.parse import urlsplit
    parsed = urlsplit(url_used)
    assert parsed.path == "", f"Path not stripped: {url_used!r}"
    # db kwarg must be 1
    assert captured_kwargs.get("db") == 1, f"Expected db=1, got {captured_kwargs.get('db')}"
    # Keys stay off DB 0
    bars = [_sample_ohlc_bar()]
    cache.set("dvr:ohlcv:AAPL:s:e", bars, 60, "ohlcv")
    db0 = fakeredis.FakeRedis(server=fake_server, db=0, decode_responses=False)
    assert db0.keys("dvr:*") == [], "Keys must not appear on DB /0"


def test_cache_redis_url_db_query_param_still_uses_db1(monkeypatch):
    """redis://host:6379?db=0 — db as query param (F1 form 2).

    redis-py parse_url honours ?db=0 and it wins over the db= kwarg.
    The sanitiser must strip the db query param before from_url is called.
    """
    import fakeredis
    import data_vendor_router.cache as cache_module
    from urllib.parse import urlsplit, parse_qsl

    fake_server = fakeredis.FakeServer()
    captured_kwargs: dict = {}

    def _patched_from_url(url, **kwargs):
        captured_kwargs.update(kwargs)
        captured_kwargs["url"] = url
        return fakeredis.FakeRedis(server=fake_server, db=kwargs.get("db", 1), decode_responses=False)

    monkeypatch.setenv("CACHE_REDIS_URL", "redis://localhost:6379?db=0")
    monkeypatch.setattr(cache_module._redis_module.Redis, "from_url", staticmethod(_patched_from_url))

    cache = DVRCache()
    client = cache._client_or_none()

    assert client is not None
    url_used = captured_kwargs.get("url", "")
    # ?db= must not appear in the sanitised URL
    qs_keys = [k for k, _ in parse_qsl(urlsplit(url_used).query)]
    assert "db" not in qs_keys, f"db still in query string: {url_used!r}"
    # db kwarg must be 1
    assert captured_kwargs.get("db") == 1, f"Expected db=1, got {captured_kwargs.get('db')}"
    # Keys stay off DB 0
    bars = [_sample_ohlc_bar()]
    cache.set("dvr:ohlcv:AAPL:s:e", bars, 60, "ohlcv")
    db0 = fakeredis.FakeRedis(server=fake_server, db=0, decode_responses=False)
    assert db0.keys("dvr:*") == [], "Keys must not appear on DB /0"


# ---------------------------------------------------------------------------
# F2: DST-boundary test — zoneinfo gives correct ET offset in summer & winter
# ---------------------------------------------------------------------------

def test_is_market_hours_dst_summer():
    """July 09:35 ET (UTC-4 DST) = 13:35 UTC — must be detected as market hours (F2)."""
    # 2026-07-09 13:35 UTC = 09:35 America/New_York (EDT, UTC-4)
    summer_utc = datetime(2026, 7, 9, 13, 35, tzinfo=timezone.utc)
    assert _is_market_hours(summer_utc), (
        "Expected 09:35 ET in July (DST active) to be within market hours"
    )


def test_is_market_hours_dst_winter():
    """Same UTC wall-clock (13:35 UTC) in January = 08:35 ET (EST, UTC-5) — before open (F2)."""
    # 2026-01-09 13:35 UTC = 08:35 America/New_York (EST, UTC-5) — before 09:30
    winter_utc = datetime(2026, 1, 9, 13, 35, tzinfo=timezone.utc)
    assert not _is_market_hours(winter_utc), (
        "Expected 08:35 ET in January (DST inactive) to be BEFORE market hours"
    )


def test_is_market_hours_dst_winter_open():
    """14:40 UTC in January = 09:40 ET (EST) — within market hours (F2)."""
    # 2026-01-09 14:40 UTC = 09:40 America/New_York (EST, UTC-5) — after 09:30
    winter_open_utc = datetime(2026, 1, 9, 14, 40, tzinfo=timezone.utc)
    assert _is_market_hours(winter_open_utc), (
        "Expected 09:40 ET in January (DST inactive) to be within market hours"
    )


# ---------------------------------------------------------------------------
# F4: unknown category in get() returns None (miss), not raw bytes
# ---------------------------------------------------------------------------

def test_get_unknown_category_returns_none():
    """get() for an unknown category must return None (miss), never raw bytes (F4)."""
    fake_server = fakeredis.FakeServer()
    cache = _make_cache_with_fake_redis(fake_server)

    # Seed a raw value directly so there IS something in Redis for this key
    raw_client = fakeredis.FakeRedis(server=fake_server, db=1, decode_responses=False)
    raw_client.setex("dvr:custom:AAPL", 60, b'{"some":"data"}')

    result = cache.get("dvr:custom:AAPL", "custom_unknown_category")
    assert result is None, (
        f"Expected None for unknown category, got {result!r}"
    )
