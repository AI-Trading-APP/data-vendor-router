# Spec: OpenBB Platform as DVR Data Provider

**Feature slug:** openbb-data-layer
**Phase:** 1 — Requirements
**Author:** pm-agent
**Date:** 2026-06-30
**Gap analysis:** `specs/openbb-data-layer/gap-analysis.md` (signed off 2026-06-30)
**SDLC standard:** `~/.claude/commands/sdlc.md` (global hub); templates auto-synced into `specs/_templates/`
**Branch:** `feature/openbb-data-layer` off `development` @ `61e4858` in repo `data-vendor-router`

---

## EPIC

The live VPS (`ktrading-test`) has yfinance permanently IP-blocked by Yahoo, leaving the platform without a reliable last-resort market-data source for OHLCV prices and fundamentals. This feature integrates the free, MIT-licensed **OpenBB Platform** Python library as one additional fallback provider inside the existing Data Vendor Router (DVR), slotting it into the chain at position 4 (after polygon/tiingo/alpaca, before the dead yfinance). It does not replace any existing DVR plumbing — it wraps the OpenBB SDK behind the same `OHLCVProvider` / `FundamentalsProvider` Protocol the router already understands, injects FMP and Polygon credentials we already hold from the environment (not a home-dir config file), and self-registers identically to the existing polygon/tiingo adapters. Net new cash spend is $0. The five consumer services (TIA, ScreenerService, Prediction Engine, precompute, newsservice) benefit automatically with no code changes. Success = at least one real AAPL OHLCV bar returned on the live VPS where bare yfinance returns nothing.

**P1 (MVP):** OHLCV provider + free SEC EDGAR fundamentals (GAPs 01–09).
**P2 (build-out):** FRED macro series endpoint + company news via `obb.news.company` (GAP-10, FRED sub-gaps).

---

## User Stories

### P1 — MVP

**US-1 — OpenBB OHLCV fallback** (REQ-OBB-01, 02, 03, 04, 07, 10)
As a data consumer service (TIA, ScreenerService, Prediction Engine), I want the DVR to fall back to OpenBB when all higher-priority OHLCV vendors fail or are breaker-open, so that price data remains available on the VPS even though yfinance is IP-blocked.

**US-2 — Credential injection without home-dir config** (REQ-OBB-06)
As an operator deploying on the ktrading-test VPS, I want OpenBB credentials (FMP_API_KEY, POLYGON_API_KEY, FRED_API_KEY) injected from environment variables at adapter init, so that the adapter works in a headless environment with no `~/.openbb_platform/user_settings.json` file.

**US-3 — OpenBB optional install group** (REQ-OBB-05)
As a developer, I want to install the OpenBB provider packages via a single `pip install data-vendor-router[openbb]` extras group, so that existing DVR consumers that do not need OpenBB remain unaffected and the install is opt-in.

**US-4 — Graceful skip when OpenBB SDK is absent** (REQ-OBB-03, REQ-OBB-05, GAP-11)
As an operator running DVR without the OpenBB extras installed, I want the adapter to silently skip registration (matching existing `ImportError` silent-skip behaviour in `register_all_available`) rather than crashing on import, so that non-OpenBB deployments are unaffected.

**US-5 — Free SEC EDGAR fundamentals via OpenBB** (REQ-OBB-08)
As a consumer service requesting company fundamentals, I want `get_fundamentals` on the DVR to be able to fall back to the OpenBB SEC EDGAR provider (no API key required), so that fundamental data remains available without paid vendor calls for SEC-covered equities.

**US-6 — Unit tests for OpenBBAdapter** (REQ-OBB-11)
As a developer or QA engineer, I want a `test_vendor_openbb.py` test file (mirroring `test_vendor_polygon.py`) that covers success, empty-result, and network-error paths with a mocked OpenBB SDK, so that the adapter is verifiable without live API calls in CI.

**US-7 — Live VPS smoke: OHLCV where yfinance is dead** (REQ-OBB-12)
As the CPO, I want confirmation that the OpenBB adapter returns at least one real OHLCV bar for AAPL on ktrading-test via FMP or Polygon, so that the original problem (yfinance IP-blocked) is provably solved before the feature is declared done.

