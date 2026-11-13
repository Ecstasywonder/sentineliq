# Gates 23-25 Engineering Handoff

**Status date:** 2026-11-13
**Candidate:** `2ce0bc6` on `fix/orchestrate-oauth-v219`
**Rule:** installations and validation run on EC2 only.

This handoff records current evidence without declaring an unmerged or
undeployed candidate complete. The canonical requirements remain the
[Master Build Prompt](master-build-prompt.md),
[Master Gate Plan](master-gate-plan.md), and
[source-of-truth hierarchy](source-of-truth.md).

## Completed on the candidate

- Context and Coordinator definitions use `react_intrinsic`, explicit
  read-only tools, and declared collaborator boundaries. Context has no peer
  collaborators; Coordinator uses Triage, Context, and Explanation as
  read-only collaborators. ReAct Core does not support native
  `structured_output`, so each exact JSON schema is in the agent instructions
  and backend Pydantic validation enforces the contract.
- Agent tools are generated from the FastAPI source of truth and limited to ten
  event-bound GET operations. The Orchestrate team connection uses OAuth2
  client credentials to mint short-lived `tools:read` service tokens.
- Simulator scenario controls are server-owned, event-isolated, and disabled
  by production configuration.
- Gate 23 runner: 73 passed, 0 failed on disposable EC2 infrastructure.
- Gate 24 deterministic smoke: 108 passed, 0 failed on disposable EC2
  infrastructure.
- Backend: 816 passed, 3 skipped, 91% coverage; focused security/tool tests:
  103 passed.
- Frontend: format, typecheck, lint, 57 unit tests, and production build passed.
- Alembic: fresh upgrade, downgrade, and re-upgrade through
  `0006_unique_service_purpose` passed.
- Historical GitHub Actions run
  [43232697244](https://github.com/Ecstasywonder/sentineliq/actions/runs/43232697244)
  passed backend, frontend, Gitleaks, Trivy, and the aggregate CI gate.
- No requested `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`
  trailer exists in current files or the candidate commits. Historical author
  metadata was not rewritten because that would require a repository-wide
  destructive history rewrite.

## Live Orchestrate status

On 2026-11-13 the live tenant proof advanced beyond availability probes:

- Context called the OAuth-protected event-detail tool and returned valid JSON.
- Coordinator executed its read-only event/assessment tools and delegated to
  Triage, Context, and Explanation collaborators.
- Fresh event `06b46f4d-76df-4979-b22b-d24aa60a30fb` completed with the three
  specialist sources recorded as `orchestrate` and ended `awaiting_review`.
- `groq/openai/gpt-oss-120b` is the working tenant model. Granite's tool-call
  argument format was incompatible with the required object contract.

This resolves the former live tool/collaborator evidence blocker. Gates 14 and
24 nevertheless remain incomplete until candidate `2ce0bc6` (and the Path-A
removal work that follows it) passes CI, merges, deploys, and repeats the proof
against the deployed revision.

## Remaining release sequence

1. Merge the reviewed candidate to `main` and confirm required CI on the final
   revision.
2. Deploy that exact revision from a clean EC2 worktree while preserving the
   existing dirty checkout; migrate through `0006` and keep simulator disabled.
3. Deploy the refresh-family ordering fix and verify real HTTPS login,
   `/auth/me`, and refresh rotation before sharing any team credential.
4. Merge and deploy the direct watsonx.ai Chat API removal, retaining only
   Orchestrate Path B plus deterministic fallback; test a forced Path-B failure.
5. Re-run the fresh event and Coordinator proof on the deployed revision.
   Retain sanitized AgentRun, tool-call, schema-validation, and human-review
   evidence.
6. Re-run affected tests on EC2, pass CI, deploy the patch, and reconcile all
   local and EC2 tracked branches with GitHub.
7. Caddy is already enabled. Re-verify public `/health`, protected API 401, and
   the frontend after deployment before sharing the URL.

## Gate 25 access and demonstration blockers

- Caddy currently serves [https://54.164.137.222/](https://54.164.137.222/).
  It is a useful test link, but login remains blocked by the deployed
  refresh-token foreign-key defect until the candidate is deployed and verified.
- The EC2 public IPv4 address is not an Elastic IP. A systemd service survives
  logout/reboot, but a stop/start may change the link unless an EIP or DNS name
  is assigned.
- Use individual least-privilege team accounts. Do not restore or distribute a
  shared fixed-password demo account.
- Production rejects the simulator flag. Demonstrate authorized ingestion on
  production; keep canonical scenario generation in a controlled non-production
  environment.
- MVP scope freeze still requires explicit operator approval after the live
  demonstration.
