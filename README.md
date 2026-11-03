# SentinelIQ — AI Security Decision Intelligence

> **A context-aware, evidence-backed, human-supervised security decision-intelligence platform.**

SentinelIQ sits **after** an existing detection system produces a security event. It
correlates that event with operational context (access control, schedules, policies,
work orders, incident history) and produces a transparent, evidence-backed risk
assessment for a security operator to act upon.

**The fundamental transformation:**
```
See Event → Gather Evidence → Assess Risk → Recommend → Human Decides → Audit
```

SentinelIQ never autonomously enforces security actions.  
**Human authority over every security decision is non-negotiable.**

---

## Project Status

| Gate | Title | Branch | Status | Tests |
|------|-------|--------|--------|-------|
| 0 | Environment & Source-of-Truth Validation | `main` | ✅ Complete | — |
| 1 | BRD, SOP & Architecture Specification | `main` | ✅ Complete | — |
| 2 | Docker Compose, Dockerfiles & Bootstrap | `main` | ✅ Complete | — |
| 3 | Data Models & Alembic Migration (26 tables) | `main` | ✅ Complete | 16 |
| 4 | Deterministic Risk Engine & Confidence Engine | `main` | ✅ Complete | 74 |
| 5 | Event Ingestion API | `main` | ✅ Complete | 113 |
| 6 | RBAC & Authentication | `main` | ✅ Complete | 144 |
| 7 | Evidence Retrieval API (Context Tools) | `main` | ✅ Complete | ~194 |
| 8 | Evidence Aggregation Service & Assessment API | `main` | ✅ Complete | ~208 |
| 9 | Risk Assessment API | `main` | ✅ Complete | ~238 |
| 10 | Operator Decision API | `gate-10-operator-decision-api` → `main` | ✅ Complete | ~270 |
| 11 | Escalation API | `gate-11-escalation-api` → `main` | ✅ Complete | ~304 |
| 12 | Audit Trail API | `gate-12-audit-trail-api` → `main` | ✅ Complete | **313** |
| 13 | Feedback API | `gate-13-feedback-api` | 🔲 Next | — |
| 14 | Triage Agent (watsonx Orchestrate) | — | 🔲 Pending | — |
| 15 | Context Agent (watsonx Orchestrate) | — | 🔲 Pending | — |
| 16 | Explanation Agent (watsonx Orchestrate) | — | 🔲 Pending | — |
| 17 | Sentinel Coordinator (watsonx Orchestrate) | — | 🔲 Pending | — |
| 18 | Agent Tool Schemas (OpenAPI → Orchestrate) | — | 🔲 Pending | — |
| 19 | End-to-End Assessment Flow | — | 🔲 Pending | — |
| 20 | Seed Data & Demo Scenarios | — | 🔲 Pending | — |
| 21 | Frontend Scaffold (React + Vite + TypeScript) | — | 🔲 Pending | — |
| 22 | Event Queue UI | — | 🔲 Pending | — |
| 23 | Event Detail & Evidence Panel UI | — | 🔲 Pending | — |
| 24 | Decision Controls UI | — | 🔲 Pending | — |
| 25 | Escalation UI | — | 🔲 Pending | — |
| 26 | Audit Trail UI | — | 🔲 Pending | — |
| 27 | Admin UI (Risk Policy, Users) | — | 🔲 Pending | — |
| 28 | Integration Health Dashboard UI | — | 🔲 Pending | — |
| 29 | Agent Evaluation Framework | — | 🔲 Pending | — |
| 30 | Evaluation Dataset (5 BRD scenarios) | — | 🔲 Pending | — |
| 31 | CI Pipeline (GitHub Actions) | — | 🔲 Pending | — |
| 32 | Full Stack Docker Compose | — | 🔲 Pending | — |
| 33 | Performance & Load Testing | — | 🔲 Pending | — |
| 34 | Security Hardening (SSO/OIDC, TLS, secrets) | — | 🔲 Pending | — |
| 35 | Production Deployment Package | — | 🔲 Pending | — |

**Current test suite: 313 passing · 93% coverage · ruff clean**

---

## Live API Surface (Gates 5–12)

