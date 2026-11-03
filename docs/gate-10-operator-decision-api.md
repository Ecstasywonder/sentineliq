# Gate 10 — Operator Decision API

**Status:** ✅ Complete  
**Branch:** `gate-10-operator-decision-api`  
**Date:** 2026-11-03  
**Author:** IBM Bob (Principal Architect)

---

## Summary

Gate 10 delivers the primary human-in-the-loop interaction surface for SentinelIQ.
An authenticated operator can now record a formal decision on any event that has
reached `awaiting_review` or `escalated` status.  Every decision:

1. Advances the event lifecycle via the state machine (ADR-006 — non-bypassable)
2. Persists an `OperatorDecision` row with full context (risk at time of decision,
   prior status, rationale, is_override flag)
3. Writes an **immutable** `AuditEvent` row (`action="human_decision"`) — the
   foundation of the compliance audit trail

Three new endpoints are provided:

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| `POST` | `/api/v1/events/{id}/decision` | `events:decide` | Record an operator decision |
| `GET` | `/api/v1/events/{id}/decision` | `events:read` | Retrieve latest decision |
| `GET` | `/api/v1/events/{id}/decisions` | `events:read` | Full decision history |

---

## Decision Type → Status Transition Map

| Decision | Resulting event status | Use case |
|----------|----------------------|----------|
| `accept` | `closed` | Operator confirms the assessment and closes the event |
| `reject` | `dismissed` | Operator rejects the alert as incorrect |
| `dismiss` | `dismissed` | Operator dismisses without contesting assessment |
| `escalate` | `escalated` | Operator escalates to a higher authority |
| `override` | `closed` | Operator overrides an agent recommendation |
| `request_context` | `context_incomplete` | Operator requests more evidence before deciding |

---

## API Contract

### `POST /api/v1/events/{id}/decision`

**Request body** (`DecisionRequest`):
```json
{
  "decision": "accept",
  "rationale": "Person confirmed as authorised contractor — badge verified.",
  "recommendation_id": null,
  "is_override": false
}
```

**Response 201** (`DecisionResponse`):
```json
{
  "decision_id": "...",
  "event_id": "...",
  "decision": "accept",
  "rationale": "Person confirmed as authorised contractor — badge verified.",
  "recommendation_id": null,
  "is_override": false,
  "decided_by": "user-uuid",
  "decided_by_role": "security_operator",
  "prior_status": "awaiting_review",
  "risk_at_decision": "high",
  "confidence_at_decision": 0.8,
  "decided_at": "2026-11-03T22:35:00+00:00",
  "event_status": "closed"
}
```

**Error codes:**

| HTTP | Code | Reason |
|------|------|--------|
| 400 | `INVALID_DECISION` | Unknown decision type |
| 404 | `DECISION_ERROR` | Event not found |
| 409 | `DECISION_ERROR` | Event not in a decidable status |
| 409 | `INVALID_TRANSITION` | State machine rejects the transition |

---

## Files Added / Changed

| File | Change |
|------|--------|
| `backend/app/schemas/decision.py` | New — `DecisionRequest`, `DecisionResponse`, `DecisionListResponse`, `VALID_DECISIONS`, `DECISION_STATUS_MAP` |
| `backend/app/services/decision_service.py` | New — `DecisionService.record()`, `.get_latest()`, `.get_all()` |
| `backend/app/api/v1/endpoints/decisions.py` | New — `POST /{id}/decision`, `GET /{id}/decision`, `GET /{id}/decisions` |
| `backend/app/api/v1/router.py` | Mounted `decisions` router under `/events` prefix |
| `backend/tests/test_decision_api.py` | New — 32 integration tests |
| `infra/ci/.github/workflows/ci.yml` | Updated — gate branches, `--cov-fail-under=85`, `ci-gate` aggregate job |
| `.github/workflows/ci.yml` | New — root-level copy (GitHub Actions requires this location) |

---

## ADR Compliance

| ADR | Constraint | Enforced By |
|-----|-----------|-------------|
| ADR-006 | Human review non-bypassable | Only `awaiting_review` / `escalated` events are decidable |
| ADR-006 | All actions auditable | `AuditEvent` row written on every decision |
| Architecture §9 | Least privilege | `events:decide` required for POST; `events:read` for GET |
| Architecture §8 | State machine | `validate_transition()` called before any status change |

---

## Test Coverage — 32 tests

### Happy path (16 tests)
- All 6 decision types advance to the correct status
- Response shape has all required fields
- Rationale stored and returned
- `null` rationale accepted
- `is_override` flag stored
- `prior_status` is `awaiting_review`
- `risk_at_decision` captured from event
- DB row persisted with correct values
- Event status updated in DB

### Audit trail (3 tests)
- `AuditEvent` row created on every decision
- `actor` equals stub user email
- `details_json` contains decision, prior_status, target_status, is_override, rationale_provided

### GET /decision (4 tests)
- 200 after POST
- Response matches POST
- 404 when no decision recorded
- 404 for unknown event

### GET /decisions (4 tests)
- 200 with empty list (no decisions yet)
- Returns decision after POST
- Multiple decisions ordered newest-first
- 404 for unknown event

### Error cases (5 tests)
- 400 for unknown decision type
- 404 for unknown event
- 409 for `normalised` status
- 409 for `dismissed` (terminal) status
- 409 for `assessing` status

---

## CI/CD Pipeline — Branch Protection Rules

From Gate 10 onwards a mandatory CI/CD rule applies:

```
Branch: main
  ✅ Require PR before merging (no direct push)
  ✅ Required status check: "CI Gate (required for merge)"
     — passes only when "Backend (lint + tests)" passes
  ✅ Require branches to be up to date before merging
  ✅ Dismiss stale reviews when new commits pushed
```

The `ci-gate` job in `.github/workflows/ci.yml` is the single registered
status check.  It only succeeds when:
1. `ruff check` passes (no lint errors)
2. `ruff format --check` passes (formatting enforced)
3. `pytest --cov-fail-under=85` passes (≥85% coverage + all tests green)

**Workflow for every gate going forward:**
```
git checkout -b gate-N-<feature>   # on EC2 + local
  ... build code + tests ...
git push origin gate-N-<feature>   # triggers CI on branch
  ... CI must show green on GitHub ...
gh pr create --base main           # open PR
  ... CI gate runs on PR ...
gh pr merge --squash               # merge only after ci-gate passes
git checkout main && git pull      # sync local + EC2
```

---

## Next Gate

**Gate 11 — Escalation API**

- `POST /api/v1/events/{id}/escalation` — create escalation record
- `GET /api/v1/events/{id}/escalation` — retrieve escalation
- `PATCH /api/v1/events/{id}/escalation` — update escalation status
- `Escalation` model: `escalations` table (Gate 3)
- Triggered automatically when operator decision is `escalate`
- Audit trail entry on every escalation state change