### P2 — Build-out

**US-8 — FRED macro series endpoint** (REQ-OBB-10 partial, GAP-10 FRED sub-scope)
As an analyst or future macro-feature consumer, I want a `get_macro(series_id, start, end)` method on the DVR public API backed by `obb.economy.fred_series`, so that macro economic series (interest rates, CPI, etc.) are accessible through the same router interface.

**US-9 — Company news via OpenBB** (REQ-OBB-09, GAP-10)
As the newsservice, I want `get_news` on the DVR to be able to fall back to the OpenBB company news provider (`obb.news.company`), so that news availability is extended beyond the existing newsapi/tiingo/benzinga/alpha_vantage/yfinance chain.

---

## Acceptance Criteria

### US-1 — OpenBB OHLCV fallback

**AC-1.1** (REQ-OBB-01)
Given the `data_vendor_router` package is installed with the `[openbb]` extras,
When `import data_vendor_router` is executed,
Then a file `src/data_vendor_router/vendors/openbb.py` exists, defines an `OpenBBAdapter` class, and that class implements the `OHLCVProvider` Protocol (`get_ohlcv(ticker: str, start: date, end: date) -> list[OHLCBar]`) as verified by `isinstance(adapter, OHLCVProvider)` returning `True`.

**AC-1.2** (REQ-OBB-02, REQ-OBB-03)
Given the package is installed with `[openbb]` extras,
When `from data_vendor_router.vendors import get_adapter` is called,
Then `get_adapter("openbb")` returns the registered `OpenBBAdapter` instance without raising `KeyError`.

**AC-1.3** (REQ-OBB-04)
Given the default DVR configuration with no `DVR_OHLCV_PRIORITY` env override,
When the OHLCV chain is resolved,
Then the chain is `["polygon", "tiingo", "alpaca", "openbb", "yfinance"]` with `"openbb"` at index 3 (before `"yfinance"`).

**AC-1.4** (REQ-OBB-07)
Given polygon, tiingo, and alpaca breakers are all open (all three are in failure state),
When `data_vendor_router.get_ohlcv("AAPL", start_date, end_date)` is called,
Then the router invokes the OpenBBAdapter, which calls `obb.equity.price.historical(symbol="AAPL", start_date=..., end_date=..., provider="fmp")` (or `"polygon"` as fallback), converts the resulting `OBBject.to_df()` rows into `list[OHLCBar]` with correct `date`, `open`, `high`, `low`, `close`, `volume` fields, and returns that list.

**AC-1.5** (REQ-OBB-10)
Given the OpenBB SDK raises an HTTP 429 / rate-limit response,
When `OpenBBAdapter.get_ohlcv` is called,
Then the adapter catches that exception and re-raises `_RateLimitError` (not the raw OpenBB exception), allowing the DVR breaker and fallback loop to handle it correctly.

**AC-1.6** (REQ-OBB-10)
Given the OpenBB SDK raises a network connectivity exception,
When `OpenBBAdapter.get_ohlcv` is called,
Then the adapter re-raises `_NetworkError`.

**AC-1.7** (REQ-OBB-10)
Given the OpenBB SDK returns an empty DataFrame (ticker not found),
When `OpenBBAdapter.get_ohlcv` is called,
Then the adapter raises `_NotFoundError`.

**AC-1.8** — Schema canary (approved risk mitigation)
Given an upgrade to `openbb-core` that changes the columns returned by `.to_df()`,
When `OpenBBAdapter.get_ohlcv` processes the OBBject,
Then if the expected columns (`open`, `high`, `low`, `close`, `volume`) are absent, the adapter raises a DVR fallback error (any DVR internal exception type) rather than propagating an `AttributeError` or `KeyError` to the caller.

**AC-1.9** (REQ-OBB-09 robustness) — Lazy import
Given the `[openbb]` extras are installed but the module is imported in a service with a cold start,
When `data_vendor_router` is imported at module load time (not during a call),
Then `import obb` (the OpenBB library) is NOT executed at module load; it is deferred to the first method call inside `OpenBBAdapter`, so module-import latency is not increased.

