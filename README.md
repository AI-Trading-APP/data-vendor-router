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

## Run tests

```bash
pip install -e ".[dev,vendors]"
pytest -v
```

Provider SDKs are stubbed in unit tests — no live API calls, no API keys required.

## License

[MIT](LICENSE)
