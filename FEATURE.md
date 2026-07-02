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
| 1 Spec | pending |
| 2 Design+roadmap | pending |
| 3 Implement | pending |
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

## Next step
Run pm-agent → spec.md (scope to approved P1/P2 gaps).

## Where to resume
Fresh session: read this file + `git -C data-vendor-router log development..HEAD` +
specs/data-layer-dedup/*.md. Do NOT re-derive audit — memory project-external-data-dedup-audit.md.
