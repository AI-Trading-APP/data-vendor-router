# data-vendor-router

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Category-routed data-fetch with automatic per-vendor fallback. One API surface, 5 vendors, transparent fallback when the primary rate-limits or goes down.

Building Block 3 (BB3) of the [TradingAgents Adoption Program](https://github.com/AI-Trading-APP/AITradingAPP/issues/101). Companion to [`structured-llm-output`](https://github.com/AI-Trading-APP/structured-llm-output) (BB1).

> **Status**: `v0.1.0` (PR-A: foundations + stub adapters; real vendor adapters land in PR-B)

## What it does

- 3 categories: **OHLCV** (price history), **News**, **Fundamentals**
- 5 vendors: **yfinance, Alpaca, Benzinga, Polygon, Alpha Vantage**
- Per-category fallback chain (configurable via env var)
- 6 failure types classified — only transient ones (rate-limit, 5xx, timeout) trigger fallback; 404 / 4xx / malformed do NOT (preserves bug visibility)
- Per-vendor circuit breakers (pybreaker)
- Standardized DTOs (`OHLCBar`, `NewsItem`, `FundamentalsSnapshot`) — vendor-specific shapes normalized internally
- OTel root + per-vendor child spans; Prometheus counters / histograms

## Quick start

```python
from datetime import date
from data_vendor_router import get_ohlcv, get_news, get_fundamentals

bars = get_ohlcv("NVDA", start=date(2026, 4, 1), end=date(2026, 4, 30))
items = get_news("NVDA", lookback_days=7, top_n=10)
snap  = get_fundamentals("NVDA")
```

## Install (consumer)

In your service's `requirements.txt`:

```
data-vendor-router @ git+https://github.com/AI-Trading-APP/data-vendor-router.git@v0.1.0
```

## Configuration

Default chains:

| Category | Chain |
|---|---|
| OHLCV | yfinance → alpaca → polygon |
| News | benzinga → alpha_vantage → yfinance |
| Fundamentals | yfinance → alpha_vantage → polygon |

Override per category via env var:

```bash
export DVR_OHLCV_PRIORITY="alpaca,polygon,yfinance"
```

## Cache layer (v0.2.0+)

DVR optionally fronts all vendor calls with a shared Redis read-through cache so
that every consuming service benefits from data fetched by any other service.

### Install

```bash
pip install data-vendor-router[cache]
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `DVR_CACHE_ENABLED` | *(unset / off)* | Set to `true` / `1` to activate the cache. When off, behaviour is byte-equivalent to v0.1.x (no Redis client constructed). |
| `CACHE_REDIS_URL` | `redis://redis:6379` | Redis connection URL. DVR always uses **DB /1**; the platform uses DB /0 so there is no key collision. |

### Key schema (Redis DB /1)

```
dvr:ohlcv:{TICKER}:{start_iso}:{end_iso}
dvr:fundamentals:{TICKER}
dvr:news:{TICKER}:{lookback_days}:{top_n}
```

Ticker is always upper-cased.

### TTL policy

| Category | During market hours (09:30–16:00 ET, weekday) | Off-hours / weekend |
|---|---|---|
| `ohlcv` | 60 s | 900 s (15 min) |
| `fundamentals` | 86 400 s (24 h) | 86 400 s |
| `news` | 300 s (5 min) | 300 s |

### Fail-open guarantee

Any Redis error (connection refused, timeout, missing `[cache]` extra) is
**swallowed** — the cache is bypassed and the vendor chain runs exactly as in
v0.1.x. A Redis outage never breaks data fetches.

### Observability

Two new Prometheus counters are emitted when the flag is on:

- `dvr_cache_hits_total{category}` — incremented on a cache hit (no vendor call).
- `dvr_cache_misses_total{category}` — incremented on a cache miss before a vendor call.

The root OTel span gains a `dvr.cache_hit` attribute (`true` / `false`) when the flag is on.

### Staging setup

```bash
# In the consumer service's start.sh (committed — never a hand-edit on the box):
export DVR_CACHE_ENABLED="${DVR_CACHE_ENABLED:-false}"
export CACHE_REDIS_URL="${CACHE_REDIS_URL:-redis://redis:6379}"
```

Set `DVR_CACHE_ENABLED=true` in the staging deployment script to activate on ktrading-test.
Production stays off until an explicit owner decision.

---

## Run tests

```bash
pip install -e ".[dev,vendors]"
pytest -v
```

Provider SDKs are stubbed in unit tests — no live API calls, no API keys required.

## License

[MIT](LICENSE)