**AC-1.10** (REQ-OBB-04) — Chain override still works
Given the env var `DVR_OHLCV_PRIORITY=openbb,polygon` is set,
When the OHLCV chain is resolved,
Then the chain is `["openbb", "polygon"]`, confirming the existing env-var override mechanism continues to work with the new vendor name.

### US-2 — Credential injection

**AC-2.1** (REQ-OBB-06)
Given env vars `FMP_API_KEY=test_fmp`, `POLYGON_API_KEY=test_poly`, and `FRED_API_KEY=test_fred` are set,
When `OpenBBAdapter()` is instantiated,
Then `obb.user.credentials.fmp_api_key`, `obb.user.credentials.polygon_api_key`, and `obb.user.credentials.fred_api_key` are set to the corresponding env-var values (verified via mocked `obb.user.credentials`).

**AC-2.2** (REQ-OBB-06)
Given none of the credential env vars are set,
When `OpenBBAdapter()` is instantiated,
Then no exception is raised and the adapter initialises successfully (credentials remain unset / default — OpenBB will use anonymous free-tier access).

**AC-2.3** (REQ-OBB-06)
Given a VPS without `~/.openbb_platform/user_settings.json`,
When the adapter is instantiated and `get_ohlcv` is called,
Then the call proceeds normally using env-injected credentials (verified on ktrading-test as part of AC-7.1 smoke).

### US-3 — Optional install group

**AC-3.1** (REQ-OBB-05)
Given `pyproject.toml` is inspected,
When the optional-dependency groups are listed,
Then an `[openbb]` group exists containing at minimum `openbb-core>=1.4,<2.0`, `openbb-equity>=1.4,<2.0`, `openbb-fmp`, `openbb-sec`, and `openbb-fred` (note: `openbb-polygon` removed — unmaintained after Polygon.io → Massive rebrand; DVR native polygon.py covers Polygon at slot 1).

**AC-3.2** (REQ-OBB-05)
Given a clean virtual environment without the `[openbb]` extras installed,
When `pip install data-vendor-router` is run (base install),
Then none of the `openbb-*` packages are pulled in, and `import data_vendor_router` succeeds without error.

### US-4 — Graceful skip when SDK absent

**AC-4.1** (REQ-OBB-03, GAP-11)
Given the `[openbb]` extras are NOT installed in the environment,
When `import data_vendor_router` is executed and `register_all_available()` runs,
Then the `openbb` adapter is silently skipped (no exception, no log ERROR), and `get_adapter("openbb")` raises `KeyError` (confirming it is absent, not partially registered).

**AC-4.2** (GAP-11)
Given the `[openbb]` extras are installed,
When the adapter module is loaded on VPS and the `ImportError`-skip path is NOT triggered,
Then a log line at INFO level confirms `"openbb"` adapter registered successfully.

### US-5 — SEC EDGAR fundamentals

**AC-5.1** (REQ-OBB-08)
Given the OpenBB extras are installed and `openbb-sec` is available,
When `data_vendor_router.get_fundamentals("AAPL")` routes to `OpenBBAdapter`,
Then the adapter calls `obb.equity.fundamental.metrics(symbol="AAPL", provider="sec")` (or `"fmp"` as first try), converts the result to a `FundamentalsSnapshot` DTO, and returns it with at least `ticker` populated.

**AC-5.2** (REQ-OBB-08)
Given a ticker not covered by SEC EDGAR (e.g. a foreign ADR with no SEC filings),
When `OpenBBAdapter.get_fundamentals` is called,
Then the adapter raises `_NotFoundError`, allowing the DVR router to try the next fundamentals provider in the chain.

**AC-5.3** (REQ-OBB-08)
Given the OpenBB SDK returns additional vendor-specific fundamental fields beyond the `FundamentalsSnapshot` common schema,
When the `FundamentalsSnapshot` is constructed,
Then the extra fields are stored in `FundamentalsSnapshot.extras` under an `"openbb"` key, and no `ValidationError` is raised.

