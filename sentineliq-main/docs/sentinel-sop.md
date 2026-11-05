# SentinelIQ — Standard Operating Procedure (SOP)

**Document ID:** SNTL-SOP-001  
**Version:** 1.0  
**Date:** 2026-11-03  
**Status:** Approved  
**Author:** IBM Bob (Principal Architect)

---

## 1. Purpose

This SOP defines how security monitoring officers and supervisors use SentinelIQ to review, assess, and act upon security events. It also defines system operating procedures for administrators.

---

## 2. Core Principle

**SentinelIQ recommends. Humans decide.**

No action described in this SOP is taken automatically by the system. Every operational action requires an authorised human decision.

---

## 3. Event Review Procedure

### 3.1 Accessing the Event Queue

1. Log in to the SentinelIQ operator dashboard with your credentials
2. The event queue displays events sorted by risk level (CRITICAL → HIGH → MEDIUM → LOW) then by time
3. Events with status `AWAITING_REVIEW` require your attention
4. Events marked `CONTEXT_INCOMPLETE` have missing evidence sources — review with that limitation in mind

### 3.2 Reviewing an Event

For each event requiring attention:

1. **Read the Summary** — the one-sentence description of what was detected, where, and when
2. **Check Risk Level** — displayed prominently as CRITICAL / HIGH / MEDIUM / LOW with icon and text label
3. **Check Confidence** — displayed separately as HIGH / MEDIUM / LOW
   - HIGH confidence = most evidence sources were available and consistent
   - LOW confidence = key sources were unavailable or contradictory
4. **Read the Explanation** — the "Why" section explains what evidence drove the risk level
5. **Review Evidence Items** — each evidence item shows source, timestamp, and status
6. **Check Missing Evidence** — any listed missing sources mean that aspect could not be verified
7. **Read the Recommendation** — the system's suggested next human action

### 3.3 Making a Decision

After reviewing, select one of the following actions:

| Action | When to Use |
|--------|------------|
| **Accept Recommendation** | Evidence supports the recommendation and you agree with the suggested action |
| **Reject Recommendation** | You disagree with the recommendation but are closing the event |
| **Dismiss** | The event is clearly not requiring action (e.g. known authorised activity) |
| **Request More Context** | You need additional information before deciding |
| **Escalate** | The event requires supervisor or response-team involvement |
| **Override** | You are taking a different action from the recommendation (requires rationale, authorised roles only) |

**Always add a comment** when rejecting, overriding, or dismissing a HIGH or CRITICAL event. This supports audit quality and team learning.

### 3.4 Escalation Procedure

To escalate an event:

1. Click **Escalate**
2. Select the escalation destination (Shift Supervisor / Response Team)
3. Add a comment describing why escalation is warranted
4. Confirm — the escalation record is created with your identity, timestamp, visible evidence, and the recommendation

Only escalate events with CRITICAL or HIGH risk unless specifically directed otherwise by your supervisor.

Do not escalate based solely on AI recommendation — confirm that the evidence supports escalation.

---

## 4. Confidence and Missing Evidence Guidance

### When Confidence is LOW

LOW confidence means one or more evidence sources were unavailable or contradictory. This does NOT mean the event is not concerning — it means you have less information.

When confidence is LOW:
- Do not dismiss without additional manual verification
- Consider requesting more context or escalating to supervisor
- Note the specific missing sources in your decision comment

### When a Source is Marked "Unavailable"

"Source unavailable" means the system could not retrieve that information at the time of assessment. It does NOT mean the badge/schedule/policy was absent.

For example:
- **"Badge status: unavailable"** ≠ "No badge was found"
- **"Schedule status: could not be verified"** ≠ "No activity was scheduled"

Always treat unavailability as uncertainty, not as confirming a negative.

---

## 5. AI Explanation Quality Checks

Before acting on a recommendation, verify:

