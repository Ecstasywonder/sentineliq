# ADR-008 — Dual-Path Agent Invocation Architecture

**Status:** Accepted  
**Date:** 2026-11-05  
**Author:** IBM Bob (Principal Architect)  
**Historical gate:** 14 (amendment) — **Master Build Prompt Gate 11**

---

## Context

Gate 14 originally targeted watsonx Orchestrate SaaS as the exclusive
runtime for agent invocation. During connection verification it was found
that:

1. No watsonx Orchestrate SaaS tenant URL is provisioned for this account.
2. The `ORCHESTRATE_BASE_URL` pointed to `https://us-south.ml.cloud.ibm.com`
   (watsonx.ai ML runtime), not an Orchestrate tenant.
3. A direct call to the watsonx.ai Chat API (`/ml/v1/text/chat`) with
   `ibm/granite-4-h-small` and the Orchestrate Developer Edition space
   (`5ff3e395-...`) was verified working end-to-end on 2026-11-05, producing
   correct structured triage output.

The decision was therefore needed on how to preserve the full intended
Orchestrate architecture while not blocking current development on an
unprovisioned service.

---

## Decision

### Three-path invocation hierarchy

The Triage, Context, and Explanation backend services implement three
invocation paths in strict priority order:

```
PATH B — watsonx Orchestrate SaaS  (primary — activates when ORCHESTRATE_URL is set)
     ↓ (on failure or not configured)
PATH A — watsonx.ai Chat API        (verified fallback — activates when WATSONX_* vars set)
     ↓ (on failure or not configured)
PATH 0 — Deterministic fallback     (always available — no LLM, no network)
```

**Path B is the intended production path.** It is implemented against IBM's
documented direct-agent chat-completions contract and has local contract-test
coverage. Invocation against the project's live tenant remains unverified and
must not be represented as live-validated until tenant credentials and an
imported agent are available.

**Path A is the currently verified remote path.** It uses
`ibm/granite-4-h-small` and the same task constraints as the corresponding
backend service. The strict backend output validator is shared across all
three paths.

**Path 0 always succeeds.** It is the rule-based Python fallback that has
been present since Gate 14. It mirrors the agent's classification rules
exactly, making it predictable and fully testable without any network.

### Configuration routing

| Variable | Purpose | Path activated |
|----------|---------|---------------|
| `ORCHESTRATE_URL` | Orchestrate tenant URL | Path B (when + API key set) |
| `ORCHESTRATE_API_KEY` | IBM Cloud API key exchanged for an IAM bearer token | Path B (and Path A only as a backwards-compatible fallback) |
| `ORCHESTRATE_API_VERSION` | Direct-agent API version (`v2` default; `v1_5` supported) | Path B |
| `WATSONX_BASE_URL` | watsonx.ai ML endpoint | Path A |
| `WATSONX_API_KEY` | IBM Cloud API key for IAM | Path A |
| `WATSONX_SPACE_ID` | Space with WML instance | Path A |
| `WATSONX_MODEL_ID` | Foundation model | Path A |
| *(none of the above)* | — | Path 0 only |

Backwards-compat shims for `ORCHESTRATE_BASE_URL` and `ORCHESTRATE_SPACE_ID`
are provided in `Settings` so existing `.env` files continue working.

### Source field in TriageResult

The `source` field records which path produced the result:
- `"orchestrate"` — Path B succeeded
- `"watsonx_ai"` — Path A succeeded
- `"deterministic_fallback"` — Path 0 used (no LLM available or both failed)

### Path B API contract

When Orchestrate is provisioned:
1. Run `orchestrate agents import --file agents/triage/agent.yaml`
2. Set `ORCHESTRATE_URL=https://<tenant>.ibm-watson-orchestrate.com`
3. Set `ORCHESTRATE_API_KEY=<api_key>`

The three backend agent services will automatically route to Path B. A live
tenant check is still required because agent import state, agent identifiers,
tenant authorization, and runtime response behavior cannot be proven by local
contract tests.

For IBM Cloud SaaS, Path B exchanges the API key at IBM Cloud IAM and sends
the resulting short-lived bearer token. `ZenApiKey` is an on-premises auth
scheme and is not used by this SaaS adapter. Path B calls:
```
POST <ORCHESTRATE_URL>/v2/orchestrate/<agent_id>/chat/completions
Authorization: Bearer <iam_access_token>

{
  "messages": [
    {"role": "system", "content": "<agent constraints>"},
    {"role": "user", "content": "<allowlisted input JSON>"}
  ],
  "stream": false
}
```

The response is parsed as an OpenAI-style `choices[0].message.content`
payload. Both string content and documented text-part arrays are accepted;
undocumented `output` or `content` top-level shapes are rejected.

All three backend agent services use `OrchestrateClient`; authentication, endpoint
construction, response parsing, and non-sensitive telemetry are no longer
duplicated across service adapters.

The imported `sentinel_coordinator` definition is a separate, read-only review
agent. It is not invoked by these backend adapters and does not replace the
transactional workflow coordination performed by `AssessmentService`. Live
coordinator import and collaborator execution remain acceptance evidence to be
collected from an Orchestrate tenant.

### All paths share the same output contract

- System prompt is identical across Path B and Path A.
- `_parse_and_validate()` applies the same allowlist filtering to all paths.
- `AgentRun` rows are persisted for all three paths.
- The `orchestrate_run_id` column stores
  `path:<orchestrate|watsonx_ai|deterministic>` for auditability.

---

## Consequences

### Positive
- No blocking dependency on Orchestrate provisioning.
- Path B activates automatically after the tenant, credentials, and imported
  agent IDs are configured.
- Architecture intent is fully preserved and documented.
- Operators and auditors can distinguish which path produced each triage result.
- All safety constraints (ADR-003 through ADR-007) hold across all paths.

### Negative / Trade-offs
- Until Path B is active, the benefits of Orchestrate (versioning, governance,
  collaborator chains, UI traces, evaluation, human-approval workflows) are absent.
- Path A does not enforce agent-level tool permissions — this is enforced by the
  SentinelIQ backend service layer instead.

### What Orchestrate adds when provisioned (Path B benefits)
- Agent versioning and change governance
- Tool permission enforcement at the agent runtime level
- Collaborator-agent chaining (Coordinator → Triage → Context → Explanation)
- Traces visible in the Orchestrate UI
- Human-approval steps within agent workflows
- Agent evaluation via Orchestrate eval framework
- Model routing across multiple foundation models

---

## Migration path to Path B

1. Provision watsonx Orchestrate instance (IBM Cloud catalog).
2. Configure ADK CLI: `orchestrate env activate`.
3. Import agents: `orchestrate agents import --file agents/triage/agent.yaml`.
4. Set `ORCHESTRATE_URL` in `.env`.
5. Invoke the imported agent through
   `POST /v2/orchestrate/<agent_id>/chat/completions` using an IAM bearer token.
   Record this as live-validated only after a tenant response passes the same
   strict output validation as the fallback paths.
6. Record the imported agent IDs in configuration and run the backend's strict
   contract tests against the live tenant before declaring Path B validated.
