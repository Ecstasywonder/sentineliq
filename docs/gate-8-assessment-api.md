# Gate 8 — Evidence Aggregation Service & Assessment API

**Status:** ✅ Complete  
**Date:** 2026-11-03  
**Author:** IBM Bob (Principal Architect)

---

## Summary

Gate 8 wires together all deterministic backend components built in Gates 3–7 into a
single assessable endpoint.  A caller posts to `POST /api/v1/events/{id}/assess` and
receives a complete `AssessmentResponse` including risk score, confidence score, per-factor
breakdown, and evidence error map — all computed deterministically with no LLM involvement
(ADR-003, ADR-004).

---

## Deliverables

### New Endpoint

| Method | Path | Permission | Description |
|--------|------|-----------|-------------|
| `POST` | `/api/v1/events/{id}/assess` | `events:decide` | Run full deterministic assessment |

**Request body** (all optional):
```json
{
  "unavailable_source_ids": ["mock_access_control"],
  "policy_version": "1.0"
}
```

**Response** (`AssessmentResponse`):
```json
{
  "event_id": "...",
  "event_status": "awaiting_review",
  "risk_score": 90.0,
  "risk_level": "high",
  "risk_policy_version": "1.0",
  "risk_factors": [
    {
      "factor_id": "after_hours_access",
      "label": "After Hours Access",
      "weight": 40.0,
      "direction": "increase",
      "triggered": true,
      "contribution": 40.0
    }
  ],
  "confidence_score": 0.8,
  "confidence_level": "high",
  "confidence_reductions": [],
  "sources_available": 6,
  "sources_required": 6,
  "evidence_errors": {},
  "assessed_at": "2026-11-03T22:30:00+00:00"
}
```

---

### Assessment Pipeline (7 Steps)

```
POST /events/{id}/assess
    │
    ├─1─ Load SecurityEvent (404 if missing)
    ├─2─ Validate & advance status: normalised → assessing
    ├─3─ EvidenceAggregator.gather() — 6 sources, error-isolated
    ├─4─ _build_signals() — deterministic signal extraction from evidence
    ├─5─ RiskEngine.assess() — DB-backed factor scoring (ADR-003, no LLM)
    ├─6─ ConfidenceEngine.assess() — independent score (ADR-004)
    ├─7─ Persist RiskAssessment + ConfidenceAssessment rows
    └─8─ Denormalise scores onto SecurityEvent + advance to awaiting_review
```

---

### Files Changed / Added

| File | Change |
|------|--------|
| `backend/app/api/v1/endpoints/events.py` | Added `POST /{event_id}/assess` endpoint |
| `backend/app/schemas/assessment.py` | New — `AssessEventRequest`, `AssessmentResponse`, `RiskFactorDetail`, `ConfidenceReductionDetail` |
| `backend/app/services/assessment_service.py` | New — `AssessmentService.run()` orchestrator |
| `backend/tests/test_assessment_api.py` | New — 14 integration tests |

---

### Signal Extraction (v1.0 policy factors)

| Signal | Source | Logic |
|--------|--------|-------|
| `after_hours_access` | `access_events` | Any access event with hour ≥ 20 or < 6 |
| `unverified_person` | `access_events` | Any record with `access_granted=False` |
| `no_work_order` | `work_orders` | Zero active work orders for location |
| `no_scheduled_entry` | `schedule` | Zero schedule entries for location |
| `known_incident_area` | `incident_history` | One or more prior incidents at location |
| `critical_zone` | `location_policy` | Active rule of type `restricted_zone` / `access_restriction` / `after_hours_restriction` |

---

### Error / Status Codes

| Code | Reason |
|------|--------|
| `200` | Assessment complete |
| `404` | Event not found |
| `409` | Event in terminal or non-assessable state (invalid transition) |
| `422` | Validation error in request body |

---

### ADR Compliance

| ADR | Constraint | Enforced By |
|-----|-----------|-------------|
| ADR-003 | LLM never produces risk score | `AssessmentService` — no LLM call path |
| ADR-004 | Risk ≠ Confidence (independent) | `RiskEngine` + `ConfidenceEngine` called separately |
| ADR-004 | Missing evidence → reduced confidence | `_build_source_statuses()` + `ConfidenceEngine.SOURCE_UNAVAILABLE` |
| ADR-006 | Human review non-bypassable | Status advances to `awaiting_review`, never skips it |

---

### Test Coverage

14 integration tests in `tests/test_assessment_api.py`:

**Happy Path (9 tests)**
- Full round-trip returns 200 with correct schema shape
- Event status advances to `awaiting_review` in DB
- `RiskAssessment` row persisted with correct values
- `ConfidenceAssessment` row persisted
- Risk scores denormalised onto `SecurityEvent`
- After-hours access triggers `after_hours_access` factor
- `access_granted=False` triggers `unverified_person` factor
- Missing work order triggers `no_work_order` factor
- Existing work order suppresses `no_work_order` factor

**Re-assessment (1 test)**
- Second call replaces old `RiskAssessment` row (idempotent upsert)

**Error Cases (2 tests)**
- 404 for non-existent event
- 409 for terminal/dismissed/closed event

**Request Body (2 tests)**
- No body uses defaults (body is fully optional)
- `unavailable_source_ids` in body reduces confidence score

---

## Next Gate

**Gate 9 — Risk Assessment API**

- `GET /api/v1/events/{id}/assessment` — retrieve persisted assessment
- `GET /api/v1/events/{id}/assessment/factors` — per-factor breakdown
