# Gap Analysis: OpenBB Platform as DVR Provider

**Feature slug:** openbb-data-layer
**Driver/Persona:** CPO/Architect (kasi@ascendsoft.co)
**Date greenlit:** 2026-06-30
**Phase:** 0 — Feasibility
**Analyst:** feasibility-agent

---

## 1. The Requirement (verbatim intent)

> "Integrate the OpenBB Platform open-source Python library (MIT-licensed, NOT the paid Pro/Workspace
> terminal) as a unified market-data provider behind our existing data-vendor-router (DVR) fallback chain.
> Wrap OpenBB BEHIND the existing DVR data interface as ONE MORE provider/fallback — no rip-and-replace,
> contained/reversible/one branch. Natural home = DVR. Prove on LIVE VPS that OpenBB returns data where
> bare yfinance dies. Start FREE (SEC EDGAR + FRED), then fold in FMP/Polygon keys.
> OUT of scope: PyPortfolioOpt, vectorbt, TA-Lib. $0 net cash spend."

**Fixed constraints (not re-litigated):**
- Owner+Architect approved 2026-06-30.
- No rip-and-replace: new provider added as fallback slot, not a refactor of DVR internals.
- No new paid subscriptions (keys we already hold are acceptable; free tiers first).
- Prove on ktrading-test VPS, not local Mac (no local builds rule).

---

## 2. Derived Product Requirements

| ID | Requirement | Existing AC / Spec | Status |
|----|-------------|-------------------|--------|
| REQ-OBB-01 | An `OpenBBAdapter` class implementing the DVR vendor `Protocol`s (`OHLCVProvider`, `FundamentalsProvider`, optionally `NewsProvider`) must exist in `src/data_vendor_router/vendors/openbb.py`. | DVR REQ-DVR-006 (adapter protocol) | net-new (file does not exist) |
| REQ-OBB-02 | `OpenBBAdapter` must self-register via `register_adapter("openbb", OpenBBAdapter())` at module import time. | DVR `_BUILTIN_ADAPTER_MODULES` pattern | net-new (openbb not in list) |
| REQ-OBB-03 | `"openbb"` must be added to `_BUILTIN_ADAPTER_MODULES` in `vendors/__init__.py` so it auto-registers when installed. | `vendors/__init__.py:69-77` | net-new |
| REQ-OBB-04 | Default fallback chains in `chains.py` must be updated so `openbb` appears in the OHLCV chain after polygon/tiingo/alpaca and before yfinance (or configurable via `DVR_OHLCV_PRIORITY`). | `chains.py:26` | net-new (extend existing) |
| REQ-OBB-05 | `openbb-core` + required provider extras (`openbb-sec`, `openbb-fred`; optionally `openbb-fmp`, `openbb-polygon`) must be added to `pyproject.toml` as optional `[openbb]` extras. | `pyproject.toml:21` — existing `[vendors]` extra | net-new extra group |
| REQ-OBB-06 | OpenBB credentials (FRED_API_KEY, FMP_API_KEY, POLYGON_API_KEY) must be injected at adapter init via `obb.user.credentials` attribute assignment, reading from env vars, not from `~/.openbb_platform/user_settings.json` (VPS has no home-dir config). | DVR pattern: `os.getenv("POLYGON_API_KEY")` | net-new (credential injection logic) |
| REQ-OBB-07 | `get_ohlcv` on `OpenBBAdapter` must map to `obb.equity.price.historical(symbol, start_date, end_date, provider=…)` and convert the returned `OBBject.to_df()` into `list[OHLCBar]`. | DTO: `dto.py:15` OHLCBar model | net-new (mapping logic) |
| REQ-OBB-08 | `get_fundamentals` on `OpenBBAdapter` must map to `obb.equity.fundamental.metrics(symbol, provider=…)` (and/or `obb.equity.fundamental.income`) and convert to `FundamentalsSnapshot`. | DTO: `dto.py:38` FundamentalsSnapshot | net-new |
| REQ-OBB-09 | (Optional P2) `get_news` on `OpenBBAdapter` may map to `obb.news.company(symbol, provider=…)` and convert to `list[NewsItem]`. | DTO: `dto.py:27` NewsItem | net-new, lower priority |
| REQ-OBB-10 | All internal OpenBB exceptions must be translated to DVR internal exception types (`_RateLimitError`, `_ServerError`, `_NetworkError`, `_NotFoundError`) so the router's breaker/fallback loop handles them correctly. | `exceptions.py:72-91` | net-new (translation layer) |
| REQ-OBB-11 | A `test_vendor_openbb.py` test file must be added covering: successful OHLCV/fundamentals round-trip (mocked), empty-result → `_NotFoundError`, network failure → `_NetworkError`, and credential injection. | `tests/test_vendor_polygon.py` as template | net-new |
| REQ-OBB-12 | On VPS, a live smoke test must confirm `openbb` provider returns ≥1 OHLCV bar for AAPL via at least one of `fmp`/`polygon`/`sec` provider where yfinance returns nothing. | memory: `reference-box-yfinance-dead-liquidity-floor.md` | net-new (VPS smoke) |

