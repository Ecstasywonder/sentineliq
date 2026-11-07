# SentinelIQ — Source of Truth

This document defines how conflicting copies, reports, and runtime observations
are resolved. It does not replace the requirements in the Master Build Prompt.

## Authority order

1. [Master Build Prompt](master-build-prompt.md) defines the required product
   gates and their acceptance criteria.
2. [Master Gate Plan](master-gate-plan.md) records the current gate status and
   links each status to evidence. A status is not complete until its stated
   merge and validation conditions are met.
3. The FastAPI-generated OpenAPI document is the executable HTTP API contract.
   Orchestrate tool definitions must be derived from, and validated against,
   that contract.
4. SQLAlchemy models plus Alembic migrations define the persistent data model;
   the deployed schema must be at the recorded Alembic head.
5. Versioned database policy records and the deterministic risk and confidence
   engines define risk and confidence calculations.
6. `agents/**/agent.yaml` defines agent configuration, but an agent is not a
   live integration until the definition has been imported and invoked in the
   target Orchestrate runtime with recorded evidence.
7. Decision, escalation, feedback, and audit rows in the database are the
   authoritative record of human and system actions for a specific event.
8. After review and merge, `origin/main` is the authoritative source code.
   Local workspaces and EC2 worktrees are candidate copies only.
9. CI results and EC2 validation are authoritative only when they identify the
   exact commit SHA, command, and environment used.

## Execution policy

All dependency installation, builds, tests, migrations, and runtime checks are
performed on EC2. The local workspace is used for authoring and review only;
it is not test evidence.

## Resolving discrepancies

When documents, source copies, or EC2 state disagree, first compare their Git
commit SHA. Then apply the authority order above. Never promote a generated
report, an uncommitted local edit, or an EC2-only change over `origin/main`
without review, CI, and merge evidence.
