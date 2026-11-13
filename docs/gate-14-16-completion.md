# Gates 14 and 16 — Candidate Completion Evidence

**Status date:** 2026-11-13
**Execution environment:** EC2 only

This is a candidate-completion record, not a claim that either gate has merged
to `main`. See [source-of-truth.md](source-of-truth.md) for the authority model.

## Gate 14 — Coordinator and end-to-end agent workflow

The backend path now records an ordered workflow state for event, triage,
context, evidence validation, risk, confidence, explanation, recommendation,
and human review. It persists the assessment/recommendation relationship and
supports idempotent assessment retrieval. The backend end-to-end path is
covered by the EC2 test suite.

The gate remains **partial**, but its former live-runtime blocker is resolved:
the Coordinator was imported and invoked in the configured tenant on
2026-11-13. It executed read-only event/assessment tools and delegated to all
three specialist collaborators. A fresh assessment recorded all specialist
sources as `orchestrate` and stayed `awaiting_review`. The remaining strict
completion conditions are merge/CI/deployment of the current candidate,
including Coordinator persisted-data grounding and Path-A removal, then
repeating that proof on the deployed revision.

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
| Backend tests | Historical candidate evidence: 537 passed, 90.39% coverage; later focused EC2 regressions include 44 passing Coordinator/trust tests and 84 passing auth/tool-contract tests |
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
3. Deploy the merged revision, verify the refresh-family foreign-key fix with
   real HTTPS login and refresh rotation, then repeat the Orchestrate run/tool/
   collaborator evidence on that revision.
4. Demonstrate deterministic fallback after an Orchestrate failure without a
   direct watsonx.ai chat attempt.
5. Update the Master Gate Plan only after the evidence above is available.
