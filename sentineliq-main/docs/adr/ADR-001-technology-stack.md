# ADR-001 — Technology Stack Selection

**Date:** 2026-11-03  
**Status:** Accepted  
**Author:** IBM Bob (Principal Architect)  
**Deciders:** Project Owner, Principal Architect

---

## Context

SentinelIQ requires a technology stack that is:

- production-capable (not a toy/demo stack)
- maintainable by a small team
- well-supported with a mature ecosystem
- compatible with IBM watsonx Orchestrate integration
- containerizable for EC2 deployment
- capable of supporting async operations, migrations, RBAC, and full audit trails

---

## Decision

### Backend

**Python 3.11+ / FastAPI / Pydantic v2 / SQLAlchemy 2 / Alembic**

### Database

**PostgreSQL 15+ with pgvector extension**

### Agent Runtime

**IBM watsonx Orchestrate** — for agent execution, tool invocation, workflow, evaluation, and governance

### Frontend

**React 18+ / TypeScript / Vite**

### Testing — Backend

**pytest + httpx** for unit, integration, and API tests

### Testing — Frontend

**Vitest + React Testing Library** for component tests  
**Playwright** for end-to-end tests

### Containerization

**Docker Engine + Docker Compose v2**

### CI

**GitHub Actions** (initial CI pipeline)

### Python Package Management

**uv** — fast, reproducible dependency resolution; falls back to pip for compatibility

---

## Rationale

| Choice | Reason |
|--------|--------|
| FastAPI | Async-native, OpenAPI generation built-in, Pydantic integration, strong typing |
| Pydantic v2 | Schema validation, serialization, agent output validation |
| SQLAlchemy 2 | Industry-standard ORM, supports async, excellent migration tooling via Alembic |
| PostgreSQL | Mature, supports pgvector for semantic search, strong consistency |
| pgvector | Avoids separate vector database infrastructure for MVP; can be replaced later |
| React + TypeScript | Accessible component model, strong typing for security-critical UI |
| Vite | Fast dev server, modern build, lightweight |
| Docker Compose | Multi-service local/EC2 development without full k8s overhead in MVP |
| GitHub Actions | Standard CI, free for public/private repos, easy matrix testing |
| uv | 10–100x faster than pip; reproducible lockfiles |

---

## Alternatives Considered

| Alternative | Reason Not Selected |
|------------|---------------------|
| Django | More opinionated; FastAPI better for API-first, async, OpenAPI |
| Node.js backend | Python ecosystem better for data/AI integration |
| MySQL | PostgreSQL preferred for pgvector support and JSON capabilities |
| Next.js frontend | Vite + React sufficient for MVP; SSR not required for operator dashboard |
| Kubernetes | Premature for MVP; Docker Compose is sufficient |
| pip only | uv is strictly better for reproducibility; pip retained as fallback |
| Separate vector DB (Qdrant, Weaviate) | pgvector removes infrastructure complexity for MVP |

---

## Consequences

- All backend code must target Python 3.11+ syntax
- Pydantic v2 models used throughout (not v1 compatibility layer)
- SQLAlchemy 2.0 `mapped_column` style used (not legacy declarative)
- All schema changes go through Alembic migrations
- Docker Compose is the canonical local development environment
- pgvector must be enabled in the PostgreSQL container

---

## Migration Impact

N/A — initial stack selection.

---

## Test Impact

- Backend tests require a test PostgreSQL instance (Docker)
- Frontend tests run in jsdom (Vitest) or real browsers (Playwright)
- CI matrix: backend tests, frontend tests, E2E tests

---

## References

- FastAPI documentation: https://fastapi.tiangolo.com
- Pydantic v2: https://docs.pydantic.dev/latest/
- SQLAlchemy 2.0: https://docs.sqlalchemy.org/en/20/
- pgvector: https://github.com/pgvector/pgvector
- uv: https://github.com/astral-sh/uv