---

## 3. Existing Functionality — What Works Today

| Component | File:line | Behavior today | Limitation for this ask |
|-----------|-----------|---------------|------------------------|
| Router loop (`_route`) | `core.py:29-134` | Tries vendor chain in order; skips open breakers; falls back on transient errors; raises terminal on 404/4xx/malformed | No `openbb` in chain — not invoked |
| Public API surface | `core.py:140-189` | Three public functions: `get_ohlcv`, `get_news`, `get_fundamentals` with optional `provider_chain` override | Contract is complete; no changes needed |
| Adapter Protocol definitions | `vendors/__init__.py:15-32` | `OHLCVProvider`, `NewsProvider`, `FundamentalsProvider` runtime-checkable protocols with typed signatures | OpenBB adapter must implement these; they are complete and ready |
| Adapter registry | `vendors/__init__.py:37-96` | `register_adapter` / `get_adapter` / `register_all_available` auto-imports all builtin modules | `"openbb"` absent from `_BUILTIN_ADAPTER_MODULES` (line 70-77) |
| DTO models | `dto.py:15-54` | `OHLCBar`, `NewsItem`, `FundamentalsSnapshot` (pydantic v2, frozen) | No gap; OpenBB OBBject columns map cleanly to these fields |
| Circuit breaker per vendor | `breakers.py:17-25` | Lazy-creates a `pybreaker.CircuitBreaker` per vendor name; 5 failures/60s → open, 30s half-open | Will auto-apply to `openbb` vendor once registered; no changes needed |
| Retry decorator | `retry.py:26-41` | Opt-in one-retry-on-transient via `RETRY_ON_TRANSIENT_VENDORS` set | OpenBB should be added to this set (network failures expected on library load) |
| Default OHLCV chain | `chains.py:26` | `["polygon", "tiingo", "alpaca", "yfinance"]` | `openbb` absent; must be inserted before yfinance |
| Fundamentals chain | `chains.py:34` | `["yfinance", "alpha_vantage", "polygon"]` | `openbb` absent; good candidate to add after polygon |
| News chain | `chains.py:30` | `["newsapi", "tiingo", "benzinga", "alpha_vantage", "yfinance"]` | `openbb` absent; lower priority for P1 |
| Env-var chain override | `chains.py:37-43` | `DVR_OHLCV_PRIORITY` env var fully overrides default chain | Can be used on VPS to test openbb in chain without code deploy |
| Polygon adapter (reference) | `vendors/polygon.py:35-139` | Full reference implementation: `get_ohlcv` + `get_fundamentals`, httpx-based, `os.getenv` for key, `register_adapter` at module end | OpenBB adapter must mirror this exact structural pattern |
| TIA DVR consumer | `tickeranalysisservice/app/services/clients/dvr_sector.py:1-130` | `fetch_ohlcv_df` + `fetch_histories` call `data_vendor_router.get_ohlcv`; handles `AllVendorsFailed` gracefully | No change needed; will benefit from deeper fallback chain automatically |
| ScreenerService DVR consumer | `ScreenerService/main.py:871-872`, `prediction_engine.py:67-68`, `ml_prediction_engine.py:166-167` | Lazy-imports `data_vendor_router.get_ohlcv`; patches with `AllVendorsFailed` | No change needed |
| PE DVR consumer | `Prediction-Engine/app_v1/domain/data/fetcher.py:389-390` | Lazy-imports DVR; falls back gracefully | No change needed |
| newsservice DVR consumer | `newsservice/news_fetcher.py:34-35` | Imports `get_news` and `AllVendorsFailed` | Would benefit from openbb in news chain (P2) |
| pyproject.toml vendor extras | `pyproject.toml:21-25` | `[vendors]` extra includes yfinance + alpaca-py | openbb packages not listed; no optional `[openbb]` group |

