# Changelog

All notable changes to `data-vendor-router` are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [0.2.1] — 2026-07-03

Bugfix release — staging-proven P0 (DLD-18 FINDING-1): unregistered vendors in
the default chain caused uncaught `ValueError` → HTTP 500 when polygon + tiingo
breakers were open (watchlistservice hit 8/10 500s on staging). No env changes,
no DB changes. Consumers must bump their pin to `>=0.2.1`.

### Fixed

- **Unregistered-vendor skip in default chain** (`core.py`): When a vendor name
  in the configured default chain has no installed SDK (e.g. `alpaca` without
  `alpaca-py`), `vendors.get_adapter` raised `ValueError: Unknown vendor` which
  was not caught by the per-vendor exception handlers and escaped to the consumer
  as an HTTP 500. `_route` now checks `vendors.is_registered` before entering
  the vendor span for default-chain vendors; unregistered vendors are skipped
  with a one-time WARN log (`dvr: vendor 'alpaca' not registered…`) and recorded
  in `attempts` as `("alpaca", "not_registered")` so `AllVendorsFailed` reporting
  remains honest. The explicit `provider_chain` validation (MIN-3) is unchanged —
  an unknown vendor in a caller-supplied chain remains a loud `ValueError`.
- **Belt-and-braces `ValueError` catch** (`core.py`): Added a `try/except
  ValueError` around `vendors.get_adapter` inside the vendor loop to guard any
  future code path that reaches `get_adapter` with an unregistered vendor name
  (e.g. a caller-supplied chain that somehow bypasses the upfront MIN-3 check).
  On catch the vendor is skipped with a WARN log; `attempts` records
  `"not_registered"` as the reason.
- **`__version__` string** (`__init__.py`): Was stale at `"0.1.0"` since the
  0.2.0 release. Now reads `"0.2.1"`.

### Added

- **Cache-hit INFO log** (`core.py`, AC-3.4 gap): On every Redis cache hit,
  `_route` emits `logger.info("dvr_cache_hit category=… ticker=… key=…")` so
  the pm2 log stream confirms cache activity without requiring Prometheus. The
  log is emitted after `dvr_cache_hits_total` is incremented and before the
  early return.

### Notes

- No env var changes. No DB/migration changes. No new dependencies.
- OpenBB PyPI pin corrections from the [Unreleased] section are rolled into
  this release.

## [Unreleased]

## [0.2.2] — 2026-07-03

Bugfix release — staging-proven P0: `pybreaker.CircuitBreakerError` leaked out of
`_route` as an uncaught exception when a vendor's failure threshold was reached
on the current call (the open-transition moment). The `breakers.is_open()` pre-check
only covers already-open breakers; the mid-call transition was not handled. Staging
trace: tiingo `_NetworkError` → pybreaker `on_failure` callback → `CircuitBreakerError:
Failures threshold reached, circuit breaker opened` → uncaught → watchlist ASGI 500
(2/10 calls per batch). Consumers must bump their pin to `>=0.2.2`.

### Fixed

- **`CircuitBreakerError` escape from `_route`** (`core.py`): Added
  `except pybreaker.CircuitBreakerError` to the per-vendor except chain, placed
  after `VendorResponseInvalid` (terminal) handlers so it cannot shadow DVR-internal
  errors. On catch: records `(vendor_name, "circuit_breaker_open")` in `attempts`,
  logs `WARNING dvr: vendor <name> circuit breaker tripped mid-call`, increments
  `skip_count`, and `continue`s to the next vendor. All-vendors-exhausted path
  produces `AllVendorsFailed` as expected.
- **OpenBB PyPI pin** (`pyproject.toml`): Corrected `[openbb]` extras — `openbb-core>=1.4,<2.0`
  (was `>=4.3,<5.0`, matched zero PyPI releases); dropped unmaintained `openbb-polygon`;
  added `openbb-equity>=1.4,<2.0` (required for `obb.equity` at runtime).

### Notes

- No env var changes. No DB/migration changes. No new runtime dependencies.
- `import pybreaker` added to `core.py` (already a runtime dep in `pyproject.toml`).
- Consumers running `>=0.2.1` must pin to `>=0.2.2` to avoid the 500 regression.

## [0.2.0] — 2026-07-03

Shared Redis read-through cache (data-layer-dedup P1, DLD-1..DLD-5). All
changes are behind the `DVR_CACHE_ENABLED` feature flag — default off, which
is byte-equivalent to v0.1.x behaviour (NFR-5).

### Added

- `src/data_vendor_router/cache.py` — `DVRCache` class: lazy Redis client
  (DB /1), per-category TTLs (ohlcv 60s/900s, fundamentals 24h, news 5m),
  Pydantic `TypeAdapter` JSON serialisation, fail-open on any Redis/serialisation
  error, lazy-reconnect backoff (EC-1), market-hours tz-aware check (EC-6).
- `[cache]` optional-dependency group: `redis>=5.0.0,<6.0.0`.
- `DVR_CACHE_ENABLED` feature flag (default off); `CACHE_REDIS_URL` env var
  (default `redis://redis:6379`, DVR uses DB /1).
- Cache read-through injected at the top of `_route` (before the vendor loop);
  write-through on every vendor success.
- Two new Prometheus counters in `observability.py`:
  `dvr_cache_hits_total{category}`, `dvr_cache_misses_total{category}`.
- `dvr.cache_hit` OTel span attribute on the root span (True/False when flag on).
- `tests/test_cache.py` — 12 unit tests covering hit/miss/TTL/fail-open/flag-off/
  db-isolation/ticker-uppercasing paths.
- `tests/test_core_cache.py` — 8 integration tests: hit skips vendor, miss calls
  vendor + writes cache, flag-off regression, counter increments, span attribute,
  Redis-down fail-open.

### Notes

- Consumers install with `pip install data-vendor-router[cache]` and set
  `DVR_CACHE_ENABLED=true` (staging only for P1; prod flip is a later owner gate).
- `fakeredis>=2.0` added to `[dev]` extras for unit tests.
- No schema changes. No new services. Zero new infra (reuses the Redis already
  on ktrading-test; DVR uses DB /1, platform services use DB /0 — isolated).
- **F3 (known, design-accepted):** The cache key does not include `provider_chain`.
  A per-call `provider_chain` override may be served cached data from a
  default-chain response (or vice versa).  Tracked as follow-up DLD-follow-F3.

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
