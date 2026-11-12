# Gate 24 — MVP release candidate

**Status:** 🟡 EC2/CI-verified candidate; live Orchestrate and merge pending

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
| Backend lint, format, and tests with coverage threshold | Pass | Passed at `993c0fe`: 816 passed, 3 skipped, 91% coverage |
| Frontend typecheck, lint, unit tests, and production build | Pass | Passed at `993c0fe`: 57 unit tests plus build |
| Migration chain and PostgreSQL safeguards | Pass on disposable/migrated EC2 database | Fresh upgrade/downgrade/re-upgrade through `0006` passed |
| Deterministic smoke test | Zero failures on EC2 | Passed at `993c0fe`: 108 passed, 0 failed |
| Gate 23 demo runner | Five scenarios pass after its contract/precondition repair | Passed at `993c0fe`: 73 passed, 0 failed |
| Evaluation and adversarial tests | Pass | Included in the backend suite and smoke run; passed |
| Dependency, secret, and image scans | Pass in current protected-branch CI | Passed in Actions run `43232697244` |
| Live watsonx Orchestrate workflow | All required agent imports, tool calls, structured outputs, and coordinator execution evidenced | Pending Gate 14 validation |
| Documentation and deployment review | Reflects the verified commit and deployed route contract | Candidate docs updated; deployment pending |

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

Then execute the smoke and repaired scenario runner with `bash` against a deliberately
prepared test database. `E2E_ALLOW_PERSISTENT_WRITES=yes` is required because
these scripts create event and audit records. Supply an existing authorized
operator identity through secure environment variables or an access token; do
not put a shared password in this document.

## Release conditions

Gate 24 may be marked complete only when all required checks pass on the same
candidate commit (or are explicitly tied to it), the GitHub Actions required
check passes, and the commit has merged to `main`. Record any skipped test with
its exact reason and a separately verified equivalent control.

## Candidate evidence record

- Commit: `993c0fe`.
- Date: 2026-11-12.
- Backend: Ruff check/format and full suite passed; 816 passed, 3 skipped,
  coverage 91%.
- Frontend: Prettier, typecheck, lint, 57 unit tests, and Vite production build
  passed.
- Migrations: fresh upgrade, downgrade to base, and re-upgrade through `0006`.
- Gate 23: 73 passed, 0 failed.
- Deterministic Gate 24 smoke: 108 passed, 0 failed; its 15 pure evaluation
  scorer tests passed as part of that run.
- CI: [Actions run 43232697244](https://github.com/Ecstasywonder/sentineliq/actions/runs/43232697244)
  passed backend, frontend, Gitleaks, both Trivy scans, and the aggregate gate.

## Known blockers

1. The updated Context/Coordinator definitions and OAuth-protected tools must
   be imported and exercised in the live watsonx Orchestrate tenant. Direct
   model/specialist probes now work, but stale tenant assets are not evidence
   of current tools, collaborators, or structured output.
2. The verified candidate must pass final review and merge to `main`.
3. The merged revision must be deployed and verified before Gate 25 team use.

No Gate 25 demonstration or MVP freeze is authorized from this candidate until
these release conditions are met.