---

## 4. Reusable Infrastructure (Already Built)

| Component | File | Relevance — what gap it pre-closes |
|-----------|------|-------------------------------------|
| `register_adapter(name, instance)` + auto-import at `import data_vendor_router` | `vendors/__init__.py:40-96` | OpenBB adapter self-registers identically to polygon/yfinance; no registry changes needed |
| `pybreaker.CircuitBreaker` lazy-registry | `breakers.py:17-25` | Breaker auto-created for `"openbb"` on first call; no code needed |
| DVR exception hierarchy (`_RateLimitError` / `_ServerError` / `_NetworkError` / `_NotFoundError`) | `exceptions.py:72-91` | OpenBB adapter catches OpenBB-specific errors and re-raises as DVR internal types; router handles rest |
| Env-var chain override (`DVR_OHLCV_PRIORITY`) | `chains.py:37-43` | Enables VPS testing of openbb position in chain without code redeploy — set `DVR_OHLCV_PRIORITY=openbb,polygon,tiingo,alpaca,yfinance` |
| `with_retry(vendor_name)` | `retry.py:26-41` | Add `"openbb"` to `RETRY_ON_TRANSIENT_VENDORS` to get one-retry on library network errors |
| Polygon adapter as structural template | `vendors/polygon.py:35-139` | Exact file structure to mirror (VENDOR constant, class, `_classify_status`, `register_adapter` at end) |
| `FundamentalsSnapshot.extras` dict (vendor-namespaced) | `dto.py:38-54` | OpenBB returns richer data than the common schema; extras field absorbs vendor-specific fields without DTO changes |
| OBBject `.to_df()` → pandas → dict/list path | Verified via OpenBB docs | OpenBB's standardized return object converts to DataFrame with standard OHLC columns matching `OHLCBar` field names |

---

## 5. The Gaps

