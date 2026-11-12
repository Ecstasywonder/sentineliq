# Gate 14–16 Engineering Handoff

**Status date:** 2026-11-12
**Status:** living handoff; Gate 14 remains pending live-runtime evidence  
**Validation rule:** perform installations and tests on the EC2 environment only.

This document is the sanitized operational handoff for the current canonical
Gate 14 work (Coordinator and end-to-end agent workflow) and transition to
Gates 15–16. It supplements, rather than replaces, the canonical
[Master Build Prompt](master-build-prompt.md), [Master Gate Plan](master-gate-plan.md),
and [source-of-truth hierarchy](source-of-truth.md).

## Evidence verified so far

### Runtime and deployment

- An IBM watsonx Orchestrate SaaS environment is configured from the EC2-only
  runtime environment; credentials remain in ignored environment files and
  are not documented here.
- The Orchestrate ADK is installed on EC2 and an active working environment
  was registered for this Gate 14 validation.
- An older SentinelIQ read-only tool set and four agents were imported during
  the prior Gate 14 work. Those tenant assets are now stale relative to the
  OAuth-protected, event-bound ten-tool contract in candidate `993c0fe` and
  must not be treated as current acceptance evidence. The tenant snapshot
  observed on 2026-11-12 used these runtime identifiers:

  | Agent | Runtime UUID |
  |---|---|
  | Triage | `76daed62-455c-4999-93b1-8ab7aff82c31` |
  | Context | `49216ec7-117f-4547-8bd5-9756aef3f523` |
  | Explanation | `093479ec-41e9-43d8-89b3-28d1cbffa75f` |
  | Coordinator | `98c49c40-3cce-4372-9030-14a71f400062` |

  Re-importing an agent can create a new UUID; confirm the active identifiers
  before changing the EC2 runtime configuration.
- The backend was rebuilt from source on EC2. Runtime image construction was
  checked so ignored environment files and private-key material are not baked
  into the image.
- The candidate migration chain was validated on a disposable EC2 PostgreSQL
  database through `0006_unique_service_purpose`, including downgrade to base
  and re-upgrade. The currently running shared deployment remains an older
  build until the candidate merges and is deliberately redeployed.

### Orchestrate invocation contract

- The live tenant accepts the service endpoint form
  `/v1/orchestrate/<agent-uuid>/chat/completions` at the HTTP layer.
- Backend configuration and client validation now require the supported `v1`
  runtime contract and canonical UUID agent identifiers when Orchestrate is
  enabled.
- Connection configuration was extended so the SentinelIQ API connection is
  represented for both `draft` and `live` environments. The import script
  provisions that connection shape and the contract test asserts it.

### Platform and transport

- Caddy was installed and configured on EC2 as the systemd-managed HTTPS proxy
  for the frontend application, API, health, and readiness routes. It is the
  intended team access path once its public host and deployed revision have
  been revalidated.
- A publicly trusted short-lived certificate for the current public IP was
  obtained successfully. The public IP is not an Elastic IP, so a stable EIP
  or DNS name remains a deployment hardening recommendation.

### Candidate verification completed on EC2

- Commit `993c0fe`: 816 backend tests passed, 3 skipped, with 91% coverage;
  the focused security/configuration/simulator/tool suite passed 103 tests.
- Frontend format, typecheck, lint, 57 unit tests, and production build passed.
- Gate 23 passed 73/73 assertions and the deterministic Gate 24 smoke passed
  108/108 checks on disposable EC2 stacks.
- GitHub Actions run `43232697244` passed backend, frontend, Gitleaks, Trivy,
  and the aggregate CI gate.

## Current live-runtime state and blocker

**Observed evidence on 2026-11-12:** the SentinelIQ-owned Groq probe returned
`PROBE_OK`; the Granite probe returned valid JSON; and the currently deployed
Triage, Context, and Explanation specialists returned valid JSON when called
with the actual backend prompts. The earlier generic-error evidence therefore
does not establish a current tenant-wide or model-wide outage.

**Remaining blocker:** the live tenant definitions do not match candidate
`993c0fe`. Context has no current event-bound tool set/structured contract and
Coordinator has no current collaborators and stale tool references. The new
OAuth team connection and ten approved GET tools also depend on the candidate
API being deployed. Direct specialist prompts are useful isolation evidence,
but do not prove tool execution, collaborator execution, or the complete
backend Path B workflow.

