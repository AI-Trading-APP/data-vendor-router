# Changelog

All notable changes to `data-vendor-router` are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [0.1.2] — 2026-05-30

Seventh vendor adapter (`tiingo`) covering BOTH News and OHLCV — second
free-tier source for each chain. Motivated by the zero-spend platform
certification plan ([AITradingAPP#431](https://github.com/AI-Trading-APP/AITradingAPP/pull/431)):
NewsAPI free is 100 req/day, Tiingo free is 1000 req/day with cleaner data,
so chaining them gives newsservice ~11× more headroom without paid keys.

### Added

- `vendors/tiingo.py` adapter implementing both `NewsProvider.get_news` and
  `OHLCVProvider.get_ohlcv` against Tiingo's REST API (token-header auth)
- Tiingo slotted into `DEFAULT_CHAINS`:
  - **news**: `[newsapi, tiingo, benzinga, alpha_vantage, yfinance]` (was `[newsapi, benzinga, alpha_vantage, yfinance]`)
  - **ohlcv**: `[yfinance, tiingo, alpaca, polygon]` (was `[yfinance, alpaca, polygon]`)
- `tiingo` added to `_BUILTIN_ADAPTER_MODULES` for auto-registration
- 18 new unit tests in `tests/test_vendor_tiingo.py` (happy-path + 429/401/404/500/network + dict-instead-of-list + adj→raw fallback + chain position + registry membership)
- `test_chains.py` assertions updated to expect Tiingo's position in news/ohlcv chains

### Notes

- Requires `TIINGO_API_KEY` env var
- No new package dependencies (uses existing `httpx`)
- Backwards-compatible — chains are env-overridable via `DVR_*_PRIORITY`, so
  deployments that want the v0.1.1 chain can set
  `DVR_NEWS_PRIORITY=newsapi,benzinga,alpha_vantage,yfinance`

## [0.1.1] — 2026-05-13

NewsAPI adapter promoted as primary in the News chain (sixth vendor).

### Added

- `vendors/newsapi.py` adapter — NewsService's actual primary today
- `DEFAULT_CHAINS["news"]` rewritten to `[newsapi, benzinga, alpha_vantage, yfinance]`

## [0.1.0] — 2026-05-04

Initial release. Building Block 3 (BB3) of the
[TradingAgents Adoption Program](https://github.com/AI-Trading-APP/AITradingAPP/issues/101).

### Added

- Three category-based public functions: `get_ohlcv`, `get_news`, `get_fundamentals`
- Five vendor adapters: yfinance, alpaca, benzinga, polygon, alpha_vantage
- Standardized Pydantic v2 frozen DTOs: `OHLCBar`, `NewsItem`, `FundamentalsSnapshot` (with vendor-namespaced `extras` dict)
- Per-vendor pybreaker circuit breakers (default: open after 5 failures in 60s, half-open after 30s)
- Per-vendor configurable single-retry on transient errors (default `True` for yfinance only)
- Six failure-type classification: rate-limit / server-error / timeout → fall back; 404 / 4xx / malformed → raise (no fallback). Preserves bug visibility — vendors-don't-have-it doesn't masquerade as a vendor outage.
- Configurable per-category fallback chains via env vars: `DVR_OHLCV_PRIORITY`, `DVR_NEWS_PRIORITY`, `DVR_FUNDAMENTALS_PRIORITY`
- Per-call `provider_chain` kwarg overrides the configured chain for one-off queries
- OpenTelemetry instrumentation: root `dvr.get_{category}` span + child `dvr.vendor.{name}` spans with outcome attribute
- Prometheus metrics: `data_vendor_router_calls_total`, `data_vendor_router_fallback_total`, `data_vendor_router_latency_seconds`, `data_vendor_circuit_breaker_state`, `data_vendor_circuit_breaker_state_changes_total`
- Auto-registration of every adapter whose vendor SDK is installed; missing SDKs skipped silently
- Typed exception hierarchy: `AllVendorsFailed`, `NotFound`, `BadRequest`, `NoVendorsConfigured`, `VendorResponseInvalid`
- RUNBOOK + Grafana sample dashboard JSON (in `ops/grafana/`)

### Tests

- 88 unit tests, 1 skipped (alpaca tests skipped if alpaca-py SDK not installed; uses `pytest.importorskip`)
- 85% line coverage overall (alpaca module 15% when SDK skipped; all others 80–100%)
- No live vendor calls in CI — all SDKs / HTTP clients stubbed

### Distribution

- Installed via `pip install data-vendor-router @ git+https://github.com/AI-Trading-APP/data-vendor-router.git@v0.1.0`
- Pattern matches `ai-trading-common` and `structured-llm-output` (existing org convention; BB1 pivot lesson applied upfront)

### Known carry-forwards (non-blocking)

- **MIN-1** Default chain ordering driven by reliability data (env-var override available; v0.2 may add automatic reordering)
- **MIN-2** `extras` dict already vendor-namespaced (`extras: dict[str, dict]`) per CTO MIN-2; tests verify no collision
- **MIN-3** `provider_chain` override validates against registered adapters (raises `ValueError` for unknown vendor)
- **MIN-4** Retry-vs-breaker order resolved: retries happen INSIDE the breaker call (1 retry = 1 breaker event)
- **MIN-5** NewsService consumer migration deferred to v0.2.x — BB3 spec assumed Benzinga/Alpha Vantage; reality is NewsAPI + RSS feeds. See [BB3 program-status note](https://github.com/AI-Trading-APP/AITradingAPP/issues/116) for the discrepancy. Possible v0.1.1 / v0.2.0 work: add NewsAPI as a 6th vendor, OR migrate Prediction-Engine's yfinance + Alpaca OHLCV calls (which already match BB3's chains).

[0.1.0]: https://github.com/AI-Trading-APP/data-vendor-router/releases/tag/v0.1.0