| Gap ID | Gap | Evidence (file:line) | Severity | Closes REQ | Build vs Reuse | How |
|--------|-----|---------------------|----------|-----------|----------------|-----|
| GAP-01 | `vendors/openbb.py` does not exist | `vendors/__init__.py:69-77` (openbb absent from `_BUILTIN_ADAPTER_MODULES`) | Critical | REQ-OBB-01, REQ-OBB-02, REQ-OBB-07, REQ-OBB-08, REQ-OBB-10 | Build (new file, mirror polygon.py pattern) | New class implementing `get_ohlcv` via `obb.equity.price.historical`, `get_fundamentals` via `obb.equity.fundamental.metrics`; translate OpenBB exceptions to DVR internals; `register_adapter("openbb", OpenBBAdapter())` at module end. Effort: M |
| GAP-02 | `"openbb"` absent from `_BUILTIN_ADAPTER_MODULES` | `vendors/__init__.py:69` | Critical | REQ-OBB-03 | Build (1-line change) | Append `"openbb"` to the tuple in `vendors/__init__.py`. Effort: S |
| GAP-03 | `openbb` not in default fallback chains | `chains.py:26,30,34` | High | REQ-OBB-04 | Build (2–3 line change) | Insert `"openbb"` in OHLCV chain before `"yfinance"` (position 4); add to fundamentals chain after `"polygon"`. Effort: S |
| GAP-04 | No `[openbb]` optional dependency group in `pyproject.toml` | `pyproject.toml:21-25` | High | REQ-OBB-05 | Build (pyproject edit) | Add `[project.optional-dependencies] openbb = ["openbb-core>=4.3", "openbb-sec>=1.0", "openbb-fred>=1.0"]` and `openbb-fmp`/`openbb-polygon` as a second `[openbb-paid]` group for keys we hold. Effort: S |
| GAP-05 | Credential injection for OpenBB on VPS (no home-dir config file) | `vendors/polygon.py:39` (env-var pattern); OpenBB docs confirm `obb.user.credentials.<key> = value` path | High | REQ-OBB-06 | Build (in OpenBBAdapter.__init__) | At adapter init: read `FRED_API_KEY`, `FMP_API_KEY`, `POLYGON_API_KEY` from env and assign to `obb.user.credentials`; do NOT rely on `~/.openbb_platform/user_settings.json` since VPS user home may not have it. Effort: S |
| GAP-06 | OpenBB `.to_df()` column names must be mapped to `OHLCBar` field names | Confirmed by OpenBB docs: columns are `open/high/low/close/volume` (lowercase) | Medium | REQ-OBB-07 | Build (inside GAP-01 implementation) | Iterate DataFrame rows; map `open→open, high→high, low→low, close→close, volume→volume`; parse index (DatetimeIndex) to `date`. Handle adjustment flags. Effort: S (within GAP-01) |
| GAP-07 | No `test_vendor_openbb.py` test file | `tests/` directory has per-vendor test files for all existing vendors | High | REQ-OBB-11 | Build (new test file, mirror `test_vendor_polygon.py`) | Mock `obb` object; test success path, empty-result, network error, credential injection. Effort: M |
| GAP-08 | VPS live smoke: confirm openbb returns OHLCV where yfinance fails on ktrading-test | memory: `reference-box-yfinance-dead-liquidity-floor.md`; VPS IP-blocked by Yahoo | High | REQ-OBB-12 | Build (VPS deploy + smoke script) | Deploy DVR with openbb installed; run `DVR_OHLCV_PRIORITY=openbb,polygon python -c "import data_vendor_router as d; print(d.get_ohlcv('AAPL', ...))"` on ktrading-test via ssh. Effort: S |
| GAP-09 | `openbb` not in `RETRY_ON_TRANSIENT_VENDORS` | `retry.py:21` | Low | REQ-OBB-01 (robustness) | Build (1-line) | Add `"openbb"` to `RETRY_ON_TRANSIENT_VENDORS` set. OpenBB SDK can have transient network hiccups. Effort: XS |
| GAP-10 | OpenBB news provider (`get_news`) not mapped | `chains.py:30` news chain uses newsapi/tiingo/benzinga/alpha_vantage/yfinance | Low | REQ-OBB-09 | Build — deferred to P2 | P2: add `get_news` via `obb.news.company`; map to `list[NewsItem]`. Existing news chain sufficient for P1. Effort: S |
| GAP-11 | OpenBB import weight and startup latency unknown on VPS | UNVERIFIED — no local install tested | Medium | REQ-OBB-05 | Reuse (silent-skip pattern in `register_all_available`) | openbb-core + 2-3 providers estimated ~50-100MB install. The existing `ImportError` silent-skip in `register_all_available` means the VPS venv just needs `pip install openbb-core openbb-fmp openbb-polygon openbb-sec openbb-fred` — no DVR code change needed for graceful absent-SDK handling. Verify install size on VPS before commit. |

---

## 6. Feasibility Verdict & Sequencing

**Verdict: Feasible (reuse-heavy)**

The DVR architecture is purpose-built for exactly this extension pattern. Every system-level concern — breaker, retry, fallback loop, DTO validation, exception routing, env-var chain override, graceful missing-SDK handling — is already operational. The OpenBB adapter is net-new code in a single new file (`vendors/openbb.py`) plus five small edits across three existing files. There is no architectural work, no consumer service changes, and no new infrastructure.

**What is already available:**
- Full router/breaker/retry/observability/DTO/exception infrastructure (0 changes needed)
- All five consumer services (TIA, ScreenerService, PE, precompute, newsservice) already consume DVR via the public API and handle `AllVendorsFailed` gracefully — they pick up openbb as a new fallback slot automatically
- Chain override via `DVR_OHLCV_PRIORITY` env var allows VPS testing before a code deploy
- `FundamentalsSnapshot.extras` absorbs OpenBB-specific fields with no DTO schema change

