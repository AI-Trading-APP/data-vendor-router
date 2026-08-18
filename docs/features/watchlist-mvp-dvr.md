# FEATURE — watchlist-mvp (data-vendor-router / DVR quote seam)

**Status:** Phase 3. Canonical plan: `<workspace>/specs/watchlist-mvp/` (design.md, roadmap.md, contracts/, .ai/PHASE_GATES.md).
This worktree carries ONLY the WL-004 quote seam (ADR-WL-8). Branch `feature/watchlist-mvp` off `development`.

## Done
- **WL-004-DVR-1 (8d5c11a) GREEN 2026-08-17** — additive quote seam mirroring the existing `OHLCVProvider` pattern:
  - `Quote` pydantic DTO (`ticker`, `bid`/`ask`/`last` nullable) in `src/data_vendor_router/dto.py`.
  - `QuoteProvider(Protocol)` (`get_quote(ticker)->Quote|None`) + a separate name-keyed `_QUOTE_PROVIDERS` registry slot (bypasses `_route`, no shared breaker/cache state) in `src/data_vendor_router/vendors/__init__.py`; `reset_registry()` clears it too.
  - Public `get_quote(ticker, *, provider_chain=None) -> Quote|None` in `src/data_vendor_router/core.py` — returns `None` cleanly when no quote provider configured (MVP $0 default).
  - Exports in `src/data_vendor_router/__init__.py`. Tests: `tests/test_quote.py`.
  - **Docker full suite: 178 passed / 2 skip** (zero regression to OHLCV/news/fundamentals). Opus adversarial 2-reviewer: APPROVE.

## Fast-follow
- **WL-004-FF3 (Low):** bump `__version__` 0.2.2 → 0.3.0 on the DVR release that carries `get_quote` (watchlistservice consumes it via a guarded import today; import guard tolerates its absence at v0.2.2, so not a defect now). The real vendor quote adapter is deferred to the WL-003 vendor-activation gate.

## Notes
- ⚠ Lock overlaps a STALE (2026-06-30, unmerged) `openbb-data-layer` claim on the provider registry `__init__.py`. This change is additive-only (new slot); semantic re-verify the registry at any future openbb merge.

## Where to resume
`/autobuild resume watchlist-mvp` → `specs/watchlist-mvp/.ai/PHASE_GATES.md` shows current phase. This worktree is complete for Wave D unless the WL-003 vendor gate activates (then: add a real `QuoteProvider` adapter here + bump version).