### US-6 — Unit tests

**AC-6.1** (REQ-OBB-11)
Given a test run of `test_vendor_openbb.py` with the `obb` SDK mocked,
When all tests in the file are executed,
Then all pass (no failures) and the following cases are covered: (a) successful OHLCV round-trip returning ≥1 `OHLCBar`, (b) empty DataFrame → `_NotFoundError`, (c) network exception → `_NetworkError`, (d) 429 response → `_RateLimitError`, (e) credential env-vars injected correctly at `__init__`, (f) schema-canary column check raises a DVR exception on missing columns.

**AC-6.2** (REQ-OBB-11)
Given `test_vendor_openbb.py` exists in the same `tests/` directory as `test_vendor_polygon.py`,
When the DVR test suite is run via the project's standard certify command,
Then the new file is discovered and run without additional configuration.

### US-7 — Live VPS smoke

**AC-7.1** (REQ-OBB-12)
Given the DVR `[openbb]` extras are installed in the ktrading-test VPS venv and credentials `FMP_API_KEY`/`POLYGON_API_KEY` are set in the environment,
When `DVR_OHLCV_PRIORITY=openbb python -c "import data_vendor_router as d; bars = d.get_ohlcv('AAPL', start, end); print(len(bars))"` is run over ssh on ktrading-test,
Then the command exits 0, prints a non-zero bar count, and does NOT raise `AllVendorsFailed`.

**AC-7.2** (REQ-OBB-12)
Given the above smoke is run with `DVR_OHLCV_PRIORITY=yfinance` (yfinance only) as a control,
When the same command is run,
Then it raises `AllVendorsFailed` (confirming yfinance is indeed dead on this VPS and the openbb result is not a no-op).

**AC-7.3** (REQ-OBB-04, REQ-OBB-12)
Given no `DVR_OHLCV_PRIORITY` override (default chain in use) and polygon/tiingo/alpaca breakers forced open,
When `get_ohlcv("AAPL", ...)` is called on ktrading-test,
Then the OpenBB adapter is reached, returns data, and the call succeeds — confirming normal fallback path works end-to-end on VPS.

### US-8 — FRED macro (P2)

**AC-8.1** (GAP-10 FRED scope)
Given the `[openbb]` extras are installed and `FRED_API_KEY` is set,
When `data_vendor_router.get_macro("DGS10", start_date, end_date)` is called (net-new public method),
Then the DVR calls `obb.economy.fred_series(symbol="DGS10", start_date=..., end_date=..., provider="fred")`, converts the result to a list of `MacroDataPoint` DTOs (each with `date` and `value` fields), and returns it.

**AC-8.2** (GAP-10)
Given an invalid FRED series ID,
When `get_macro` is called,
Then a `_NotFoundError` (or equivalent DVR exception) is raised, not a raw OpenBB exception.

### US-9 — Company news via OpenBB (P2)

**AC-9.1** (REQ-OBB-09, GAP-10)
Given the `[openbb]` extras are installed,
When `data_vendor_router.get_news("AAPL")` exhausts newsapi/tiingo/benzinga/alpha_vantage/yfinance (all breaker-open),
Then the `OpenBBAdapter.get_news` method is invoked, calls `obb.news.company(symbols="AAPL", provider="fmp")`, and returns a `list[NewsItem]` with at least `ticker`, `headline`, and `published_at` populated.

**AC-9.2** (REQ-OBB-09)
Given `"openbb"` is in the news chain default,
When the chain is resolved (no env override),
Then `"openbb"` appears after `"yfinance"` in the news chain (or at the position defined by the architect in the LLD — exact position is an architecture decision), and `get_news` on `OpenBBAdapter` satisfies the `NewsProvider` Protocol.

---

## Non-Functional Requirements

**NFR-1 — Cold-start latency (GAP-11)**
Importing `data_vendor_router` at module load must not increase cold-start time by more than 200 ms on the VPS. OpenBB SDK import must be deferred (lazy) inside adapter methods; measured via `time python -c "import data_vendor_router"` before vs after.

