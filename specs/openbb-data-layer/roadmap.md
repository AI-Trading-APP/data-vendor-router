# Roadmap: OpenBB Data Layer
**Feature slug:** openbb-data-layer
**Repo/branch:** `data-vendor-router` @ `feature/openbb-data-layer` (off `development @ 61e4858`)
**Design:** `specs/openbb-data-layer/design.md` | **Spec:** `specs/openbb-data-layer/spec.md`
**SDLC standard:** `~/.claude/commands/sdlc.md` | **Templates:** `specs/_templates/`
**Date:** 2026-06-30

---

## SDLC Gate Note

Before development starts, two human-gate items from `design.md §11` must be resolved (see "Blocked / Needs Clarification" at the bottom). Tickets are written assuming the recommended P1 scope (OHLCV + SEC fundamentals both in P1).

---

## P1 Cluster — MVP (ship + prove on VPS first)

---

### BE-1 — pyproject.toml `[openbb]` extras + version bump

**Category:** Backend
**Priority:** P0
**Repo:** `data-vendor-router`
**Files touched:**
- `/Users/kasireddy/Personal_Projects/AI-Trading-APP/data-vendor-router/pyproject.toml`

**Description:**
Add the `[project.optional-dependencies]` group `openbb` to `pyproject.toml` with pinned packages:
```
openbb-core>=4.3,<5.0
openbb-fmp
openbb-polygon
openbb-sec
```
(`openbb-fred` is P2 — do NOT add it here.) Bump `version` from current to `0.1.3`. Update the `description` field to include `openbb` in the vendor list. This matches design §5 edit#5 and satisfies NFR-3 (pin) and AC-3.1 (extras group). No code changes; no behavior change in base install.

**Dependencies:** none
**Maps to:** US-3, AC-3.1, AC-3.2, NFR-3, NFR-4, NFR-5
**Acceptance:**
- `[openbb]` group present in `pyproject.toml` with the four packages listed above
- `pip install data-vendor-router` (without `[openbb]`) succeeds in a clean venv with no openbb packages pulled
- `version` bumped, `description` updated

---

### BE-2 — `vendors/openbb.py` — OpenBBAdapter (OHLCV + fundamentals)

**Category:** Backend
**Priority:** P0
**Repo:** `data-vendor-router`
**Files touched:**
- `/Users/kasireddy/Personal_Projects/AI-Trading-APP/data-vendor-router/src/data_vendor_router/vendors/openbb.py` **(NEW)**

**Description:**
Create the adapter file implementing the full P1 surface. The file must contain:

1. Module-level `ImportError` guard (cheap `import openbb` probe so `register_all_available()` silently skips when SDK is absent — matches existing pattern in other adapters). The heavy `from openbb import obb` is deferred to `__init__` and method bodies (NFR-1).
2. `OpenBBAdapter` class with:
   - `name = "openbb"`
   - `__init__`: inject `FMP_API_KEY`, `POLYGON_API_KEY`, `FRED_API_KEY` from env into `obb.user.credentials` — only when env var is present (AC-2.2); no home-dir file (AC-2.3)
   - `get_ohlcv(ticker, start, end) -> list[OHLCBar]`: call `obb.equity.price.historical` with `provider="fmp"` then `provider="polygon"` internal fallback (EC-2); run `_obbject_to_bars` to map result
   - `_obbject_to_bars`: call `.to_df()`, run `_EXPECTED_OHLC_COLS` schema canary (AC-1.8 / EC-5), map DatetimeIndex rows to `OHLCBar` DTOs
   - `get_fundamentals(ticker) -> FundamentalsSnapshot`: call `obb.equity.fundamental.metrics` with `provider="sec"` then `"fmp"` fallback; map first row to `FundamentalsSnapshot`, store full row dict in `extras["openbb"]` (AC-5.3); empty df raises `_NotFoundError` (AC-5.2 / EC-7)
   - `_translate(exc, ticker) -> Exception`: exception translation table (AC-1.5, AC-1.6) — map rate-limit / network / 404 / 5xx signals to `_RateLimitError` / `_NetworkError` / `_NotFoundError` / `_ServerError`; default branch returns `_NetworkError` (never raw crash)
3. Module-end registration: `register_adapter("openbb", OpenBBAdapter())` + INFO log line (AC-4.2)

Reference implementation: `vendors/polygon.py` (same structure: VENDOR constant, class, `register_adapter` at module end).