- [ ] The explanation references specific evidence items
- [ ] The explanation does not make claims about things not in evidence
- [ ] Missing evidence is explicitly listed
- [ ] The recommended action is proportionate to the risk level
- [ ] The language is neutral — no unsupported labels applied to individuals

If any of these checks fail, use **Reject Recommendation** and add a comment. This feedback improves the system.

---

## 6. Handling AI Unavailability

If the AI assessment layer is unavailable:

1. The event will appear in the queue with status `FAILED` or `CONTEXT_INCOMPLETE`
2. Available deterministic evidence (risk factors, access status, schedule status) may still be shown
3. The AI explanation section will be marked as **unavailable**
4. You MUST perform a manual review using available evidence
5. Document your manual assessment in the comment field
6. Apply your decision using the standard decision controls

**Do not wait for AI assessment before acting on CRITICAL deterministic signals** (e.g. forced-door alarm, explicit security breach indicator from a detection system).

---

## 7. Shift Supervisor Procedures

### 7.1 Reviewing Escalated Events

1. Review all events with status `ESCALATED` directed to Shift Supervisor queue
2. Review the full evidence package, not just the summary
3. Review the escalating officer's comment
4. Check the AI recommendation and whether the officer agreed or disagreed

Actions available:
- **Approve escalation** (forward to response team)
- **De-escalate** (return to officer queue with comment)
- **Override and close** (with documented rationale)

### 7.2 Override Procedure

Overrides require documented rationale. An override record includes:
- Your user ID and role
- The prior decision state
- Your override action
- Your written rationale

Overrides are visible in the audit trail and may be reviewed by compliance auditors.

---

## 8. Feedback Procedure

After closing an event, optionally provide feedback:

1. Rate the recommendation: **Useful / Not useful / Misleading**
2. Optionally note: what was missing, what was incorrect, or what context would have helped

Feedback is used to improve agent evaluation and risk policy calibration.

---

## 9. Administrator Procedures

### 9.1 Risk Policy Management

Risk policies are versioned. To update:

1. Create a new policy version via the Administration interface (or API)
2. Set the effective date
3. Do NOT delete old versions — they must remain for audit reconstruction
4. Notify the AI/Agent Administrator so evaluations can be re-run

### 9.2 Integration Health Monitoring

Monitor the Integration Health view regularly. A degraded source means:

- Evidence from that source is unavailable or stale
- Confidence scores will be reduced for events during that period
- Officers should be informed of any prolonged outage

### 9.3 User Management

- Apply least-privilege role assignment
- Remove access promptly when a user leaves or changes role
- Review role assignments quarterly

### 9.4 Incident Post-Mortems

For significant incidents, use the Audit / History view to reconstruct:

1. Original event
2. Evidence collected and any missing sources
3. Risk and confidence at time of assessment
4. AI recommendation
5. Officer decision and rationale
6. Escalation chain
7. Outcome

Document findings and submit to the AI/Agent Administrator if agent quality improvements are identified.

---

## 10. Agent Administration Procedures

### 10.1 Agent Version Changes

Any change to agent instructions or tool permissions MUST:
1. Be captured in an Architecture Decision Record
2. Be evaluated against the evaluation dataset before deployment
3. Receive approval before promotion to production
4. Be reverted immediately if evaluation scores degrade below threshold

### 10.2 Evaluation Cadence

- Run agent evaluations after every agent or risk policy change
- Run baseline evaluation monthly
- Review operator agreement/override rates quarterly

### 10.3 Prohibited Changes

The following changes to agents are PROHIBITED without explicit documented approval:
- Removing human-review requirement from any decision path
- Granting an agent access to operational actuators (doors, alarms, dispatch)
- Removing evidence citation requirements from explanation output
- Bypassing the deterministic risk engine in favour of LLM-only scoring

---

## 11. Document History

| Version | Date | Author | Change |
|---------|------|--------|--------|
| 1.0 | 2026-11-03 | IBM Bob | Initial SOP — Gate 1 |
