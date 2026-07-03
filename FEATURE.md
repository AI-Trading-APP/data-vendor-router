# FEATURE: data-layer-dedup

**Slug:** data-layer-dedup
**Driver:** CPO (kasi@ascendsoft.co) — cost/rate-limit/quota protection
**Started:** 2026-07-03 (autonomous-feature-builder)

## The ask
Unified external-data reuse layer inside DVR: dedup (single-flight request coalescing) +
shared Redis-backed cache + per-vendor quota/budget tracking, so the same vendor data is
fetched once and reused platform-wide. Migrate 4 straggler services onto DVR. Fold into the
OpenBB data-layer program (OpenBB = a provider behind DVR; this = the reuse/cache layer).

## Business driver
Polygon FREE tier = 5 calls/min + EOD; yfinance DEAD on VPS. Duplicate cross-service fetches
burn the scarce quota. Dedup + cache = quota/cost protection.

## Repos touched (worktrees created off `development`)
- data-vendor-router (CORE — add cache/coalescing/quota)  → feature/data-layer-dedup
- ScreenerService (straggler: yfinance+FMP direct)        → feature/data-layer-dedup
- portfolioservice (straggler: yfinance, dual-phase dup)  → feature/data-layer-dedup
- watchlistservice (straggler: yfinance direct)           → feature/data-layer-dedup
- papertradingservice (straggler: yfinance direct)        → feature/data-layer-dedup

## Audit baseline (memory: project-external-data-dedup-audit.md, 2026-07-03)
- DVR = shared LIBRARY, per-category fallback chains, per-vendor circuit breakers. NO cache,
  NO single-flight, NO quota tracking (RUNBOOK: consumer's responsibility).
- 4 divergent cache stacks (mem/Redis/PG/SQLite), inconsistent TTLs (30s..6h).
- OpenBB program greenlit (specs/openbb-data-layer/) — must be ONE program, not two.

## Status
| Phase | State |
|-------|-------|
| 0 Feasibility | DONE — FEASIBLE (reuse-heavy, no new infra) |
| 1 Spec | DONE (spec.md signed off, US-1..US-9 P1) |
| 2 Design+roadmap | DONE (design.md + roadmap.md, ADR-1 approved) |
| 3 Implement PR-1 | **IN PROGRESS** — DLD-1..DLD-4 COMPLETE; DLD-5 (staging deploy + v0.2.0 tag) PENDING |
| 3 Implement PR-2..PR-5 | Blocked on DLD-5 (v0.2.0 tag gate) |
| 4 DoD | pending |
| Deploy staging | pending |

## Decision log (autonomous)
- 2026-07-03: Created worktrees off `development` in all 5 repos; claimed locks.
- 2026-07-03: Framed as complementary to openbb-data-layer (reuse layer vs provider layer),
  same DVR chokepoint — architect to confirm fold.


- 2026-07-03 Phase-0 DONE: gap-analysis.md written. VERDICT FEASIBLE, reuse-heavy, ZERO new infra.
  Staging Redis 7 CONFIRMED live (redis://redis:6379/0, multi-repo-deploy.sh:118-208, shared by NPP/TIA/Reasoning).
  Injection point = DVR `core.py:29-41` `_route` (covers get_ohlcv/get_news/get_fundamentals in one wrap).
  RedisHybridCache L1+L2 fail-open pattern already battle-tested x3 (Screener/Portfolio/Watchlist) = template.
  Architect decisions I OWN (recorded, not human-gated): TTL per class (rec OHLCV 60s / fundamentals 24h / news 5min),
  cross-process coalescing = P2 (in-process threading.Event P1), Redis DB index namespace, keep per-service L1 mem.
  NO genuine human gate (no paid tier, no prod go-live in scope). Proceeding to Phase 1 spec.


- 2026-07-03 Resolved all feasibility-flagged "gates" as OWNED architecture decisions (none are real human gates):
  (1) Redis namespace: use dedicated DB index /1 for DVR cache (namespace isolation from NPP/TIA on /0).
  (2) TTL policy: OHLCV/quote 60s market / 15min off-hours; fundamentals 24h; news 5min. (architect finalizes in HLD)
  (3) Coalescing: in-process threading.Event = P1; cross-process Redis NX = P2 (complexity deferred).
  (4) Dead-yfinance market-index (Screener GAP-S2): route via DVR (polygon-first); drop yfinance path.
  (5) Merge-order: openbb (0ed659f #7) ALREADY on `development` in DVR; our worktrees stack cleanly on it. NO conflict.
  Both feasibility runs agreed: FEASIBLE, reuse-heavy, ZERO new infra, cache est. cuts vendor calls 70-90%.

## PR-1 implementation log (2026-07-03)
DLD-1 (cache.py): dd2692a — DVRCache, _ttl_for, _cache_key, get_dvr_cache() singleton.
DLD-2 (core.py + observability.py): 0972118 — cache read/write-through in _route,
  dvr_cache_hits_total + dvr_cache_misses_total counters, dvr.cache_hit span attribute.
DLD-3 (pyproject + README + CHANGELOG): be9c55c — version 0.2.0, [cache] extra, doc-drift sweep.
DLD-4 (tests): 2806001 — 22 unit tests (test_cache.py) + 8 integration tests (test_core_cache.py).
Gate-1 result: 162 passed, 1 skipped (live_vendor), 0 failed — local Python 3.9.6 / system pip.

## Next step (RESUME HERE)
DLD-5: merge PR-1 to development, deploy DVR library to ktrading-test via consumer service
redeploy (any DVR consumer), pip install data-vendor-router[cache]>=0.2.0,<0.3.0, set
DVR_CACHE_ENABLED=true (committed to start.sh), run two sequential curl calls, confirm
redis-cli -n 1 keys "dvr:*" has entries and redis-cli -n 0 keys "dvr:*" returns nothing,
then tag v0.2.0 on development HEAD. After that PR-2..PR-5 (straggler services) can proceed
in parallel.

## Where to resume
Fresh session: read this file + `git log` on feature/data-layer-dedup branch.
Specs at specs/data-layer-dedup/. Do NOT re-derive — memory project-external-data-dedup-audit.md.