Full skeleton and all method bodies are in `design.md §4.1–4.6`. Implementer must NOT add any P2 methods (`get_macro`, `get_news`) — those belong in BE-5.

**Dependencies:** BE-1 (extras must be defined before the adapter is installable)
**Maps to:** US-1 (AC-1.1, 1.4–1.9), US-2 (AC-2.1–2.3), US-4 (AC-4.1–4.2), US-5 (AC-5.1–5.3), EC-1–EC-7, NFR-1, NFR-5, NFR-6
**Acceptance:**
- `isinstance(OpenBBAdapter(), OHLCVProvider)` is `True`
- `isinstance(OpenBBAdapter(), FundamentalsProvider)` is `True`
- Module-level import of `data_vendor_router` does NOT trigger `from openbb import obb` (lazy check)
- Creds injected from env at init; absent env vars do not raise
- `_obbject_to_bars` raises `VendorResponseInvalid` on missing OHLC columns
- `_translate` maps the exception types listed in design §4.6 correctly

---

### BE-3 — Wire adapter into DVR: `vendors/__init__.py`, `chains.py`, `retry.py`

**Category:** Backend
**Priority:** P0
**Repo:** `data-vendor-router`
**Files touched:**
- `/Users/kasireddy/Personal_Projects/AI-Trading-APP/data-vendor-router/src/data_vendor_router/vendors/__init__.py` — append `"openbb"` to `_BUILTIN_ADAPTER_MODULES`
- `/Users/kasireddy/Personal_Projects/AI-Trading-APP/data-vendor-router/src/data_vendor_router/chains.py` — edit OHLCV chain + fundamentals chain
- `/Users/kasireddy/Personal_Projects/AI-Trading-APP/data-vendor-router/src/data_vendor_router/retry.py` — add `"openbb"` to `RETRY_ON_TRANSIENT_VENDORS`

**Description:**
Apply the three small wiring edits from design §5:

