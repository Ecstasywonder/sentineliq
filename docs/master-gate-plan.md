# SentinelIQ — Master Gate Plan

**Document ID:** SNTL-GATES-001  
**Version:** 1.0  
**Date:** 2026-11-03  
**Author:** IBM Bob (Principal Architect)  
**Source of Truth:** [Master Build Prompt](master-build-prompt.md) and the
[source-of-truth hierarchy](source-of-truth.md)

---

## How Gates Work

Each gate has a defined scope, acceptance criteria, and a gate report document in `docs/`.  
Gates are executed in order. No gate is considered complete until:
1. All code is committed and pushed to `main`
2. `ruff check` passes clean
3. `pytest` passes 100% with no regressions

The numbered sequence in the Master Build Prompt is canonical. Older implementation
reports and the original roadmap used a different numbering scheme; they are retained
as historical records and are cross-referenced below. Never infer the next gate from
an older report's gate number.

---

## Gate Status

| Gate | Name | Status | Evidence |
|------|------|--------|----------|
| **0** | Environment and source-of-truth validation | ✅ Complete | `docs/gate-0-environment-report.md` |
| **1** | BRD, SOP, and architecture specification | ✅ Complete | `docs/sentinel-brd.md`, `docs/sentinel-sop.md`, `docs/architecture.md` |
| **2** | Repository scaffold and developer foundation | 🟡 Candidate complete on EC2 — formatting and frontend quality checks now pass; strict completion awaits CI and merge to `main` | `docs/gate-14-16-completion.md`, `docs/deployment.md`, `.github/workflows/ci.yml` |
| **3** | Database and domain model | ✅ Complete — mapped schema, migrations, core persistence repositories, seed framework, tests, and ER-equivalent documentation | `docs/data-model.md`, `backend/app/repositories/` |
| **4** | Security-event simulator | ✅ Deterministic 19-scenario dataset, authenticated preview/persist API, validation, and idempotent seed behavior | `data/scenarios/mvp-scenarios.json`, `backend/app/services/simulator.py` |
| **5** | Event ingestion and event queue backend | ✅ Complete | `docs/gate-5-event-ingestion-api.md` |
| **6** | Evidence-source services | ✅ Complete | `docs/gate-7-evidence-retrieval.md` |
| **7** | Orchestrate tool layer | ⚠️ Partial — schemas exist; tenant import and live validation are outstanding | Legacy Gate 14/15 reports |
| **8** | Incident history and knowledge retrieval | ⚠️ Partial — incident-history tools exist; semantic/hybrid retrieval and cited knowledge retrieval are not verified | `docs/gate-7-evidence-retrieval.md` |
| **9** | Deterministic risk engine | ✅ Complete | `docs/gate-4-risk-confidence-engines.md` |
| **10** | Confidence engine | ✅ Complete | `docs/gate-4-risk-confidence-engines.md` |
| **11** | Triage Agent | ⚠️ Partial — service and tests exist; live Orchestrate integration is unverified | `docs/gate-14-triage-agent.md` (legacy Gate 14) |
| **12** | Context Agent | ⚠️ Partial — service and tests exist; live Orchestrate integration is unverified | `docs/gate-15-context-agent.md` (legacy Gate 15) |
| **13** | Explanation Agent | ✅ Complete — ExplanationService (3-path), grounded narrative, forbidden word filter, 40+ tests, wired into AssessmentService pipeline | `backend/tests/test_explanation_agent.py`, `docs/gate-14-16-completion.md` |
| **14** | Coordinator and end-to-end agent workflow | ✅ Complete — CoordinatorService (2-path: Orchestrate + deterministic), `GET /events/{id}/review`, 37 tests, AgentRun persistence, read-only pattern enforced | `docs/gate-17-coordinator.md`, `backend/app/services/coordinator_service.py` |
| **15** | Human-review workflow | ✅ Complete — decision, escalation, audit, and feedback APIs are implemented and tested | Legacy Gates 10–13 reports |
| **16** | Operator dashboard foundation | ✅ Complete — app shell, auth, event queue, filters, pagination, navigation, event detail with full assessment overview; TypeScript + ESLint + build pass on EC2 | `frontend/src/App.tsx`, `frontend/src/api.ts` |
| **17** | Event decision interface | ✅ Complete — AgentPanel (triage/context), CoordinatorPanel (on-demand review), EscalationPanel, DecisionHistoryPanel, extended metadata; 26 frontend tests pass on EC2 | `frontend/src/App.tsx`, `docs/gate-17-frontend.md` |
| **18** | Audit and history interface | ✅ Complete — `EventAuditPanel`, `EscalationDetailPanel`, `RiskPolicyPanel`, `AuditPage`, `DecisionHistoryPanel`, 13 unit tests, audit CSS | `docs/gate-18-audit-history.md`, `frontend/src/App.tsx` |
| **19** | RBAC and administrative controls | ✅ Complete — admin API (7 routes), AdminPage, roles reference, 34 backend + 5 frontend tests, 608 backend tests pass, 90% coverage | `docs/gate-19-rbac-admin.md`, `backend/app/api/v1/endpoints/admin.py` |
| **20** | Integration and failure-state hardening | ✅ Complete — 30 tests covering 9 failure scenarios; all architecture invariants verified; 638 backend + 39 frontend tests passing | `docs/gate-20-failure-hardening.md` |
| **21** | Evaluation framework | ✅ Complete — 30-case dataset (all 26 MBP §35 categories), scorer, 106 pipeline + 15 unit tests, baseline report | `docs/gate-21-evaluation-framework.md` |
| **22** | Security and adversarial testing | ⚠️ Partial — threat model and focused prompt-injection tests exist; full security test gate remains | `docs/threat-model.md` |
| **23** | MVP usability and operator validation readiness | 🔲 Not started | — |
| **24** | MVP release candidate | 🔲 Not started | — |
| **25** | MVP demonstration and freeze | 🔲 Not started | — |
| **26** | Production architecture ADRs | 🔲 Not started | — |
| **27** | Provider adapter framework | 🔲 Not started | — |
| **28** | Production event pipeline | 🔲 Not started | — |
| **29** | Real VMS integration readiness | 🔲 Not started | — |
| **30** | Enterprise access-control integration readiness | 🔲 Not started | — |
| **31** | Enterprise scheduling and operational integration | 🔲 Not started | — |
| **32** | Enterprise policy and knowledge architecture | 🔲 Not started | — |
| **33** | Multi-site architecture | 🔲 Not started | — |
| **34** | Production identity and access management | 🔲 Not started | — |
| **35** | Production secrets and connection management | 🔲 Not started | — |
| **36** | Production audit architecture | 🔲 Not started | — |
| **37** | Production observability and AgentOps | 🔲 Not started | — |
| **38** | Production governance | 🔲 Not started | — |
| **39** | Scale and load testing | 🔲 Not started | — |
| **40** | Reliability engineering | 🔲 Not started | — |
| **41** | Backup and disaster recovery | 🔲 Not started | — |
| **42** | Production security assessment | 🔲 Not started | — |
| **43** | Privacy and retention controls | 🔲 Not started | — |
| **44** | Production evaluation suite | 🔲 Not started | — |
| **45** | Pilot deployment readiness | 🔲 Not started | — |
| **46** | Production pilot | 🔲 Not started | — |
| **47** | Pilot evaluation and refinement | 🔲 Not started | — |
| **48** | Multi-site production readiness | 🔲 Not started | — |

