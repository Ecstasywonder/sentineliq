# Gates 14 and 16 — Candidate Completion Evidence

**Status date:** 2026-11-07
**Execution environment:** EC2 only

This is a candidate-completion record, not a claim that either gate has merged
to `main`. See [source-of-truth.md](source-of-truth.md) for the authority model.

## Gate 14 — Coordinator and end-to-end agent workflow

The backend path now records an ordered workflow state for event, triage,
context, evidence validation, risk, confidence, explanation, recommendation,
and human review. It persists the assessment/recommendation relationship and
supports idempotent assessment retrieval. The backend end-to-end path is
covered by the EC2 test suite.

The gate remains **partial**: an Orchestrate Coordinator definition has not
been imported into a configured tenant and invoked live. The repository's
agent YAML is therefore configuration evidence, not proof of a live coordinator
workflow. This must be completed and recorded before Gate 14 can be marked
complete.

## Gate 16 — Operator dashboard foundation

The dashboard candidate includes the application shell, sign-in/session
handling, event queue, status and risk filters, navigation, pagination, and
role-aware controls. The frontend is implementation-complete for this gate,
but its strict gate status remains pending until the pushed candidate is
reviewed, validated in CI, and merged into `main`.

## EC2 validation evidence

| Area | Result |
|------|--------|
| Backend quality | `ruff check` passed; `ruff format --check` passed across 114 files |
| Backend tests | 537 passed; 90.39% coverage on Python 3.11 with greenlet-aware tracing; the 85% gate passed |
| Database migration | Fresh upgrade → downgrade → upgrade and simulated released legacy-stamp upgrade reached Alembic head `0004`; 29 public tables and the JSON decision-snapshot column are present |
| Frontend quality | fresh install, format check, TypeScript check, ESLint, 14 unit tests, and production build passed |
| Frontend dependencies | production audit found 0 vulnerabilities; full audit has 0 high/critical findings and 6 moderate dev-only transitive findings |
| Frontend container path | Production image built on EC2; SPA returned 200 and same-origin `/api/v1/events` reached the protected backend with the expected 401 |
| Container secret boundary | Backend and frontend images built from scratch; backend image contains no runtime `.env` or PEM/key/P12/PFX files |

Validation is EC2-specific evidence for the candidate worktree. Re-run the
same checks in CI against the merge commit before changing a strict gate status
to complete.

## Required next evidence

1. Open a reviewed pull request from the pushed candidate branch.
2. Record CI results against the merge commit and merge to `origin/main`.
3. Configure the target Orchestrate runtime, import the Coordinator, invoke it
   against the backend tool contract, and retain the import/run evidence.
4. Update the Master Gate Plan only after the evidence above is available.