| Method | Path | Gate | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/auth/token` | 6 | Login — returns JWT |
| `POST` | `/api/v1/auth/refresh` | 6 | Rotate access token |
| `GET` | `/api/v1/auth/me` | 6 | Caller identity |
| `POST` | `/api/v1/events` | 5 | Ingest a security event |
| `GET` | `/api/v1/events` | 5 | Paginated event queue (risk-priority ordered) |
| `GET` | `/api/v1/events/{id}` | 5 | Single event |
| `PATCH` | `/api/v1/events/{id}/status` | 5 | Lifecycle state transition |
| `POST` | `/api/v1/events/{id}/assess` | 8 | Run deterministic risk + confidence assessment |
| `GET` | `/api/v1/events/{id}/assessment` | 9 | Retrieve persisted assessment |
| `GET` | `/api/v1/events/{id}/assessment/factors` | 9 | Per-factor risk breakdown |
| `POST` | `/api/v1/events/{id}/decision` | 10 | Record operator decision |
| `GET` | `/api/v1/events/{id}/decision` | 10 | Latest operator decision |
| `GET` | `/api/v1/events/{id}/decisions` | 10 | Full decision history |
| `POST` | `/api/v1/events/{id}/escalation` | 11 | Create escalation record |
| `GET` | `/api/v1/events/{id}/escalation` | 11 | Latest escalation |
| `PATCH` | `/api/v1/events/{id}/escalation` | 11 | Acknowledge / resolve / cancel |
| `GET` | `/api/v1/events/{id}/audit` | 12 | Event-scoped audit trail |
| `GET` | `/api/v1/audit` | 12 | Global audit trail (filtered, paginated) |
| `GET` | `/api/v1/risk-policies` | 9 | List risk policy versions |
| `GET` | `/api/v1/risk-policies/{id}` | 9 | Policy with factor definitions |
| `GET` | `/api/v1/tools/access-events` | 7 | Access control evidence |
| `GET` | `/api/v1/tools/schedule` | 7 | Schedule evidence |
| `GET` | `/api/v1/tools/work-orders` | 7 | Work order evidence |
| `GET` | `/api/v1/tools/delivery` | 7 | Delivery evidence |
| `GET` | `/api/v1/tools/location-policy` | 7 | Location policy / security rules |
| `GET` | `/api/v1/tools/incident-history` | 7 | Prior incident history |
| `GET` | `/api/v1/tools/integration-health` | 7 | Integration health status |
| `GET` | `/health` | 2 | Application health check |

---

## Repository Structure

```
sentineliq/
├── .github/
│   └── workflows/
│       └── ci.yml               # GitHub Actions CI (ruff + pytest --cov-fail-under=85)
│
├── docs/
│   ├── adr/                     # Architecture Decision Records (ADR-000 to ADR-006)
│   ├── master-gate-plan.md      # Gate tracker and progress log
│   ├── sentinel-brd.md          # Business Requirements Document
│   ├── sentinel-sop.md          # Standard Operating Procedures
│   ├── architecture.md          # System architecture
│   ├── threat-model.md          # Threat model
│   ├── api-contracts.md         # API surface definition
│   ├── deployment.md            # Deployment guide
│   ├── gate-0-environment-report.md
│   ├── gate-4-risk-confidence-engines.md
│   ├── gate-5-event-ingestion-api.md
│   ├── gate-6-rbac-auth.md
│   ├── gate-7-evidence-retrieval.md
│   ├── gate-8-assessment-api.md
│   ├── gate-9-risk-assessment-api.md
│   ├── gate-10-operator-decision-api.md
│   ├── gate-11-escalation-api.md
│   └── gate-12-audit-trail-api.md
│
├── backend/                     # Python 3.11+ · FastAPI · SQLAlchemy 2
│   ├── app/
│   │   ├── api/v1/endpoints/    # auth, events, decisions, escalations, audit,
│   │   │                        # tools, risk_policies, health
│   │   ├── models/              # 26 SQLAlchemy ORM models
│   │   ├── schemas/             # Pydantic v2 schemas (events, assessment,
│   │   │                        # decision, escalation, audit, tools, auth)
│   │   ├── services/            # assessment_service, decision_service,
│   │   │                        # escalation_service, risk_engine,
│   │   │                        # confidence_engine, evidence_aggregator,
│   │   │                        # event_lifecycle
│   │   ├── security/            # JWT tokens, bcrypt passwords, RBAC
│   │   ├── integrations/        # Mock adapters (access_control, schedule,
│   │   │                        # work_order, delivery)
│   │   └── db/                  # session, seed
│   ├── alembic/                 # Database migrations (1 migration = 26 tables)
│   └── tests/                   # 313 integration tests (SQLite in-memory)
│
├── agents/                      # watsonx Orchestrate agent definitions (Gate 14+)
├── workflows/                   # Orchestrate workflow definitions (Gate 14+)
├── tools/                       # Orchestrate tool implementations (Gate 18+)
├── data/                        # Seed data + demo scenarios (Gate 20+)
├── evaluations/                 # Evaluation datasets (Gate 29+)
├── frontend/                    # React 18 + TypeScript + Vite (Gate 21+)
│
└── infra/
    ├── docker/
    │   ├── docker-compose.yml   # PostgreSQL + pgvector, backend, frontend
    │   ├── Dockerfile.backend
    │   ├── Dockerfile.frontend
    │   └── bootstrap-ec2.sh     # EC2 one-time setup
    └── ci/
        └── .github/workflows/ci.yml