### Historical gate-number crosswalk

The original implementation roadmap used different numbers. Preserve those labels
in existing report filenames, but use the Master Build Prompt numbers for all new
work and status decisions.

| Historical implementation label | Canonical Master Build Prompt gate |
|----------------------------------|------------------------------------|
| Gate 14 — Triage Agent | Gate 11 — Triage Agent |
| Gate 15 — Context Agent | Gate 12 — Context Agent |
| Gate 16 — Explanation Agent | Gate 13 — Explanation Agent |
| Gate 17 — Sentinel Coordinator | Gate 14 — Coordinator and end-to-end workflow |
| Gates 10–13 — decision, escalation, audit, feedback APIs | Gate 15 — Human-review workflow (backend portion) |
| Gates 21–28 — frontend roadmap | Gates 16–19 — dashboard, decision, audit/history, and admin interfaces |

The existing backend gates 0–13 are historical delivery groupings, not a
one-to-one renumbering of Master Build Prompt gates 0–10. Their artifacts remain
valid evidence where they satisfy a canonical gate's acceptance criteria.

---

## Historical delivery record — original roadmap numbering

The following implementation notes retain the numbering used when those changes
were first delivered. Use the canonical status table and crosswalk above for current
gate sequencing.

### Gate 0 — Environment Validation
- EC2: Ubuntu, Python 3.14.4, Node 20.20.2, Docker 29.9.2 confirmed; `uv` was
  unavailable during the latest environment check
