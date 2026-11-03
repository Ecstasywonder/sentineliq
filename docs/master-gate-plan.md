# SentinelIQ — Master Gate Plan

**Document ID:** SNTL-GATES-001  
**Version:** 1.0  
**Date:** 2026-11-03  
**Author:** IBM Bob (Principal Architect)  
**Source of Truth:** Master Build Prompt + session progress

---

## How Gates Work

Each gate has a defined scope, acceptance criteria, and a gate report document in `docs/`.  
Gates are executed in order. No gate is considered complete until:
1. All code is committed and pushed to `main`
2. `ruff check` passes clean
3. `pytest` passes 100% with no regressions

---

## Gate Status

| Gate | Name | Status | Report |
|------|------|--------|--------|
| **0** | Environment & Source-of-Truth Validation | ✅ Complete | `docs/gate-0-environment-report.md` |
| **1** | BRD, SOP & Architecture Specification | ✅ Complete | Embedded in `docs/sentinel-brd.md`, `docs/sentinel-sop.md`, `docs/architecture.md` |
| **2** | Docker Compose, Dockerfiles & Bootstrap | ✅ Complete | `docs/deployment.md` |
| **3** | Data Models & Alembic Migration | ✅ Complete | 26 tables live in PostgreSQL |
| **4** | Deterministic Risk Engine & Confidence Engine | ✅ Complete | `docs/gate-4-risk-confidence-engines.md` |
| **5** | Event Ingestion API | ✅ Complete | `docs/gate-5-event-ingestion-api.md` |
| **6** | RBAC & Authentication | ✅ Complete | `docs/gate-6-rbac-auth.md` |
| **7** | Evidence Retrieval API (Context Tools) | ✅ Complete | `docs/gate-7-evidence-retrieval.md` |
| **8** | Evidence Aggregation Service | ✅ Complete | `docs/gate-8-assessment-api.md` |
| **9** | Risk Assessment API | ✅ Complete | `docs/gate-9-risk-assessment-api.md` |
| **10** | Operator Decision API | ✅ Complete | `docs/gate-10-operator-decision-api.md` |
| **11** | Escalation API | 🔲 Next | — |
| **12** | Audit Trail API | 🔲 Pending | — |
| **13** | Feedback API | 🔲 Pending | — |
| **14** | Triage Agent (watsonx Orchestrate) | 🔲 Pending | — |
| **15** | Context Agent (watsonx Orchestrate) | 🔲 Pending | — |
| **16** | Explanation Agent (watsonx Orchestrate) | 🔲 Pending | — |
| **17** | Sentinel Coordinator (watsonx Orchestrate) | 🔲 Pending | — |
| **18** | Agent Tool Schemas (OpenAPI → Orchestrate) | 🔲 Pending | — |
| **19** | End-to-End Assessment Flow (Agents + Backend) | 🔲 Pending | — |
| **20** | Seed Data & Demo Scenarios | 🔲 Pending | — |
| **21** | Frontend Scaffold (React + Vite + TypeScript) | 🔲 Pending | — |
| **22** | Event Queue UI | 🔲 Pending | — |
| **23** | Event Detail & Evidence Panel UI | 🔲 Pending | — |
| **24** | Decision Controls UI | 🔲 Pending | — |
| **25** | Escalation UI | 🔲 Pending | — |
| **26** | Audit Trail UI | 🔲 Pending | — |
| **27** | Admin UI (Risk Policy, Users) | 🔲 Pending | — |
| **28** | Integration Health Dashboard UI | 🔲 Pending | — |
| **29** | Agent Evaluation Framework | 🔲 Pending | — |
| **30** | Evaluation Dataset (5 BRD scenarios) | 🔲 Pending | — |
| **31** | CI Pipeline (GitHub Actions) | 🔲 Pending | — |
| **32** | Full Stack Docker Compose (all services up) | 🔲 Pending | — |
| **33** | Performance & Load Testing | 🔲 Pending | — |
| **34** | Security Hardening (SSO/OIDC, TLS, secrets) | 🔲 Pending | — |
| **35** | Production Deployment Package | 🔲 Pending | — |

---

## Completed Gates — Key Artifacts

### Gate 0 — Environment Validation
- EC2: Ubuntu, Python 3.14, Node 20, Docker 29, uv 0.13 — all confirmed
- Git remote: `https://github.com/Ecstasywonder/sentineliq.git`
- All work runs on EC2; local machine is source-of-truth for files

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

## Gate 11 — Escalation API (Next)

**Scope:**
- `POST /api/v1/events/{id}/escalation` — create escalation record
- `GET /api/v1/events/{id}/escalation` — retrieve escalation
- `PATCH /api/v1/events/{id}/escalation` — update escalation status (resolve/close)
- `Escalation` model: `escalations` table (Gate 3)
- Audit trail entry on every escalation state change

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

| Gate | Tests Added | Cumulative | Coverage |
|------|-------------|-----------|----------|
| 3 | 16 (model tests) | 16 | — |
| 4 | 58 (risk + confidence) | 74 | 88% |
| 5 | 39 (events API + lifecycle) | 113 | 90% |
| 6 | 31 (auth + RBAC) | 144 | 90% |
| 7 | ~50 (tools API + aggregator) | ~194 | TBC |
| 8 | 14 (assessment API round-trip) | ~208 | TBC |
| 9 | 30 (retrieval + factors + risk policies) | ~238 | TBC |
| 10 | 32 (decision API — all 6 types, audit trail, errors) | ~270 | TBC |
