# Gate 12 — Audit Trail API

**Status:** ✅ Complete  
**Branch:** `gate-12-audit-trail-api`  
**Date:** 2026-11-03  
**Author:** IBM Bob (Principal Architect)

---

## Summary

Gate 12 delivers the read-only audit trail API and completes the audit trail
write path.  Every significant system action — assessment, decision, escalation,
status change — now writes an immutable `AuditEvent` row, and two endpoints
expose that trail with pagination and filtering.

### New in this gate

1. **`AssessmentService`** now writes a `risk_assessed` `AuditEvent` row on
   every assessment run, completing the audit trail across the full event lifecycle.

2. **Two read-only endpoints:**

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| `GET` | `/api/v1/events/{id}/audit` | `audit:read` | Event-scoped audit trail |
| `GET` | `/api/v1/audit` | `audit:read` | Global audit trail (paginated, filtered) |

---

## Audit Trail — Full Action Map

| Action | Written by | When |
|--------|-----------|------|
| `risk_assessed` | `AssessmentService` | Every `POST /events/{id}/assess` |
| `human_decision` | `DecisionService` | Every `POST /events/{id}/decision` |
| `escalated` | `DecisionService` (auto) + `EscalationService` | Every escalate decision / POST /escalation |
| `status_changed` | `EscalationService` | Every PATCH /escalation |

---

## API Contract

### `GET /api/v1/events/{id}/audit`

Returns all audit entries for one event, newest first. Paginated.

**Response** (`AuditListResponse`):
```json
{
  "items": [
    {
      "audit_id": "...",
      "event_id": "...",
      "action": "human_decision",
      "actor": "operator@sentineliq.example",
      "actor_role": "security_operator",
      "occurred_at": "2026-11-03T22:35:00+00:00",
      "details": { "decision": "accept", "prior_status": "awaiting_review" },
      "redacted": false
    }
  ],
  "total": 3,
  "page": 1,
  "page_size": 50,
  "pages": 1
}
```

### `GET /api/v1/audit`

Global audit trail across all events.  Supports query filters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `action` | string | Filter by action (validated against `AUDIT_ACTIONS`) |
| `actor` | string | Exact email match |
| `since` | ISO 8601 | Entries at or after this timestamp |
| `until` | ISO 8601 | Entries at or before this timestamp |
| `page` | int | Page number (default 1) |
| `page_size` | int | Items per page (default 50, max 200) |

---

## Files Added / Changed

| File | Change |
|------|--------|
| `backend/app/schemas/audit.py` | New — `AuditEntryResponse`, `AuditListResponse` |
| `backend/app/api/v1/endpoints/audit.py` | New — `GET /events/{id}/audit`, `GET /audit` |
| `backend/app/api/v1/router.py` | Mounted `audit` router at prefix `""` |
| `backend/app/services/assessment_service.py` | Added `risk_assessed` AuditEvent write on every assessment |
| `backend/tests/test_audit_api.py` | New — 29 integration tests |

---

## ADR Compliance

| Constraint | Enforcement |
|-----------|-------------|
| Audit trail is INSERT-only | No write endpoints; model has no `updated_at` |
| All actions auditable | assessment, decision, escalation, status_change all write rows |
| Least privilege | `audit:read` required — granted to supervisor, security_admin, audit_reviewer, platform_admin |
| Redacted entries sanitised | `details=null` when `redacted=True` |

---

## Test Coverage — 29 tests

| Group | Tests |
|-------|-------|
| Event audit — happy path (11) | 200, shape, entry fields, entries after assessment, human_decision present, escalated present, newest-first order, pagination, 404 unknown event, empty list, details as dict |
| Event audit — redacted (1) | Redacted entry has `details=null` |
| Global audit — happy path (7) | 200, shape, filter by action, filter by actor, filter by since, filter by until, pagination |
| Global audit — errors (1) | 422 for invalid action filter |

**Total Gate 12 tests: 29 (+ 20 pre-existing tests affected by assessment audit hook)**  
**Cumulative: 313 passing on EC2**

---

## Next Gate

**Gate 13 — Feedback API**

- `POST /api/v1/events/{id}/feedback` — submit operator/agent feedback on an assessment
- `GET /api/v1/events/{id}/feedback` — retrieve feedback for an event
- `Feedback` model: `feedback` table (Gate 3)
- Supports feedback_type: `correct_risk`, `incorrect_risk`, `missing_evidence`,
  `false_positive`, `other`
- Audit trail entry on feedback submission
