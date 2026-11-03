# SentinelIQ: AI Security Decision Intelligence

> **A context-aware, evidence-backed, human-supervised security decision-intelligence platform.**

SentinelIQ sits **after** an existing detection system produces a security event. It correlates that event with operational context (access control, schedules, policies, work orders, incident history) and produces a transparent, evidence-backed risk assessment with a supervised recommendation for a security operator to act upon.

**The fundamental transformation:**
```
See Event → Understand Context → Recommend Action → Human Decides
```

SentinelIQ never autonomously enforces security actions. Human authority over every security decision is non-negotiable.

---

## Project Status

| Gate | Title | Status |
|------|-------|--------|
| 0 | Environment & source-of-truth validation | ✅ Complete |
| 1 | BRD, SOP & architecture specification | ✅ Complete |
| 2 | Repository scaffold & developer foundation | 🔲 Pending |
| 3 | Database & domain model | 🔲 Pending |
| 4 | Security-event simulator | 🔲 Pending |
| 5 | Event ingestion & event queue backend | 🔲 Pending |
| 6 | Evidence-source services | 🔲 Pending |
| 7 | Orchestrate tool layer | 🔲 Pending |
| 8 | Incident history & knowledge retrieval | 🔲 Pending |
| 9 | Deterministic risk engine | 🔲 Pending |
| 10 | Confidence engine | 🔲 Pending |
| 11 | Triage Agent | 🔲 Pending |
| 12 | Context Agent | 🔲 Pending |
| 13 | Explanation Agent | 🔲 Pending |
| 14 | Coordinator & end-to-end agent workflow | 🔲 Pending |
| 15 | Human-review workflow | 🔲 Pending |
| 16 | Operator dashboard foundation | 🔲 Pending |
| 17 | Event decision interface | 🔲 Pending |
| 18 | Audit & history interface | 🔲 Pending |
| 19 | RBAC & administrative controls | 🔲 Pending |
| 20 | Integration & failure-state hardening | 🔲 Pending |
| 21 | Evaluation framework | 🔲 Pending |
| 22 | Security & adversarial testing | 🔲 Pending |
| 23 | MVP usability & operator validation readiness | 🔲 Pending |
| 24 | MVP release candidate | 🔲 Pending |
| 25 | MVP demonstration & freeze | 🔲 Pending |

---

## Repository Structure

```
sentineliq/
├── docs/                        # All project documentation
│   ├── adr/                     # Architecture Decision Records
│   ├── sentinel-brd.md          # Business Requirements Document
│   ├── sentinel-sop.md          # Standard Operating Procedures
│   ├── architecture.md          # System architecture
│   ├── threat-model.md          # Threat model
│   ├── api-contracts.md         # API contracts
│   ├── data-model.md            # Data model & ER reference
│   ├── agent-design.md          # Agent architecture
│   ├── risk-model.md            # Risk & confidence model
│   ├── evaluation-plan.md       # Evaluation strategy
│   └── deployment.md            # Deployment guide
│
├── frontend/                    # React + TypeScript operator dashboard
│   ├── src/
│   └── tests/
│
├── backend/                     # Python + FastAPI application
│   ├── app/
│   │   ├── api/                 # Route handlers
│   │   ├── models/              # SQLAlchemy ORM models
│   │   ├── schemas/             # Pydantic schemas
│   │   ├── services/            # Business logic
│   │   ├── repositories/        # Data access layer
│   │   ├── security/            # Auth, RBAC, token handling
│   │   ├── audit/               # Audit trail logic
│   │   └── integrations/        # External source adapters
│   └── tests/
│
├── agents/                      # watsonx Orchestrate agent definitions
│   ├── coordinator/
│   ├── triage/
│   ├── context/
│   └── explanation/
│
├── workflows/                   # Orchestrate workflow definitions
│   └── event_assessment/
│
├── tools/                       # Orchestrate tool implementations
│   ├── access_control/
│   ├── schedules/
│   ├── location_policy/
│   ├── incident_history/
│   ├── work_orders/
│   ├── risk_engine/
│   └── audit/
│
├── data/                        # Seed data and scenario definitions
│   ├── seed/
│   └── scenarios/
│
├── evaluations/                 # Agent evaluation framework
│   ├── datasets/
│   ├── expected/
│   └── reports/
│
├── infra/                       # Infrastructure configuration
│   ├── docker/
│   ├── ci/
│   └── deployment/
│
└── README.md
```

---

## Quick Start (EC2 / Linux)

```bash
# 1. Clone the repository
git clone <repo-url> sentineliq
cd sentineliq

# 2. Run the bootstrap script (installs all runtimes)
chmod +x infra/docker/bootstrap-ec2.sh
./infra/docker/bootstrap-ec2.sh

# 3. Copy environment template and configure
cp backend/.env.example backend/.env
# Edit backend/.env with your values

# 4. Start all services with Docker Compose
docker compose -f infra/docker/docker-compose.yml up -d

# 5. Apply database migrations
docker compose -f infra/docker/docker-compose.yml exec backend alembic upgrade head

# 6. Verify health
curl http://localhost:8000/health
```

---

## Development Principles

- **Human authority over every security decision** — no autonomous enforcement
- **Risk ≠ Confidence** — modelled independently, never merged
- **Missing evidence ≠ negative evidence** — unavailable sources reduce confidence, not risk
- **Every recommendation is evidence-backed** — no hallucinated facts
- **Full audit trail** — every event, decision, and override is preserved
- **Gates are sequential** — no gate begins until the previous is approved

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic |
| Database | PostgreSQL 15+, pgvector |
| Agent Runtime | watsonx Orchestrate |
| Frontend | React 18+, TypeScript, Vite |
| Testing (BE) | pytest, httpx |
| Testing (FE) | Vitest, React Testing Library, Playwright |
| Containers | Docker, Docker Compose |
| CI | GitHub Actions |

---

## Security Notice

SentinelIQ is NOT:
- A facial recognition platform
- An autonomous enforcement system
- A criminality classifier
- A replacement for security officers

It IS a **supervised decision-support tool** that makes security operators better informed.

---

## License

Proprietary — SentinelIQ Project. All rights reserved.
