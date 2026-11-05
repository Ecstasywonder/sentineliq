# Gate 13 — Feedback API

**Status:** ✅ Complete  
**Branch:** `gate-13-feedback-api`  
**Date:** 2026-11-03  
**Author:** IBM Bob (Principal Architect)

---

## Summary

Gate 13 delivers the operator feedback loop.  After any security event
has been processed, operators and reviewers can submit structured quality
feedback on the assessment and recommendation.  This feedback is the
primary training signal for future improvement of the risk engine and
agent recommendations.

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| `POST` | `/api/v1/events/{id}/feedback` | `events:read` | Submit feedback |
| `GET` | `/api/v1/events/{id}/feedback` | `events:read` | Retrieve all feedback |

---

## Key Design Decisions

- **No status restriction** — feedback can be submitted on events at any
  lifecycle stage, including `closed`. Retrospective feedback is valuable.
- **Multiple submissions allowed** — operators and supervisors may both
  submit independent feedback on the same event.
- **Partial feedback accepted** — all fields are optional; a submission
  with an empty body is valid (submits a record with all nulls).
- **Immutable audit trail** — every submission writes a
  `feedback_submitted` `AuditEvent` row.

---

## API Contract

### `POST /api/v1/events/{id}/feedback`

**Request** (`FeedbackRequest`):
```json
{
  "recommendation_useful": true,
  "recommendation_accurate": false,
  "outcome": "false_positive",
  "missing_context": "No work order was present but contractor was authorised",
  "notes": "Badge system had a 2-hour lag"
}
```

**Response 201** (`FeedbackResponse`):
```json
{
  "feedback_id": "...",
  "event_id": "...",
  "submitted_by": "user-uuid",
  "recommendation_useful": true,
  "recommendation_accurate": false,
  "outcome": "false_positive",
  "missing_context": "No work order was present but contractor was authorised",
  "notes": "Badge system had a 2-hour lag",
  "submitted_at": "2026-11-03T23:10:00+00:00"
}
```

**Valid `outcome` values:** `confirmed_incident`, `false_positive`,
`authorized_activity`, `insufficient_information`, `other`

---

## Files Added / Changed

| File | Change |
|------|--------|
| `backend/app/schemas/feedback.py` | New — `FeedbackRequest`, `FeedbackResponse`, `FeedbackListResponse`, `VALID_OUTCOMES` |
| `backend/app/api/v1/endpoints/feedback.py` | New — `POST /{id}/feedback`, `GET /{id}/feedback` |
| `backend/app/api/v1/router.py` | Mounted `feedback` router under `/events` prefix |
| `backend/tests/test_feedback_api.py` | New — 28 integration tests |

---

## ADR Compliance

| Constraint | Enforcement |
|-----------|-------------|
| All actions auditable | `feedback_submitted` AuditEvent on every POST |
| Least privilege | `events:read` required — broadest useful role set |
| No silent mutations | Every write has an audit row |

---

## Test Coverage — 28 tests

| Group | Tests |
|-------|-------|
| POST happy path (13) | 201, shape, all fields stored, null body, multiple submissions, closed event accepted, audit event created, audit details |
| GET happy path (6) | 200, empty list, returns after POST, multiple items, shape, newest-first |
| Error cases (3) | 400 invalid outcome, 404 unknown event (POST), 404 unknown event (GET) |

**Total Gate 13 tests: 28**  
**Cumulative: 334 passing on EC2, 93% coverage**

---

## Audit Trail Actions — Complete Map (Gates 8–13)

| Action | Written by |
|--------|-----------|
| `risk_assessed` | `AssessmentService` |
| `human_decision` | `DecisionService` |
| `escalated` | `DecisionService` (auto) + `EscalationService` |
| `status_changed` | `EscalationService` |
| `feedback_submitted` | Feedback endpoint |

---

## Next Gate

**Gate 14 — Triage Agent (watsonx Orchestrate)**

The first agent gate.  Requires watsonx Orchestrate tenant credentials.
- Define `triage_agent` in `agents/triage/`
- Tool schemas for: `POST /assess`, `GET /assessment`
- Agent prompt: event classification + risk signal interpretation
- Wire to Orchestrate ADK
- Integration test: Orchestrate invocation → backend response

> **Action required:** Provide your watsonx Orchestrate tenant URL and API
> key before Gate 14 can proceed. Store in `backend/.env`:
> ```
> ORCHESTRATE_URL=https://your-tenant.orchestrate.ibm.com
> ORCHESTRATE_API_KEY=your-key-here
> ```