**NFR-2 — FMP free-tier rate limit**
The OpenBB FMP provider usage must not exceed 300 requests/day on the free tier. The adapter must sit at chain slot 4 (higher-priority paid/free-tier vendors are tried first), minimising FMP hits via OpenBB. No dedicated rate-limit counter is required; slot position is the control.

**NFR-3 — openbb-core version pin**
`openbb-core` must be pinned `>=1.4,<2.0` in `pyproject.toml` (corrected from `>=4.3,<5.0` — `openbb-core` uses 1.x versioning, not 4.x; the old pin matched zero PyPI releases). A schema-canary assertion in `get_ohlcv` must raise a DVR internal exception (not crash) if the OBBject column schema diverges from expectations, ensuring a major OpenBB upgrade does not silently corrupt data.

**NFR-4 — Graceful degradation (GAP-11)**
If `openbb-core` is not installed, the DVR must behave identically to today (no `openbb` in chain, no error). Existing consumers must not experience any regression.

**NFR-5 — $0 net spend**
All credentials used by the OpenBB adapter must be keys already held by the project (FMP, Polygon). No new paid subscription or trial is initiated. FRED and SEC EDGAR are free with no key required.

**NFR-6 — Retry on transient network errors**
`"openbb"` must be added to `RETRY_ON_TRANSIENT_VENDORS` (`retry.py`), so the existing one-retry-on-transient decorator applies when OpenBB SDK has a transient network hiccup.

---

## Edge Cases

**EC-1 — OpenBB returns partial date range**
If `obb.equity.price.historical` returns bars for a subset of the requested date range (e.g. market holidays create gaps), the adapter must return whatever bars are available. The DVR router does not require a full date range from a single vendor.

**EC-2 — Both FMP and Polygon fail inside OpenBBAdapter**
If `obb.equity.price.historical(provider="fmp")` and `obb.equity.price.historical(provider="polygon")` both raise exceptions, the adapter must raise a single DVR exception (not two stacked tracebacks), allowing the router's fallback loop to move on to `yfinance` (or declare `AllVendorsFailed`).

**EC-3 — Simultaneous requests — no shared obb credential state**
If multiple threads call `OpenBBAdapter.get_ohlcv` concurrently, credential state set in `obb.user.credentials` at `__init__` must not be overwritten mid-request. The adapter must be thread-safe with respect to credential injection (credentials set once at init, not mutated per call).

**EC-4 — VPS missing FRED/SEC keys**
If `FRED_API_KEY` is absent, the adapter must still init successfully and serve OHLCV (FMP/Polygon). FRED macro calls will fail with `_NetworkError`/`_NotFoundError` and fall through the router; they must not crash the adapter or block OHLCV calls.

**EC-5 — Schema canary fires on OpenBB upgrade**
If an upgrade to `openbb-core>=5.0` (violating the pin) slips through and changes OBBject column names, the schema-canary assertion fires and the router logs the error and tries the next vendor, rather than propagating a raw `KeyError` to the caller.

**EC-6 — Ticker with special characters (e.g. `BRK.B`, `BF.B`)**
The adapter must pass the ticker to OpenBB as-is and not reformat it, since OpenBB handles dotted tickers natively.

**EC-7 — Empty fundamentals response from SEC EDGAR**
If `obb.equity.fundamental.metrics` returns an empty result for a ticker (e.g. recently listed company with no SEC filings), the adapter raises `_NotFoundError`, not a `ValidationError` from attempting to construct a `FundamentalsSnapshot` from empty data.