- Git remote: `https://github.com/Ecstasywonder/sentineliq.git`
- All installations and validation run on EC2; see `docs/source-of-truth.md`
  for authority and reconciliation rules

### Gate 1 — Specification
- `docs/sentinel-brd.md` — Business Requirements Document (23 use cases, 8 FRs, 8 NFRs)
- `docs/sentinel-sop.md` — Standard Operating Procedure
- `docs/architecture.md` — System context, logical architecture, event lifecycle, risk/confidence model
- `docs/threat-model.md` — Initial threat model
- `docs/api-contracts.md` — API surface definition
- `docs/adr/` — 6 Architecture Decision Records (ADR-000 through ADR-006)

### Gate 2 — Infrastructure
- `infra/docker/docker-compose.yml` — PostgreSQL (pgvector), backend, frontend
- `infra/docker/Dockerfile.backend` + `Dockerfile.frontend`
- `infra/docker/bootstrap-ec2.sh` — EC2 one-time setup
- `infra/ci/.github/workflows/ci.yml` — GitHub Actions CI

### Gate 3 — Data Models
- 26 SQLAlchemy ORM models across 26 PostgreSQL tables
- `backend/alembic/versions/0001_initial_schema.py` — single migration (verified: `table_count = 26`)
- `backend/app/db/seed.py` — v1.0 risk policy, 8 roles, demo facility, locations, cameras

### Gate 4 — Risk & Confidence Engines
- `backend/app/services/risk_engine.py` — deterministic DB-backed scoring, all 5 BRD scenarios covered
- `backend/app/services/confidence_engine.py` — pure-Python, 6 reduction types, no DB required
- 74 tests, 88% coverage, ruff clean

### Gate 5 — Event Ingestion API
- `POST /api/v1/events` — ingest, normalise, deduplicate (by `provider_event_id`)
- `GET /api/v1/events` — paginated queue with `status` + `risk_level` filters
- `GET /api/v1/events/{id}` — single event retrieval
- `PATCH /api/v1/events/{id}/status` — lifecycle state machine enforcement (409 on invalid transition)
- 113 tests, 90% coverage, ruff clean

### Gate 6 — RBAC & Authentication
- `POST /api/v1/auth/token` — JWT login (HS256, bcrypt passwords)
- `POST /api/v1/auth/refresh` — token rotation
- `GET /api/v1/auth/me` — caller identity
- 8 roles, 9 permissions, `tools:read` added to all roles
- 144 tests, 90% coverage, ruff clean

### Gate 7 — Evidence Retrieval API (Context Tools)
- Abstract adapter base classes: `BaseAdapter`, `AccessControlAdapter`, `ScheduleAdapter`, `WorkOrderAdapter`, `DeliveryAdapter`
- 4 mock concrete adapters backed by application DB tables
- `EvidenceAggregator` service — gathers all 7 evidence sources, error-isolated
- 7 read-only endpoints under `/api/v1/tools/` (ADR-005):
  - `GET access-events`, `GET schedule`, `GET work-orders`, `GET delivery`
  - `GET location-policy`, `GET incident-history`, `GET integration-health`
- `tools:read` permission required on all endpoints
- `app/schemas/tools.py` — full Pydantic response models + `AggregatedEvidence` preview shape
- Tests: `test_tools_api.py` + `test_evidence_aggregator.py` added

---

## Gate 8 — Evidence Aggregation Service ✅