**Required proof:** after the candidate API is deployed, import and deploy only
the four SentinelIQ definitions and approved tool bundle, update the ignored
runtime UUID settings, then capture a fresh event whose specialist sources are
`orchestrate` plus a Coordinator run showing real event-bound tool and
collaborator telemetry.

## Architecture decision now in force

Path B, watsonx Orchestrate, is the intended and sole LLM architecture. Once
its live execution produces valid specialist output, remove the automatic
watsonx.ai (Path A) fallback rather than silently changing providers. Keep the
deterministic fallback as a non-LLM safety behavior: it preserves the event,
does not fabricate AI output, and continues to require human review where the
workflow requires it.

Until Path B has been demonstrated functional, do not remove the existing
fallback implementation prematurely; it currently preserves safe operation
while the Orchestrate runtime defect is isolated. Update ADR-008 and the older
agent reports when Path A removal is implemented, so documentation no longer
describes dual-provider routing as the target architecture.

## Remaining Gate 14 exit criteria

Gate 14 is **pending** until all of the following are evidenced on EC2:

1. Import the candidate OAuth connection, tools, and four agent definitions;
   verify the active tenant definitions match the checked-in contracts.
2. Run a new synthetic event through the complete backend path and show all
   three specialist sources as `orchestrate`, with persisted `AgentRun` and
   tool-call observability.
3. Invoke the deployed Coordinator as a read-only reviewer and retain
   sanitized run/tool evidence. The transactional workflow authority remains
   the backend `AssessmentService`.
4. Remove the watsonx.ai Path A fallback, update targeted tests and
   configuration/docs, and demonstrate the retained deterministic safety path
   for Orchestrate failure.
5. Run the focused regression suite on EC2 again after Path A removal, then run
   the broader relevant quality gates.
6. Update the canonical gate plan/source-of-truth only after the above evidence
   is available and the changes have passed CI on the pushed commit.

## Gate 15 and Gate 16 handoff

### Gate 15 — Human-review workflow

The canonical Gate 15 backend workflow is already recorded as complete in the
Master Gate Plan: decision, escalation, audit, and feedback APIs are present.
Its entry condition from Gate 14 is an assessment that remains reviewable by a
human regardless of model health. The current synthetic run demonstrates the
safe state (`awaiting_review` and human review required), but final Gate 14
evidence must confirm the same behavior with live Orchestrate specialist
output and Coordinator review.

### Gate 16 — Operator dashboard foundation

The dashboard implementation candidate has passed its prior EC2 validation,
but strict completion is still pending CI and merge evidence. Before starting
the next dashboard work (Gate 17 decision interface), verify that the UI
renders the completed Gate 14 assessment fields, including clearly labeled
agent provenance, fallback/error state, recommendation, and non-bypassable
human-review requirement. Do not expose internal runtime errors or sensitive
connection details in the operator interface.

## Recommended next actions

1. Merge and deploy the validated candidate API so its OAuth service-token and
   event-bound tools are publicly reachable through the hardened HTTPS route.
2. Configure the purpose-bound OAuth team connection without printing or
   committing its client secret.
3. Re-import/redeploy only the four SentinelIQ agents and ten approved tools, capture new
   UUIDs, and update the ignored EC2 runtime configuration accordingly.
4. Execute a fresh synthetic event (do not overwrite the prior evidence),
   verify specialist provenance and persisted observability, then execute the
   Coordinator run.
5. Implement Path A removal only after Path B works end-to-end; retain and test
   deterministic safety fallback behavior.
6. Update the Gate 14 evidence, ADR, source-of-truth, and gate-plan documents
   with sanitized facts; run validation exclusively on EC2.

## Source-control and reconciliation requirements

- Preserve existing user changes and never commit ignored runtime environment
  files, credentials, tokens, tenant identifiers, or generated test artifacts.
- Commit the completed implementation and evidence documentation on the active
  branch, push it to GitHub, and wait for the GitHub Actions result.
- Reconcile local, EC2, and GitHub after the final push: fetch remotes and
  confirm each relevant branch is neither ahead nor behind its GitHub tracking
  branch. Resolve any divergence deliberately; do not force-reset a worktree.
- Strict gate status changes require the pushed/CI-validated commit and the
  documented evidence above, not an unpushed EC2 result.

## Sensitive-data boundary

This handoff intentionally omits service URLs beyond their generic path form,
environment values, API keys, tokens, tenant instance identifiers, personal
emails, IAM identifiers, and application user identifiers. Keep those values
in the approved ignored runtime configuration only.