```

---

## Quick Start (EC2 / Linux)

```bash
# 1. Clone
git clone https://github.com/Ecstasywonder/sentineliq.git
cd sentineliq

# 2. Bootstrap EC2 (installs Python, Node, Docker, uv — idempotent)
chmod +x infra/docker/bootstrap-ec2.sh
./infra/docker/bootstrap-ec2.sh

# 3. Configure environment
cp backend/.env.example backend/.env
# Edit backend/.env — set DATABASE_URL, SECRET_KEY, etc.

# 4. Start services
docker compose -f infra/docker/docker-compose.yml up -d

# 5. Apply migrations
docker compose -f infra/docker/docker-compose.yml exec backend alembic upgrade head

# 6. Seed initial data (risk policy v1.0, 8 roles, demo facility)
docker compose -f infra/docker/docker-compose.yml exec backend python -m app.db.seed

# 7. Verify
curl http://localhost:8000/health
```

### Run tests locally (EC2)

```bash
cd backend
source .venv/bin/activate
pytest tests/ -q --tb=short          # 313 tests, ~7 s
ruff check app/ tests/               # lint
ruff format --check app/ tests/      # format
```

---

## CI/CD Workflow

Every gate uses its own branch: `gate-N-<feature-name>`.

```
git checkout -b gate-N-<feature>   # create branch (local + EC2)
  ... write code + tests ...
  ruff check && pytest              # must pass on EC2 before commit
git push origin gate-N-<feature>   # triggers GitHub Actions CI
  ... wait for "CI Gate" check ...
gh pr create --base main           # open PR
gh pr merge --squash               # merge only after CI gate passes
git checkout main && git pull      # sync local + EC2
```

**Required GitHub branch protection (Settings → Rules → Rulesets → `main`):**
- Require pull request before merging
- Required status check: `CI Gate (required for merge)`
- Require branches to be up to date before merging

---

## Event Lifecycle

```
RECEIVED ──► NORMALISED ──► ASSESSING ──► AWAITING_REVIEW
                                               ├──► DISMISSED  (terminal)
                                               ├──► CLOSED      (terminal)
                                               ├──► CONTEXT_INCOMPLETE ──► ASSESSING (loop)
                                               └──► ESCALATED ──► CLOSED (terminal)
                                                                └──► AWAITING_REVIEW (loop)
```

---

## Audit Trail — Actions

Every significant system event writes an immutable `AuditEvent` row:

| Action | Written by |
|--------|-----------|
| `risk_assessed` | `AssessmentService` |
| `human_decision` | `DecisionService` |
| `escalated` | `DecisionService` (auto) + `EscalationService` |
| `status_changed` | `EscalationService` |
| `feedback_submitted` | `FeedbackService` *(Gate 13)* |

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic |
| Database | PostgreSQL 15+ with pgvector |
| Agent Runtime | IBM watsonx Orchestrate *(Gates 14–18)* |
| Frontend | React 18+, TypeScript, Vite *(Gate 21+)* |
| Testing (BE) | pytest, pytest-asyncio, httpx, aiosqlite (in-memory) |
| Testing (FE) | Vitest, React Testing Library, Playwright *(Gate 21+)* |
| Lint / Format | ruff |
| Containers | Docker, Docker Compose |
| CI | GitHub Actions — `CI Gate (required for merge)` |
| Deployment | AWS EC2 (Ubuntu) — `ec2-54-164-137-222.compute-1.amazonaws.com` |

---

## Architecture Principles (Non-Negotiable)

| Principle | ADR |
|-----------|-----|
| LLM **never** produces risk score | ADR-003 |
| Risk and Confidence are **independent** models | ADR-004 |
| Missing evidence → **reduced confidence**, not altered risk | ADR-004 |
| Evidence tool adapters are **replaceable** | ADR-005 |
| Human review is **non-bypassable** | ADR-006 |
| Every action is **auditable** — append-only `audit_events` table | Architecture §9 |

---

## Security Notice

SentinelIQ is **NOT**:
- A facial recognition or biometric identification platform
- An autonomous enforcement system
- A criminality or threat-level classifier
- A replacement for trained security officers

It **IS** a supervised decision-support tool that makes security operators better
informed under time pressure — with full transparency, human authority, and a
complete audit trail.

---

## License

Proprietary — SentinelIQ Project. All rights reserved.
