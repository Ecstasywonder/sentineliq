# Gate 5 — Event Ingestion API

**Date:** 2026-11-03  
**Gate:** 5  
**Status:** Complete  
**Author:** IBM Bob (Principal Architect)

---

## 1. Scope

Gate 5 delivers the first live API surface of SentinelIQ — the event ingestion and queue endpoints that allow detection systems (or the simulator) to submit security events and operators to retrieve them.

---

## 2. Files Delivered

| File | Purpose |
|------|---------|
| `backend/app/schemas/events.py` | Pydantic schemas — inbound and outbound contracts |
| `backend/app/services/event_lifecycle.py` | State machine — valid transitions, terminal states |
| `backend/app/api/v1/endpoints/events.py` | Four routes: POST, GET list, GET by ID, PATCH status |
| `backend/app/api/v1/router.py` | Updated — events router wired at `/api/v1/events` |
| `backend/tests/test_events_api.py` | 34 tests — full request/response + state machine unit tests |
| `docs/deployment.md` | Updated with Gate 5 run commands and endpoint table |

---

## 3. API Surface

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/api/v1/events` | 201 / 200 | Ingest event; 200 + `Duplicate-Event: true` on dedup hit |
| `GET` | `/api/v1/events` | 200 | Paginated queue; filterable by `status` and `risk_level` |
| `GET` | `/api/v1/events/{id}` | 200 / 404 | Single event retrieval |
| `PATCH` | `/api/v1/events/{id}/status` | 200 / 404 / 409 / 422 | Lifecycle transition enforcement |

---

## 4. Event Lifecycle State Machine

```
RECEIVED
    ├── -> NORMALISED
    └── -> FAILED

NORMALISED
    ├── -> ASSESSING
    └── -> FAILED

ASSESSING
    ├── -> AWAITING_REVIEW
    ├── -> CONTEXT_INCOMPLETE
    └── -> FAILED

AWAITING_REVIEW
    ├── -> DISMISSED      (human decision)
    ├── -> CLOSED         (human decision)
    ├── -> ESCALATED      (human decision)
    └── -> ASSESSING      (re-assess with more context)

CONTEXT_INCOMPLETE
    ├── -> AWAITING_REVIEW
    ├── -> ASSESSING
    └── -> FAILED

ESCALATED
    ├── -> CLOSED
    └── -> AWAITING_REVIEW

CLOSED     [terminal]
DISMISSED  [terminal]
FAILED     [terminal]
```

Invalid transitions return HTTP **409 Conflict** with `code: INVALID_TRANSITION`.

---

## 5. Deduplication

When `provider_event_id` is set, the engine checks for an existing event with the same ID created within `Settings.event_dedup_window_seconds` (default: 300s).

- **Duplicate found:** returns HTTP **200** with the existing event and header `Duplicate-Event: true`. No new row is created.
- **No duplicate / no provider_event_id:** creates a new event, returns HTTP **201**.

---

## 6. Ingestion Flow

```
POST /api/v1/events
        │
        ├── Pydantic validation (event_type enum, required fields, confidence range)
        │
        ├── Deduplication check (provider_event_id + time window)
        │       └── Duplicate? Return existing event, HTTP 200
        │
        ├── Normalise raw_metadata -> JSON string
        ├── Build normalised_data JSON (structured snapshot)
        │
        └── Persist SecurityEvent (status = "normalised")
                └── Return EventResponse, HTTP 201
```

Gate 7 (Agent Trigger) will advance status from `normalised` → `assessing` and invoke watsonx Orchestrate.

---

## 7. Test Coverage

| Test Class / Function | What is Verified |
|----------------------|-----------------|
| `test_ingest_event_happy_path` | 201, status=normalised, correct fields |
| `test_ingest_returns_event_id` | ID is non-empty string |
| `test_ingest_all_optional_fields` | Optional fields accepted and returned |
| `test_ingest_invalid_event_type` | 422 on unknown event type |
| `test_ingest_missing_required_location` | 422 on missing location_id |
| `test_ingest_missing_required_timestamp` | 422 on missing event_timestamp |
| `test_ingest_detector_confidence_out_of_range` | 422 on confidence > 1.0 |
| `test_ingest_deduplication_returns_200` | 200 + Duplicate-Event header on re-submission |
| `test_ingest_no_provider_id_never_deduplicates` | Always creates new event without provider_event_id |
| `test_ingest_all_valid_event_types` | All 8 event types accepted |
| `test_get_event_by_id` | 200 + correct body |
| `test_get_event_not_found` | 404 + EVENT_NOT_FOUND code |
| `test_list_events_returns_list` | Pagination structure present |
| `test_list_events_filter_by_status` | Only matching status returned |
| `test_list_events_invalid_status_returns_422` | 422 on bad status filter |
| `test_list_events_invalid_risk_level_returns_422` | 422 on bad risk_level filter |
| `test_list_events_pagination` | page + page_size respected |
| `test_list_events_page_size_limit` | 422 on page_size > 100 |
| `test_status_transition_valid` | normalised -> assessing, 200 |
| `test_status_transition_invalid_returns_409` | 409 + INVALID_TRANSITION code |
| `test_status_transition_unknown_status_returns_422` | 422 on unknown status |
| `test_status_transition_event_not_found` | 404 |
| `TestEventLifecycle` (14 unit tests) | Every valid/invalid transition; terminal states; error messages |

---

## 8. Acceptance Criteria — Gate 5

- [x] `POST /api/v1/events` implemented, tested, validated
- [x] `GET /api/v1/events` with pagination and filters implemented, tested
- [x] `GET /api/v1/events/{id}` with 404 handling implemented, tested
- [x] `PATCH /api/v1/events/{id}/status` with state machine enforcement, tested
- [x] Deduplication by `provider_event_id` within configurable time window
- [x] Status advances `received → normalised` on successful ingest
- [x] All 8 event types accepted and validated
- [x] State machine covers all transitions per `docs/architecture.md §8`
- [x] Invalid transitions rejected HTTP 409 (never silently accepted)
- [x] Terminal states enforced (closed/dismissed/failed cannot transition out)
- [x] Router wired: `GET /docs` shows Events tag in Swagger UI
- [x] 34 tests covering happy paths, error cases, deduplication, state machine
- [x] `docs/deployment.md` updated

---

## 9. Next Gate

**Gate 6 — RBAC & Authentication**

Will produce:
- JWT token issuance (`POST /api/v1/auth/token`)
- Role-based permission guards on all event endpoints
- `officer`, `supervisor`, `response_team`, `security_admin` role enforcement
- Token refresh endpoint
- Tests for all role-gated scenarios
