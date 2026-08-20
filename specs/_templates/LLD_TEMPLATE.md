# Low-Level Design (LLD) — <Module/Feature Name>

> **Canonical LLD template** (adopted from the PayPal LLD standard, 2026-06-19). Produced in SDLC **Phase 3b**
> by the **techlead-agent** / **developer-agent** per building block, before implementation. Save per block as
> `specs/<feature>/lld/<block>.md`. All 15 sections mandatory.

## 1. Module / Feature Name
- Name · Owner (agent/role) · Date

## 2. Overview
- **Objective:** what this module does. · **Scope:** covered / out of scope.

## 3. High-Level Architecture
- Architecture diagram (or link to the HLD). · **Dependencies:** internal/external services & APIs.

## 4. Components & Classes
- Core + helper classes with responsibilities (one row each: Class | Responsibility | Collaborators).

## 5. APIs (Internal/External)
- Endpoints: | Method | Path (`/api/v1/...`) | Description | Params | Response | Status codes |.
- **Authentication & Authorization:** include object-level authz (ownership/workspace) — guard IDOR/BOLA.

## 6. Data Model
- Tables/collections: name, fields, type, description. · Relationships (ERD / joins). · Migrations are additive (Prisma migrate, not ddl-auto); rollback script per change.

## 7. Workflow / Sequence Diagrams
- Core workflows as sequence / activity / state diagrams (mermaid).

## 8. Configuration
- Env vars / **feature flags** (`ff_<feature>_<component>`): name, default, description. · External configs / secrets references (never commit secrets).

## 9. Logging, Monitoring & Alerts
- Logs (which, levels, format — structured). · Metrics & dashboards (Prometheus/Grafana). · Alerts/thresholds. · OTel spans at service boundaries, DB calls, external API calls.

## 10. Testing Plan
- Unit (scope + target ≥90% line on new code). · Integration (end-to-end modules/services). · Test data requirements (link `golden-data.json`). · Map every acceptance criterion → ≥1 test.

## 11. Error Handling & Retries
- Failure scenarios + handling. · Retry logic (exponential backoff, queue-based). · Error taxonomy.

## 12. Deployment Considerations
- Service name · Containerization (Dockerfile) · CI/CD pipeline gates · Rollback strategy (<15 min, tested).

## 13. Security Considerations
- Data sensitivity & protection (encryption at rest/in transit). · Vulnerability mitigation (input validation, rate limiting, SAST/DAST). · Audit logs for state-changing ops.

## 14. Assumptions & Open Questions
- Assumptions. · Open questions / dependencies.

## 15. Approval & Sign-off
| Reviewed By | Verdict | Sign-off Date |
|-------------|---------|---------------|
| Sr. Software Architect (Reviewer) | | |