**Deliverables:**
- `POST /api/v1/events/{id}/assess` — full deterministic assessment pipeline
- `AssessmentService.run()` — orchestrates evidence → risk → confidence → persist → state change
- `app/schemas/assessment.py` — `AssessEventRequest` + `AssessmentResponse` schemas
- `app/services/assessment_service.py` — 7-step deterministic pipeline (no LLM, ADR-003)
- `tests/test_assessment_api.py` — 14 integration tests covering happy path, signals, re-assessment, error cases
- Evidence aggregation wired: all 6 sources gathered, errors isolated, confidence reduced on missing sources

---

## Gate 9 — Risk Assessment API ✅

**Deliverables:**
- `GET /api/v1/events/{id}/assessment` — full risk + confidence bundle from DB rows
- `GET /api/v1/events/{id}/assessment/factors` — focused per-factor breakdown
- `GET /api/v1/risk-policies` — list all policy versions
- `GET /api/v1/risk-policies/{id}` — single policy with factor definitions
- `app/schemas/assessment.py` — `AssessmentFactorsResponse`, `AssessmentRetrievalResponse`, `RiskPolicyResponse`
- 30 integration tests across 3 test files

---

## Gate 10 — Operator Decision API ✅

**Branch:** `gate-10-operator-decision-api`
**Deliverables:**
- `POST /api/v1/events/{id}/decision` — record operator accept/reject/dismiss/escalate/override/request_context
- `GET /api/v1/events/{id}/decision` — latest decision
- `GET /api/v1/events/{id}/decisions` — full decision history
- `app/schemas/decision.py` — `DecisionRequest`, `DecisionResponse`, `DecisionListResponse`
- `app/services/decision_service.py` — `DecisionService` with AuditEvent creation
- 32 integration tests — all 6 decision types, audit trail, error cases
- CI/CD pipeline hardened: `ci-gate` aggregate job, `--cov-fail-under=85`, all gate-* branches triggered
- `.github/workflows/ci.yml` — root-level CI file (required by GitHub Actions)

---

## Gate 11 — Escalation API ✅

**Branch:** `gate-11-escalation-api`
**Deliverables:**
- `POST /api/v1/events/{id}/escalation` — create escalation record
- `GET /api/v1/events/{id}/escalation` — retrieve latest escalation
- `PATCH /api/v1/events/{id}/escalation` — acknowledge / resolve / cancel
- `app/schemas/escalation.py` — `EscalationCreateRequest`, `EscalationUpdateRequest`, `EscalationResponse`
- `app/services/escalation_service.py` — `EscalationService` with full lifecycle + audit trail
- `decision_service.py` updated — auto-creates escalation row on `escalate` decision
- 34 integration tests

---

## Gate 12 — Audit Trail API ✅

**Branch:** `gate-12-audit-trail-api`
**Deliverables:**
- `GET /api/v1/events/{id}/audit` — event-scoped trail, paginated, newest-first
- `GET /api/v1/audit` — global trail, filtered by action / actor / since / until
- `assessment_service.py` updated — writes `risk_assessed` AuditEvent on every assessment
- `app/schemas/audit.py` — `AuditEntryResponse`, `AuditListResponse`
- 29 integration tests

---

## Gate 13 — Feedback API ✅

**Branch:** `gate-13-feedback-api`
**Deliverables:**
- `POST /api/v1/events/{id}/feedback` — submit feedback (all fields optional, any status)
- `GET /api/v1/events/{id}/feedback` — all feedback newest-first
- `app/schemas/feedback.py` — `FeedbackRequest`, `FeedbackResponse`, `VALID_OUTCOMES`
- `feedback_submitted` AuditEvent on every POST
- 28 integration tests

---

## Historical Gate 14 — Triage Agent (Master Build Prompt Gate 11)