**What must be built (total effort estimate: M — 3-5 engineer-days including VPS smoke):**

| Item | Effort | Files touched |
|------|--------|---------------|
| `vendors/openbb.py` — new adapter (OHLCV + fundamentals, credential injection, exception mapping) | M | 1 new file |
| Register in `_BUILTIN_ADAPTER_MODULES` | XS | `vendors/__init__.py:70` |
| Insert into default chains | XS | `chains.py:26,34` |
| Add `[openbb]` extras to `pyproject.toml` | S | `pyproject.toml` |
| Add `"openbb"` to `RETRY_ON_TRANSIENT_VENDORS` | XS | `retry.py:21` |
| `tests/test_vendor_openbb.py` | M | 1 new file |
| VPS deploy + live smoke | S | ops/scripts or manual |

**Gated / dependent work:**
- Polygon-curated-universe is already merged to development (confirmed via git log: `61e4858`). The openbb feature branch is off that development HEAD — no coordination blocker.
- No other in-flight feature has claimed `vendors/openbb.py` (new file, no collision).

**MVP slice using existing infra (P1):**
1. `get_ohlcv` only via `obb.equity.price.historical(provider="fmp")` + `obb.equity.price.historical(provider="polygon")` — proves the VPS yfinance-dead case
2. Wire into OHLCV chain: `["polygon", "tiingo", "alpaca", "openbb", "yfinance"]`
3. Use existing FMP + Polygon keys we hold — $0 new spend

**Sequencing:**

- **P0 (no correctness defects found):** No Critical live defects identified outside scope of this feature. No P0 fixes needed before proceeding.
- **P1 (MVP — OHLCV provider, 3-5 days):** GAP-01, GAP-02, GAP-03 (OHLCV chain only), GAP-04, GAP-05, GAP-06, GAP-07, GAP-08, GAP-09. Deploy to ktrading-test and prove 1 real AAPL OHLCV fetch where yfinance returns nothing.
- **P2 (build-out — fundamentals + news, 2-3 days):** GAP-03 (fundamentals chain), GAP-01 (`get_fundamentals` method), GAP-10 (`get_news` + news chain), plus extend test file.

---

## Required for Phase-0 Sign-Off

The following decisions/assumptions must be confirmed by the owner before pm-agent or architect-agent proceeds:

1. **Chain position for openbb in OHLCV:** Recommended default is slot 4 — `["polygon", "tiingo", "alpaca", "openbb", "yfinance"]`. Confirm or adjust. Note yfinance is dead on VPS; openbb with FMP/Polygon keys becomes the real last-resort before the chain exhausts.

2. **Free-first slice provider order inside OpenBBAdapter:** Recommended: try `provider="fmp"` first (FMP key we hold; free tier 300 req/day), then `provider="polygon"` (Polygon key we hold). SEC EDGAR via `openbb-sec` returns filings, NOT OHLCV bars — it is useful for `get_fundamentals` (income statements, balance sheets) but NOT for `get_ohlcv`. Confirm this scope: SEC/FRED = fundamentals/macro only; FMP/Polygon = OHLCV.

3. **FRED macro data scope:** FRED (`obb.economy.fred_series`) does not provide per-ticker OHLCV or fundamentals. It provides macro series (interest rates, CPI, etc.). Confirm whether a `get_macro` / `get_fred_series` method should be added to the DVR public API surface as a net-new category, or FRED is deferred to P2/P3.

4. **Python version on VPS:** DVR `pyproject.toml` requires `>=3.11`. OpenBB Platform supports Python 3.9–3.12 (3.9/3.10 support dropping fall 2025). Confirm ktrading-test VPS Python is >=3.11 (likely already confirmed for polygon-curated-universe, but verify).

5. **P1 scope confirmation:** Confirm P1 = OHLCV only (GAPs 01-09), P2 = fundamentals + news (GAP-10 + fundamentals method). Or confirm if owner wants OHLCV + fundamentals both in P1.

