# ADR-007 — Triage Agent Integration Strategy

**Status:** Accepted  
**Date:** 2026-11-05  
**Author:** IBM Bob (Principal Architect)  
**Gate:** 14

---

## Context

Gate 14 introduces the Triage Agent — a watsonx Orchestrate agent that
classifies incoming security events and identifies which evidence sources
must be queried.  A decision was needed on how to integrate the agent
into the existing deterministic backend pipeline without:

1. Breaking the event if Orchestrate is unavailable.
2. Allowing the agent to influence the deterministic risk score.
3. Allowing prompt-injected content in agent output to reach the audit trail.

---

## Decision

### 1. Triage runs before the deterministic pipeline

The `TriageService` is invoked at the start of `AssessmentService.run()`,
after the event is loaded from the database.  The triage result (category,
urgency signals, required context) is stored alongside the assessment but
does NOT influence the deterministic risk or confidence calculation.

This preserves ADR-003 (deterministic risk engine is LLM-independent) and
ADR-004 (risk ≠ confidence).

### 2. Mandatory deterministic fallback

`TriageService` always returns a `TriageResult`.  If Orchestrate is
unavailable, returns an invalid response, or is not configured, the service
runs a deterministic fallback that applies the same classification rules
defined in the agent's instructions — so the output is predictable and
testable without a live Orchestrate connection.

The fallback is not a degraded mode — it is an expected operational path.
The `source` field in `TriageResult` distinguishes:

- `"orchestrate"` — validated agent response
- `"deterministic_fallback"` — Orchestrate unavailable or invalid output
- `"skipped"` — Orchestrate not configured

### 3. Agent output is treated as untrusted data

The `_parse_and_validate()` method in `TriageService` filters all agent
output fields against allowlists before constructing `TriageResult`:

- `category` must be in `_ALL_CATEGORIES`; otherwise defaults to `"unclassified"`
- `urgency_signals` items must be in `_ALL_SIGNALS`; unknown items are dropped
- `required_context` items must be in `_ALL_CONTEXT`; unknown items are dropped
- `triage_rationale` is truncated to 512 characters

This prevents prompt-injected content in retrieved incident history or other
sources from propagating instructions through the agent output into the
system's audit trail or downstream services.

### 4. Agent tool access is least-privilege

The Triage Agent is granted one read-only tool: `get_event_detail`.
It cannot call evidence retrieval tools, the risk engine, the escalation
API, or any write endpoint.  Evidence retrieval remains the responsibility
of the Context Agent (Gate 15).

### 5. AgentRun record is always created

Every call to `TriageService.run()` creates an `AgentRun` row, even for
fallback and skipped cases (`status = "failed"` or `"skipped"`).  This
ensures the audit trail always records that a triage attempt was made and
what source produced the classification.

---

## Consequences

### Positive
- Events are never lost due to Orchestrate unavailability.
- Triage output is always validated against a schema before use.
- The deterministic risk engine remains LLM-independent (ADR-003 preserved).
- Every triage invocation is observable via `AgentRun` / `ToolCall` tables.
- The pattern is directly extensible to the Context Agent (Gate 15) and
  Explanation Agent (Gate 16).

### Negative / Trade-offs
- Two calls to `TriageService.run()` were considered (pre-load + post-load);
  this was simplified to a single call after the event is loaded.
- The Orchestrate agent API path used (`/v1/chat/completions`) is the current
  Orchestrate-compatible endpoint.  If the Orchestrate API changes, only
  `_invoke_orchestrate()` in `TriageService` needs to be updated.

### Migration impact
- No schema migration required — `AgentRun` and `ToolCall` tables were
  created in Gate 3 (`0001_initial_schema.py`).
- `AssessmentResponse` gains an optional `triage` field (non-breaking change).

---

## Alternatives considered

### Alternative A — Triage as a separate API endpoint

Rejected: would require the caller to sequence two API calls and manage
partial failures.  Embedding triage in the assessment pipeline is simpler
and ensures every assessment always includes triage.

### Alternative B — Triage output influences risk score

Rejected: violates ADR-003.  The risk score must remain deterministic and
reproducible.  Triage categorisation informs routing/display, not scoring.

### Alternative C — Fail the assessment when Orchestrate is unavailable

Rejected: violates the master prompt's safe-default principle (section 11)
and the failure semantics requirement (section 10).  The event must remain
available for manual review even if the AI layer is down.
