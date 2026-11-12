# Gates 23-25 Engineering Handoff

**Status date:** 2026-11-12
**Candidate:** `993c0fe` on `fix/orchestrate-reconcile-access`
**Rule:** installations and validation run on EC2 only.

This handoff records current evidence without declaring an unmerged or
undeployed candidate complete. The canonical requirements remain the
[Master Build Prompt](master-build-prompt.md),
[Master Gate Plan](master-gate-plan.md), and
[source-of-truth hierarchy](source-of-truth.md).

## Completed on the candidate

- Context and Coordinator definitions use `react_intrinsic`, explicit
  read-only tools, declared collaborator boundaries, and strict structured
  output where required. Context has no peer collaborators; Coordinator uses
  Triage, Context, and Explanation as read-only collaborators.
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
- GitHub Actions run
  [43232697244](https://github.com/Ecstasywonder/sentineliq/actions/runs/43232697244)
  passed backend, frontend, Gitleaks, Trivy, and the aggregate CI gate.
- No requested `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`
  trailer exists in current files or the candidate commits. Historical author
  metadata was not rewritten because that would require a repository-wide
  destructive history rewrite.

## Live Orchestrate status

Direct EC2 probes on 2026-11-12 established that the tenant/runtime is
available: the SentinelIQ-owned Groq probe returned `PROBE_OK`, the Granite
probe returned valid JSON, and the currently deployed Triage, Context, and
Explanation specialists returned valid JSON when invoked with their exact
backend prompts. This supersedes the earlier tenant-wide model-outage
hypothesis.

The deployed tenant assets are nevertheless stale relative to `993c0fe`:
Context lacks the new tools/structured contract, Coordinator lacks the current
collaborators/tool set, and the OAuth-backed ten-tool bundle has not been
imported against the candidate API. Therefore Gate 14 and Gate 24 are not yet
complete. A real event-bound tool call and full Coordinator collaborator run
must be captured after deployment.

## Remaining release sequence

1. Merge the reviewed candidate to `main` and confirm required CI on the final
   revision.
2. Deploy that exact revision from a clean EC2 worktree while preserving the
   existing dirty checkout; migrate through `0006` and keep simulator disabled.
3. Provision/rotate the purpose-bound Orchestrate OAuth identity, revoke refresh
   families for known disabled fixed-credential accounts, and import/deploy only
   the four SentinelIQ agents plus the ten approved tools.
4. Update ignored EC2 agent UUID settings, then run a fresh event through
   Triage, Context, Explanation, and Coordinator. Retain sanitized AgentRun,
   tool-call, structured-output, and human-review evidence.
5. Once Path B is proven end to end, remove the watsonx.ai Path A fallback;
   retain and test the deterministic non-LLM fallback.
6. Re-run affected tests on EC2, pass CI, deploy the patch, and reconcile all
   local and EC2 tracked branches with GitHub.
7. Start and enable the hardened Caddy service. Verify public `/health` is 200,
   public `/ready` is intentionally 404, protected APIs reject unauthenticated
   requests, and the frontend renders over HTTPS before sharing the URL.

## Gate 25 access and demonstration blockers

- The public team URL is not ready until the merged revision and hardened Caddy
  configuration pass the checks above.
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
