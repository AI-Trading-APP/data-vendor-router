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
| 0 Feasibility | IN PROGRESS |
| 1 Spec | pending |
| 2 Design+roadmap | pending |
| 3 Implement | pending |
| 4 DoD | pending |
| Deploy staging | pending |

## Decision log (autonomous)
- 2026-07-03: Created worktrees off `development` in all 5 repos; claimed locks.
- 2026-07-03: Framed as complementary to openbb-data-layer (reuse layer vs provider layer),
  same DVR chokepoint — architect to confirm fold.

## Next step
Run feasibility-agent → specs/data-layer-dedup/gap-analysis.md.

## Where to resume
Fresh session: read this file + `git -C data-vendor-router log development..HEAD` +
specs/data-layer-dedup/*.md. Do NOT re-derive audit — memory project-external-data-dedup-audit.md.