---

## Phase-0 Boundary Study — 2026-07-03

**Author:** feasibility-agent
**Trigger:** PR-1 shipped (code DONE, 2-reviewer PASS, DoD PASS) but BLOCKED from deploy by a reported `pip install` hard failure: the specified packages `openbb-core>=4.3,<5.0`, `openbb-fmp`, `openbb-polygon`, `openbb-sec` were reported NOT to exist on PyPI. This study resolves whether those package names are real, corrects any version pins that are wrong, defines the non-overlapping boundary between this program and data-layer-dedup, and gives a final go/pivot verdict.

---

### 1. PyPI Reality — Actual Package Names and Versions

**Finding: the original version pin `openbb-core>=4.3,<5.0` is WRONG — `openbb-core` uses a 1.x versioning scheme, NOT 4.x. The packages exist but the pin references a version range that has never existed on PyPI.**

The OpenBB Platform ecosystem uses two separate version tracks that are commonly confused:

- The **meta-package `openbb`** (what you get with `pip install openbb`) is currently at 4.7.2 (released May 2026). This is the full-platform bundle with all standard providers. Its internal version counter tracks platform/product releases.
- The **infrastructure package `openbb-core`** (the importable SDK library that adapters use directly) has its own independent version track: current latest is **1.6.1** (released March 2026). It went from 0.x alphas through 1.0.0rc, 1.0, 1.4.x, 1.5.x, and is now at 1.6.1. It has never had a 4.x release.

The spec and `pyproject.toml` on the feature branch specified `openbb-core>=4.3,<5.0`. That constraint matches zero releases on PyPI. A `pip install` with that pin fails with "No matching distribution found" — which is the exact blocker that was reported. The package name `openbb-core` is correct; only the version range is wrong.

**Correct pip-installable package names and latest versions (as of 2026-07-03):**

| Package | PyPI name | Latest version | Notes |
|---------|-----------|---------------|-------|
| Core SDK | `openbb-core` | **1.6.1** | Released 2026-03-05. The importable `from openbb import obb` entry point. Correct name; version pin was wrong. |
| Equity router | `openbb-equity` | **1.4+** | The `/equity` router is its own PyPI package. Without it `obb.equity` raises `AttributeError` at runtime — `get_ohlcv` and `get_fundamentals` both fail silently at slot 4. MUST be listed in extras. |
| FMP provider | `openbb-fmp` | **1.5.1** | Released 2025-10-20. Confirmed on PyPI. Provides `obb.equity.price.historical(provider="fmp")`. |
| SEC provider | `openbb-sec` | Available | Confirmed on PyPI (exact patch version unresolved from search, but the package page exists and is installable). Provides SEC EDGAR filings/fundamentals. |
| FRED provider | `openbb-fred` | **1.6.2** | Confirmed on PyPI. Provides `obb.economy.fred_series`. |
| Polygon provider | `openbb-polygon` | **RISK — see note** | Versions 1.4.0 and 1.5.1 were listed on PyPI. However, a recent OpenBB commit removed Polygon.io support because Polygon.io was acquired and rebranded as "Massive." The `openbb-polygon` package may be present on PyPI but unmaintained/broken against the current Polygon API. Treat as unreliable for P1; use `openbb-fmp` as the primary OHLCV provider inside the adapter instead. |
| Alternative meta-install | `pip install openbb` | 4.7.2 | Installs core + all standard providers including fmp, sec, fred in one command. Heavy (~200-400 MB transitive deps including pandas, pydantic, etc.) but simpler ops. Only sensible on VPS where disk is not a constraint. |

**Minimal installable set for OHLCV + fundamentals + SEC filings:**
```
pip install openbb-core>=1.4,<2.0 openbb-equity>=1.4,<2.0 openbb-fmp openbb-sec openbb-fred
```

The version pin in `pyproject.toml` on the feature branch must be corrected from `openbb-core>=4.3,<5.0` to `openbb-core>=1.4,<2.0` before the deploy can proceed. This is a one-line fix in `pyproject.toml`; no adapter code changes are needed.

