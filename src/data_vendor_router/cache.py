"""DVR read-through cache backed by Redis DB /1.

Design: specs/data-layer-dedup/design.md §1a, §2 Component Map, §Redis key schema,
        §TTL policy, §Fail-open semantics.

Feature flag: ``DVR_CACHE_ENABLED`` environment variable (default off).
When off: no Redis client is constructed, all methods are no-ops / return None.

Install the ``[cache]`` extra to activate:
    pip install data-vendor-router[cache]

The ``redis`` package is imported lazily so that its absence silently disables
the cache rather than crashing at import time (AC-2.3, NFR-5).
"""
from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Lazy Redis import guard — if the [cache] extra is not installed, the cache
# is simply disabled (fail-open at import level, AC-2.3).
# ---------------------------------------------------------------------------
try:
    import redis as _redis_module
    from redis import Redis, RedisError  # noqa: F401

    _REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _REDIS_AVAILABLE = False
    _redis_module = None  # type: ignore[assignment]
    Redis = None  # type: ignore[assignment,misc]
    RedisError = Exception  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# TTL constants (confirmed in design §TTL policy)
# ---------------------------------------------------------------------------
_TTL_OHLCV_MARKET_HOURS: int = 60       # seconds during 09:30–16:00 ET weekday
_TTL_OHLCV_OFF_HOURS: int = 900         # 15 min outside market hours / weekends
_TTL_FUNDAMENTALS: int = 86_400         # 24 h (same off / on hours)
_TTL_NEWS: int = 300                    # 5 min always

# Backoff window: if Redis errored < N seconds ago, skip the attempt (EC-1).
_ERROR_BACKOFF_SECONDS: int = 5

# Market-hours window (ET)
_MARKET_OPEN_H: int = 9
_MARKET_OPEN_M: int = 30
_MARKET_CLOSE_H: int = 16
_MARKET_CLOSE_M: int = 0


def _is_market_hours(now: datetime) -> bool:
    """Return True if *now* falls within 09:30–16:00 ET on a weekday.

    Uses stdlib ``zoneinfo`` (Python ≥ 3.11) for a DST-correct US/Eastern
    conversion (EC-6) — never VPS local time, never a fixed UTC offset.
    ``now`` may be naive (assumed UTC) or tz-aware; either is converted to ET.
    """
    from datetime import timezone as _tz

    if now.tzinfo is None:
        now = now.replace(tzinfo=_tz.utc)
    now_et = now.astimezone(_ET)

    if now_et.weekday() >= 5:  # Saturday=5, Sunday=6
        return False

    market_open = now_et.replace(
        hour=_MARKET_OPEN_H, minute=_MARKET_OPEN_M, second=0, microsecond=0
    )
    market_close = now_et.replace(
        hour=_MARKET_CLOSE_H, minute=_MARKET_CLOSE_M, second=0, microsecond=0
    )
    return market_open <= now_et < market_close


def _ttl_for(category: str, now: datetime) -> int:
    """Return the cache TTL in seconds for *category* at *now*.

    TTL policy (design §2, §TTL policy):
    - ohlcv / quote : 60 s market hours, 900 s off-hours
    - fundamentals  : 86400 s always
    - news          : 300 s always
    """
    if category in ("ohlcv", "quote"):
        return _TTL_OHLCV_MARKET_HOURS if _is_market_hours(now) else _TTL_OHLCV_OFF_HOURS
    if category == "fundamentals":
        return _TTL_FUNDAMENTALS
    if category == "news":
        return _TTL_NEWS
    # Unknown category — use the most conservative (shortest) TTL so stale data
    # doesn't sit indefinitely.  Fail-open: no exception.
    return _TTL_OHLCV_MARKET_HOURS


def _cache_key(category: str, ticker: str, *parts: Any) -> str:
    """Build the Redis key for *category* / *ticker* / optional *parts*.

    Key schema (design §2 Redis key schema):
      dvr:{category}:{TICKER}                           (fundamentals)
      dvr:{category}:{TICKER}:{part1}:{part2}...        (ohlcv, news)

    Ticker is always upper-cased (matches existing DVR span normalisation).
    """
    base = f"dvr:{category}:{ticker.upper()}"
    if parts:
        base += ":" + ":".join(str(p) for p in parts)
    return base


# ---------------------------------------------------------------------------
# Pydantic type-adapters for (de)serialisation — keyed by category.
# Built lazily so the module can still be imported without pydantic (it always
# is, but let's be defensive).
# ---------------------------------------------------------------------------

def _build_type_adapters() -> dict[str, Any]:
    """Return a dict mapping category → pydantic TypeAdapter."""
    from pydantic import TypeAdapter
    from .dto import FundamentalsSnapshot, NewsItem, OHLCBar

    return {
        "ohlcv": TypeAdapter(list[OHLCBar]),
        "quote": TypeAdapter(list[OHLCBar]),
        "news": TypeAdapter(list[NewsItem]),
        "fundamentals": TypeAdapter(FundamentalsSnapshot),
    }


_TYPE_ADAPTERS: dict[str, Any] | None = None


def _get_type_adapter(category: str) -> Any | None:
    global _TYPE_ADAPTERS
    if _TYPE_ADAPTERS is None:
        _TYPE_ADAPTERS = _build_type_adapters()
    return _TYPE_ADAPTERS.get(category)


# ---------------------------------------------------------------------------
# DVRCache
# ---------------------------------------------------------------------------