**EC-8 — P2: FRED series returns no data for date range**
If `obb.economy.fred_series` returns an empty series (series exists but no data in range), `get_macro` returns an empty list (not an error), consistent with how `get_ohlcv` handles a holiday-only date range.

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| `data-vendor-router` DVR repo | Internal — code | All edits are in this repo. Branch: `feature/openbb-data-layer` off `development @ 61e4858`. |
| `openbb-core>=1.4,<2.0` | External — Python package | MIT-licensed. Must be installed as `[openbb]` extras on VPS venv. (Pin corrected from `>=4.3,<5.0` — openbb-core uses 1.x versioning.) |
| `openbb-equity>=1.4,<2.0` | External — Python package | The `/equity` router is its own PyPI package; without it `obb.equity` is absent at runtime. |
| `openbb-fmp` | External — Python package | Uses FMP_API_KEY already held by the project. (`openbb-polygon` dropped — unmaintained post Polygon.io → Massive rebrand; DVR native polygon.py covers Polygon at slot 1.) |
| `openbb-sec`, `openbb-fred` | External — Python packages | Free (no key required for basic usage; FRED key for higher rate limits). |
| `FMP_API_KEY`, `POLYGON_API_KEY` in VPS env | Ops — secrets | Already present on ktrading-test from Polygon-curated-universe feature. No new secret provisioning. |
| `FRED_API_KEY` in VPS env | Ops — secrets (P2) | Optional; FRED works without a key at reduced rate. Provision before P2 goes live. |
| `ktrading-test` VPS (Python ≥3.11) | Infra | Confirmed running Python ≥3.11 (polygon-curated-universe already deployed there). |
| Polygon-curated-universe feature | Feature dependency | Already merged to `development` @ `61e4858`. No coordination blocker. |
| `vendors/polygon.py:35-139` | Reference implementation | Structural template for `vendors/openbb.py` (VENDOR constant, class, `_classify_status`, `register_adapter` at module end). |
| Consumer services (TIA, ScreenerService, PE, precompute, newsservice) | Downstream — no changes | Benefit automatically; zero code changes required in any consumer. |

---

## Out of Scope

- **PyPortfolioOpt, vectorbt, TA-Lib** — explicitly deferred by owner; do not add these packages.
- **OpenBB Pro / Workspace terminal / paid API** — only the open-source `openbb-core` library and free provider extensions.
- **Refactoring DVR internals** — no changes to `core.py`, `breakers.py`, `dto.py`, `exceptions.py` router logic, or any consumer service. This is an additive extension only.
- **New paid API subscriptions** — only keys already held are used.
- **`~/.openbb_platform/user_settings.json` home-dir config** — the VPS adapter must work entirely from environment variables.
- **Replacing yfinance** — yfinance remains in the chain (slot 5 / last). OpenBB is an additional fallback, not a replacement.
- **OpenBB UI / charting features** — only the Python SDK data-fetch methods are used.
- **Architectural changes to the DVR Protocol definitions** — `OHLCVProvider`, `NewsProvider`, `FundamentalsProvider` in `vendors/__init__.py:15-32` are not modified.
- **`get_macro` / FRED in P1** — deferred to P2. No consumer currently requires macro series.
- **OpenBB news in P1** — deferred to P2. Existing news chain (newsapi/tiingo/benzinga/alpha_vantage/yfinance) is sufficient for P1.
- **Local Mac builds or tests** — all build/test/deploy verification runs on the ktrading-test VPS or in Docker; no local ARM Mac validation.

---

## Required for Phase-1 Sign-Off

None. All decisions that were listed in the Phase-0 sign-off checklist have been resolved and logged in `FEATURE.md` (§Phase-0 decisions). The spec is scoped exclusively to the approved gaps. The architect-agent may proceed to Phase 2 (HLD/LLD) immediately.

For completeness, the resolved decisions are:

1. OHLCV chain position: `["polygon","tiingo","alpaca","openbb","yfinance"]` — **confirmed**.
2. SEC EDGAR = fundamentals only, not OHLCV; FMP/Polygon keys = OHLCV — **confirmed**.
3. FRED macro = P2, not P1 — **confirmed**.
4. Python ≥3.11 on VPS — **confirmed** (polygon-curated-universe runs there).
5. P1 = OHLCV + SEC fundamentals; P2 = FRED macro + news — **confirmed**.
6. Packages = `openbb-core>=1.4,<2.0 + openbb-equity>=1.4,<2.0 + openbb-fmp + openbb-sec + openbb-fred` (NOT meta-package; `openbb-polygon` removed — unmaintained) — **corrected 2026-07-03 per PR#9 review findings**.
