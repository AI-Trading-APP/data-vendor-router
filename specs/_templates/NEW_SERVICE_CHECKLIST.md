# New Microservice Scaffold Checklist

Run this checklist ONCE at service creation, before the first commit. It is a PREREQUISITE to the
first Phase-0 gap analysis for the new service. Items here are scaffold-time setup concerns that
are painful to retrofit later; all are language/framework-agnostic unless annotated.

---

## Checklist

- [ ] **Dependency management version pinned to org standard** — parent POM version / base image
  tag / language runtime pinned to the org's canonical version, not `latest` or an ad-hoc pin.
  Reference the org's version registry or a peer service's manifest.

- [ ] **Internal service-to-service auth wired** — the service accepts (and validates) the org's
  standard internal auth token/header on all non-public endpoints. Reject requests missing it with
  401, not a silent pass-through. Copy the pattern from a peer service; do NOT invent a new scheme.

- [ ] **Health and readiness endpoints** — `/health` (liveness) and `/ready` (readiness, checks DB
  and critical dependencies) available before the first deploy. Required by load balancers, deploy
  scripts, and smoke suites.

- [ ] **Migration profile split** — schema migration tool (Flyway, Liquibase, Alembic, etc.)
  configured in two profiles:
  - **prod/staging**: `validate`-only (fail fast if schema diverges from migrations; never auto-alter)
  - **test**: `create-drop` or `update` (or equivalent) so test runs are self-contained
  Never run `update`/`create-drop` in prod/staging — silent DDL omissions cause runtime 500s.

- [ ] **Structured logging in org format** — log lines emit JSON (or the org's standard format)
  with at minimum: timestamp, level, service name, trace/correlation ID. Plaintext logs are not
  parseable by the central log aggregator.

- [ ] **Dockerfile — multi-stage, non-root user** — build stage produces the artifact; runtime
  stage is a minimal base image. The process runs as a non-root user (add `USER nonroot` or
  equivalent). Image must build cleanly in CI without host toolchain.

- [ ] **Feature flag OFF by default** — any user-facing surface added by this service is behind a
  flag, defaulting OFF in all environments. The service starts, routes, and health-checks correctly
  even when all flags are off.

- [ ] **Port registered before code is written** — reserve the service port in the org's static
  port registry (deployment config / docker-compose / service manifest) AND verify it is free live
  on the target host (`ss -ltn` / `docker ps`) before writing a single line of code. Collisions
  discovered at deploy time are more expensive to fix than at scaffold time.

- [ ] **API/contract stub registered with gateway or service registry** — add the service's base
  path and OpenAPI stub to the API gateway routing table (even if all routes return 501 Not
  Implemented) before implementation begins. This closes the seam-contract gap at scaffold time:
  callers can integrate against the registered shape, and the cross-service contract-alignment
  review (Two-Reviewer Rule) has a concrete artifact to check.

---

## How to use

1. Copy this file to `specs/_templates/NEW_SERVICE_CHECKLIST.md` in the new service's repo (the
   sync-sdlc script does this automatically).
2. Work through each item before the first feature commit.
3. Keep the filled checklist at `specs/scaffold-checklist.md` in the service repo for auditability.
4. Reference it in the service's project `CLAUDE.md` under "Service Architecture."
