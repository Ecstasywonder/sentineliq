# Gate 22 — Security and adversarial testing

Gate 22 makes the CI Gate a blocking supply-chain control and verifies the
adversarial testing requirements from Master Build Prompt Gate 22. The `CI Gate
(required for merge)` status must remain a required branch-protection check.
The active `main-ci-gate` repository ruleset requires pull requests and this
status check on `main`.

## Final validation evidence

- EC2 isolated backend: Ruff check and format passed; **782 tests passed** with
  **90.82% coverage** (above the 85% threshold).
- Disposable PostgreSQL migration run: UPDATE, DELETE, and TRUNCATE against
  `audit_events` each failed with the expected SQLSTATE `55000`.
- The prior candidate run passed frontend typecheck, lint, build, and **39
  unit tests**; `npm audit --audit-level=high` reported no high/critical
  findings.
- The final candidate images scanned with Trivy had **0 high/critical
  findings**; Gitleaks scans of full history and working tree had **0
  findings**.
- Final candidate commit `306a7cd` passed every blocking job in both the
  [push run](https://github.com/Ecstasywonder/sentineliq/actions/runs/42424358453)
  and the
  [pull-request run](https://github.com/Ecstasywonder/sentineliq/actions/runs/42424362147),
  including `CI Gate (required for merge)`.
- [PR #2](https://github.com/Ecstasywonder/sentineliq/pull/2) merged to `main`
  as commit `4a9d8c02f76eeb8bb0d92a08c8d03f514230891d` on 2026-11-08
  (Africa/Lagos).

## GitHub Actions failure analysis

- Initial runs `42422533437` and `42422537402` failed the Python audit with
  eight advisories across two packages. The JSON report stayed in runner
  temporary storage and was not uploaded; EC2 reproduction identified the
  affected toolchain packages as `uv==0.6.3` and `setuptools==79.0.1`.
- The initial Trivy jobs stopped before any image scan because the workflow
  referenced nonexistent action tag `aquasecurity/trivy-action@0.28.0`.
  After adding the `v` prefix, runs `42424184820` and `42424188963` exposed a
  second upstream metadata failure: that release referenced unavailable
  `aquasecurity/setup-trivy@v0.2.1`. Neither failure produced a Trivy finding or
  scan artifact.
- The initial PR-context Gitleaks job stopped before scanning with a GitHub API
  `403` while reading PR commits. The job now has only `contents: read` and
  `pull-requests: read`, with comments disabled. Available
  `gitleaks-results.sarif` artifacts contain zero results; the failed
  pre-scan PR job produced no artifact.
- The final runs passed strict Python and npm audits, Gitleaks, and both Trivy
  production-image scans. The aggregate required gate passed in both event
  contexts.

## Blocking checks

| Check | Scope | Failure threshold |
| --- | --- | --- |
| Gitleaks | Push/PR commit range from a complete checkout (`fetch-depth: 0`) | Any detected secret |
| `pip-audit --requirement` | Frozen backend test/runtime dependency set, captured before installing the auditor | Any known advisory or skipped distribution |
| `npm audit --audit-level=high` | Frontend runtime and development dependency set | High or critical advisory |
| Trivy | Built backend and frontend production images; OS and language packages | High or critical advisory, including unfixed findings |

The image builds use the production Dockerfiles, and the backend Dockerfile
installs the base project (`.`), not the `dev` optional dependency group.
Base images and the `uv` builder image use explicit release versions; upgrades
should be made intentionally and reviewed with the Trivy result.

`pyproject.toml` currently declares version ranges and no committed lock file.
Until a reviewed lock file is introduced, CI audits the exact resolved
environment on every run.  A future lock-file migration must add a
`uv lock --check` gate and update this document.

CI snapshots `pip freeze --exclude-editable` before installing `pip-audit`, then
audits that requirements file in strict mode. This excludes the unpublished editable
`sentineliq-backend` project and prevents the auditor's own transitive
dependencies from being misreported as application dependencies. The JSON
report is checked to ensure the audit inspected a non-empty set and skipped no
distributions. Dependency-collection errors, vulnerability-database errors, and
known advisories fail CI.
The CI toolchain pins `uv==0.13.7` and upgrades the runner's setuptools to
`84.1.0`; these versions remediate advisories found by the initial PR CI run.

JWT handling uses PyJWT with the configured algorithm explicitly allow-listed.
This removes the affected `python-jose` and transitive `ecdsa` distributions.

Actions are release-version pinned rather than referenced through `latest`.
Gitleaks v3 runs on the supported Node 24 action runtime; its job receives only
read access to repository contents and pull-request metadata, with PR comments
disabled.
The Trivy jobs use the immutable `v0.36.0` release, whose setup dependency is
pinned by commit SHA; this replaces `v0.28.0`, which referenced a setup tag no
longer available to GitHub Actions.
For higher-assurance deployments, renovate/dependabot plus commit-SHA action
pinning can be added once an automated update owner is in place.

## Security controls implemented

### JWT supply-chain hardening
- `python-jose` and its transitive `ecdsa` dependency removed; replaced with
  `PyJWT[crypto]>=2.10.1`.  Algorithm is always passed as an explicit allow-list
  (`algorithms=[s.algorithm]`); no implicit algorithm negotiation is possible.
- `alg: none` algorithm-confusion attacks are rejected by PyJWT before any
  application logic is reached.  This is covered by
  `TestAuthorizationBoundaries.test_algorithm_confusion_attack_rejected`.

### Purpose-bound service identities (migration 0005)
- `users.service_purpose` column constrains machine identities to one of
  `orchestrate_tools` or `event_ingestion` at the database level (CHECK
  constraint) and at the token level (audience + purpose claims).
- Service tokens carry a hardcoded `aud: sentineliq-service` and a `purpose`
  claim.  `decode_access_token` validates both.
- `service_purpose_allows()` applies an immutable upper-bound policy: even if a
  database administrator inadvertently grants elevated roles to a service account,
  the token cannot exercise those permissions.  Covered by
  `test_service_identity_security.py`.
- Password login is rejected for all service-purpose identities (`SERVICE_ACCOUNT_LOGIN_DISABLED`).
- Service identity provisioner (`provision_service_identity.py`) is the only
  supported path to create a machine identity; it re-normalises the role set on
  every call, removing accidental privilege grants.

### Append-only audit enforcement (migration 0005)
- PostgreSQL trigger `audit_events_append_only` raises SQLSTATE 55000 on any
  UPDATE or DELETE against `audit_events`; a separate statement-level trigger
  rejects TRUNCATE. Both use the same backing function and are created
  idempotently in the migration.
- Migration contract verified by `test_audit_guard_migration.py`; the Gate 22
  candidate also exercised UPDATE, DELETE, and TRUNCATE against disposable
  PostgreSQL, with each operation rejected using SQLSTATE 55000.
- No HTTP endpoint exposes DELETE, PATCH, or PUT on audit rows; verified by
  `TestAuditIntegrity` in `test_adversarial_security.py`.

### Prompt-injection defence
- `KnowledgeRetrievalService._has_instruction_text()` matches four compiled
  instruction-override patterns against all retrieved incident and policy content.
  Flagged results carry `prompt_injection_detected=True` in the API response.
- `CoordinatorService._parse_and_validate()` overrides the agent-supplied
  `event_id` with the server-side value; sets `human_review_required=True`
  regardless of agent output; and replaces forbidden pre-judgment labels via
  `_sanitise_summary()`.
- Covered by `TestPromptInjectionDefence` in `test_adversarial_security.py`.

### Login brute-force protection
- The rate-limiting middleware applies a separate `authentication` scope keyed on
  the raw ASGI peer address (never a caller-supplied token) to
  `POST /api/v1/auth/token`, `/auth/refresh`, and `/auth/logout`.
- A bearer token header presented during a login request cannot shift the attempt
  into another principal's bucket.  Covered by `TestAuthBruteForceRateLimit`.

### Input abuse defences
- Pydantic schemas enforce `max_length` on all string fields; unknown enum values
  return `422 UNPROCESSABLE_ENTITY` before reaching the database.
- Audit `action` filter rejects unknown or metacharacter-containing values with
  `422 INVALID_ACTION` (allow-list enforced in the API handler).
- `sanitize_metadata()` applies recursive depth, key-count, item-count, and
  per-string byte limits to all `raw_metadata` payloads.  Non-finite floats and
  unsupported value types are rejected.
- Request body ceiling (configurable, default 1 MB) returns `413 REQUEST_TOO_LARGE`.
- Covered by `test_security_controls.py` and `TestInputAbuse` in
  `test_adversarial_security.py`.

### Authorization boundaries
- `get_current_human_user` dependency rejects service-purpose tokens on
  human-only endpoints (`HUMAN_TOKEN_REQUIRED 403`).
- `require_permission` checks both the role-level grant and the service-purpose
  ceiling in sequence.
- Malformed or tampered JWTs return `401 UNAUTHORIZED` without leaking internal
  details.
- Cross-user token rebinding is prevented by the refresh-token family model:
  the family row's `user_id` is verified against the JWT `sub` claim on every
  rotation.  Covered by `test_auth.py`.
- Covered by `TestAuthorizationBoundaries` in `test_adversarial_security.py`.

## Known limitations / future work

- No committed `uv.lock` file.  A future lock-file migration must add a
  `uv lock --check` gate and update this document.
- Renovate/Dependabot automation for action SHA pinning is deferred until an
  automated update owner is assigned.
- The `AUDIT_GUARD_TEST_DSN` live PostgreSQL proof in
  `test_audit_guard_migration.py` is skipped in default CI unless configured
  against a migrated test database; it was run against a disposable migrated
  PostgreSQL instance during this Gate 22 candidate validation.
