# ADR-008 — Watsonx Orchestrate Agent Invocation

**Status:** Superseded decision implemented; final code removal of the retired path is pending merge and deployment
**Date:** 2026-11-13
**Historical gate:** 14 (amendment) — **Master Build Prompt Gates 11–14**

## Context

SentinelIQ must use watsonx Orchestrate as its LLM-agent runtime. An earlier
temporary design allowed direct watsonx.ai Chat API invocation ("Path A") when
Orchestrate was unavailable. That was a provisioning workaround, not the
target architecture.

On 2026-11-13, EC2 validation demonstrated the intended Orchestrate path
against the live tenant:

- a fresh event completed Triage, Context, and Explanation with source
  `orchestrate`;
- Context called the event-detail tool through the OAuth-protected SentinelIQ
  API and returned valid JSON;
- Coordinator executed its read-only event/assessment tools and delegated to
  Triage, Context, and Explanation collaborators;
- the selected tenant model was `groq/openai/gpt-oss-120b`. The previously
  tested Granite model emitted tool-call arguments as JSON strings rather than
  objects and did not meet the tool-call contract.

The ReAct Core runtime does not support its native `structured_output` setting.
The checked-in agents therefore carry their exact JSON response schema in their
instructions, and the backend Pydantic validators remain the enforcement point.
This is an intentional compatibility adaptation, not a relaxation of the
output contract.

## Decision

The only remote LLM invocation path is **Path B — watsonx Orchestrate**.

```
watsonx Orchestrate (Path B, sole remote LLM runtime)
       ↓ on configuration, transport, or validation failure
Deterministic fallback (Path 0, non-LLM safety behavior)
```

Direct watsonx.ai Chat API inference is retired. The implementation removing
its service branches, configuration routing, source labels, and tests is in
the active candidate and must be merged, CI-validated, and deployed before the
repository or live service is described as Path-B-only in operation.

Watsonx credentials may continue to be used for the independent embeddings
integration. That use is not a chat-generation fallback and must be configured
and named independently from agent invocation.

## Runtime contract

- Agent definitions use ReAct intrinsic agents with explicit read-only tools
  and declared collaborator boundaries.
- Context has no peer collaborators. Coordinator may request bounded,
  read-only input from Triage, Context, and Explanation; it has no workflow or
  enforcement authority.
- Backend services treat every agent response as untrusted: they validate a
  strict Pydantic model, server-own event identifiers and workflow facts, and
  persist `AgentRun`/tool telemetry.
- Coordinator operator-facing fields are reconstructed from the persisted
  assessment bundle after validation, preventing a collaborator from adding
  invented evidence to the review.
- On any Path B failure, the deterministic fallback preserves the event and
  retains the non-bypassable human-review requirement. It never fabricates LLM
  output.

## Evidence recorded

Current live tenant runtime IDs (re-import may change them):

| Agent | Runtime UUID |
|---|---|
| Triage | `76daed62-455c-4999-93b1-8ab7aff82c31` |
| Context | `29220055-2483-4d4f-9efc-2f0ff93d457a` |
| Explanation | `093479ec-41e9-43d8-89b3-28d1cbffa75f` |
| Coordinator | `0e56991e-cd11-4f77-812f-ced7b31aeac7` |

The evidence event was `06b46f4d-76df-4979-b22b-d24aa60a30fb`; it reached
`awaiting_review` with deterministic risk/confidence and the three specialist
sources recorded as `orchestrate`. These identifiers are operational evidence,
not configuration values to commit into runtime environment files.

## Consequences

Positive consequences are a single governed agent runtime, tenant-visible
traces, explicit tool/collaborator controls, and no silent provider switch.
The trade-off is that an Orchestrate outage yields deterministic reviewable
results rather than remote model output. That trade-off is required by the
master prompt's safety and human-oversight rules.

## Remaining completion conditions

1. Merge the Path A-removal candidate, pass CI, and deploy that exact revision
   to EC2.
2. Verify a forced Orchestrate failure returns the deterministic fallback and
   does not attempt direct watsonx.ai chat inference.
3. Re-run the fresh-event and Coordinator proof against the deployed revision.
4. Keep the OAuth client secret and tenant credentials only in ignored EC2
   configuration.
