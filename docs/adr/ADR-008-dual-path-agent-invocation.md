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

Every agent service (Triage, Context, Explanation, Coordinator) implements
three invocation paths in strict priority order:

```
PATH B — watsonx Orchestrate SaaS  (primary — activates when ORCHESTRATE_URL is set)
     ↓ (on failure or not configured)
PATH A — watsonx.ai Chat API        (verified fallback — activates when WATSONX_* vars set)
     ↓ (on failure or not configured)
PATH 0 — Deterministic fallback     (always available — no LLM, no network)
```

**Path B is the intended production path.** It is implemented now, tested
against the expected Orchestrate API contract, and will activate
automatically when `ORCHESTRATE_URL` is set in the environment.

**Path A is the current active path.** It is verified working. It uses the
same model (`ibm/granite-4-h-small`) and the same prompt as the Orchestrate
agent definition, so the output contract is identical.

**Path 0 always succeeds.** It is the rule-based Python fallback that has
been present since Gate 14. It mirrors the agent's classification rules
exactly, making it predictable and fully testable without any network.

### Configuration routing

| Variable | Purpose | Path activated |
|----------|---------|---------------|
| `ORCHESTRATE_URL` | Orchestrate tenant URL | Path B (when + API key set) |
| `ORCHESTRATE_API_KEY` | API key for Orchestrate auth | Path B and A |
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

`TriageService` will automatically route to Path B. No other code changes required.

Path B uses `ZenApiKey` auth (Orchestrate's own scheme) and calls:
```
POST <ORCHESTRATE_URL>/v1/agents/<agent_id>/run
  { "input": "<event_metadata_json>" }
```

The Orchestrate response is expected in one of:
- `{ "output": "<text>" }` — Orchestrate native
- `{ "choices": [{ "message": { "content": "<text>" } }] }` — if Orchestrate proxies chat completions

### All paths share the same output contract

- System prompt is identical across Path B and Path A.
- `_parse_and_validate()` applies the same allowlist filtering to all paths.
- `AgentRun` rows are persisted for all three paths.
- The `orchestrate_run_id` column stores `path:<B|A|deterministic>` for auditability.

---

## Consequences

### Positive
- No blocking dependency on Orchestrate provisioning.
- Path B activates automatically when Orchestrate is provisioned — zero code change.
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
5. Verify with `curl <ORCHESTRATE_URL>/v1/agents/sentinel_triage_agent/run`.
6. Path B activates automatically — no code changes required.
