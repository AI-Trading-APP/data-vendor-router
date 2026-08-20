# Definition of Done — Checklist for <Feature/Release>

> **Canonical DoD gate** (adopted from the PayPal SDLC DoD, 2026-06-19). The **DoD Auditor Agent** fills and
> verifies this per feature before it can be marked Done. Copy to `specs/<feature>/dod-checklist.md`. A box is
> only ticked with evidence (file/PR/run link). **No feature is Done with any unchecked Critical item or any
> open critical/high bug.** Maps PayPal's 8 phases to this platform's DoD dimensions.

Feature: `__________` · Auditor: `DoD Auditor Agent` · Date: `____` · Verdict: ☐ Done ☐ Not Done

> **Two-Reviewer Confirmation Rule (MANDATORY, see `/sdlc`):** Every AI update/result/confirmation needs a
> MINIMUM of 2 independent reviews (fresh agents; the producer may not review its own work; ≥1 must re-run/
> re-derive the evidence — not re-state it) before it's ticked here. Reviewer roles are chosen by work type
> (backend→peer+QA, frontend→peer+QA, DB→database+architect, design→architect+CPO/CTO, spec→CPO+PMO,
> deploy→devops+QA/SRE, bug→triage+QA, claim→two re-derivations); disagreement escalates to a 3rd.
> Carve-out: skip ONLY for changes that are non-behavioral **and** self-evidently correct **and** low-blast-
> radius (typos/docs/formatting/rename/log-text) — mark "(trivial — single-pass)". If in doubt, not trivial.

## 1. Requirements
- [ ] Business requirements documented & stakeholder-approved (`spec.md`)
- [ ] Functional + non-functional requirements reviewed & signed off
- [ ] Acceptance criteria defined per requirement (BDD Given/When/Then)
- [ ] Requirements traceable to business objectives (`traceability.md`, REQ-IDs)
- [ ] Tracking stories/tasks created (GitHub Issues / JIRA) per requirement
- [ ] **Prototype Approval Gate** — frozen clickable prototype signed off (`prototype-signoff.md`: approver, date, prototype SHA); this is the design-time UI/UX contract

## 2. Design
- [ ] HLD created & peer-reviewed — uses `_templates/HLD_TEMPLATE.md` (`design.md`)
- [ ] LLD covers components, APIs, DB schema, sequence/data-flow diagrams — `_templates/LLD_TEMPLATE.md`
- [ ] Design review conducted with Architect/CTO gate
- [ ] Design adheres to security, scalability, performance best practices
- [ ] Stakeholders signed off on design

## 3. Development
- [ ] Code follows coding standards
- [ ] Meaningful commits + branching strategy (GitFlow/dev integration)
- [ ] Static analysis (SonarQube **or** ESLint+tsc strict) — no critical issues
- [ ] Unit tests ≥ **90% line coverage** on new code
- [ ] Feature flags/toggles used where applicable (`ff_<feature>_<component>`)
- [ ] Code peer-reviewed & approved via PR (dual-agent reviewer)

## 4. Testing
- [ ] Unit + integration + system test cases written & reviewed
- [ ] Automated suites executed green
- [ ] Functional test coverage ≥ **85%** for new functionality
- [ ] Regression tests pass — no breaking changes
- [ ] UAT done & signed off by business users
- [ ] **Demo Sign-Off Gate** — working software demoed E2E on the hybrid local+staging env (changed service local in Docker, other services + DB on staging); parity vs frozen prototype confirmed; two-reviewer-verified dry-run with evidence under `specs/<feature>/demo/`; signed off in `demo-signoff.md` (approver, date, branch SHA, services/DB used, deviations)
- [ ] Bugs triaged, fixed, re-tested (`ISSUE_REGISTER.md`)

## 5. Deployment
- [ ] CI/CD executed green in staging **and** production
- [ ] Deployment configs version-controlled
- [ ] IaC scripts validated & reviewed
- [ ] Post-deploy smoke tests pass
- [ ] Rollback strategy documented & tested (<15 min)
- [ ] Release notes & changelog published

## 6. Documentation
- [ ] Technical docs updated (API/OpenAPI, code comments, architecture diagrams)
- [ ] User manuals & operational runbooks created/updated
- [ ] Onboarding & support docs ready
- [ ] KB articles for known issues created

## 7. Security & Compliance
- [ ] SAST + DAST completed
- [ ] Sensitive-data handling verified vs compliance (GDPR/HIPAA as applicable)
- [ ] Vulnerability scans — no high-severity issues
- [ ] Audit logs enabled where required (state-changing ops)

## 8. Post-Release / Maintenance
- [ ] Monitoring & alerting configured (Prometheus/Grafana)
- [ ] Logs & metrics verified for operational visibility
- [ ] SLA/SLO compliance tracked
- [ ] Production feedback collected & triaged
- [ ] Hotfix/escalation plan in place (SEV-1…4 SLAs)

## Final DoD (Release Gate)
- [ ] All 8 checklists complete
- [ ] Business **and** QA sign-off received
- [ ] **No critical/high bugs open** (verify `ISSUE_REGISTER.md`)
- [ ] Deployed to production & monitored
- [ ] Documentation, training & support material shared with relevant teams

**Auditor verdict & evidence summary:** `__________`
