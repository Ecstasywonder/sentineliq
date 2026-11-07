# Gate 14–16 Engineering Handoff

**Status date:** 2026-11-07  
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
- The SentinelIQ read-only tool set was imported: `get_event_detail`,
  `get_access_events`, `get_assessment_bundle`, `get_delivery`,
  `get_incident_history`, `get_integration_health`, `search_knowledge`,
  `get_location_policy`, `get_schedule`, and `get_work_orders`.
- Four SentinelIQ agents were imported and deployed. Their current runtime
  identifiers are:

  | Agent | Runtime UUID |
  |---|---|
  | Triage | `03b55ef8-ff71-4605-8ba4-4e1fb2588b15` |
  | Context | `a0746580-6bbf-42c5-98dc-8668c8fb84b1` |
  | Explanation | `77cca91e-63f5-475e-a410-529025eb0b2d` |
  | Coordinator | `98c49c40-3cce-4372-9030-14a71f400062` |

  Re-importing an agent can create a new UUID; confirm the active identifiers
  before changing the EC2 runtime configuration.
- The backend was rebuilt from source on EC2. Runtime image construction was
  checked so ignored environment files and private-key material are not baked
  into the image.
- Database migrations through Alembic revision `0004_decision_snapshot` were
  applied on EC2. The backend health endpoint is healthy.

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

- Caddy was installed and configured on EC2 as the HTTPS reverse proxy for
  the backend API, including health handling and API proxying.
- A publicly trusted short-lived certificate for the current public IP was
  obtained successfully. The public IP is not an Elastic IP, so a stable EIP
  or DNS name remains a deployment hardening recommendation.

### Focused verification already completed on EC2

- Focused backend tests covering configuration, Orchestrate client behavior,
  triage behavior, and tool contract behavior passed (99 tests before the
  latest draft/live connection regression test was added).
- Ruff and shell syntax checks for the agent import/delete scripts passed.
- A synthetic normalized event completed the persisted backend assessment
  workflow: event status advanced to `awaiting_review`, deterministic risk and
  confidence were calculated, a recommendation was persisted, and mandatory
  human review remained required.

## Current live-runtime blocker

**Observed evidence:** Calls to each deployed Orchestrate specialist reach the
live runtime and return HTTP 200, but the assistant content is the generic
runtime error message rather than the required structured JSON. The backend
correctly rejects that non-JSON output.

**Effect:** The synthetic assessment persisted safely, but its specialist
sources showed the interim fallbacks rather than verified `orchestrate` output:
triage and explanation used the former watsonx.ai path, and context used the
deterministic fallback. This is not sufficient evidence to close Gate 14.

**Likely isolation steps (not yet proven):** validate a SentinelIQ-owned
minimal no-tool/no-schema probe with a tenant-enabled model; then separately
introduce structured output and read-only tools. This distinguishes model
availability, output-schema compatibility, and connection/tool configuration
without touching unrelated tenant resources. Retain sanitized run evidence for
each result.

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

1. Resolve the generic live Orchestrate runtime response for SentinelIQ-owned
   agents and verify valid schema-conforming outputs from triage, context, and
   explanation.
2. Run a new synthetic event through the complete backend path and show all
   three specialist sources as `orchestrate`, with persisted `AgentRun` and
   tool-call observability.
3. Invoke the deployed Coordinator as a read-only reviewer and retain
   sanitized run/tool evidence. The transactional workflow authority remains
   the backend `AssessmentService`.
4. Remove the watsonx.ai Path A fallback, update targeted tests and
   configuration/docs, and demonstrate the retained deterministic safety path
   for Orchestrate failure.
5. Run the focused regression suite on EC2 again (including the new
   draft/live connection test), then run the broader relevant quality gates.
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

1. On EC2, list only safe model identifiers/statuses and run an isolated,
   SentinelIQ-owned minimal agent probe. Do not alter or delete unrelated
   tenant agents, connections, or tools.
2. If the probe identifies model configuration as the cause, update the
   SentinelIQ agent definitions to a tenant-enabled model; otherwise add back
   structured output and tools one at a time to isolate the failing feature.
3. Re-import/redeploy only the four SentinelIQ agents as needed, capture new
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