- `vendors/__init__.py` line ~69-77: append `"openbb",` to `_BUILTIN_ADAPTER_MODULES` tuple (edit #1)
- `chains.py` OHLCV default: change to `["polygon", "tiingo", "alpaca", "openbb", "yfinance"]` — `"openbb"` at index 3 (edit #2)
- `chains.py` fundamentals default: append `"openbb"` to produce `["yfinance", "alpha_vantage", "polygon", "openbb"]` (edit #3)
- `retry.py` `RETRY_ON_TRANSIENT_VENDORS`: change to `{"yfinance", "openbb"}` (edit #4)

Also update the `chains.py` docstring to list `openbb` in the vendor description (doc-drift sweep per design §11 item 3).

**Dependencies:** BE-2 (adapter file must exist before wiring references it)
**Maps to:** US-1 (AC-1.2, AC-1.3, AC-1.10), US-4 (AC-4.1), US-5 (AC-5.1), NFR-6, REQ-OBB-02/03/04
**Acceptance:**
- `from data_vendor_router.vendors import get_adapter; get_adapter("openbb")` returns `OpenBBAdapter` instance (no `ValueError`)
- Default OHLCV chain is `["polygon","tiingo","alpaca","openbb","yfinance"]`
- Default fundamentals chain contains `"openbb"` at the end
- `"openbb"` is in `RETRY_ON_TRANSIENT_VENDORS`
- `DVR_OHLCV_PRIORITY=openbb,polygon` env override still yields `["openbb","polygon"]` (AC-1.10)

---

### TEST-1 — `tests/test_vendor_openbb.py` — unit tests with mocked SDK

**Category:** Testing
**Priority:** P0
**Repo:** `data-vendor-router`
**Files touched:**
- `/Users/kasireddy/Personal_Projects/AI-Trading-APP/data-vendor-router/tests/test_vendor_openbb.py` **(NEW)**

**Description:**
Create the unit test file mirroring `tests/test_vendor_polygon.py`. All tests mock the OpenBB SDK via `patch.dict(sys.modules, {"openbb": fake_openbb_module})` injected before adapter instantiation (lazy import makes `patch("…vendors.openbb.obb", …)` unreliable — use sys.modules injection as documented in design §6).

Build a helper that returns a fake `OBBject` whose `.to_df()` returns a controlled pandas DataFrame with `DatetimeIndex` and lowercase `open/high/low/close/volume` columns.

Required test cases (all from design §6 table):

| Test | Covers |
|---|---|
| `test_get_ohlcv_happy_path` | ≥1 `OHLCBar` returned, correct `date`/`close`; provider="fmp" | AC-1.4, AC-6.1(a) |
| `test_get_ohlcv_empty_df_not_found` | `.to_df()` → empty DataFrame both providers → `_NotFoundError` | AC-1.7, AC-6.1(b) |
| `test_get_ohlcv_network_error` | obb call raises `ConnectionError` → `_NetworkError` | AC-1.6, AC-6.1(c) |
| `test_get_ohlcv_rate_limit` | exc msg "429 rate limit" → `_RateLimitError` | AC-1.5, AC-6.1(d) |
| `test_credentials_injected_at_init` | `FMP_API_KEY=test_fmp` etc. set; spy credentials attrs | AC-2.1, AC-6.1(e) |
| `test_credentials_absent_no_error` | no env vars → adapter init succeeds | AC-2.2 |
| `test_schema_canary_drift_raises` | df missing `close` → `VendorResponseInvalid` | AC-1.8, AC-6.1(f), EC-5 |
| `test_ohlcv_fmp_fails_then_polygon` | fmp raises network exc, polygon returns df → bars returned | EC-2 |
| `test_get_fundamentals_happy_path` | `metrics` df 1 row → `FundamentalsSnapshot`, `extras["openbb"]` set | AC-5.1, AC-5.3 |
| `test_get_fundamentals_empty_not_found` | empty df both providers → `_NotFoundError` | AC-5.2, EC-7 |
| `test_isinstance_protocol` | `isinstance(adapter, OHLCVProvider)` and `isinstance(adapter, FundamentalsProvider)` both `True` | AC-1.1 |

Tests must use `@pytest.mark.no_live_vendor` (or equivalent skip tag) so the certify Docker run never hits real APIs. All run via `tools/certify/certify-local.sh` (Docker, not local ARM Mac).

**Dependencies:** BE-2, BE-3
**Maps to:** US-6, AC-6.1(a–f), AC-6.2
**Acceptance:**
- All 11 tests pass in Docker certify run
- No live API calls made (SDK fully mocked)
- File discovered automatically by pytest (no `conftest.py` edits required)

---

### DEVOPS-1 — VPS deploy + live smoke (AC-7)

**Category:** DevOps
**Priority:** P0
**Repo:** `data-vendor-router` (deploy artifact) / ktrading-test VPS
**Files touched (VPS operations, no source edits):**
- VPS venv at `/opt/ai-trading/data-vendor-router/` (or equivalent dvr venv path)
- No committed source file changes

**Description:**
After P1 source tickets (BE-1, BE-2, BE-3, TEST-1) are reviewed and merged to `development`, promote `development → release` and deploy to ktrading-test from a clean `release` checkout per §2a (CLAUDE.md global protocol — `git fetch && git reset --hard origin/release`, no on-box edits).

Deploy steps:
1. On ktrading-test: `pip install "data-vendor-router[openbb]"` in the DVR venv (installs `openbb-core`, `openbb-fmp`, `openbb-polygon`, `openbb-sec`)
2. Confirm `FMP_API_KEY` and `POLYGON_API_KEY` are set in the VPS env (already present from polygon-curated-universe feature per project memory)
3. Run control smoke (AC-7.2): `DVR_OHLCV_PRIORITY=yfinance python -c "import data_vendor_router as d; d.get_ohlcv('AAPL', ...)"` — must raise `AllVendorsFailed` (proves yfinance is dead, openbb result is not a no-op)
4. Run primary smoke (AC-7.1): `DVR_OHLCV_PRIORITY=openbb python -c "..."` — must print non-zero bar count, exit 0
5. Run fallback-chain smoke (AC-7.3): with polygon/tiingo/alpaca breakers forced open and no override, call `get_ohlcv("AAPL", ...)` — must succeed via openbb slot-4
6. Measure cold-start latency: `time python -c "import data_vendor_router"` before vs after — must not exceed +200ms (NFR-1)

All smoke commands run over `ssh -i ~/.ssh/ktrading_deploy root@147.93.27.80` (TIA VPS host from project memory).

**Dependencies:** BE-1, BE-2, BE-3, TEST-1 (all merged to release)
**Maps to:** US-7, AC-7.1, AC-7.2, AC-7.3, AC-2.3, NFR-1
**Acceptance:**
- AC-7.1: AAPL OHLCV returns ≥1 bar via openbb on ktrading-test
- AC-7.2: yfinance-only smoke raises `AllVendorsFailed` (control)
- AC-7.3: default chain + forced breakers → openbb slot-4 succeeds
- NFR-1: cold-start delta ≤200ms
- Deploy is from clean `origin/release`, no on-box source edits

---

## P2 Cluster — Build-out (after P1 shipped and proven on VPS)

---

### BE-4 — `vendors/openbb.py` P2 methods: `get_macro` + `get_news`

**Category:** Backend
**Priority:** P1
**Repo:** `data-vendor-router`
**Files touched:**
- `/Users/kasireddy/Personal_Projects/AI-Trading-APP/data-vendor-router/src/data_vendor_router/vendors/openbb.py` — add `get_macro` and `get_news` methods

**Description:**
Extend the P1 adapter with the two P2 data methods (design §4.7):

- `get_macro(series_id: str, start: date, end: date) -> list[MacroDataPoint]`: call `obb.economy.fred_series(symbol=series_id, start_date=..., end_date=..., provider="fred")`; empty series returns `[]` (EC-8); invalid id raises `_NotFoundError` (AC-8.2). Requires the `MacroDataPoint` DTO (see BE-5).
- `get_news(ticker: str, lookback_days: int, top_n: int) -> list[NewsItem]`: call `obb.news.company(symbols=ticker, provider="fmp")`; map to `NewsItem` DTOs with at least `ticker`, `headline`, `published_at`. Must satisfy `NewsProvider` Protocol.

**Dependencies:** DEVOPS-1 (P1 proven on VPS before P2 starts), BE-5
**Maps to:** US-8 (AC-8.1, AC-8.2), US-9 (AC-9.1, AC-9.2)
**Acceptance:**
- `get_macro("DGS10", start, end)` returns `list[MacroDataPoint]` (mocked in tests)
- `get_macro` with invalid id raises `_NotFoundError`
- `get_macro` with empty result returns `[]`
- `get_news("AAPL")` returns `list[NewsItem]` with required fields
- `isinstance(adapter, NewsProvider)` is `True`

---

### BE-5 — DVR P2 wiring: `dto.py` new DTOs + `chains.py` macro/news chains + `pyproject.toml` `openbb-fred`

**Category:** Backend
**Priority:** P1
**Repo:** `data-vendor-router`
**Files touched:**
- `/Users/kasireddy/Personal_Projects/AI-Trading-APP/data-vendor-router/src/data_vendor_router/dto.py` — add `MacroDataPoint` dataclass (`date`, `value`)
- `/Users/kasireddy/Personal_Projects/AI-Trading-APP/data-vendor-router/src/data_vendor_router/chains.py` — add `"macro"` chain `["openbb"]`; append `"openbb"` after `"yfinance"` in news chain
- `/Users/kasireddy/Personal_Projects/AI-Trading-APP/data-vendor-router/src/data_vendor_router/core.py` — add net-new public function `get_macro(series_id, start, end)` (design §4.7)
- `/Users/kasireddy/Personal_Projects/AI-Trading-APP/data-vendor-router/pyproject.toml` — add `openbb-fred` to `[openbb]` extras

**Description:**
This is the P2 wiring counterpart to BE-3. Three concerns are bundled here because they are each a single line / small dataclass and are tightly coupled (the DTO, the public function, and the chain entry must land together to be independently testable):

- `MacroDataPoint(date: date, value: float)` dataclass in `dto.py` (mirrors `OHLCBar` style)
- `get_macro` public function in `core.py` routing through the new `"macro"` chain
- `"macro": ["openbb"]` chain entry in `chains.py`
- `"openbb"` appended to news chain in `chains.py` (after `"yfinance"`)
- `openbb-fred` added to `[openbb]` extras in `pyproject.toml`

If this ticket would exceed ~5 files or the `core.py` change is materially complex, split `core.py` into a separate BE-6 ticket.

**Dependencies:** DEVOPS-1
**Maps to:** US-8 (AC-8.1), US-9 (AC-9.2), design §4.7
**Acceptance:**
- `MacroDataPoint` importable from `data_vendor_router.dto`
- `data_vendor_router.get_macro("DGS10", start, end)` callable (routes to openbb chain)
- `"openbb"` in news chain default
- `openbb-fred` in `[openbb]` extras

---

### TEST-2 — P2 test extension: `test_vendor_openbb.py` macro + news cases

**Category:** Testing
**Priority:** P1
**Repo:** `data-vendor-router`
**Files touched:**
- `/Users/kasireddy/Personal_Projects/AI-Trading-APP/data-vendor-router/tests/test_vendor_openbb.py` — append P2 test cases

**Description:**
Extend the P1 test file with the P2 method cases (all mocked):

| Test | Covers |
|---|---|
| `test_get_macro_happy_path` | `fred_series` returns df → `list[MacroDataPoint]` | AC-8.1 |
| `test_get_macro_empty_returns_list` | empty df → `[]` (not error) | EC-8 |
| `test_get_macro_invalid_id_not_found` | invalid id → `_NotFoundError` | AC-8.2 |
| `test_get_news_happy_path` | `obb.news.company` returns df → `list[NewsItem]` with ticker/headline/published_at | AC-9.1 |
| `test_isinstance_news_protocol` | `isinstance(adapter, NewsProvider)` is `True` | AC-9.2 |

**Dependencies:** BE-4, BE-5
**Maps to:** US-8 (AC-8.1, AC-8.2), US-9 (AC-9.1), EC-8
**Acceptance:**
- All 5 new tests pass in Docker certify run
- SDK fully mocked, no live calls

---

## Suggested Execution Order

```
BE-1  ──────────────────────────────────────────────────────────────────────────────┐
                                                                                     │
BE-2 (depends BE-1) ──────────────┐                                                 │
                                   ├── BE-3 ── TEST-1 ── (PR-1 review) ── DEVOPS-1 ─┘
                                   │                                         │
                                   │                                         │
                                   │    (P1 shipped + VPS proven)            │
                                   │                                         ▼
                                   │                              BE-5 ──┐
                                   │                              BE-4 ──┴── TEST-2 ── (PR-2 review)
```

**Parallel opportunities:**
- BE-1 can start immediately (no dependencies).
- BE-2 can start as soon as BE-1 is done (or in parallel if extras install not needed for local dev iteration).
- BE-3 and TEST-1 are sequential (BE-3 must wire the adapter before tests reference the chain behavior).
- BE-4 and BE-5 can run in parallel (both depend on DEVOPS-1 but are independent of each other); TEST-2 waits for both.

---

## PR Cadence Plan

**2 PRs to `development`, then each promotes to `release` before deploy:**

- **PR-1 (P1 MVP):** BE-1 + BE-2 + BE-3 + TEST-1 — one new adapter file + 5 small edits + test file. Well under 2,000 net LOC. Merge to `development` → promote to `release` → DEVOPS-1 VPS smoke.
- **PR-2 (P2 build-out):** BE-4 + BE-5 + TEST-2 — `get_macro`/`get_news` methods + DTO + chain edits + test extension. Merge to `development` → promote to `release` → P2 VPS smoke (FRED key provisioning may be needed before P2 deploy).

Each PR gets the standard 2-reviewer gate and DoD audit per `~/.claude/commands/sdlc.md` before merge.

---

## Blocked / Needs Clarification

**Human-gate item 1 (genuine scope decision — blocks BE-2, BE-3, PR-1):**
Design §11 item 1: confirm that P1 includes SEC fundamentals (`openbb-sec` in P1 extras, `get_fundamentals` in `vendors/openbb.py`, fundamentals chain edit in `chains.py`). The roadmap is written assuming **yes** (spec US-5 is P1). If the owner wants P1 restricted to OHLCV-only, BE-2 must drop `get_fundamentals`, BE-3 must omit the fundamentals chain edit, and `openbb-sec` moves to BE-5/PR-2. Confirm before implementer starts BE-2.

**Human-gate item 2 (AC errata — no code change, but affects TEST-1 assertion):**
Design §4.1 / design §11 item 2: `get_adapter("openbb")` raises `ValueError` (not `KeyError`) when absent, per the actual registry at `vendors/__init__.py:48`. Spec AC-1.2 / AC-4.1 say `KeyError`. Approve the 1-word AC correction so TEST-1 asserts `ValueError` (or uses `is_registered("openbb") is False` instead). No code change to the adapter or registry.

**No other blockers.** All infra (VPS, FMP/Polygon keys, Python ≥3.11) confirmed available per project memory. Consumer services require zero changes.
