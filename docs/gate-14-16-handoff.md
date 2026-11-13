# Gate 14–16 Engineering Handoff

**Status date:** 2026-11-13
**Status:** implementation evidence is current; final merge, CI, and deployment evidence remains required where noted
**Validation rule:** installations and tests run on EC2 only.

This handoff supplements the canonical [Master Build Prompt](master-build-prompt.md),
[Master Gate Plan](master-gate-plan.md), and [source-of-truth hierarchy](source-of-truth.md).

## Confirmed EC2 evidence

Watsonx Orchestrate Path B is now proven in the live tenant. A new event,
`06b46f4d-76df-4979-b22b-d24aa60a30fb`, completed the backend assessment with
Triage, Context, and Explanation all recorded as `orchestrate`; the event
remained `awaiting_review` and therefore required human review. Risk and
confidence continued to be determined by the server's deterministic engines.

Context directly called its event-detail tool through the OAuth-protected
SentinelIQ API and returned valid JSON. Coordinator executed its read-only
event/assessment tools and delegated to the Triage, Context, and Explanation
collaborators. This is live tool and collaborator execution evidence, not just
agent-definition import evidence.

The working runtime model is `groq/openai/gpt-oss-120b` within watsonx
Orchestrate. The tested Granite model emitted tool-call arguments as JSON
strings rather than objects, so it did not satisfy the agent tool contract.

| Agent | Current tenant UUID |
|---|---|
| Triage | `76daed62-455c-4999-93b1-8ab7aff82c31` |
| Context | `29220055-2483-4d4f-9efc-2f0ff93d457a` |
| Explanation | `093479ec-41e9-43d8-89b3-28d1cbffa75f` |
| Coordinator | `0e56991e-cd11-4f77-812f-ced7b31aeac7` |

Re-importing can change these UUIDs. Treat them as evidence to reconfirm, not
as values to place in version-controlled configuration.

## Architecture now in force

Path B (watsonx Orchestrate) is the sole remote LLM architecture. The direct
watsonx.ai Chat API fallback is being removed; the deterministic fallback is
retained as the safe, non-LLM behavior for Orchestrate configuration, transport,
or response-validation failures. Watsonx may still be used independently for
embeddings; that is not a generation fallback.

ReAct Core does not support native `structured_output`. Each agent therefore
contains its exact JSON schema in its instructions, and strict backend Pydantic
validation remains the enforcement boundary. Context uses `react_intrinsic`,
explicit read-only tools, and no peer collaborators. Coordinator uses the same
agent style, explicit tools, and bounded read-only collaborators.

The current candidate also grounds Coordinator output in the persisted server
assessment bundle after schema validation, so collaborator text cannot inject
invented evidence into operator-facing reviews.

## Deployment and access state

- Caddy is enabled as a systemd service on EC2. The live team URL is
  [https://54.164.137.222/](https://54.164.137.222/); public `/` and `/health`
  returned 200, and a protected API endpoint returned 401 without credentials.
- The host does not have an Elastic IP. Caddy survives service restart and host
  reboot, but an EC2 stop/start can change this IP; an EIP or DNS name is still
  required for durable external identity.
- A refresh-token persistence defect was identified in the currently deployed
  backend: `refresh_tokens` could be flushed before its parent
  `refresh_token_families` record, causing the foreign-key error after nominal
  login. The candidate explicitly flushes the parent before the child and adds
  a regression test. It is **not live until that candidate is deployed**.

## Remaining exit conditions

1. Merge the active candidate, pass GitHub Actions, and deploy that exact
   revision to EC2.
2. Re-run focused backend tests on EC2, including the auth family-order,
   Coordinator grounding, and Path-A-removal suites; then run the required
   broader quality gates.
3. Verify real HTTPS login, `/auth/me`, and refresh-token rotation after the
   deployed auth fix. Do not distribute test credentials until this passes.
4. Force an Orchestrate failure and demonstrate deterministic fallback with no
   direct watsonx.ai chat attempt.
5. Re-run a fresh event and Coordinator review on the deployed revision,
   retain sanitized `AgentRun`/tool evidence, and update the gate plan only
   after the merge/CI/deployment chain is complete.

## Gate 15 and Gate 16 implications

Gate 15's decision, escalation, audit, and feedback workflow remains complete:
the newly proven agent path still ends in `awaiting_review` and does not bypass
human authority. Gate 16's dashboard remains a validated implementation
candidate. Its final operational demonstration depends on the deployment and
login verification above; the UI must continue to show agent provenance,
fallback/error state, recommendation, and the human-review requirement without
exposing runtime secrets or raw internal errors.

## Source-control and sensitive-data boundary

Preserve existing user changes, ignored EC2 environment files, tokens, OAuth
client secrets, and generated artifacts. Push candidate code and documentation,
wait for CI, and reconcile the local, EC2, and GitHub tracking branches only
after the final revision is known. Do not force-reset a dirty worktree.
