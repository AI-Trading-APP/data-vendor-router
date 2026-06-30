# FEATURE: OpenBB Platform as unified data provider behind DVR

_Last updated: 2026-06-30 — Phases 0-2 DONE, Phase 3 (P1 implementation) starting_

## What & why (plain English)
Add the free, open-source **OpenBB Platform** Python library as one more market-data
provider inside our existing data-vendor-router (DVR) fallback chain. Get real data on
the live VPS where bare yfinance is IP-blocked and dies. Start free (SEC EDGAR fundamentals
+ later FRED macro), reuse FMP/Polygon keys we already hold for OHLCV. $0 net spend.

## Greenlit constraints (do NOT re-litigate)
- Owner approved 2026-06-30, $0 net spend. Behind existing DVR interface, no rip-and-replace.
- Home = `data-vendor-router`. Polygon work already merged into development HEAD we branched from.
- OUT of scope: PyPortfolioOpt, vectorbt, TA-Lib. Prove on LIVE VPS (ktrading-test).

## Branch / worktree
- Repo: data-vendor-router | Worktree: ../data-vendor-router-feat-openbb-data-layer
- Branch: feature/openbb-data-layer (off origin/development @61e4858) | Target: development (NOT main)

## Confirmed DVR contract (file:line — from gap-analysis)
- Protocols `vendors/__init__.py:15-32` (structural/getattr-dispatched, no inheritance); registry `:37-96`
- Router/fallback `core.py:29-134`; public API `core.py:140-189`; breaker `breakers.py:17-25`; retry `retry.py:26-41`
- Chains `chains.py:26/30/34` + env override `DVR_OHLCV_PRIORITY` `:37-43`; DTOs `dto.py:15-54`
- Template to mirror: `vendors/polygon.py:35-139`. Consumers (TIA/Screener/PE/precompute/news) need NO change.

## Phases done
- Phase 0 feasibility: gap-analysis.md (Feasible, reuse-heavy). 
- Phase 1 spec: spec.md (9 stories, 34 ACs, 6 NFRs, 8 edge cases). No human-gate.
- Phase 2 design+roadmap: design.md (LLD + exception table + schema-canary) + roadmap.md (8 tickets, 2 PRs).

## All scoping decisions (autonomous, logged — reversible technical, NOT business gates)
1. OHLCV chain = ["polygon","tiingo","alpaca","openbb","yfinance"] (openbb slot 4).
2. Free split: OHLCV via OpenBB→FMP then Polygon (keys held); fundamentals via OpenBB→SEC(free)+FMP; macro via FRED(free).
3. P1 INCLUDES SEC EDGAR fundamentals (confirmed; spec US-5 is P1). P2 = FRED macro + news.
4. AC errata: get_adapter raises ValueError not KeyError — implementer corrects TEST assertion. No code change.
5. Packages openbb-core>=4.3,<5.0 + openbb-fmp + openbb-polygon + openbb-sec (P1); openbb-fred (P2). Not meta-package.
6. Creds via obb.user.credentials from env. Lazy-import obb inside methods; module-level ImportError guard for silent-skip.
7. Schema-canary: missing OHLC cols -> VendorResponseInvalid (loud fallback, not crash). Pin openbb-core<5.0.

## Roadmap / PR cadence
- PR-1 (P1 MVP): BE-1 (pyproject extras) → BE-2 (openbb.py adapter: get_ohlcv+get_fundamentals) →
  BE-3 (wire __init__/chains/retry) → TEST-1 (11 mocked unit tests) → DEVOPS-1 (VPS deploy+live smoke).
- PR-2 (P2): BE-4 (get_macro+get_news) + BE-5 (DTO+core get_macro+chains+openbb-fred) + TEST-2 (5 tests).

## Done
- Phases 0-2 committed on branch (a7af663, 50b8c5f, 23db908, + roadmap commit pending).

## Next
- Phase 3 PR-1: spawn backend-agent for BE-1+BE-2+BE-3 cluster (one file + small edits), then a
  verifier/qa for TEST-1 that RE-RUNS the Docker test build. Then 2-reviewer gate. Then DEVOPS-1.

## Where to resume
Read this file + roadmap.md + `git -C data-vendor-router log development..feature/openbb-data-layer`.
Active work unit = PR-1 (P1 MVP). Deploy + VPS smoke is the proof gate (OpenBB beats dead yfinance).
