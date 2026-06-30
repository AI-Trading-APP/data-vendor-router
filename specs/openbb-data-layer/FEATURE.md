# FEATURE: OpenBB Platform as unified data provider behind DVR

_Last updated: 2026-06-30 — Phases 0-2 DONE; PR-1 (P1) BUILT + 2-reviewer VERIFIED green. Next: DoD audit → release → VPS smoke._

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
- VPS: ssh ktrading-test (= root@147.93.27.80, key ~/.ssh/ktrading_deploy). NOT teclavya.

## Phases done
- Phase 0 feasibility, Phase 1 spec, Phase 2 design+roadmap — all committed (gap-analysis/spec/design/roadmap.md).
- Phase 3 PR-1 (P1 MVP) BUILT + 2-reviewer VERIFIED:
  - Commit 9a76205 "feat(openbb): PR-1 MVP cluster". Files: NEW vendors/openbb.py (152L), NEW tests/test_vendor_openbb.py (299L),
    edits to pyproject.toml (v0.1.3 + [openbb] extras), vendors/__init__.py, chains.py, retry.py, tests/test_chains.py.
  - Implementer Docker test: 11 new passed; full suite 123 passed/2 skipped.
  - INDEPENDENT verifier (fresh Docker re-run, did NOT build it): VERDICT PASS. 11/11 + 123 passed/2 skipped, ZERO regressions,
    no pre-existing issues, no blockers. Every AC checked w/ file:line evidence. Lazy-import + protocol conformance confirmed.

## All scoping decisions (autonomous, logged — reversible technical, NOT business gates)
1. OHLCV chain = ["polygon","tiingo","alpaca","openbb","yfinance"]. Fundamentals chain += "openbb" tail.
2. Free split: OHLCV via OpenBB→FMP then Polygon (keys held); fundamentals via OpenBB→SEC(free)+FMP; macro via FRED(free,P2).
3. P1 INCLUDES SEC EDGAR fundamentals (built). P2 = FRED macro + news.
4. AC errata: get_adapter raises ValueError not KeyError — handled in TEST-1 via isinstance. No code change.
5. Packages openbb-core>=4.3,<5.0 + openbb-fmp + openbb-polygon + openbb-sec (P1); openbb-fred (P2). Not meta-package.
6. Creds via obb.user.credentials from env. Lazy-import obb; module-level ImportError guard for silent-skip.
7. Schema-canary missing OHLC cols -> VendorResponseInvalid. Pin openbb-core<5.0.
8. Unit tests MOCK openbb (sys.modules) — real openbb packages only needed at VPS deploy, not for unit tests.

## PR cadence
- PR-1 (P1 MVP): BE-1/BE-2/BE-3/TEST-1 — DONE+VERIFIED on branch. Pending: DoD audit → merge dev → release → DEVOPS-1 VPS smoke.
- PR-2 (P2): BE-4 (get_macro+get_news) + BE-5 (DTO+core get_macro+chains+openbb-fred) + TEST-2 — AFTER P1 proven on VPS.

## Next (resume here)
1. Phase 4: independent dod-auditor-agent (must NOT be builder/verifier/orchestrator) RE-RUNS evidence vs 8-phase DoD. Honor any block.
2. If DoD passes: merge feature/openbb-data-layer → development (PR), promote development → release.
3. DEVOPS-1 (devops-agent, haiku): clean-release deploy to ktrading-test, `pip install "data-vendor-router[openbb]"` in DVR venv,
   confirm FMP_API_KEY/POLYGON_API_KEY in VPS env (present from polygon feature), run AC-7 smokes:
   (a) DVR_OHLCV_PRIORITY=yfinance AAPL -> AllVendorsFailed (control proving yfinance dead),
   (b) DVR_OHLCV_PRIORITY=openbb AAPL -> >=1 bar (PROOF), (c) default chain + forced breakers -> openbb slot-4 succeeds,
   (d) cold-start delta <=200ms. ALL via clean origin/release, NO on-box source edits (§2a).
4. Then PR-2 (P2). Then learning-promoter-agent close-out. Do NOT run token-economist (on-demand only).

## Where to resume
Read this file + roadmap.md + `git -C data-vendor-router log development..feature/openbb-data-layer`.
The OpenBB-beats-yfinance PROOF is the DEVOPS-1 live VPS smoke — that is the feature's whole point and the final gate.
