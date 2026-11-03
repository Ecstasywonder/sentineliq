# ADR-006 — Human Review Is Non-Bypassable

**Date:** 2026-11-03  
**Status:** Accepted  
**Author:** IBM Bob (Principal Architect)  
**Deciders:** Project Owner, Principal Architect

---

## Context

SentinelIQ produces AI-assisted recommendations. The fundamental product principle is that every actionable recommendation must terminate in human review — the AI recommends, the human decides.

There is a risk that, as the system evolves, shortcuts or automation could erode this principle. For example:
- An agent could be granted escalation tools directly
- A "high confidence" threshold could be configured to auto-dismiss
- A workflow shortcut could bypass the review step

Any of these would violate the core product safety guarantee and create accountability gaps.

---

## Decision

Human review is **architecturally non-bypassable** in SentinelIQ.

The following rules are enforced at the application level, not the agent level:

1. **Human review state is owned by the SentinelIQ backend**, not by the agent
   - After assessment, the backend sets status = `AWAITING_REVIEW` and persists the recommendation
   - The agent cannot set the final event status to anything other than `AWAITING_REVIEW` (unless explicitly failing to `CONTEXT_INCOMPLETE` / `FAILED`)

2. **Escalation tools are not available to agents**
   - Agents have no tool that creates an escalation record or contacts a response system
   - Only authenticated human users can call `POST /api/v1/events/{event_id}/escalate`

3. **Auto-dismiss and auto-close are prohibited by configuration**
   - There is no configuration setting that causes SentinelIQ to automatically close or dismiss events
   - Feature flags for any future "low risk auto-review" capability must first receive ADR approval

4. **Override history is always visible**
   - All overrides are logged in the audit trail with user ID, role, and rationale
   - The audit trail cannot be deleted or modified

5. **Agent evaluation tests include human-oversight compliance as a required metric**
   - Any evaluation result that shows the agent bypassing human review is a failing test

---

## Rationale

This is the fundamental safety guarantee of the product. Without it:
- SentinelIQ becomes an autonomous enforcement system
- Accountability is lost
- The product violates its own stated design principles
- Legal and operational liability increases significantly

The cost of enforcing this architecturally (rather than relying on configuration discipline) is minimal. The benefit is permanent protection against accidental or deliberate bypass.

---

## Alternatives Considered

| Alternative | Reason Not Selected |
|------------|---------------------|
| Policy-based: configurable auto-approve on high confidence | Violates product principle; configuration drift risk |
| Agent-controlled escalation with human confirmation | Insufficient separation; agent still initiates enforcement path |
| Trust the operator to always review | No architectural enforcement; human fatigue leads to skip |

---

## Consequences

- The backend assessment flow always ends in `AWAITING_REVIEW` for actionable events
- No agent has an escalation tool in its tool permission set
- CI evaluation tests include a `human_oversight_compliance` assertion
- Future requests to add auto-approve capability require a new ADR and product owner approval

---

## Migration Impact

N/A — initial design decision. Future production architecture must preserve this guarantee.

---

## Test Impact

Critical test: Verify that no code path exists that moves an event from `ASSESSING` directly to `ESCALATED` or `DISMISSED` without a `human_decision` record with a valid user ID.