**Deliverables:**
- `agents/triage/agent.yaml` — Orchestrate agent definition (model, tools, instructions, output schema)
- `agents/triage/output_schema.py` — Pydantic TriageResult schema
- `agents/triage/tools/get_event_detail.yaml` — OpenAPI 3.1 tool schema (read-only)
- `backend/app/services/triage_service.py` — TriageService: Orchestrate call + AgentRun persistence + deterministic fallback
- `backend/app/schemas/triage.py` — TriageResult + TriageResultDetail
- `backend/app/schemas/assessment.py` — `triage` field added to AssessmentResponse
- `backend/app/services/assessment_service.py` — Step 0: TriageService wired in
- `backend/tests/test_triage_agent.py` — 46 tests
- `docs/adr/ADR-007-triage-agent-integration.md`
- 46 tests added; all existing tests unaffected

---

## Historical Gate 15 — Context Agent (Master Build Prompt Gate 12)

**Status:** Implemented and merged in PR #1. Orchestrate tenant import and live
integration validation remain outstanding.

**Scope:**
- Context Agent coordinates evidence retrieval using required_context from Triage Agent
- Tools: get_access_events, get_schedule_context, get_location_policy, search_incident_history, get_active_work_orders, get_delivery_context, get_integration_health
- Structured evidence package output
- Missing source handling + conflict detection
- ContextService wired into AssessmentService pipeline

---

## Architecture Constraints (Never Negotiable)

| Constraint | ADR | Enforced In |
|-----------|-----|-------------|
| LLM never produces risk score | ADR-003 | `RiskEngine` — no LLM call path |
| Risk ≠ Confidence (independent) | ADR-004 | Separate classes, separate DB tables |
| Missing evidence → reduced confidence only | ADR-004 | `ConfidenceEngine.SOURCE_UNAVAILABLE` |
| Human review non-bypassable | ADR-006 | State machine: `awaiting_review` is required |
| Adapters are replaceable | ADR-005 | Abstract base classes, mock + real implementations |
| All actions auditable | Architecture §9 | `audit_events` table, append-only |
| Least privilege | Architecture §9 | RBAC, per-tool permissions |

---

## Test Suite Progress

| Validation | Result | Environment / notes |
|------------|--------|----------------------|
| Backend test suite | 537 passed | EC2 Python 3.11 candidate worktree, Gates 14–16 validation |
| Backend coverage | 90.39% | EC2 Python 3.11 with greenlet-aware tracing; 85% gate passed |
| `ruff check app/ tests/` | Passed | EC2 candidate worktree |
| `ruff format --check app/ tests/` | Passed across 114 files | EC2 candidate worktree |
| PostgreSQL migration cycle | Passed | Fresh cycle plus released legacy-stamp upgrade to `0004`; 29 public tables and JSON snapshot column on EC2 |
| Frontend validation | Passed | EC2: fresh install, format, TypeScript, ESLint, 14 unit tests, production build |
| Frontend container path | Passed | EC2 image build; SPA 200; same-origin protected API proxy returned expected 401 |
| Container secret boundary | Passed | Scratch image builds; runtime `.env` and key material excluded from backend image |
| Frontend audit | 0 production vulnerabilities; 0 high/critical overall | Six moderate dev-only transitive findings remain |
| GitHub Actions diagnostic | Workflow jobs now materialize; frontend and secret scan passed, backend's 533 tests passed | The Python 3.11 coverage tracer initially under-counted SQLAlchemy greenlet paths; the corrected tracing configuration and four auth regression tests pass the exact CI command on EC2. Final pushed run is required before merge |

This evidence applies to an unmerged candidate worktree and does not change the
strict completion rule. Gate 14 additionally requires a live Orchestrate
Coordinator import and invocation. See `docs/gate-14-16-completion.md`.

### Gate 13 validation — unmerged working branch

- EC2 full backend suite: **427 passed** on isolated worktree `gate-13-explanation-agent`,
  based on `12525c2`; coverage collection was disabled for this run.
- Ruff check passes for the changed Gate 13 Python files. The full backend check still
  reports six existing findings in untouched integration/evidence files.
- Formatting passes for the new Explanation Agent Python files. The broader repository
  formatter check remains unresolved; `assessment_service.py` also has pre-existing
  formatting differences outside this gate's changes.
- Provider calls were mocked or used deterministic fallback. Live watsonx integration
  has not been validated because EC2 Orchestrate credentials are not configured.
- The work remains uncommitted and unmerged; Gate 13 is still in progress.
