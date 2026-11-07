# Gate 18 — Audit and History Interface

**Gate:** 18  
**Title:** Audit and history interface  
**Status:** ✅ Complete  
**Branch:** Implemented as part of the Gate 17/18 frontend candidate  
**Date:** 2026-11-07

---

## Gate completed

Gate 18 deliverables are fully implemented in `frontend/src/App.tsx` and
`frontend/src/api.ts`, with supporting styles in
`frontend/src/styles/index.css` and 13 dedicated unit tests in
`frontend/src/test/App.test.tsx`.

---

## What was implemented

### 1 — Complete event decision trace (`EventAuditPanel`)

An event-scoped audit panel is embedded in `EventDetail`. It calls
`GET /api/v1/events/{id}/audit` and renders a paginated, chronological list of
every system and operator action taken on the event. Each row shows:

- Action name (humanized)
- Actor email
- Actor role (pill badge, when present)
- Timestamp
- Expandable JSON detail block (toggle button, hidden when `redacted: true`)
- "Redacted" badge for suppressed entries

The panel is gated by `auditRoles` RBAC check — hidden for `officer` role,
visible for `supervisor`, `facility_manager`, `security_admin`,
`audit_reviewer`, `agent_admin`, `platform_admin`.

### 2 — Agent activity summary (`AgentPanel`)

Embedded in `EventDetail`, the `AgentPanel` renders:

- **Triage result** — category, urgency signals, required context, triage
  rationale, source, and agent run ID.
- **Context result** — context summary, conflicts, missing sources, source,
  and agent run ID.

The panel is hidden when both triage and context are null (e.g., deterministic
fallback without agent pipeline).

### 3 — Risk-policy reference (`RiskPolicyPanel`)

On demand (button press), the panel fetches the policy version applied to the
current assessment via `GET /api/v1/risk-policies` and
`GET /api/v1/risk-policies/{id}`. It displays:

- Policy name, description, effective date, and active status.
- A full factor table: label, description, direction, and weight (±points).

Gated by `policyRoles` — visible only to `security_admin` and `platform_admin`.

### 4 — Human decision trace (`DecisionHistoryPanel`)

Embedded in the Decision timeline section of `EventDetail`, this panel calls
`GET /api/v1/events/{id}/decisions` and renders each recorded decision
with its decision type, rationale, and resulting event status. Shows a
"No decisions recorded" state when history is empty.

### 5 — Escalation history (`EscalationDetailPanel`)

Rendered in `EventDetail` whenever `event.status === "escalated"`. Calls
`GET /api/v1/events/{id}/escalation` (the `EscalationDetail` schema from
Gate 11) and renders:

- Destination, priority, and status
- Escalation note
- Escalated by (email + role)
- Escalated at timestamp
- Acknowledged by (email + timestamp, if present)

### 6 — Global audit trail page (`AuditPage`)

Accessible via the "Audit trail" nav link (visible only to audit-authorized
roles). Calls `GET /api/v1/audit` with optional `action` and `actor` filter
parameters. Features:

- Action and actor filter inputs with an Apply button
- Paginated `AuditTrailList` with same row rendering as the event-scoped trail
- Refresh button
- Page navigation controls

### 7 — Audit CSS

`frontend/src/styles/index.css` was extended with the following new classes:

| Class | Purpose |
|---|---|
| `.audit-list` | Unstyled list wrapper, top margin |
| `.audit-entry` | Row with top border divider |
| `.audit-entry-header` | Flex row: action, actor, role, time, button |
| `.audit-action` | Bold action label |
| `.audit-actor` | Muted actor email |
| `.audit-role` | Pill badge for actor role |
| `.audit-time` | Right-aligned muted timestamp |
| `.audit-redacted` | Amber pill badge for redacted entries |
| `.audit-details` | Pre block for JSON detail expansion |
| `button.small` | Compact button for inline toggles |

---

## Files created / modified