**OpenBB internal caching:** `openbb-core` maintains a result registry (the `OBBject` registry) that the CLI uses for interactive session state. In library/programmatic use (which is how the DVR adapter uses it — `obb.equity.price.historical(...)` called directly, no CLI), this registry is populated per-call but is not a persistent cache. There is no TTL-based shared cache inside `openbb-core` that would duplicate what data-layer-dedup does. The OBBject registry is in-process and per-call-result; it does not persist across process restarts or share state across the five DVR-consuming services. Conclusion: no OpenBB internal cache needs to be disabled; the two caching systems do not conflict.

---

### 2. Boundary: Provider Layer vs Caching Layer

The two programs touch different DVR seams and have non-overlapping responsibilities. The boundary is clean.

**Provider layer — this program (openbb-data-layer):**
- Seam: `vendors/openbb.py` (new file) + `vendors/__init__.py:_BUILTIN_ADAPTER_MODULES` (registration) + `chains.py` (chain position).
- Responsibility: data ACQUISITION from external APIs. The OpenBBAdapter implements `OHLCVProvider` / `FundamentalsProvider`, calls `obb.equity.price.historical(...)` or `obb.equity.fundamental.metrics(...)`, converts `OBBject.to_df()` to DVR DTOs, and re-raises OpenBB exceptions as DVR internal types. It is one more interchangeable slot in the vendor chain — no awareness of caching, coalescing, or quota.
- DVR `_route` location: the adapter is invoked inside the vendor loop in `core.py:_route`, after the cache check (see below) and after the breaker check. The adapter never sees a cache hit; it is only called on a miss.

**Caching layer — data-layer-dedup program:**
- Seam: `cache.py` (new `DVRCache` class, reads from Redis DB/1) + `core.py:_route` top (cache check before the vendor loop) + `observability.py` (cache hit/miss counters). P2 adds `coalescing.py` (single-flight) and `quota.py` (per-vendor sliding-window counter, checked inside the loop before the breaker).
- Responsibility: cache/coalesce/quota INSIDE DVR routing. The cache layer wraps the entire vendor loop — on a Redis hit it returns the cached DTO without calling any adapter at all. On a miss, the vendor loop runs (which may invoke the openbb adapter), and the successful result is written to Redis.
- DVR `_route` location: cache check is at the very top of `_route`, before the vendor loop. The openbb adapter, like all adapters, sits inside the vendor loop, which only runs on a cache miss.

**The three non-overlap guarantees:**

- The OpenBBAdapter has zero Redis dependency. It does not import `cache.py`, does not read or write `dvr:*` keys, and does not know whether it was called on a miss or called directly. It is byte-equivalent to the polygon adapter in this regard.
- The DVRCache layer has zero provider-SDK dependency. It does not import `openbb`, does not call `obb.*`, and does not know which vendor filled a cache entry. It serializes and deserializes DVR DTOs regardless of origin.
- The data-layer-dedup design explicitly documents this split (`specs/data-layer-dedup/design.md:9`): "OpenBB = a provider *inside* DVR; this = the cache/dedup layer *above* the whole chain." The dedup feature branch (`feature/data-layer-dedup`) already includes the openbb feature's DVR commit (`0ed659f`) as its base, meaning dedup was designed with the openbb adapter present.

**Dependency sequencing vs the dedup v0.2.0 tag:**
- The openbb feature branch (`feature/openbb-data-layer` @ `44edc4b`) must merge to `development` and be promoted to `release` BEFORE or simultaneously with data-layer-dedup, because dedup's feature branch was rebased on top of the openbb changes (the dedup design references DVR @ `0ed659f`, which is a post-openbb commit). If openbb merges first (which is the natural order since it is code-complete and dedup is paused pre-implementation), dedup's PR-1 will rebase cleanly. If dedup ships first without openbb, the openbb adapter would need a rebase — no architecture conflict, just a merge sequencing preference.
- The dedup `v0.2.0` tag gates the cache feature. The openbb adapter does not need the cache to function; it works with or without `DVR_CACHE_ENABLED`. No hard ordering constraint between the two ship dates from a functionality standpoint — just the rebase preference above.

**What a merged single "data-layer program" roadmap looks like:**

