# High-Level Design (HLD) — <Feature Name>

> **Canonical HLD template** (adopted from the PayPal HLD standard, 2026-06-19). Produced in SDLC **Phase 2**
> by the **architect-agent**, peer-reviewed by the **CTO** gate, signed off before Phase 3. Save as
> `specs/<feature>/design.md`. Sections 1–13 (incl. 3a Solution Options) are mandatory; 14–16 are this project's required extensions.
> Carry `REQ-xxx` IDs forward from `spec.md` — introduce no new scope.

## 1. Document Information
| Field | Value |
|-------|-------|
| Module / Feature Name | |
| Author (agent/role) | |
| Reviewed By | CTO gate / Architect |
| Date | |
| Version | |
| Spec ref | `specs/<feature>/spec.md` |
| Prototype ref | `specs/<feature>/prototype/index.html` |

## 2. Purpose
- Objective of this HLD; what the feature is intended to achieve (tie to the business goal in `spec.md`).

## 3. Scope
- In scope / out of scope. Map to the approved gaps in `gap-analysis.md`.

## 3a. Solution Options & Trade-off Analysis *(MANDATORY — decide before designing)*
- Weigh real alternatives before committing. **Right-size the depth:** for GREEN/reuse-heavy/single-service work, a 3–5 line note ("considered A vs B; chose B because … aligns with long-term arch") replaces the tables below — delete them. Use the full table + matrix only for AMBER/RED scope, a net-new service, or a changed boundary/dependency/cross-cutting pattern.
- Full form: evaluate **≥2–3 candidate solutions**.

| Option | Approach summary | Build-vs-reuse | Rough effort | Key pros | Key cons |
|--------|------------------|----------------|--------------|----------|----------|
| A | | | | | |
| B | | | | | |
| C | | | | | |

- **Decision matrix** — score each option against weighted criteria (**Long-term architectural alignment** weighted highest, then maintainability/extensibility, coupling/cohesion, performance & cost, security/blast-radius, migration & rollback risk, time-to-ship):

| Criterion (weight) | A | B | C |
|--------------------|---|---|---|
| Long-term arch. alignment (×3) | | | |
| Maintainability / extensibility (×2) | | | |
| Coupling / cohesion (×2) | | | |
| Performance & cost (×1) | | | |
| Security / blast-radius (×2) | | | |
| Migration & rollback risk (×1) | | | |
| Time-to-ship (×1) | | | |
| **Weighted total** | | | |

- **Chosen option + rationale:** which option wins and WHY it best fits the platform's long-term architecture.
- **Rejected options:** the specific reason each lost.
- **ADR:** record one if the choice changes an external dependency, a service boundary, or a cross-cutting pattern (flag the doc-drift sweep for the implementing PR).

## 4. System Overview
- High-level explanation of the system, components, user roles, expected behavior.

## 5. Architecture Diagram
- Macro-level architecture (components, APIs, databases). Use a mermaid diagram.

## 6. Component Overview
- Each major component and its purpose. **Tag each `[BUILT]` (with `file:line`) / `[PARTIAL]` / `[NET-NEW]`** — reuse-first per Phase 0.

## 7. Data Flow Diagrams
- Sequence + data-flow diagrams (Level 1 and 2) for major workflows (mermaid `sequenceDiagram`).

## 8. Key Functionalities
- Major features, each linked to its `REQ-xxx`.

## 9. Non-Functional Requirements
- Scalability · Availability · Performance (SLOs: p50<100ms, p99<500ms) · Security · Compliance · Localization.

## 10. Technology Stack
- Frontend / Backend / Database / Queue / Hosting / Monitoring. **Existing-project stacks are fixed** — detect from `CLAUDE.md`, do not override without explicit approval.

## 11. Assumptions
- e.g. "User data pre-validated by identity service." Tag unverified ones `[ASSUMPTION]`.

## 12. Risks and Mitigations
- Risk register rows: | Risk | Probability | Impact | Mitigation | Owner |.

## 13. Open Questions
- Unresolved technical/business questions → adjudicated at the Phase-2 gate; record the decision log.

---
### 14. FE-BE API Contracts *(mandatory — Phase-2 gate blocker)*

> **This section must be complete before Phase-2 sign-off.** Frontend and backend tickets are
> issued in parallel after the gate; the contract is the shared handshake that makes that safe.
> Each contract is written here and extracted to `specs/<feature>/contracts/<endpoint-slug>.md`.
> FE may start mock-coding as soon as "Contract frozen" is stamped. Any deviation during
> implementation requires an explicit contract amendment + re-sign-off — not a silent change.

#### 14a. Endpoint inventory

For every new or changed endpoint, fill one row. No endpoint may be left TBD at sign-off.

| # | Method | Path (`/api/v1/…`) | Auth | Request body (schema / fields) | Response (schema / fields) | Error codes | BE ticket | FE ticket | Contract frozen |
|---|--------|--------------------|------|-------------------------------|----------------------------|-------------|-----------|-----------|-----------------|
| 1 | | | | | | | | | |

#### 14b. Shared type definitions

List types/interfaces shared between FE and BE (TypeScript types, Python Pydantic models, or JSON Schema).
These types are the canonical truth; both sides import/mirror them. Changes require sign-off.

```
// Example: shared type
interface PredictionResult {
  ticker: string;
  direction: 'BUY' | 'SELL' | 'HOLD';
  confidence: number;   // 0.0–1.0
  generatedAt: string;  // ISO-8601
}
```

#### 14c. Error envelope

All endpoints return errors in this standard shape (fill in or reference the project standard):

```json
{ "error": { "code": "VALIDATION_ERROR", "message": "human-readable", "details": {} } }
```

#### 14d. Versioning & breaking-change policy
- URL-versioned `/api/v1`; breaking change ⇒ version bump; old version supported ≥2 sprints.
- A breaking change is: field removed/renamed, type narrowed, new required field, status code changed.
- Non-breaking (additive): new optional field, new endpoint, new non-error status code.

#### 14e. Contract files
Extract each row of §14a into `specs/<feature>/contracts/<endpoint-slug>.md` after sign-off.
The techlead-agent links each contract file in the relevant BE and FE tickets.

### 15. Service Resilience *(project-required)*
- Per outbound call: circuit breaker, retry+backoff (max 3, jitter), timeout (5s default), bulkhead, fallback.

### 16. Per-Block Build Plan *(project-required)*
- Decompose into high-cohesion/low-coupling blocks; mark parallelizable; map to `roadmap.md` sprints.

---
### Sign-off
| Reviewed By | Verdict | Date |
|-------------|---------|------|
| CTO gate | Approve / Request Changes | |
