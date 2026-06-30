# FEATURE: OpenBB Platform as unified data provider behind DVR

_Last updated: 2026-06-30 — Phase 0 DONE, Phase 1 (spec) in progress_

## What & why (plain English)
Add the free, open-source **OpenBB Platform** Python library as one more market-data
provider inside our existing data-vendor-router (DVR) fallback chain. Goal: get real
data on the live VPS where bare yfinance is IP-blocked and dies. Start free
(SEC EDGAR filings + FRED macro), then fold in FMP/Polygon keys we already hold.
Net cash spend = $0 (likely a small DROP via free SEC/FRED).

## Greenlit constraints (do NOT re-litigate)
- Owner approved 2026-06-30, $0 net spend.
- HARD: wrap OpenBB BEHIND existing DVR interface as one more provider/fallback. No rip-and-replace.
- Home = `data-vendor-router` (DVR). Polygon work already merged into development HEAD we branched from.
- OUT of scope: PyPortfolioOpt, vectorbt, TA-Lib.
- Prove on LIVE VPS (ktrading-test).

## Branch / worktree
- Repo: data-vendor-router | Worktree: ../data-vendor-router-feat-openbb-data-layer
- Branch: feature/openbb-data-layer (off origin/development @61e4858) | Target: development (NOT main)

## Phase 0 feasibility — DONE (verdict: Feasible, reuse-heavy)
Confirmed DVR contract (file:line evidence in gap-analysis.md):
- Adapter Protocols: `vendors/__init__.py:15-32` — `OHLCVProvider`, `NewsProvider`, `FundamentalsProvider` (runtime-checkable)
- Registry: `register_adapter(name, instance)` + `_BUILTIN_ADAPTER_MODULES` auto-import `vendors/__init__.py:37-96`
- Router/fallback loop: `core.py:29-134`; public API `get_ohlcv/get_news/get_fundamentals` `core.py:140-189`
- Breaker (per-vendor, lazy): `breakers.py:17-25`; retry opt-in: `retry.py:26-41`
- Default chains: `chains.py:26/30/34`; env override `DVR_OHLCV_PRIORITY` `chains.py:37-43`
- DTOs: `dto.py:15-54` OHLCBar/NewsItem/FundamentalsSnapshot (pydantic v2 frozen; `.extras` absorbs vendor fields)
- Reference template to mirror: `vendors/polygon.py:35-139`
- Consumers (NO change needed): TIA, ScreenerService, Prediction-Engine, precompute, newsservice
Net-new: `vendors/openbb.py` + ~5 small edits (__init__ tuple, chains, pyproject extras, retry set) + tests + VPS smoke.

## Phase-0 decisions (autonomous, logged — owner pre-cleared, these are reversible technical scoping)
1. OHLCV chain = `["polygon","tiingo","alpaca","openbb","yfinance"]` (openbb slot 4, real last-resort on VPS).
2. SEC EDGAR + FRED do NOT serve OHLCV. Split: OHLCV via OpenBB→FMP/Polygon (keys held);
   fundamentals via OpenBB→SEC EDGAR (truly free); macro via OpenBB→FRED (truly free).
3. FRED macro = thin get_macro capability, deferred to P2 (no P1 consumer; VPS-proof is OHLCV).
4. Python ≥3.11 on VPS verified at deploy (devops-agent); polygon work already runs there.
5. P1 = OHLCV (prove VPS yfinance-dead case) + free SEC EDGAR fundamentals. P2 = FRED macro + news.
6. Packages: openbb-core + openbb-sec + openbb-fred + openbb-fmp + openbb-polygon (NOT the full meta-package).
   Credentials via `obb.user.credentials` from env (no ~/.openbb_platform home config on VPS).

## Done
- Phase 0: worktree, lock, gap-analysis.md (feasible, reuse-heavy). Decisions logged above.

## Next
- Phase 1: pm-agent → spec.md scoped to approved gaps (GAP-01..09 P1, GAP-10 + FRED P2).

## Where to resume
Read this file + `git -C data-vendor-router log development..feature/openbb-data-layer` + specs/openbb-data-layer/gap-analysis.md.