These two programs are already architecturally unified at the DVR seam; what they need is a shipping sequence, not a re-design. The combined program is: (1) openbb adapter merges and deploys first — it resolves the immediate VPS yfinance-dead problem and proves AAPL OHLCV returns via FMP. This is the AC-7 proof the program has been waiting for. (2) data-layer-dedup PR-1 (DLD-1..5, DVR `cache.py` + `_route` cache check + Redis dark-launch) follows, adding the shared Redis cache above the whole vendor loop including the openbb slot — from this point, a cache hit for AAPL skips all adapters (polygon, fmp, openbb, etc.) entirely. (3) data-layer-dedup P2 (coalescing + quota tracker, DLD-6..10) closes the single-flight and rate-limit problems, including the Polygon 5-req/min quota that currently requires the openbb fallback to absorb overflow.

The combined effect is a DVR that: acquires data through an expanded provider set (polygon, tiingo, alpaca, openbb/FMP, yfinance) AND caches results cross-process in Redis to eliminate redundant vendor calls platform-wide. Neither program needs the other to function; together they compound.

---

### 3. Feasibility Verdict — Updated

**Verdict: Feasible with one blocking fix (version pin correction). The program is NOT a pivot candidate.**

The reported `pip install` blocker is a wrong version pin (`>=4.3,<5.0` against a `1.x` package), not a missing or renamed package. The package names `openbb-core`, `openbb-fmp`, `openbb-sec`, `openbb-fred` are all real and installable on PyPI today. The adapter code (152 lines in `vendors/openbb.py`, tests at 299 lines) and all five small edits to existing files are correct for the `1.x` API — the `obb.equity.price.historical()` / `obb.equity.fundamental.metrics()` / `obb.user.credentials` interface has been stable across the 1.x series. The only required change is a one-line correction in `pyproject.toml`:

```
# WRONG (original branch):
"openbb-core>=4.3,<5.0"

# CORRECT (fixed in PR#9):
"openbb-core>=1.4,<2.0"
```

Additionally, `openbb-equity>=1.4,<2.0` must be added — the `/equity` router (`obb.equity`) is its own PyPI package and is not pulled in transitively by `openbb-fmp` alone.

The `openbb-polygon` provider carries a secondary risk (Polygon.io was acquired/rebranded as Massive; the `openbb-polygon` extension may be unmaintained). The adapter uses `openbb-fmp` as the primary OHLCV provider and `openbb-polygon` has been removed from the `[openbb]` extras group. The DVR already has a native `polygon.py` adapter (slot 1 in the chain) that uses the Polygon REST API directly and is proven working — there is no value in duplicating that through an unmaintained OpenBB extension.

Corrected extras group (applied in PR#9 `fix/openbb-pypi-pins`):
```toml
[project.optional-dependencies]
openbb = [
    "openbb-core>=1.4,<2.0",
    "openbb-equity>=1.4,<2.0",
    "openbb-fmp",
    "openbb-sec",
    "openbb-fred",
]
```

The pivot alternative (drop OpenBB, add EDGAR/FRED as direct DVR vendors) remains structurally valid — it is Option B from the design doc — but it is not warranted. The install blocker is a typo-class error, not evidence that the OpenBB SDK is unsuitable. The code, tests, and design are all done. Fixing one line and dropping `openbb-polygon` from the extras unblocks the deploy with no architectural change.

**Required actions before DEVOPS-1 can resume:**
1. Fix `pyproject.toml` on the feature branch: `openbb-core>=1.4,<2.0` (was `>=4.3,<5.0`). DONE in PR#9.
2. Add `openbb-equity>=1.4,<2.0` to `[openbb]` extras. DONE in PR#9.
3. Remove `openbb-polygon` from the `[openbb]` extras group. DONE in PR#9 (adapter already uses fmp-only).
4. Re-run the certify gate with the corrected `pyproject.toml` to confirm `pip install data-vendor-router[openbb]` resolves cleanly.
5. Then proceed with DEVOPS-1 (push → PR → merge → release → VPS deploy → AC-7 live smoke) as documented in `FEATURE.md`.