class DVRCache:
    """Read-through cache layer for the Data Vendor Router.

    Thread-safe for concurrent reads/writes (Redis operations are atomic).
    A single module-level instance is reused across calls (see ``get_dvr_cache``).

    All Redis and serialisation errors are swallowed — the caller always gets a
    cache miss / no-op (fail-open, NFR-1, US-2).  Logs WARN at most once per
    ``_ERROR_BACKOFF_SECONDS`` window to avoid log floods on a dead Redis (EC-1).
    """

    def __init__(self) -> None:
        self._client: Any | None = None  # Redis client, lazy-initialised
        # Use None to mean "no error yet" to avoid the false-positive triggered
        # when time.monotonic() is small (e.g. shortly after process start) and
        # _last_error_time=0.0 would look like "error happened just now".
        self._last_error_time: float | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get(self, key: str, category: str) -> Any | None:
        """Return the cached value for *key* or ``None`` on any error / miss.

        Deserialises using the Pydantic TypeAdapter registered for *category*.
        A validation error (schema drift after a DVR upgrade) is treated as a
        cache miss so the vendor path refills with the current schema (design §Serialisation).
        """
        client = self._client_or_none()
        if client is None:
            return None
        try:
            raw = client.get(key)
        except Exception as exc:
            self._record_error(exc)
            return None

        if raw is None:
            return None

        # Deserialise
        adapter = _get_type_adapter(category)
        if adapter is None:
            # Unknown category — treat as a miss so callers never receive raw
            # bytes they cannot interpret (F4, design §Serialisation).
            logger.warning(
                "DVRCache: unknown category %r for key=%r — treating as miss", category, key
            )
            return None
        try:
            return adapter.validate_json(raw)
        except Exception as exc:
            logger.warning("DVRCache: deserialisation failed for key=%r (%s) — treating as miss", key, exc)
            return None

    def set(self, key: str, value: Any, ttl: int, category: str) -> None:
        """Serialise *value* and write it to Redis with *ttl* seconds expiry.

        Any error is swallowed (never propagates to the caller).
        """
        client = self._client_or_none()
        if client is None:
            return
        adapter = _get_type_adapter(category)
        if adapter is None:
            return
        try:
            raw: bytes = adapter.dump_json(value)
        except Exception as exc:
            logger.warning("DVRCache: serialisation failed for key=%r (%s) — skipping write", key, exc)
            return
        try:
            client.setex(key, ttl, raw)
        except Exception as exc:
            self._record_error(exc)

    def ttl_for(self, category: str, now: datetime | None = None) -> int:
        """Return the appropriate TTL for *category* at *now* (defaults to utcnow)."""
        if now is None:
            from datetime import timezone
            now = datetime.now(tz=timezone.utc)
        return _ttl_for(category, now)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _client_or_none(self) -> Any | None:
        """Return the Redis client, constructing it lazily.

        Returns ``None`` when:
        - ``redis`` package is not installed ([cache] extra absent)
        - We are within the error backoff window (EC-1)
        """
        if not _REDIS_AVAILABLE:
            return None

        # Within backoff window — avoid hammering a dead Redis.
        if self._last_error_time is not None and (
            time.monotonic() - self._last_error_time < _ERROR_BACKOFF_SECONDS
        ):
            return None

        if self._client is None:
            try:
                url = os.environ.get("CACHE_REDIS_URL", "redis://redis:6379")
                # F1: redis-py honours the /db path in the URL and URL kwargs
                # WIN over positional db= when both are supplied — so
                # CACHE_REDIS_URL=redis://host/0 would silently land keys in
                # DB 0 alongside app keys.  Strip any trailing /<digits> path
                # from the URL first, then pass db=1 authoritatively (EC-7,
                # NFR-4).
                sanitised_url = re.sub(r"/\d+$", "", url.rstrip("/"))
                if sanitised_url != url.rstrip("/"):
                    logger.warning(
                        "DVRCache: CACHE_REDIS_URL %r specifies a DB path that "
                        "would override the required DB 1 — ignoring URL path "
                        "and forcing db=1 (F1/EC-7).",
                        url,
                    )
                self._client = _redis_module.Redis.from_url(
                    sanitised_url,
                    db=1,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                    decode_responses=False,  # keep bytes for Pydantic JSON
                )
            except Exception as exc:
                self._record_error(exc)
                return None
        return self._client

    def _record_error(self, exc: Exception) -> None:
        """Log WARN and start the backoff window (EC-1).

        Also resets the client to None so the next attempt after the backoff
        window will try to reconnect (lazy reconnect, EC-1).
        """
        self._last_error_time = time.monotonic()
        self._client = None  # force lazy reconnect after backoff
        logger.warning("DVRCache: Redis error (%s: %s) — bypassing cache", type(exc).__name__, exc)


# ---------------------------------------------------------------------------
# Module-level singleton + flag helper (used by core.py)
# ---------------------------------------------------------------------------

_INSTANCE: DVRCache | None = None


def get_dvr_cache() -> DVRCache | None:
    """Return the module-level ``DVRCache`` singleton when the feature flag is on.

    Returns ``None`` when ``DVR_CACHE_ENABLED`` is unset / falsy — guaranteeing
    zero Redis connections and zero counter increments (NFR-5, AC-9.1).

    The singleton is re-used across calls within the same process.  It is safe
    to call this on every ``_route`` invocation (no lock needed: Python's GIL
    protects the simple assignment).
    """
    enabled = os.environ.get("DVR_CACHE_ENABLED", "").lower() in ("1", "true", "yes", "on")
    if not enabled:
        return None

    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = DVRCache()
    return _INSTANCE
