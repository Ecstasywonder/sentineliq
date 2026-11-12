# Gate 24 — MVP release candidate

**Status:** 🟡 Candidate; release verification pending

Gate 24 is the release-verification gate. It is not complete merely because a
candidate branch contains the implementation. The current candidate must first
be tested on EC2, pass protected-branch CI, and merge to `main`; Gate 23 must
also have current successful runner evidence.

## Required release evidence

Run all commands in an isolated EC2 worktree for the candidate commit. Do not
copy historical test totals into this document; record the fresh command output,
commit SHA, date, and tool version with the release evidence.

| Check | Required result | Current state |
|---|---|---|
| Backend lint, format, and tests with coverage threshold | Pass | Pending current EC2 run |
| Frontend typecheck, lint, unit tests, and production build | Pass | Pending current EC2 run |
| Migration chain and PostgreSQL safeguards | Pass on disposable/migrated EC2 database | Pending current EC2 run |
| Deterministic smoke test | Zero failures on EC2 | Pending current EC2 run |
| Gate 23 demo runner | Five scenarios pass after its contract/precondition repair | Blocked by Gate 23 |
| Evaluation and adversarial tests | Pass | Pending current EC2 run |
| Dependency, secret, and image scans | Pass in current protected-branch CI | Pending CI |
| Live watsonx Orchestrate workflow | All required agent imports, tool calls, structured outputs, and coordinator execution evidenced | Pending Gate 14 validation |
| Documentation and deployment review | Reflects the verified commit and deployed route contract | In progress |

## EC2 validation commands

Use the repository’s pinned scripts and CI commands, with credentials supplied
through EC2 secrets rather than committed shell history. At a minimum:

```bash
# backend (inside the isolated candidate worktree)
cd backend
ruff check app/ tests/
ruff format --check app/ tests/
pytest tests/ -q --tb=short --cov=app --cov-fail-under=85

# frontend
cd ../frontend
npm run typecheck
npm run lint
npm run test:unit
npm run build
```

Then execute the smoke and repaired scenario runner against a deliberately
prepared test database. `E2E_ALLOW_PERSISTENT_WRITES=yes` is required because
these scripts create event and audit records. Supply an existing authorized
operator identity through secure environment variables or an access token; do
not put a shared password in this document.

## Release conditions

Gate 24 may be marked complete only when all required checks pass on the same
candidate commit (or are explicitly tied to it), the GitHub Actions required
check passes, and the commit has merged to `main`. Record any skipped test with
its exact reason and a separately verified equivalent control.

## Known blockers

1. The repaired Gate 23 runner and its scenario-isolation controls have not yet
   produced current EC2 evidence.
2. Gate 14’s live watsonx Orchestrate execution remains unverified; deterministic
   fallback is a safety property, not proof of the required Orchestrate path.
3. The latest candidate CI formatting failure must be corrected and rerun.

No Gate 25 demonstration or MVP freeze is authorized from this candidate until
these release conditions are met.