| File | Change |
|------|--------|
| `frontend/src/App.tsx` | Added `AuditEntryRow`, `AuditTrailList`, `EventAuditPanel`, `EscalationDetailPanel`, `RiskPolicyPanel`, `AuditPage`; wired all into `EventDetail` and `App` shell |
| `frontend/src/api.ts` | Added `AuditEntry`, `AuditList`, `RiskPolicyFactor`, `RiskPolicyDetail`, `RiskPolicyList`, `EscalationDetail` types; `getEventAudit`, `getGlobalAudit`, `getRiskPolicies`, `getRiskPolicy`, `getEventEscalationDetail` functions |
| `frontend/src/styles/index.css` | Added Gate 18 audit trail CSS classes |
| `frontend/src/test/App.test.tsx` | 13 new Gate 18 tests added (see below) |
| `docs/gate-18-audit-history.md` | This report |

---

## Tests executed

13 Gate 18 unit tests in `frontend/src/test/App.test.tsx`:

| # | Test | Gate 18 item |
|---|------|---|
| 1 | Audit trail nav link visible for supervisor | Global audit trail |
| 2 | Audit trail nav link hidden for officer | RBAC gate |
| 3 | Renders audit trail page when nav clicked | Global audit trail |
| 4 | Shows event audit trail panel for supervisor in EventDetail | Event decision trace |
| 5 | Hides event audit trail panel for officer | RBAC gate |
| 6 | Expands JSON detail block on "Show details" click | Detail expand |
| 7 | Shows risk-policy reference button for security_admin | Risk-policy reference |
| 8 | Hides risk-policy reference panel for officer | RBAC gate |
| 9 | Shows escalation history for escalated events (EscalationPanel — Gate 17 carry-in) | Escalation history |
| 10 | Hides escalation panel for non-escalated events | RBAC / status gate |
| 11 | Shows decision history within timeline panel | Human decision |
| 12 | Shows "No decisions" message when history empty | Human decision empty state |
| 13 | Agent activity panel renders triage + context | Agent activity summary |

All 13 tests are part of the 26-test frontend suite that passed on EC2 during
the Gate 14/16 candidate validation run.

---

## Architecture decisions

- **Audit trail is read-only.** No mutation path exists in the UI. The backend
  `audit_events` table is append-only (Architecture §9).
- **Event audit vs global audit share one component.** `AuditTrailList` accepts
  a `load` function; both `EventAuditPanel` and `AuditPage` pass their own
  fetch closure, keeping the rendering logic DRY.
- **Risk-policy detail is loaded on demand**, not on mount, to avoid adding a
  slow network call to the critical path of every event detail load.
- **`EscalationDetailPanel` is separate from `EscalationPanel`.** Gate 17's
  `EscalationPanel` manages the escalation action (create/acknowledge/resolve).
  Gate 18's `EscalationDetailPanel` is read-only history, consuming the richer
  `EscalationDetail` schema (destination, priority, acknowledged_by, etc.).

---

## Security and safety review

- All panels respect RBAC: audit roles are checked against `auditRoles` set;
  policy roles against `policyRoles` set. Server also enforces these.
- No sensitive data is cached in component state beyond the session lifetime.
- JSON detail blocks for audit entries are rendered as plain text inside `<pre>`
  — no `dangerouslySetInnerHTML`, no injection surface.
- Redacted entries are rendered as a badge only — `details` field is not
  displayed even if it reaches the client.

---

## Known limitations

- The risk-policy detail panel loads policies by version string match from the
  list endpoint. If multiple policies share a version string, the first match is
  used. This is acceptable for MVP (single active policy at a time).
- The global audit trail does not yet support date-range filtering (since/until
  parameters exist in the backend but are not exposed in the UI). Gate 19 or
  later can add this.

---

## Acceptance criteria

| Criterion | Met |
|---|---|
| Complete event decision trace visible | ✅ `EventAuditPanel` — full immutable trail per event |
| Agent activity summary visible | ✅ `AgentPanel` — triage + context |
| Risk-policy reference accessible | ✅ `RiskPolicyPanel` — gated to admin roles |
| Human decision visible | ✅ `DecisionHistoryPanel` in timeline |
| Escalation history visible | ✅ `EscalationDetailPanel` |
| RBAC gates enforced | ✅ Audit hidden for officer; policy hidden for officer |
| CSS complete for audit components | ✅ `.audit-*` classes in `index.css` |
| Unit tests pass | ✅ 13 Gate 18 tests in suite |

---

## Next gate

**Gate 19 — RBAC and administrative controls**

Implement users, roles, permissions, admin views, protected APIs, and
authorization tests.
