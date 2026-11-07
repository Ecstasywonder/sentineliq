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

The [Master Build Prompt](docs/master-build-prompt.md) defines the canonical gate
sequence. The [source-of-truth guide](docs/source-of-truth.md) defines how
requirements, source, runtime evidence, and EC2 copies are reconciled. Older
gate reports retain their original labels; the
[master gate plan](docs/master-gate-plan.md) contains the numbering crosswalk.

| Gate | Title | Status |
|------|-------|--------|
| 0 | Environment and source-of-truth validation | ✅ Complete |
| 1 | BRD, SOP, and architecture specification | ✅ Complete |
| 2 | Repository scaffold and developer foundation | 🟡 Candidate complete on EC2; strict completion awaits CI and merge |
| 3 | Database and domain model | ✅ Complete |
| 4 | Security-event simulator | ✅ Complete |
| 5 | Event ingestion and event queue backend | ✅ Complete |
| 6 | Evidence-source services | ✅ Complete |
| 7 | Orchestrate tool layer | ⚠️ Partial — schemas exist; tenant import/live validation outstanding |
| 8 | Incident history and knowledge retrieval | ⚠️ Partial |
| 9 | Deterministic risk engine | ✅ Complete |
| 10 | Confidence engine | ✅ Complete |
| 11 | Triage Agent | ⚠️ Partial — implementation/tests exist; live Orchestrate validation outstanding |
| 12 | Context Agent | ⚠️ Partial — implementation/tests exist; live Orchestrate validation outstanding |
| 13 | Explanation Agent | 🟡 Candidate implementation validated on EC2; live provider integration and strict CI/merge evidence remain outstanding |
| 14 | Coordinator and end-to-end agent workflow | ⚠️ Partial — backend workflow passes on EC2; live Coordinator import/invocation unverified |
| 15 | Human-review workflow | ✅ Backend APIs implemented |
| 16 | Operator dashboard foundation | 🟡 Implementation complete on EC2; strict completion awaits CI and merge |
| 17 | Event decision interface | ✅ Complete |
| 18 | Audit and history interface | ✅ Complete |
| 19 | RBAC and administrative controls | ✅ Complete |
| 20 | Integration and failure-state hardening | ✅ Complete |
| 21 | Evaluation framework | ✅ Complete |
| 22 | Security and adversarial testing | ✅ Complete |
| 23–48 | Remaining MVP and production gates | 🔲 Pending |

**Latest validation (Gate 22):** 782 backend tests passed with 90.82% coverage on
isolated EC2; 39 frontend tests, dependency and secret scans, and both production
image scans passed. The required GitHub CI Gate passed and PR #2 merged as
`4a9d8c0`. See the [Gate 22 report](docs/gate-22-ci-supply-chain.md).

**Stop point:** Gate 22 is complete. Gate 23 has not started.

---

## Current Backend API Surface

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/auth/token` | Login — returns JWT |
| `POST` | `/api/v1/auth/refresh` | Rotate access token |
| `POST` | `/api/v1/auth/logout` | Revoke the refresh-token family |
| `GET` | `/api/v1/auth/me` | Caller identity |
| `POST` | `/api/v1/events` | Ingest a security event |
| `GET` | `/api/v1/events` | Paginated event queue (risk-priority ordered) |
| `GET` | `/api/v1/events/{id}` | Single event |
| `PATCH` | `/api/v1/events/{id}/status` | Lifecycle state transition |
| `POST` | `/api/v1/events/{id}/assess` | Run deterministic risk + confidence assessment |
| `GET` | `/api/v1/events/{id}/assessment` | Retrieve persisted assessment |
| `GET` | `/api/v1/events/{id}/assessment/factors` | Per-factor risk breakdown |
| `POST` | `/api/v1/events/{id}/decision` | Record operator decision |
| `GET` | `/api/v1/events/{id}/decision` | Latest operator decision |
| `GET` | `/api/v1/events/{id}/decisions` | Full decision history |
| `POST` | `/api/v1/events/{id}/escalation` | Create escalation record |
| `GET` | `/api/v1/events/{id}/escalation` | Latest escalation |
| `PATCH` | `/api/v1/events/{id}/escalation` | Acknowledge / resolve / cancel |
| `GET` | `/api/v1/events/{id}/audit` | Event-scoped audit trail |
| `GET` | `/api/v1/audit` | Global audit trail (filtered, paginated) |
| `GET` | `/api/v1/risk-policies` | List risk policy versions |
| `GET` | `/api/v1/risk-policies/{id}` | Policy with factor definitions |
| `GET` | `/api/v1/tools/access-events` | Access control evidence |
| `GET` | `/api/v1/tools/schedule` | Schedule evidence |
| `GET` | `/api/v1/tools/work-orders` | Work order evidence |
| `GET` | `/api/v1/tools/delivery` | Delivery evidence |
| `GET` | `/api/v1/tools/location-policy` | Location policy / security rules |
| `GET` | `/api/v1/tools/incident-history` | Prior incident history |
| `GET` | `/api/v1/tools/integration-health` | Integration health status |
| `POST` | `/api/v1/events/{id}/feedback` | Submit operator feedback |
| `GET` | `/api/v1/events/{id}/feedback` | Retrieve all feedback for an event |
| `GET` | `/health` | Application health check |

---

## Repository Structure

```
sentineliq/
├── .github/
│   └── workflows/
│       └── ci.yml               # GitHub Actions CI (ruff + pytest --cov-fail-under=85)
│
├── docs/
│   ├── adr/                     # Architecture Decision Records (ADR-000 to ADR-008)
│   ├── master-build-prompt.md   # Canonical product and gate specification
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
│   ├── gate-12-audit-trail-api.md
│   ├── gate-14-triage-agent.md    # Historical roadmap numbering
│   └── gate-15-context-agent.md   # Historical roadmap numbering
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
│   └── tests/                   # Backend tests (SQLite in-memory)
│
├── agents/                      # watsonx Orchestrate agent definitions (Gate 11+)
├── workflows/                   # Orchestrate workflow definitions (Gate 14+)
├── tools/                       # Orchestrate tool implementations (Gate 7+)
├── data/                        # Seed data + event scenarios (Gate 4+)
├── evaluations/                 # Evaluation datasets (Gate 21+)
├── frontend/                    # React 18 + TypeScript + Vite (Gate 16+)
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
pytest tests/ -q --tb=short          # run backend test suite
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
| `feedback_submitted` | `FeedbackService` *(legacy implementation Gate 13; human-review workflow)* |

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic |
| Database | PostgreSQL 15+ with pgvector |
| Agent Runtime | IBM watsonx Orchestrate *(Gates 11–14)* |
| Frontend | React 18+, TypeScript, Vite *(Gate 16+)* |
| Testing (BE) | pytest, pytest-asyncio, httpx, aiosqlite (in-memory) |
| Testing (FE) | Vitest, React Testing Library, Playwright *(Gate 16+)* |
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
